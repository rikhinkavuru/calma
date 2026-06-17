"""The patch gate. Reviewer #0 (anti-test-hacking) is non-negotiable: the goalposts must be
byte-identical across the repair, and the re-verify must have judged the same claim/metric/contract/
artifact under the same isolation. Then spec/smell/build reviewers. Returns (all_passed, [reason, ...]).
NEVER imports verdict-core (it reads the new ledger/diff/run.json as data; the firewall stays intact)."""
import hashlib
import json
import os
import re

CONTRACT_NAME = "verify.yaml"


def _sha_file(p):
    h = hashlib.sha256()
    try:
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _touches(diff_text, *needles):
    """True if the unified diff adds/removes lines touching any needle (a content token, e.g. a seed)."""
    return any(n in diff_text for n in needles)


def _modified_files(diff_text):
    """The set of files a unified diff actually MODIFIES, parsed from its ---/+++ headers (NOT a substring
    scan of the content -- a comment or string literal that merely mentions verify.yaml must not count as
    'modifying' it, and conversely a real edit must be caught even if obfuscated in the content)."""
    files = set()
    for ln in (diff_text or "").splitlines():
        if ln.startswith(("--- ", "+++ ")):
            p = ln[4:].split("\t")[0].strip().strip('"')
            if p in ("/dev/null", ""):
                continue
            for pre in ("a/", "b/"):
                if p.startswith(pre):
                    p = p[len(pre):]
                    break
            files.add(os.path.normpath(p))
    return files


def anti_test_hacking(scratch, diag, goalposts, new_ledger, new_diff, applied_diff):
    """REJECT if any goalpost moved. The ONLY thing allowed to change is the producing code. FAILS CLOSED:
    a flip must AFFIRMATIVELY re-state every goalpost (same claim value, metric, contract hash, artifact
    identity, isolation tier, determinism mode, independent binding); a missing/None field is treated as a
    failure to confirm, never as 'unchanged' -- otherwise a gamed re-verify that simply DROPS a field would
    pass."""
    reasons = []
    modified = _modified_files(applied_diff)
    # (1) the contract file is NOT among the patch's modified files, and still hashes to the captured one
    if any(os.path.basename(f) == CONTRACT_NAME for f in modified):
        reasons.append("patch modifies %s (the contract is a goalpost)" % CONTRACT_NAME)
    cur_sha = _sha_file(os.path.join(scratch, CONTRACT_NAME))
    if goalposts.contract_sha256 is None or cur_sha != goalposts.contract_sha256:
        reasons.append("verify.yaml is absent or changed across the repair (contract not pinned)")
    # (2) the re-verify AFFIRMATIVELY re-judged the SAME claim value + metric, with the strong binding
    nc = next((c for c in (new_ledger.get("claims") or [])
               if c.get("metric") == goalposts.metric_id), None)
    if nc is None:
        reasons.append("re-verify did not judge the original metric %r" % goalposts.metric_id)
    else:
        if goalposts.claim_value is not None and nc.get("claimed_value") != goalposts.claim_value:
            reasons.append("the claimed_value under test changed (%s -> %s)"
                           % (goalposts.claim_value, nc.get("claimed_value")))
        if nc.get("input_binding_status") != "independently-bound":
            reasons.append("binding is %r, not independently-bound -- a flip must keep the strong binding"
                           % nc.get("input_binding_status"))
    # (3) the patch must not edit/relocate a bound artifact. An EMPTY goalpost artifact set means capture
    #     FAILED -> fail closed (we cannot prove the recompute artifact was untouched).
    if not goalposts.artifact_paths:
        reasons.append("goalpost artifact set is empty (capture incomplete) -- cannot verify the "
                       "recompute artifact was untouched")
    for p in goalposts.artifact_paths:
        if p and os.path.normpath(p) in modified:
            reasons.append("patch directly edits/relocates the recompute artifact %s" % p)
    # (4) isolation tier not downgraded, determinism not loosened (a dropped field fails closed)
    sc = new_ledger.get("scope") or {}
    if goalposts.isolation_tier:
        nt = sc.get("isolation_tier")
        if not nt or _weaker_tier(nt, goalposts.isolation_tier):
            reasons.append("isolation tier downgraded or absent (%s -> %s)"
                           % (goalposts.isolation_tier, nt))
    if goalposts.determinism_mode:
        nd = sc.get("determinism_mode")
        if not nd or _weaker_determinism(nd, goalposts.determinism_mode):
            reasons.append("determinism mode loosened or absent (%s -> %s)"
                           % (goalposts.determinism_mode, nd))
    return (not reasons), reasons


def spec_review(diag, finding):
    """The patch addresses the finding's locator + dimension, not an unrelated change."""
    reasons = []
    if finding and diag.dimension and finding.get("dimension") and diag.dimension != finding["dimension"]:
        reasons.append("patch dimension %r != finding dimension %r"
                       % (diag.dimension, finding["dimension"]))
    if not diag.target_files:
        reasons.append("patch names no target files")
    return (not reasons), reasons


def smell_review(applied_diff, goalposts, new_ledger):
    """The patch is minimal and does not hard-code the number, disable randomness controls, or swap the
    artifact. Heuristic but load-bearing (SWE-Judge: catch the obvious games)."""
    reasons = []
    changed = sum(1 for ln in applied_diff.splitlines()
                  if ln[:1] in "+-" and not ln.startswith(("+++", "---")))
    if changed > 60:
        reasons.append("patch is not minimal (%d changed lines)" % changed)
    # hard-coded number: the claimed value (or a near-literal of it) appears as a NEW constant
    cv = goalposts.claim_value
    if isinstance(cv, (int, float)):
        for lit in {repr(cv), "%g" % cv, "%.4f" % cv}:
            if any(ln.startswith("+") and lit in ln for ln in applied_diff.splitlines()):
                reasons.append("patch hard-codes the claimed value (%s)" % lit)
                break
    # fabricated DATA SERIES: the "feed the check a constant" attack replaces a computed emission with a
    # hard-coded series that happens to recompute to the claim. A literal-match on the headline scalar
    # misses it, so flag a long run of added bare-numeric lines OR an added inline constant array.
    added = [ln[1:] for ln in applied_diff.splitlines()
             if ln.startswith("+") and not ln.startswith("+++")]
    bare_num = sum(1 for ln in added
                   if re.fullmatch(r"\s*[-+]?\d+\.?\d*([eE][-+]?\d+)?,?\s*", ln or ""))
    if bare_num >= 8:
        reasons.append("patch adds %d constant numeric lines -- a hard-coded/fabricated data series, not "
                       "a computed fix" % bare_num)
    else:
        for ln in added:
            if len(re.findall(r"[-+]?\d+\.\d+", ln or "")) >= 12:   # an inline array of float constants
                reasons.append("patch adds an inline constant array of floats -- a fabricated series, "
                               "not a computed fix")
                break
    # disabling determinism controls / seeds (a reproducibility dodge)
    if _touches(applied_diff, "PYTHONHASHSEED", "random.seed", "np.random.seed", "manual_seed",
                "OMP_NUM_THREADS"):
        if any(ln.startswith("-") and t in ln
               for ln in applied_diff.splitlines()
               for t in ("seed", "OMP_NUM_THREADS", "HASHSEED")):
            reasons.append("patch removes a randomness/determinism control")
    return (not reasons), reasons


def build_review(res):
    """The re-verify ran clean: the run did not introduce a new failure (run.json exit_code 0, not
    killed), so the flip is from a genuine green re-execution, not a crash that dodged the recompute."""
    reasons = []
    try:
        run = json.load(open(os.path.join(res["run_dir"], "run.json")))
        if run.get("exit_code") not in (0, None):
            reasons.append("re-verify entrypoint exited non-zero (%s)" % run.get("exit_code"))
        if run.get("killed"):
            reasons.append("re-verify was killed (timeout/OOM)")
    except (OSError, ValueError):
        pass   # absence of run.json is not itself a rejection; the --json verdict already gates clean-ness
    return (not reasons), reasons


def _recompute_column_degenerate(scratch, goalposts):
    """The 'feed the check a constant' attack writes a hard-coded CONSTANT series to the recompute
    artifact (e.g. `oos_rets = [r]*n`) that compounds to the claim. A literal-line smell can't see a
    GENERATED constant, but the OUTPUT gives it away: a real computed return/price/score series VARIES,
    so a many-row recompute column with one distinct value (or ~0 dispersion) is a forgery. Reads the
    re-emitted column the headline metric recomputes from; returns a reason string if degenerate, else
    None."""
    import csv as _csv
    try:
        contract = json.load(open(os.path.join(scratch, CONTRACT_NAME)))
    except (OSError, ValueError):
        return None
    metric = next((m for m in (contract.get("metrics") or [])
                   if m.get("metric_id") == goalposts.metric_id), None)
    if not metric:
        return None
    artifact = metric.get("artifact")
    col = next(iter((metric.get("binding") or {}).values()), None)   # the primary bound column
    if not artifact or not col:
        return None
    try:
        with open(os.path.join(scratch, artifact), newline="") as fh:
            rd = _csv.reader(fh)
            header = next(rd, [])
            if col not in header:
                return None
            idx = header.index(col)
            vals = []
            for row in rd:
                if idx < len(row):
                    try:
                        vals.append(float(row[idx]))
                    except ValueError:
                        pass
    except OSError:
        return None
    finite = [v for v in vals if v == v and v not in (float("inf"), float("-inf"))]
    if len(finite) < 8:
        return None                                          # too short to judge dispersion
    distinct = len({round(v, 12) for v in finite})
    mean = sum(finite) / len(finite)
    var = sum((v - mean) ** 2 for v in finite) / len(finite)
    rel_std = (var ** 0.5) / abs(mean) if mean else (var ** 0.5)
    if distinct <= 1 or rel_std < 1e-9:
        return ("the recompute column %r in %s is a CONSTANT series (%d rows, %d distinct value(s)) -- a "
                "fabricated/hard-coded output, not a computed result" % (col, artifact, len(finite),
                                                                         distinct))
    return None


def review(scratch, diag, goalposts, new_ledger, new_diff, res, finding, *, base_ckpt,
           applied_diff=None):
    """Run reviewer #0 (anti-test-hacking) FIRST; if it fails, short-circuit (the flip is illegitimate).
    Then a FABRICATION check on the re-emitted output, then spec/smell/build. Returns (all_passed, reasons).

    `applied_diff` is the REAL applied PATCH (the code change), captured BEFORE the re-verify re-emits
    artifacts -- the orchestrator passes it so re-emitted CSVs + the run's .calma dir do not leak into
    the gate (which would falsely trip the artifact-touch and minimality checks). When omitted (a
    standalone review of a still-clean scratch), it is recomputed from base_ckpt."""
    from edges.repair import checkpoints as CK
    if applied_diff is None:
        applied_diff = CK.diff_since(scratch, base_ckpt)   # the REAL applied change, not the proposed text
    ok0, r0 = anti_test_hacking(scratch, diag, goalposts, new_ledger, new_diff, applied_diff)
    if not ok0:
        return False, ["ANTI-TEST-HACKING: " + r for r in r0]
    fab = _recompute_column_degenerate(scratch, goalposts)
    if fab:
        return False, ["FABRICATION: " + fab]              # a forged constant output, not a computed fix
    ok1, r1 = spec_review(diag, finding)
    ok2, r2 = smell_review(applied_diff, goalposts, new_ledger)
    ok3, r3 = build_review(res)
    reasons = r1 + r2 + r3
    return (ok1 and ok2 and ok3), reasons


# tier/determinism ordering helpers (no verdict-core import): a fix may not move DOWN these ladders.
_TIER_RANK = {"none": 0, "host-not-isolated": 1, "seatbelt-verified": 2, "bwrap-verified": 2,
              "tier0": 3, "container": 3, "vm": 4, "e2b-firecracker": 4,
              "e2b-firecracker (self-hosted)": 4}
_DET_RANK = {"uncontrolled": 0, "measured-band": 1, "controlled-to-bit": 2}


def _weaker_tier(new, old):
    return _TIER_RANK.get(new, 0) < _TIER_RANK.get(old, 0)


def _weaker_determinism(new, old):
    return _DET_RANK.get(new, 0) < _DET_RANK.get(old, 0)
