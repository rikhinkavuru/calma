"""The patch gate. Reviewer #0 (anti-test-hacking) is non-negotiable: the goalposts must be
byte-identical across the repair, and the re-verify must have judged the same claim/metric/contract/
artifact under the same isolation. Then spec/smell/build reviewers. Returns (all_passed, [reason, ...]).
NEVER imports verdict-core (it reads the new ledger/diff/run.json as data; the firewall stays intact)."""
import hashlib
import json
import os

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
    """True if the unified diff adds/removes lines touching any needle (path or token)."""
    return any(n in diff_text for n in needles)


def anti_test_hacking(scratch, diag, goalposts, new_ledger, new_diff, applied_diff):
    """REJECT if any goalpost moved. The ONLY thing allowed to change is the producing code."""
    reasons = []
    # (1) the contract file was not modified by the patch (and still hashes to the original)
    if _touches(applied_diff, CONTRACT_NAME):
        reasons.append("patch modifies %s (the contract is a goalpost)" % CONTRACT_NAME)
    if _sha_file(os.path.join(scratch, CONTRACT_NAME)) not in (None, goalposts.contract_sha256):
        reasons.append("verify.yaml content changed across the repair (contract_sha256 moved)")
    # (2) the re-verify judged the SAME claim value + metric id (read back from the new ledger's claim)
    nc = next((c for c in (new_ledger.get("claims") or [])
               if c.get("metric") == goalposts.metric_id), None)
    if nc is None:
        reasons.append("re-verify did not judge the original metric %r" % goalposts.metric_id)
    elif nc.get("claimed_value") not in (None, goalposts.claim_value):
        reasons.append("the claimed_value under test changed (%s -> %s)"
                       % (goalposts.claim_value, nc.get("claimed_value")))
    # (3) the bound artifacts the recompute reads were NOT hand-edited (must be RE-EMITTED by the run, so
    #     a post-patch hash MAY differ -- but the patch text must not write/rename/delete it directly)
    for p in goalposts.artifact_paths:
        if p and _touches(applied_diff, p):
            reasons.append("patch directly edits/relocates the recompute artifact %s" % p)
    # (4) isolation tier was not downgraded and determinism mode was not loosened
    sc = new_ledger.get("scope") or {}
    if sc.get("isolation_tier") and goalposts.isolation_tier and \
            _weaker_tier(sc["isolation_tier"], goalposts.isolation_tier):
        reasons.append("isolation tier downgraded (%s -> %s)"
                       % (goalposts.isolation_tier, sc["isolation_tier"]))
    if sc.get("determinism_mode") and goalposts.determinism_mode and \
            _weaker_determinism(sc["determinism_mode"], goalposts.determinism_mode):
        reasons.append("determinism mode loosened (%s -> %s)"
                       % (goalposts.determinism_mode, sc["determinism_mode"]))
    # (5) the binding stayed independently-bound (a REFUTED can't legitimately flip by weakening binding)
    if nc is not None and nc.get("input_binding_status") not in (None, "independently-bound"):
        reasons.append("binding weakened to %r -- a flip via weaker binding is not a fix"
                       % nc.get("input_binding_status"))
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


def review(scratch, diag, goalposts, new_ledger, new_diff, res, finding, *, base_ckpt,
           applied_diff=None):
    """Run reviewer #0 (anti-test-hacking) FIRST; if it fails, short-circuit (the flip is illegitimate).
    Then spec/smell/build. Returns (all_passed, reasons).

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
