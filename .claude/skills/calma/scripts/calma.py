"""calma - the orchestrator. One command chains the whole pipeline and emits the verdict.

  calma.py verify <target> ["<claim>"] [--claim VALUE] [--metric ID] [--run-id ID] [--fail-on MODE]
  calma.py teardown <target> ["<claim>"] [--metric ID]
  calma.py replay <run_dir>
  calma.py attest keygen|sign <run_dir>|verify <bundle> [--key PATH] [--replay]

Steps: draft-or-load contract -> run_hermetic (verified isolation, re-emit raw artifacts) -> recompute
(reference-deterministic) -> compare (calibrated budget + shared verdict()) -> assemble + gate the ledger
-> attest (SBOM manifest + Ed25519-signed DSSE bundle when a key exists) -> strictly-progressive report.
The model READS the report; every number and the verdict label come from the scripts. Writes everything
under <target>/.calma/<run-id>/.
"""
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attest
import compare as CMP
import draft_contract as DC
import ledger as LED
import recipes as RCP
import recompute as RC
import report as REP
import run_hermetic as H
import verdict as V

__version__ = "0.7.0"

QUANT_METRICS = {"total_return", "sharpe", "max_drawdown"}
DEFAULT_TIMEOUT_S = 120
VERIFIED_TIERS = ("seatbelt-verified", "tier0", "container", "vm")


def _trace_enabled():
    """Pipeline narration on stderr: on for interactive terminals, off for pipes/CI/--json
    consumers (stdout is never touched). CALMA_TRACE=1/0 overrides."""
    v = os.environ.get("CALMA_TRACE")
    if v is not None:
        return v not in ("0", "", "off")
    return sys.stderr.isatty()


def _color_enabled():
    """Color/symbols on the verdict only for an interactive stdout, and never when NO_COLOR is set
    (the de-facto standard) - so pipes/CI/files stay plain."""
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


class _Spinner:
    """A single self-updating stderr line ('⠹ label (Ns)') during a long step, so re-execution
    doesn't look like a frozen terminal. Active only on an interactive stderr (never in pipes/CI/
    --json, and off when CALMA_TRACE=0); a no-op otherwise. Cleared on exit, leaving no trace."""
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label):
        self.label = label
        self._on = _trace_enabled() and sys.stderr.isatty()
        self._stop = None
        self._thread = None

    def __enter__(self):
        if not self._on:
            return self
        import threading
        import time as _t
        self._stop = threading.Event()

        def _spin():
            i, t0 = 0, _t.time()
            while not self._stop.wait(0.1):
                sys.stderr.write("\r\x1b[2m  %s %s (%.0fs)\x1b[0m\x1b[K"
                                 % (self.FRAMES[i % len(self.FRAMES)], self.label, _t.time() - t0))
                sys.stderr.flush()
                i += 1
        self._thread = threading.Thread(target=_spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        if self._on and self._stop:
            self._stop.set()
            self._thread.join(timeout=1)
            sys.stderr.write("\r\x1b[K")   # erase the spinner line; the verdict prints fresh
            sys.stderr.flush()
        return False


def _trace(step, msg):
    if not _trace_enabled():
        return
    if sys.stderr.isatty():
        print("  \x1b[2m%-9s\x1b[0m %s" % (step, msg), file=sys.stderr, flush=True)
    else:
        print("  %-9s %s" % (step, msg), file=sys.stderr, flush=True)


def _invocation():
    """How THIS process was invoked, for echo-able hints: `calma` when launched via the wrapper,
    `python3 <path>/calma.py` when the script was run directly. Reproduce/next-step hints printed
    with this prefix are copy-pasteable in the caller's own style."""
    invoked = os.environ.get("CALMA_INVOKED_AS")   # set by the bin/calma wrapper -> copy-pasteable
    if invoked:
        return invoked
    a0 = sys.argv[0] if sys.argv else ""
    if os.path.basename(a0) == "calma.py":
        return "python3 %s" % a0
    return "calma"


def _reconcile_claim(contract, claim, metric):
    """P0 gate: a committed verify.yaml pins HOW to verify (entrypoint, bindings, conventions) -
    it must never silently substitute WHAT is being claimed. The claim under test is the USER's.

      (a) the user's claim names the same metric and the same value (numeric comparison within the
          claim's own reported precision, never string equality) -> proceed, no warning.
      (b) the user names a metric (claim text or --metric) the contract does not pin -> BLOCK:
          CAN'T-CONFIRM with a fix line. Never a verdict about a metric the user didn't claim.
      (c) same metric, different value -> verify the USER's value. Design choice (anti-gaming
          intact): the contract pins bindings/conventions, not the claim value; claim_confirmed
          still requires the metric to be NAMED (claim text or --metric), so an unnamed value
          override can never manufacture a REFUTED. Other pinned claims are demoted to
          reproduction-only so no verdict is ever shown about a claim the user didn't make.
      (d) the user's text contains no checkable number -> verify the committed claim, but SAY SO.

    Returns (note, block_finding); block_finding is non-None only for (b). May mutate `contract`
    in-memory for (c) - the committed file is never rewritten."""
    mets = contract.get("metrics") or []
    if (claim is None and metric is None) or not mets:
        return None, None
    cv, hint = DC.parse_claim(claim)
    user_metric = metric or hint
    head = next((m for m in mets if m.get("headline")), mets[0])
    pinned_ids = [m.get("metric_id") for m in mets if m.get("metric_id")]
    if user_metric and user_metric not in pinned_ids:
        named_via = ("--metric %s conflicts with verify.yaml (it pins %r)"
                     % (metric, head.get("metric_id"))) if metric \
            else ("your claim is about %r but verify.yaml pins %r"
                  % (user_metric, head.get("metric_id")))
        return None, {
            "id": "f-claim-contract", "claim_id": "c1", "dimension": "contract-grounding",
            "severity": "major", "status": "open", "confidence": "deterministic",
            "fixable_by": "author",
            "locator": "%s - refusing to verify a claim you didn't make" % named_via,
            "unblock": "add a %s metric to verify.yaml, or move/remove verify.yaml to auto-detect"
                       % user_metric,
            "reverify": {"kind": "static-reread", "source": "contract",
                         "expected": "the claim's metric is pinned in verify.yaml"},
        }
    if cv is None:
        if claim is None:
            return None, None  # bare --metric that matches the contract: nothing to reconcile
        return ("your text contains no checkable claim; verifying the committed claim: %s %s"
                % (head.get("metric_id"),
                   REP.fmt_value(head.get("claimed_value"), head.get("metric_id")))), None
    target_m = next((m for m in mets if m.get("metric_id") == user_metric), head) \
        if user_metric else head
    committed_v = target_m.get("claimed_value")
    prec = DC.claim_precision(claim)
    tol = prec if prec is not None else (1e-9 + 1e-9 * abs(cv))
    if committed_v is not None and abs(cv - committed_v) <= tol:
        return None, None  # (a): numerically the same claim at the claim's own precision
    # (c): the user's value replaces the committed one for THIS run (file untouched)
    target_m["claimed_value"] = cv
    target_m["claimed_precision"] = prec
    target_m["headline"] = True
    target_m["claim_confirmed"] = user_metric is not None
    if isinstance(claim, str):
        target_m["convention"] = DC.infer_convention(claim, target_m.get("metric_id")) \
            or target_m.get("convention")
    for m in mets:  # never show a verdict about a committed claim the user didn't make
        if m is not target_m and m.get("claimed_value") is not None:
            m["claimed_value"] = None
            m["claimed_precision"] = None
            m["headline"] = False
    return ("checking YOUR claim (%s %s) - verify.yaml pins the bindings, but its committed "
            "claim value (%s) is not what is being verified"
            % (target_m.get("metric_id"), "%g" % cv,
               "%g" % committed_v if isinstance(committed_v, (int, float)) else committed_v)), None


def _not_verified(metric_ids):
    """Honest 'what we did NOT check' list, phrased for the family actually verified."""
    if any(m in QUANT_METRICS for m in metric_ids):
        return ["deflated-Sharpe / PBO overfitting stats (CLI roadmap)",
                "survivorship-free vendor data (managed roadmap)"]
    return ["leakage re-run (roadmap)", "overfitting statistics (roadmap)"]


def _inconclusive_ledger(run_res, finding=None, target_name=None):
    """A valid INCONCLUSIVE ledger for paths where re-execution could not produce a verdict.
    The finding carries the actionable unblock (the 'here's the fix' line)."""
    vi = {"killed": run_res.get("killed", False),
          "exit_codes": [run_res.get("exit_code", 0)]}
    led = {
        "schema": "calma/ledger@1",
        "claims": [{"id": "c1", "headline": True, "headline_confidence": 0.0,
                    "verdict": V.INCONCLUSIVE, "input_binding_status": "author-asserted",
                    "verdict_inputs": vi, "verdict_status": "stable", "verdict_history": [],
                    "waivable": False}],
        "findings": [finding] if finding else [],
        "scope": {"isolation_tier": run_res.get("isolation_tier"),
                  "determinism_mode": run_res.get("determinism_mode")},
        "repo_verdict": V.INCONCLUSIVE,
    }
    if target_name:
        led["target"] = target_name
    return led


def _assemble_ledger(contract, diff, run_res):
    claims, findings = [], []
    for i, m in enumerate(diff["metrics"]):
        cid = "c%d" % (i + 1)
        vi = m["verdict_inputs"]
        label = m["verdict"]
        claim = {
            "id": cid, "headline": m["headline"],
            "headline_confidence": V.confidence(vi, label),
            "metric": m["metric_id"], "claimed_value": m["claimed"], "recomputed_value": m["recomputed"],
            "verdict": label, "input_binding_status": vi["binding_status"],
            "verdict_inputs": vi, "verdict_status": "stable", "verdict_history": [], "waivable": False,
            "recipe_authority": "canonical", "set_maturity": "reviewed",
            "reason": m.get("reason"),
        }
        if label == V.REFUTED:
            claim["driving_dimension"] = "metric-mismatch"
            _rd = run_res.get("run_dir", "./.calma/run")
            try:  # show a short cwd-relative run dir (no $HOME leak) when it's under cwd
                _rel = os.path.relpath(_rd)
                _rd = _rel if not _rel.startswith("..") else _rd
            except ValueError:
                pass
            claim["reproduction_or_reverify"] = {
                "kind": "requires-reexecution",
                "command": "%s replay %s" % (_invocation(), _rd),
                "manifest_ref": run_res.get("manifest_ref", "sha256:unavailable"),
                "expected": "recomputed differs from claimed beyond the calibrated budget",
            }
            findings.append({
                "id": "f-%s-mm" % cid, "claim_id": cid, "dimension": "metric-mismatch",
                "severity": "blocker", "status": "open", "confidence": "deterministic",
                "fixable_by": "author",
                "locator": "claimed %s but the code recomputes %s" % (m["claimed"], m["recomputed"]),
                "reverify": {"kind": "requires-reexecution", "source": m.get("metric_id"),
                             "expected": "recomputed within budget of claimed"},
            })
        claims.append(claim)
    # FLAKY: two identical re-executions disagreed -> blocking finding with the seed fix
    recheck = run_res.get("determinism_recheck")
    if recheck and not recheck.get("stable", True):
        findings.append({
            "id": "f-flaky", "claim_id": claims[0]["id"] if claims else None,
            "dimension": "reproducibility", "severity": "blocker", "status": "open",
            "confidence": "deterministic", "fixable_by": "author",
            "locator": "outputs differ across identical re-runs (FLAKY): %s"
                       % ", ".join(recheck.get("differing_artifacts", [])[:4]),
            "unblock": "set a fixed seed (and write outputs deterministically), then re-run calma verify",
            "reverify": {"kind": "requires-reexecution", "source": "run",
                         "expected": "identical artifacts across re-runs"},
        })
    # a failed re-execution is itself a blocking finding (the verdict guard already forced INCONCLUSIVE)
    rc = run_res.get("exit_code", 0)
    if rc not in (0, 3, 4):
        findings.append({
            "id": "f-run-fail", "claim_id": claims[0]["id"] if claims else None,
            "dimension": "reproducibility", "severity": "blocker", "status": "open",
            "confidence": "deterministic", "fixable_by": "author",
            "locator": "the entrypoint exited non-zero - the result was NOT reproduced"
                       + ((" | stderr: " + run_res["stderr_tail"].strip()[-200:])
                          if run_res.get("stderr_tail") else ""),
            "unblock": "make the entrypoint run to completion (exit 0), then re-run calma verify",
            "reverify": {"kind": "requires-reexecution", "source": "run",
                         "expected": "entrypoint exits 0"},
        })
    # baseline corroborating finding
    bl = diff.get("baseline")
    if bl and bl.get("finding") and claims:
        findings.append({
            "id": "f-baseline", "claim_id": claims[0]["id"], "dimension": "baseline",
            "severity": "major", "status": "open", "confidence": "deterministic", "fixable_by": "author",
            "locator": bl["finding"],
            "reverify": {"kind": "requires-reexecution", "source": "baseline",
                         "expected": "strategy edge over baseline > 0"},
        })
    metric_ids = [m["metric_id"] for m in diff["metrics"]]
    # surface which binding was auto-picked (the one surface the producer influences)
    binding_note = None
    for m in contract.get("metrics", []):
        if m.get("binding_source") == "auto-detected" and m.get("claimed_value") is not None:
            binding_note = ("%s over %s (auto-detected binding %s) - pass --metric to override"
                            % (m["metric_id"], m.get("artifact"), m.get("binding")))
    led = {
        "schema": "calma/ledger@1", "claims": claims, "findings": findings,
        "scope": {
            "isolation_tier": run_res.get("isolation_tier"),
            "determinism_mode": run_res.get("determinism_mode"),
            "run_network": run_res.get("run_network"),
            "reproducibility_scope": "same-platform",
            "determinism_recheck": (
                "stable across %d re-runs" % run_res["determinism_recheck"]["reruns"]
                if run_res.get("determinism_recheck", {}).get("stable")
                else ("FLAKY across re-runs" if run_res.get("determinism_recheck") else None)),
            "binding_note": binding_note,
            "families": {"reproducibility": "checked" if run_res.get("exit_code", 0) == 0 else "FAILED",
                         "recomputation": "checked",
                         "baseline": "checked" if bl else "not-applicable"},
            "not_verified": _not_verified(metric_ids),
        },
        "repo_verdict": None,
    }
    led["repo_verdict"] = LED.compute_repo_verdict(led)
    return led


def _input_fingerprint(target, contract):
    """Content-address everything the verdict depends on: the contract (minus draft notes), the
    entrypoint bytes, and every bound artifact's bytes. Same fingerprint => the prior verdict is the
    verdict (re-verification would re-derive it from identical inputs)."""
    h = hashlib.sha256()
    # the verifier's own version and the interpreter line are part of the key: upgrading either
    # invalidates the cache (a different verifier run is a different computation)
    h.update(("calma-cache@1|calma=%s|py=%d.%d\n"
              % (__version__, sys.version_info[0], sys.version_info[1])).encode())
    h.update(json.dumps({k: v for k, v in contract.items() if not str(k).startswith("_")},
                        sort_keys=True).encode())
    rt = os.path.realpath(target)
    paths = []
    entry = (contract.get("run") or {}).get("entrypoint")
    if entry and entry != "MANUAL":
        paths.append(entry)
    for a in contract.get("artifacts", []):
        if isinstance(a, dict) and a.get("path"):
            paths.append(a["path"])
    for rel in sorted(set(paths)):
        full = os.path.realpath(os.path.join(rt, rel))
        if full != rt and not full.startswith(rt + os.sep):
            continue
        h.update(rel.encode() + b"\x00")
        try:
            with open(full, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
        except OSError:
            h.update(b"<missing>")
    return h.hexdigest()


def _ledger_sha256(led_path):
    """sha256 of the ledger file's exact bytes, or None when unreadable. The cache key for
    'is the run dir still holding the ledger this cache entry was derived from'."""
    h = hashlib.sha256()
    try:
        with open(led_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _cached_result(target, fingerprint):
    """Return the prior result for this fingerprint, or None. Only definite verdicts are served from
    cache (an INCONCLUSIVE may have been environmental - it always re-runs).

    Run dirs are shared across claims (run_id defaults to "run"), so a later verification of a
    DIFFERENT claim overwrites the ledger this entry pointed at. The entry therefore pins the
    exact ledger bytes (ledger_sha256) it was stored against: any mismatch - or a cached verdict
    that disagrees with the ledger on disk - rejects the hit and falls through to a fresh run.
    Without this, verify A (REFUTED) / verify B (CONFIRMED) / re-verify A would serve B's
    CONFIRMED ledger for claim A."""
    cache_path = os.path.join(target, ".calma", "cache.json")
    try:
        cache = json.load(open(cache_path))
    except (OSError, ValueError):
        return None
    ent = cache.get(fingerprint)
    if not ent:
        return None
    run_dir = os.path.join(target, ".calma", ent.get("run_id", ""))
    led_path = os.path.join(run_dir, "ledger.json")
    if not ent.get("ledger_sha256") or _ledger_sha256(led_path) != ent["ledger_sha256"]:
        return None  # the run dir has been overwritten by another claim (or entry is pre-0.6.1)
    try:
        led = json.load(open(led_path))
    except (OSError, ValueError):
        return None
    if led.get("repo_verdict") != ent.get("repo_verdict"):
        return None  # cached verdict and stored ledger disagree - never serve it
    code, summary = LED.validate_obj(led)
    if led.get("repo_verdict") not in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "MIXED"):
        return None
    rendered = ("(cached: code, data, and claim unchanged since the last verification - "
                "pass --force to re-execute)\n") + REP.render(led)
    return {"gate_exit": code, "gate": summary, "repo_verdict": led["repo_verdict"],
            "report": rendered, "teardown": REP.teardown_card(led), "run_dir": run_dir,
            "ledger": led, "cached": True}


def _store_cache(target, fingerprint, run_id, repo_verdict):
    if repo_verdict not in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "MIXED"):
        return
    led_sha = _ledger_sha256(os.path.join(target, ".calma", run_id, "ledger.json"))
    if led_sha is None:
        return  # no ledger on disk -> nothing a future hit could be checked against
    cache_path = os.path.join(target, ".calma", "cache.json")
    try:
        cache = json.load(open(cache_path))
    except (OSError, ValueError):
        cache = {}
    cache[fingerprint] = {"run_id": run_id, "repo_verdict": repo_verdict,
                          "ledger_sha256": led_sha}
    # atomic: a crash mid-write must never leave a truncated cache.json behind
    tmp = cache_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(cache, fh, indent=2)
    os.replace(tmp, cache_path)


def _artifact_hashes(target, contract):
    """Hash every bound artifact (not the entrypoint): the re-run comparison set for FLAKY detection."""
    out = {}
    rt = os.path.realpath(target)
    for a in contract.get("artifacts", []):
        if not (isinstance(a, dict) and a.get("path")):
            continue
        full = os.path.realpath(os.path.join(rt, a["path"]))
        if full != rt and not full.startswith(rt + os.sep):
            continue
        h = hashlib.sha256()
        try:
            with open(full, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            out[a["path"]] = h.hexdigest()
        except OSError:
            out[a["path"]] = "<missing>"
    return out


def _redact_home(text):
    """$HOME never enters ledgers, findings, or bundles via captured output tails."""
    if not text:
        return text
    home = os.path.expanduser("~")
    for h in sorted({home, os.path.realpath(home)}, key=len, reverse=True):
        if h and h != "/":
            text = text.replace(h, "~")
    return text


def _first_run_notice(target, tier):
    """The one-time trust footnote (what calma did to this machine + the counterparty escape hatch).
    Returns the line ONCE per target dir (marker in .calma/), else None. The caller prints it AFTER
    the verdict so the answer leads and this reads as the footnote it is - never above the result."""
    marker = os.path.join(target, ".calma", "trust_notice")
    if os.path.exists(marker):
        return None
    try:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w") as fh:
            fh.write("shown\n")
    except OSError:
        return None
    return ("calma re-executed this project's code in a sandbox (tier: %s) - "
            "pass --trust third-party for counterparty code" % tier)


def _resolve_timeout(cli_timeout, contract):
    """The re-execution wall-clock budget: --timeout wins, then run.timeout in verify.yaml,
    then the 120s default. Clamped to [1, 86400]."""
    t = cli_timeout if cli_timeout is not None else (contract.get("run") or {}).get("timeout")
    try:
        t = int(t) if t is not None else DEFAULT_TIMEOUT_S
    except (TypeError, ValueError):
        t = DEFAULT_TIMEOUT_S
    return max(1, min(t, 86400))


def verify(target, claim=None, metric=None, run_id="run", force=False, check_determinism=False,
           trust="own-code", timeout=None):
    target = os.path.realpath(target)
    if trust not in ("own-code", "third-party"):
        raise ValueError("--trust must be own-code or third-party (got %r)" % trust)
    if metric and RCP.get(metric) is None:
        import difflib
        close = difflib.get_close_matches(metric, RCP.ids(), n=3, cutoff=0.4)
        # common slip: passing a binding TAG ("return", "prediction") instead of a recipe id
        tag_hits = sorted(m for m in RCP.ids()
                          if metric in (RCP.get(m).manifest.get("required_tags") or []))[:4]
        hint = ("did you mean: %s?" % ", ".join(close)) if close else ""
        if tag_hits:
            hint = ("%r is a binding tag, not a recipe - recipes that bind it: %s. %s"
                    % (metric, ", ".join(tag_hits), hint)).strip()
        raise ValueError("no recipe named %r. %s (full list: calma recipes)"
                         % (metric, hint or "run `calma recipes` for the full list"))
    if not os.path.isdir(target):
        raise ValueError("target directory does not exist: %s" % target)
    if not any(n for n in os.listdir(target) if n not in (".calma", ".DS_Store")):
        raise ValueError("nothing to verify: %s is empty (expected code + machine-readable outputs)" % target)
    run_dir = os.path.join(target, ".calma", run_id)
    os.makedirs(run_dir, exist_ok=True)

    committed = os.path.join(target, "verify.yaml")
    claim_note = block_finding = None
    first_run_notice = None  # set when the run block executes; safe default for early/other paths
    if os.path.exists(committed):
        contract_path = committed
        contract = DC.load_contract(contract_path)
        errs = DC.validate_contract(contract)
        if errs:
            raise ValueError("verify.yaml is invalid: %s\na minimal valid verify.yaml:\n%s"
                             % ("; ".join(errs), DC.CONTRACT_EXAMPLE))
        # the claim under test is the USER's: reconcile it against the committed contract instead
        # of silently substituting the contract's claim (see _reconcile_claim). The note lands
        # at the top of the rendered report (and in --json as "note").
        claim_note, block_finding = _reconcile_claim(contract, claim, metric)
    else:
        contract = DC.draft(target, claim=claim, metric=metric)
        contract_path = os.path.join(run_dir, "verify.yaml")
        json.dump(contract, open(contract_path, "w"), indent=2)

    # --trust third-party overrides the contract's trust posture AT RUNTIME (in memory only -
    # committed and drafted contracts keep their own-code default): run_hermetic then refuses
    # to execute unless a verified container/VM tier is live.
    if trust == "third-party":
        contract.setdefault("env", {})["trust"] = "untrusted-third-party"
    eff_timeout = _resolve_timeout(timeout, contract)

    m0 = (contract.get("metrics") or [{}])[0]
    if m0.get("metric_id"):
        _trace("contract", "%s: claim binds %s -> recipe %s (%s)"
               % ("verify.yaml (committed)" if contract_path == committed else "drafted",
                  "%s::%s" % (m0.get("artifact"), ", ".join(map(str, (m0.get("binding") or {}).values()))),
                  m0["metric_id"], m0.get("binding_status", "ungraded")))
    else:
        _trace("contract", "drafted: entrypoint %s (no metric bound yet - outputs may only exist post-run)"
               % contract.get("run", {}).get("entrypoint"))

    # the cache: same contract + same entrypoint bytes + same artifact bytes => same verdict.
    # Inline/agent-loop use re-verifies only what changed; --force always re-executes, and a
    # determinism check is new evidence, so it never reads the cache (it still stores).
    if block_finding is None and not force and not check_determinism:
        hit = _cached_result(target, _input_fingerprint(target, contract))
        if hit:
            _trace("cache", "code+data+claim unchanged -> prior verdict (--force re-executes)")
            if claim_note:
                hit["claim_note"] = claim_note
                hit["report"] = "note: %s\n\n%s" % (claim_note, hit["report"])
            return hit

    diff = None
    refused = killed = False
    entry = contract.get("run", {}).get("entrypoint")
    if block_finding is not None:
        # P0 gate: the user's claim names a metric the committed contract does not pin. Never
        # substitute the contract's claim - degrade to INCONCLUSIVE with the exact unblock.
        run_res = {"exit_code": 0, "isolation_tier": "n/a", "killed": False, "run_dir": run_dir}
        led = _inconclusive_ledger(run_res, finding=block_finding,
                                   target_name=os.path.basename(target))
    elif entry == "MANUAL":
        run_res = {"exit_code": 3, "isolation_tier": "n/a", "killed": False, "run_dir": run_dir}
        led = _inconclusive_ledger(run_res, finding={
            "id": "f-entrypoint", "claim_id": "c1", "dimension": "contract-grounding",
            "severity": "major", "status": "open", "confidence": "deterministic", "fixable_by": "author",
            "locator": "no entrypoint detected (looked for %s, then a single script in the root)"
                       % ", ".join(DC.ENTRYPOINT_CANDIDATES),
            "unblock": "name your script main.py/run.py, or set run.entrypoint in verify.yaml",
            "reverify": {"kind": "static-reread", "source": "contract", "expected": "an entrypoint exists"},
        }, target_name=os.path.basename(target))
        run_res["run_dir"] = run_dir
    else:
        import time as _time
        _trace("re-run", "executing %s in the sandbox (network off)..."
               % contract.get("run", {}).get("entrypoint"))
        _t0 = _time.time()
        with _Spinner("re-executing %s" % contract.get("run", {}).get("entrypoint")):
            run_res = H.run(contract_path, base=target, timeout=eff_timeout,
                            trust_override=("untrusted-third-party" if trust == "third-party"
                                            else None))
        run_res["run_dir"] = run_dir
        for _tail in ("stdout_tail", "stderr_tail"):
            if run_res.get(_tail):
                run_res[_tail] = _redact_home(run_res[_tail])
        _trace("re-run", "exit %s in %.1fs | isolation %s | determinism %s"
               % (run_res.get("exit_code"), _time.time() - _t0,
                  run_res.get("isolation_tier"), run_res.get("determinism_mode")))
        first_run_notice = _first_run_notice(target, run_res.get("isolation_tier"))
        if run_res.get("exit_code") in (3, 4):
            # refused (no isolation for untrusted) or killed -> INCONCLUSIVE, never a verdict
            refused = run_res.get("exit_code") == 3
            killed = run_res.get("exit_code") == 4
            if killed:
                unblock = ("the run timed out after %ds - raise it with --timeout SECONDS "
                           "(or run.timeout in verify.yaml), or make the entrypoint faster"
                           % eff_timeout)
            elif trust == "third-party":
                unblock = ("this code is marked --trust third-party and the achieved isolation "
                           "tier (%s) is not a verified container/VM - refusing to execute it; "
                           "verify on a host with one, or pass --trust own-code if you wrote "
                           "this code" % run_res.get("isolation_tier"))
            else:
                unblock = run_res.get("reason", "isolation was refused") + \
                    " - run on a host with a verified sandbox, or mark trust: own-code if this is your code"
            led = _inconclusive_ledger(run_res, finding={
                "id": "f-run-blocked", "claim_id": "c1",
                "dimension": "reproducibility" if run_res.get("exit_code") == 4 else "isolation-security",
                "severity": "major", "status": "open", "confidence": "deterministic",
                "fixable_by": "operator",
                "locator": run_res.get("reason", "execution did not complete"),
                "unblock": unblock,
                "reverify": {"kind": "requires-reexecution", "source": "run",
                             "expected": "the entrypoint completes under a verified tier"},
            }, target_name=os.path.basename(target))
        else:
            # chicken-and-egg: on a fresh project the outputs only exist AFTER the first run, so a
            # pre-run draft finds no metrics. Re-draft from the artifacts the run just produced.
            if not contract.get("metrics") and contract_path != committed \
                    and run_res.get("exit_code") == 0:
                redrafted = DC.draft(target, claim=claim, metric=metric)
                if redrafted.get("metrics"):
                    contract = redrafted
                    json.dump(contract, open(contract_path, "w"), indent=2)
            # optional FLAKY check: re-execute a second time and diff the artifact bytes. Identical
            # inputs producing different outputs is itself a verdict-blocking finding (G1c).
            outputs_unstable = False
            if check_determinism and run_res.get("exit_code") == 0:
                h1 = _artifact_hashes(target, contract)
                run2 = H.run(contract_path, base=target, timeout=eff_timeout)
                if run2.get("exit_code") == 0:
                    h2 = _artifact_hashes(target, contract)
                    unstable_paths = sorted(p for p in set(h1) | set(h2) if h1.get(p) != h2.get(p))
                else:
                    unstable_paths = ["<second run exited %s>" % run2.get("exit_code")]
                outputs_unstable = bool(unstable_paths)
                run_res["determinism_recheck"] = {
                    "reruns": 2, "stable": not outputs_unstable,
                    "differing_artifacts": unstable_paths,
                }
            rec = RC.recompute_contract(contract_path, base=target)
            json.dump(rec, open(os.path.join(run_dir, "recompute.json"), "w"), indent=2)
            for _rm in rec.get("metrics", []):
                if not _rm.get("degenerate"):
                    _trace("recompute", "%s rebuilt from raw %s: %s (deterministic kernels, "
                           "%dx identical)"
                           % (_rm.get("metric_id"), _rm.get("artifact", "outputs"),
                              REP.fmt_value(_rm.get("value"), _rm.get("metric_id")),
                              _rm.get("k", 1)))
            man = attest.manifest_for(os.path.join(target, "runs")) if os.path.isdir(os.path.join(target, "runs")) else {}
            json.dump(man, open(os.path.join(run_dir, "manifest.json"), "w"), indent=2)
            run_res["manifest_ref"] = "sha256:" + man.get("manifest_sha256", "none")
            run_res["_manifest"] = man
            if man.get("files"):
                _trace("manifest", "%d raw artifacts content-hashed (root %s...)"
                       % (len(man["files"]), man.get("manifest_sha256", "")[:12]))
            # committed multi-metric contracts: re-derive each metric's binding from the now-emitted
            # data + confirm its claim target, so a fabricated SECONDARY metric REFUTES (-> repo MIXED)
            # instead of being silently demoted. Never downgrades an author-declared status.
            if contract_path == committed:
                DC.regrade_committed(contract, target)
            diff = CMP.compare(rec, contract, isolation_tier=run_res.get("isolation_tier", "none"),
                               determinism_mode=run_res.get("determinism_mode", "uncontrolled"),
                               untrusted=(contract.get("env", {}).get("trust") == "untrusted-third-party"),
                               killed=run_res.get("killed", False),
                               exit_codes=[run_res.get("exit_code", 0)],
                               outputs_unstable=outputs_unstable)
            json.dump(diff, open(os.path.join(run_dir, "diff.json"), "w"), indent=2)
            for _dm in diff.get("metrics", []):
                if _dm.get("claimed") is not None:
                    _trace("compare", "claimed %s vs recomputed %s -> %s"
                           % (REP.fmt_value(_dm.get("claimed"), _dm.get("metric_id")),
                              REP.fmt_value(_dm.get("recomputed"), _dm.get("metric_id")),
                              "within the calibrated budget" if _dm.get("verdict") in
                              ("CONFIRMED", "CONFIRMED-WITH-CAVEATS")
                              else "OUTSIDE the calibrated budget"))
            led = _assemble_ledger(contract, diff, run_res)
            if not diff["metrics"]:
                # P1-5: a committed contract that pins NO artifacts next to recomputable outputs is
                # the cause - name verify.yaml in the fix instead of asking for files that exist
                candidates = []
                if contract_path == committed and not contract.get("artifacts"):
                    candidates = [a["path"] for a in DC._scan_csvs(target)
                                  if any(s["tag"] for s in a["columns"].values())]
                if candidates:
                    led["findings"].append({
                        "id": "f-no-metric", "claim_id": None, "dimension": "contract-grounding",
                        "severity": "major", "status": "open", "confidence": "deterministic",
                        "fixable_by": "author",
                        "locator": "verify.yaml pins no artifacts, but recomputable outputs exist (%s)"
                                   % ", ".join(candidates[:3]),
                        "unblock": "your verify.yaml lists no artifacts - add %s (with its columns) "
                                   "to verify.yaml, or delete verify.yaml to auto-detect"
                                   % candidates[0],
                        "reverify": {"kind": "static-reread", "source": "contract",
                                     "expected": "verify.yaml pins at least one artifact"},
                    })
                else:
                    led["findings"].append({
                        "id": "f-no-metric", "claim_id": None, "dimension": "contract-grounding",
                        "severity": "major", "status": "open", "confidence": "deterministic",
                        "fixable_by": "author",
                        "locator": "no machine-readable output with a recognizable metric column was found",
                        "unblock": "write the result to a CSV the recompute can read "
                                   "(e.g. predictions.csv with y_true,y_pred / returns.csv with strat_return)",
                        "reverify": {"kind": "artifact-recheck", "source": "artifacts",
                                     "expected": "a bindable metric column exists"},
                    })

    led.setdefault("target", os.path.basename(target))
    _man = run_res.get("_manifest")
    if _man:
        json.dump(attest.intoto_statement(_man, led["target"], led["repo_verdict"], led.get("scope")),
                  open(os.path.join(run_dir, "attestation.json"), "w"), indent=2)
        json.dump(attest.ml_bom(_man, led["target"], led.get("scope")),
                  open(os.path.join(run_dir, "mlbom.json"), "w"), indent=2)
    json.dump(led, open(os.path.join(run_dir, "ledger.json"), "w"), indent=2)
    # auto-sign when a local key exists: the bundle is the counterparty artifact, never load-bearing
    # for the verdict itself, so a signing failure must not fail the verification
    if attest.load_signing_key() is not None:
        try:
            bundle, _out = attest.sign_run(run_dir)
            _trace("attest", "verdict signed: DSSE + SSHSIG, keyid %s..."
                   % bundle["envelope"]["signatures"][0]["keyid"][:16])
        except (OSError, ValueError):
            pass
    code, summary = LED.validate_obj(led)
    _trace("verdict", "%s - every label re-derived byte-for-byte from its stored inputs"
           % led.get("repo_verdict"))
    rendered = REP.render(led, diff)                                  # plain - for the file + callers
    display = REP.render(led, diff, color=_color_enabled())           # symbols/color - for the terminal
    if claim_note:
        rendered = "note: %s\n\n%s" % (claim_note, rendered)
        display = "note: %s\n\n%s" % (claim_note, display)
    open(os.path.join(run_dir, "report.txt"), "w").write(rendered)
    card = REP.teardown_card(led)
    if card:
        open(os.path.join(run_dir, "teardown.txt"), "w").write(card)
    _store_cache(target, _input_fingerprint(target, contract), run_id, led["repo_verdict"])
    # append-only, human-readable history: one JSON line per verification (the audit trail is a feature)
    c0 = (led.get("claims") or [{}])[0]
    try:
        import time
        with open(os.path.join(target, ".calma", "history.jsonl"), "a") as fh:
            fh.write(json.dumps({
                "ts": int(time.time()), "run_id": run_id, "verdict": led["repo_verdict"],
                "metric": c0.get("metric"), "claimed": c0.get("claimed_value"),
                "recomputed": c0.get("recomputed_value"),
                "isolation": led.get("scope", {}).get("isolation_tier"),
                "calma": __version__,
            }) + "\n")
    except OSError:
        pass
    return {"gate_exit": code, "gate": summary, "repo_verdict": led["repo_verdict"],
            "report": rendered, "display": display, "first_run_notice": first_run_notice,
            "teardown": card, "run_dir": run_dir, "ledger": led,
            "cached": False, "claim_note": claim_note, "refused": refused, "killed": killed}


def replay(run_dir):
    """Re-run a prior verification from its saved run dir and check the verdict reproduces.
    Accepts the path printed on a REFUTED card (<target>/.calma/<id>). Exit 0 iff reproduced."""
    run_dir = os.path.realpath(run_dir)
    prior_path = os.path.join(run_dir, "ledger.json")
    if not os.path.exists(prior_path):
        raise ValueError("no ledger.json under %s - pass the .calma/<run-id> dir from a previous verify" % run_dir)
    prior = json.load(open(prior_path))
    target = os.path.dirname(os.path.dirname(run_dir))
    # replay under the SAME contract terms: reuse the prior run's claim + metric
    claim = metric = None
    prior_contract = os.path.join(run_dir, "verify.yaml")
    if os.path.exists(prior_contract):
        pc_obj = DC.load_contract(prior_contract)
        mets = pc_obj.get("metrics") or [{}]
        claim, metric = mets[0].get("claimed_value"), mets[0].get("metric_id")
    res = verify(target, claim=claim, metric=metric,
                 run_id=os.path.basename(run_dir) + "-replay", force=True)
    same_verdict = res["repo_verdict"] == prior.get("repo_verdict")
    pc = (prior.get("claims") or [{}])[0]
    nc = (res["ledger"].get("claims") or [{}])[0]
    pv, nv = pc.get("recomputed_value"), nc.get("recomputed_value")
    same_value = (pv is None and nv is None) or \
        (isinstance(pv, float) and isinstance(nv, float) and abs(pv - nv) <= 1e-9 + 1e-6 * abs(pv))
    ok = same_verdict and same_value
    lines = ["CALMA REPLAY  -  %s" % prior.get("target", os.path.basename(target)),
             "  prior:    %s  (recomputed %s)" % (prior.get("repo_verdict"), pv),
             "  replayed: %s  (recomputed %s)" % (res["repo_verdict"], nv),
             "  %s" % ("REPRODUCED - the verdict holds under re-execution" if ok
                       else "DID NOT REPRODUCE - the prior verdict no longer holds")]
    return ok, "\n".join(lines)


def stats(target):
    """Summarize the append-only verification history for a target. Returns (data, rendered)."""
    target = os.path.realpath(target)
    path = os.path.join(target, ".calma", "history.jsonl")
    if not os.path.exists(path):
        raise ValueError("no verification history at %s - run `calma verify` first" % path)
    rows = []
    for line in open(path):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    # teardown's internal re-verify is bookkeeping, not a new verification - count it separately
    verifs = [r for r in rows if r.get("run_id") != "teardown"]
    teardowns = len(rows) - len(verifs)
    counts = {}
    for r in verifs:
        v = r.get("verdict", "?")
        counts[v] = counts.get(v, 0) + 1
    lines = ["CALMA STATS  -  %s" % os.path.basename(target),
             "  verifications: %d" % len(verifs)]
    if teardowns:
        lines.append("  teardown re-checks: %d (not counted as verifications)" % teardowns)
    for v in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "MIXED", "INCONCLUSIVE"):
        if counts.get(v):
            lines.append("  %-24s %d" % (v, counts[v]))
    catches = [r for r in verifs if r.get("verdict") in ("REFUTED", "MIXED")]
    for c in catches[-3:]:
        lines.append("  catch: claimed %s -> recomputed %s (%s)"
                     % (REP.fmt_value(c.get("claimed"), c.get("metric")),
                        REP.fmt_value(c.get("recomputed"), c.get("metric")), c.get("metric")))
    # the zero-touch hook's breadcrumb trail (auto-verifications it fired or skipped)
    auto = {"total": 0, "events": {}, "claims": []}
    apath = os.path.join(target, ".calma", "auto_history.jsonl")
    if os.path.exists(apath):
        for line in open(apath):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            auto["total"] += 1
            auto["events"][r.get("event", "?")] = auto["events"].get(r.get("event", "?"), 0) + 1
            if r.get("claim") and r["claim"] not in auto["claims"]:
                auto["claims"].append(r["claim"])
        if auto["total"]:
            lines.append("  zero-touch hook: %d events (%s); %d distinct claims seen"
                         % (auto["total"],
                            ", ".join("%s %d" % (k, v)
                                      for k, v in sorted(auto["events"].items())),
                            len(auto["claims"])))
    return {"total": len(verifs), "teardowns": teardowns, "counts": counts,
            "auto": auto}, "\n".join(lines)


def _json_result(res):
    """The agent-consumable structured verdict (stable shape; no prose parsing needed). The top-level
    metric/claimed/recomputed mirror the FIRST claim for back-compat; `metrics` carries ALL of them so
    a multi-metric contract's every verdict is reachable without parsing the ledger."""
    led = res["ledger"]
    claims = led.get("claims") or [{}]
    c0 = claims[0]
    return {
        "verdict": res["repo_verdict"],
        "clean": res["gate_exit"] == 0,
        "gate_exit": res["gate_exit"],
        "cached": bool(res.get("cached")),
        "confidence": c0.get("headline_confidence"),
        "metric": c0.get("metric"),
        "claimed": c0.get("claimed_value"),
        "recomputed": c0.get("recomputed_value"),
        "reason": c0.get("reason"),
        "metrics": [{"metric": c.get("metric"), "verdict": c.get("verdict"),
                     "claimed": c.get("claimed_value"), "recomputed": c.get("recomputed_value"),
                     "headline": bool(c.get("headline")), "reason": c.get("reason")}
                    for c in claims if c.get("metric")],
        "fix": REP.fix_line(led) if res["repo_verdict"] != "CONFIRMED" else None,
        "note": res.get("claim_note"),
        "isolation_tier": led.get("scope", {}).get("isolation_tier"),
        "determinism_mode": led.get("scope", {}).get("determinism_mode"),
        "run_dir": res["run_dir"],
    }


def _batch_jobs(targets, manifest):
    """Resolve (path, claim, metric) jobs from dir/glob targets (committed contracts) + a TSV manifest
    of 'path<TAB>claim<TAB>[metric]' rows."""
    import glob as _glob
    jobs = []
    for t in targets or []:
        matches = sorted(_glob.glob(t)) or [t]
        for m in matches:
            if os.path.isdir(m):
                jobs.append((m, None, None))
    if manifest:
        for line in open(manifest):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("\t")]
            jobs.append((parts[0], parts[1] if len(parts) > 1 and parts[1] else None,
                         parts[2] if len(parts) > 2 and parts[2] else None))
    return jobs


def run_batch(targets, manifest=None, fail_on="not-clean", timeout=None, force=False):
    """Verify many targets; return a list of per-target result rows (for the summary + roll-up)."""
    rows = []
    for path, claim, met in _batch_jobs(targets, manifest):
        try:
            res = verify(path, claim=claim, metric=met, run_id="batch", force=force, timeout=timeout)
        except Exception as e:
            rows.append({"target": os.path.basename(os.path.normpath(path)), "verdict": "ERROR",
                         "metric": None, "claimed": None, "recomputed": None,
                         "clean": False, "error": str(e)[:140]})
            continue
        led = res["ledger"]
        c0 = (led.get("claims") or [{}])[0]
        clean = res["gate_exit"] == 0 if fail_on == "not-clean" \
            else res["repo_verdict"] not in ("REFUTED", "MIXED")
        rows.append({"target": os.path.basename(os.path.normpath(path)),
                     "verdict": res["repo_verdict"], "metric": c0.get("metric"),
                     "claimed": c0.get("claimed_value"), "recomputed": c0.get("recomputed_value"),
                     "clean": clean, "run_dir": res["run_dir"]})
    return rows


def _render_batch(rows, color=False):
    """A single scannable summary table for N targets + a roll-up line."""
    n = len(rows)
    refuted = sum(1 for r in rows if r["verdict"] in ("REFUTED", "MIXED"))
    confirmed = sum(1 for r in rows if r["verdict"] in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS"))
    inconcl = sum(1 for r in rows if r["verdict"] in ("INCONCLUSIVE", "ERROR"))
    tw = max([len(str(r["target"])) for r in rows] + [6])
    mw = max([len(str(r["metric"] or "-")) for r in rows] + [6])
    head = "CALMA BATCH  -  %d targets  -  %d REFUTED, %d confirmed, %d can't-confirm" \
        % (n, refuted, confirmed, inconcl)
    out = ["", head, "-" * max(len(head), 60),
           "  %-*s  %-*s  %12s  %12s  %s" % (tw, "TARGET", mw, "METRIC", "CLAIMED", "RECOMPUTED", "VERDICT")]
    for r in rows:
        sym = REP._SYMBOL.get(r["verdict"], "·")
        if color and r["verdict"] in REP._ANSI:
            sym = "\x1b[%sm%s\x1b[0m" % (REP._ANSI[r["verdict"]], sym)
        out.append("  %-*s  %-*s  %12s  %12s  %s %s"
                   % (tw, r["target"], mw, (r["metric"] or "-"),
                      REP.fmt_value(r["claimed"], r["metric"]) if r["claimed"] is not None else "-",
                      REP.fmt_value(r["recomputed"], r["metric"]) if r["recomputed"] is not None else "-",
                      sym, REP.display(r["verdict"]) if r["verdict"] != "ERROR" else "ERROR"))
    out.append("-" * max(len(head), 60))
    return "\n".join(out)


def main():
    if sys.version_info < (3, 9):
        print("error: calma requires Python 3.9 or newer (this is Python %d.%d) - "
              "run it with a newer python3" % (sys.version_info[0], sys.version_info[1]),
              file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(
        prog="calma",
        description="Verify a computational result by re-executing it and recomputing the headline "
                    "number from the raw outputs. The verdict comes from deterministic scripts.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="re-run + recompute + diff against the claim")
    v.add_argument("target", help="folder containing the code and its outputs")
    v.add_argument("claim_text", nargs="?", default=None,
                   help="the claim to check, e.g. \"accuracy 0.87\" or \"+14,698%%\" (optional)")
    v.add_argument("--claim", help="same as the positional claim")
    v.add_argument("--metric",
                   help="force a metric id, e.g. sharpe or accuracy (run `calma recipes` "
                        "for the full list of %d)" % len(RCP.ids()))
    v.add_argument("--run-id", default="run",
                   help="name of the run directory under <target>/.calma/ (default: run)")
    v.add_argument("--fail-on", choices=["not-clean", "refuted"], default="not-clean",
                   help="process exit policy: not-clean (default; INCONCLUSIVE also fails) or refuted")
    v.add_argument("--trust", choices=["own-code", "third-party"], default="own-code",
                   help="trust posture for the code being re-executed: own-code (default) runs "
                        "under the verified sandbox; third-party REFUSES to execute (exit 3) "
                        "unless a verified container/VM tier is live")
    v.add_argument("--timeout", type=int, default=None, metavar="SECONDS",
                   help="re-execution wall-clock budget (default 120, or run.timeout in "
                        "verify.yaml); on overrun the run is killed (exit 4)")
    v.add_argument("--force", action="store_true",
                   help="re-execute even if code, data, and claim are unchanged since the last verification")
    v.add_argument("--check-determinism", action="store_true",
                   help="re-execute TWICE and require identical artifacts (catches FLAKY results)")
    v.add_argument("--json", action="store_true", dest="as_json",
                   help="print a machine-readable verdict object instead of the report")
    b = sub.add_parser("batch", help="verify MANY targets at once + a summary table (CI/sprint use)")
    b.add_argument("targets", nargs="*",
                   help="dirs (each with a committed verify.yaml) or globs, e.g. 'runs/*'")
    b.add_argument("--manifest", metavar="TSV",
                   help="a TSV of rows 'path<TAB>claim<TAB>[metric]' (# comments allowed) - for "
                        "targets without a committed verify.yaml")
    b.add_argument("--fail-on", choices=["not-clean", "refuted"], default="not-clean",
                   help="exit policy applied across ALL targets (exit 1 if any fails)")
    b.add_argument("--timeout", type=int, default=None, metavar="SECONDS",
                   help="per-target re-execution budget")
    b.add_argument("--force", action="store_true", help="re-execute every target")
    b.add_argument("--json", action="store_true", dest="as_json",
                   help="print a machine-readable array of per-target results")
    t = sub.add_parser("teardown", help="print a shareable card when a claim breaks")
    t.add_argument("target", help="folder containing the code and its outputs")
    t.add_argument("claim_text", nargs="?", default=None,
                   help="the claim to check, e.g. \"accuracy 0.87\" (optional)")
    t.add_argument("--claim", help="same as the positional claim")
    t.add_argument("--metric",
                   help="force a metric id (run `calma recipes` for the full list)")
    t.add_argument("--force", action="store_true",
                   help="re-execute even if code, data, and claim are unchanged")
    t.add_argument("--svg", help="also write the share card as a dark SVG image to this path")
    r = sub.add_parser("replay", help="re-run a saved verification and check it reproduces")
    r.add_argument("run_dir", help="the .calma/<run-id> dir printed on the original verdict")
    s = sub.add_parser("stats", help="summarize this target's verification history")
    s.add_argument("target", help="folder whose .calma verification history to summarize")
    s.add_argument("--json", action="store_true", dest="as_json",
                   help="print the summary as machine-readable JSON")
    dm = sub.add_parser("demo", help="watch calma catch a real inflated backtest "
                                     "(bundled fixture; offline, a few seconds)")
    dm.add_argument("--keep", action="store_true",
                    help="keep the temp copy of the fixture (prints its path)")
    rc = sub.add_parser("recipes", help="list every built-in metric recipe, grouped by family")
    rc.add_argument("--json", action="store_true", dest="as_json",
                    help="print {family: [metric ids]} as JSON")
    at = sub.add_parser("attest", help="sign a run into a portable bundle, or verify one offline")
    atsub = at.add_subparsers(dest="attest_cmd", required=True)
    kg = atsub.add_parser("keygen", help="generate a local Ed25519 signing key (~/.calma/keys)")
    kg.add_argument("--force", action="store_true", help="overwrite an existing key")
    kg.add_argument("--import", dest="import_key", metavar="SSH_KEY",
                    help="adopt an existing UNENCRYPTED OpenSSH ed25519 key (e.g. ~/.ssh/id_ed25519)")
    sg = atsub.add_parser("sign", help="sign a run dir's ledger+manifest into attestation.bundle.json")
    sg.add_argument("run_dir", help="the .calma/<run-id> dir from a previous verify")
    sg.add_argument("--key", help="signing key file (default: ~/.calma/keys/ed25519.key)")
    sg.add_argument("--out", help="bundle output path (default: <run_dir>/attestation.bundle.json)")
    sg.add_argument("--timestamp", action="store_true",
                    help="also countersign with an RFC 3161 trusted timestamp (needs network once)")
    sg.add_argument("--tsa", default=None, help="timestamp authority URL (default: freetsa.org)")
    ts = atsub.add_parser("timestamp", help="add an RFC 3161 trusted timestamp to an existing bundle")
    ts.add_argument("bundle", help="path to attestation.bundle.json")
    ts.add_argument("--tsa", default=None, help="timestamp authority URL (default: freetsa.org)")
    sx = atsub.add_parser("sigstore", help="lab tier: Sigstore keyless countersign (needs sigstore-python)")
    sx.add_argument("bundle", help="path to attestation.bundle.json")
    sx.add_argument("--out", help="output path (default: <bundle dir>/attestation.sigstore.json)")
    av = atsub.add_parser("verify", help="verify a bundle offline: signature + verdict re-derivation")
    av.add_argument("bundle", help="path to attestation.bundle.json")
    av.add_argument("--key", help="pin the signer: hex public key, or a path to the .pub file")
    av.add_argument("--replay", action="store_true",
                    help="also re-execute the run next to the bundle and check the verdict reproduces")
    sl = sub.add_parser("seal", help="one command for the whole proof chain: sign + RFC 3161 "
                                     "timestamp + counterparty instructions (+ optional publish)")
    sl.add_argument("run_dir", help="the .calma/<run-id> dir from a previous verify")
    sl.add_argument("--no-timestamp", action="store_true",
                    help="skip the trusted timestamp (the one step that needs network)")
    sl.add_argument("--publish", metavar="REGISTRY_DIR", default=None,
                    help="also append a redacted entry to this catch-history registry")
    sl.add_argument("--note", default=None, help="one redacted line of context for the registry entry")
    sl.add_argument("--engagement", default=None, help="link the registry entry to an engagement id")
    sl.add_argument("--key", help="signing key file (default: ~/.calma/keys/ed25519.key)")
    pb = sub.add_parser("publish", help="append a REDACTED entry (claim/verdict/gap only - never "
                                        "code or data) to the public catch-history registry")
    pb.add_argument("run_dir", nargs="?", default=None,
                    help="the .calma/<run-id> dir of an attested run (omit with --open)")
    pb.add_argument("--registry", default=None,
                    help="registry directory (default: $CALMA_REGISTRY_DIR, then ./registry)")
    pb.add_argument("--engagement", default=None, help="link the outcome to an engagement id")
    pb.add_argument("--open", dest="open_id", metavar="ENGAGEMENT_ID", default=None,
                    help="publish an engagement-opened entry at contract signing "
                         "(a missing outcome is then visible - the clinical-trial property)")
    pb.add_argument("--note", default=None, help="one redacted line of context")
    pb.add_argument("--key", help="signing key file (default: ~/.calma/keys/ed25519.key)")
    rg = sub.add_parser("registry", help="audit the catch-history registry chain offline")
    rgsub = rg.add_subparsers(dest="registry_cmd", required=True)
    rgv = rgsub.add_parser("verify", help="re-hash every entry, walk the chain, check every signature")
    rgv.add_argument("dir", nargs="?", default=None,
                     help="registry directory (default: $CALMA_REGISTRY_DIR, then ./registry)")
    rgv.add_argument("--key", help="pin the signer: hex public key, or a path to the .pub file")
    # bare `calma` (or `calma help`) is a person looking for the door, not an error
    if len(sys.argv) <= 1 or sys.argv[1] == "help":
        ap.print_help()
        print("\nstart here:\n"
              "  calma demo                         watch a real inflated backtest get caught "
              "(offline, a few seconds)\n"
              "  calma verify <folder> \"<claim>\"    check your own result, "
              "e.g. calma verify ./out \"accuracy 0.87\"\n"
              "  calma recipes                      the %d metrics it can recompute" % len(RCP.ids()))
        return 0
    a = ap.parse_args()
    try:
        if a.cmd == "verify":
            res = verify(a.target, a.claim_text or a.claim, a.metric, a.run_id,
                         force=a.force, check_determinism=a.check_determinism,
                         trust=a.trust, timeout=a.timeout)
            if a.fail_on == "refuted":
                exit_code = 1 if res["repo_verdict"] in ("REFUTED", "MIXED") else 0
            else:
                exit_code = res["gate_exit"]
            # refusal/kill outcomes get their own exit codes (documented in the README table):
            # 3 = execution refused (trust posture), 4 = killed (timeout) - regardless of policy
            if res.get("refused"):
                exit_code = 3
            elif res.get("killed"):
                exit_code = 4
            if a.as_json:
                print(json.dumps(_json_result(res), indent=2))
            else:
                print(res.get("display") or res["report"])
                # the trust footnote prints AFTER the verdict (dimmed on a tty), never above it
                note = res.get("first_run_notice")
                if note:
                    print(("\x1b[2m%s\x1b[0m" if _color_enabled() else "%s") % ("  " + note))
                # human vocabulary on the exit line: INCONCLUSIVE displays as CAN'T-CONFIRM.
                rv = res["repo_verdict"]
                label = REP.display(rv)
                if rv in ("REFUTED", "MIXED"):
                    # a REFUTED is the catch working, not a misconfiguration - say so on the exit line
                    tail = " - claim refuted (the catch; --fail-on sets exit behavior)"
                elif exit_code == 0:
                    tail = ""
                else:
                    if label.startswith("CONFIRMED") and res.get("gate_exit") != 0:
                        label += ", with caveat findings"
                    tail = " - see --fail-on for the exit policy"
                print("\n[exit %d (%s)%s]" % (exit_code, label, tail))
            return exit_code
        if a.cmd == "batch":
            if not a.targets and not a.manifest:
                print("error: batch needs target dirs/globs and/or --manifest TSV", file=sys.stderr)
                return 2
            rows = run_batch(a.targets, manifest=a.manifest, fail_on=a.fail_on,
                             timeout=a.timeout, force=a.force)
            if not rows:
                print("error: no targets matched", file=sys.stderr)
                return 2
            if a.as_json:
                print(json.dumps(rows, indent=2, default=str))
            else:
                print(_render_batch(rows, color=_color_enabled()))
            # roll-up: exit 1 if ANY target failed its policy
            return 0 if all(r["clean"] for r in rows) else 1
        if a.cmd == "demo":
            # zero-to-verdict: a real overfit BTC backtest ships with the skill. Copy it to a temp
            # dir (without its .calma state), re-execute, recompute, and show the verdict card.
            # Offline by construction (the fixture vendors its data snapshot).
            import shutil
            import tempfile
            src = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                "..", "assets", "btc"))
            if not os.path.isdir(src):
                print("error: bundled fixture missing at %s" % src, file=sys.stderr)
                return 2
            dst = os.path.join(tempfile.mkdtemp(prefix="calma-demo-"), "btc-backtest")
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".calma"))
            print("re-verifying a real overfit backtest (it claimed +14,698% on BTC)...\n")
            res = verify(dst)
            print(res["report"])
            if a.keep:
                print("\n[fixture copy kept at %s]" % dst)
            print("\nthat was a real inflated backtest. now try your own:  "
                  "%s verify <folder> \"<claim>\"" % _invocation())
            return 0 if res["repo_verdict"] == "REFUTED" else 1
        if a.cmd == "recipes":
            fams = {}
            for mid in RCP.ids():
                fams.setdefault(RCP.get(mid).manifest.get("family") or "other", []).append(mid)
            if a.as_json:
                print(json.dumps(fams, indent=2, sort_keys=True))
                return 0
            import textwrap
            print("CALMA RECIPES - %d metrics. Pin one with: "
                  "calma verify <folder> \"<claim>\" --metric <id>" % len(RCP.ids()))
            for fam in sorted(fams):
                print("\n  %s (%d)" % (fam, len(fams[fam])))
                for ln in textwrap.wrap(", ".join(fams[fam]), width=88):
                    print("    " + ln)
            return 0
        if a.cmd == "teardown":
            res = verify(a.target, a.claim_text or a.claim, a.metric, "teardown", force=a.force)
            print(res.get("teardown") or "(no teardown: result was not REFUTED)")
            if a.svg and res.get("teardown"):
                svg = REP.svg_card(res["ledger"])
                if svg:
                    open(a.svg, "w").write(svg)
                    print("\n[share card written: %s]" % a.svg)
            return 0 if res.get("teardown") else 1
        if a.cmd == "replay":
            ok, text = replay(a.run_dir)
            print(text)
            return 0 if ok else 1
        if a.cmd == "stats":
            data, rendered = stats(a.target)
            print(json.dumps(data, indent=2) if a.as_json else rendered)
            return 0
        if a.cmd == "attest":
            if a.attest_cmd == "keygen":
                info = attest.keygen(force=a.force, import_key=a.import_key)
                print("key written: %s (0600)%s\npublic key:  %s\nssh form:    %s\nkeyid:       %s"
                      % (info["key_path"],
                         (" - imported from %s" % a.import_key) if a.import_key else "",
                         info["public_key"], info["ssh_public_key"], info["keyid"]))
                return 0
            if a.attest_cmd == "sign":
                run_dir = os.path.realpath(a.run_dir)
                bundle, out = attest.sign_run(run_dir, key_path=a.key, out=a.out)
                if a.timestamp:
                    import rfc3161
                    entry = rfc3161.timestamp_bundle(bundle, a.tsa or rfc3161.DEFAULT_TSA)
                    json.dump(bundle, open(out, "w"), indent=2)
                    print("timestamped: %s (RFC 3161, %s)" % (entry["gen_time"], entry["tsa_url"]))
                print("signed: %s\nkeyid:  %s" % (out, bundle["envelope"]["signatures"][0]["keyid"]))
                print("counterparty check with stock OpenSSH (no installs):\n"
                      "  cd %s && ssh-keygen -Y verify -f %s -I %s -n %s -s %s < %s"
                      % (os.path.dirname(out) or ".", attest.SIGNERS_SIDECAR,
                         bundle["ssh"]["principal"], bundle["ssh"]["namespace"],
                         attest.SSHSIG_SIDECAR, attest.PAYLOAD_SIDECAR))
                return 0
            if a.attest_cmd == "timestamp":
                import rfc3161
                bundle = json.load(open(a.bundle))
                entry = rfc3161.timestamp_bundle(bundle, a.tsa or rfc3161.DEFAULT_TSA)
                json.dump(bundle, open(a.bundle, "w"), indent=2)
                attest.write_ssh_sidecars(bundle, os.path.dirname(os.path.realpath(a.bundle)))
                print("timestamped: %s\n  TSA:    %s\n  serial: %s\nthe token verifies offline; "
                      "network was needed only for this step"
                      % (entry["gen_time"], entry["tsa_url"], entry["serial"]))
                return 0
            if a.attest_cmd == "sigstore":
                import sigstore_l2
                bundle = json.load(open(a.bundle))
                out = a.out or os.path.join(os.path.dirname(os.path.realpath(a.bundle)),
                                            "attestation.sigstore.json")
                info = sigstore_l2.sigstore_sign(bundle, out)
                print("sigstore bundle: %s\n  identity: %s\n  rekor log index: %s"
                      % (info["out"], info.get("identity"), info.get("log_index")))
                return 0
            if a.attest_cmd == "verify":
                try:
                    bundle = json.load(open(a.bundle))
                except (OSError, ValueError) as e:
                    print("error: cannot read bundle: %s" % e, file=sys.stderr)
                    return 2
                pinned = None
                if a.key:
                    pinned = open(a.key).read().strip() if os.path.exists(a.key) else a.key.strip()
                ok, checks = attest.verify_bundle(bundle, pinned_pub_hex=pinned)
                print(attest.render_verify(bundle, ok, checks))
                if ok and a.replay:
                    rok, text = replay(os.path.dirname(os.path.realpath(a.bundle)))
                    print("\n" + text)
                    ok = ok and rok
                if not ok:
                    print("\nnext: ask the producer to re-run `calma seal <run_dir>` "
                          "and resend the bundle (a stale or tampered bundle never verifies)")
                return 0 if ok else 1
        if a.cmd == "seal":
            run_dir = os.path.realpath(a.run_dir)
            bpath = os.path.join(run_dir, attest.BUNDLE_NAME)
            if attest.load_signing_key(a.key) is None:
                print("error: no signing key - run `calma attest keygen` first (one time)",
                      file=sys.stderr)
                return 2
            bundle, _ = attest.sign_run(run_dir, key_path=a.key)  # idempotent: re-signs fresh
            keyid = bundle["envelope"]["signatures"][0]["keyid"]
            print("signed      DSSE + SSHSIG (keyid %s...)" % keyid[:16])
            if a.no_timestamp:
                print("timestamp   skipped (--no-timestamp)")
            else:
                import rfc3161
                try:
                    entry = rfc3161.timestamp_bundle(bundle, rfc3161.DEFAULT_TSA)
                    json.dump(bundle, open(bpath, "w"), indent=2)
                    attest.write_ssh_sidecars(bundle, run_dir)  # refresh instructions w/ timestamp
                    print("timestamp   %s (%s) - verifies offline forever"
                          % (entry["gen_time"], entry["tsa_url"]))
                except (OSError, ValueError) as e:
                    # ValueError = a malformed/ungrantable RFC 3161 response; never a traceback
                    # mid-seal - the bundle stays valid, only the timestamp layer is deferred
                    print("timestamp   SKIPPED - TSA unreachable or returned a bad response (%s); "
                          "run `calma attest timestamp %s` later" % (e, bpath))
            ok, checks = attest.verify_bundle(bundle)
            print("self-check  %s (%d checks)" % ("VERIFIED" if ok else "FAILED",
                                                  len(checks)))
            if not ok:
                print(attest.render_verify(bundle, ok, checks), file=sys.stderr)
                return 1
            if a.publish:
                import registry as REG
                os.makedirs(a.publish, exist_ok=True)
                seed = attest.load_signing_key(a.key)
                entry = REG.derive_entry(bundle, engagement=a.engagement, note=a.note)
                fname, wrapper = REG.append_entry(a.publish, entry, seed)
                print("published   %s/entries/%s (%s)"
                      % (a.publish, fname, wrapper["entry"].get("verdict")))
                print("            to make it PUBLIC: commit registry/ with a signed commit "
                      "and push - the site rebuilds itself")
            print("sealed      %s" % run_dir)
            print("            share this folder; VERIFY-THIS.txt inside has the exact "
                  "commands a counterparty runs (incl. zero-install OpenSSH)")
            return 0
        if a.cmd == "publish":
            import registry as REG
            reg_dir = a.registry or os.environ.get("CALMA_REGISTRY_DIR") or "registry"
            if a.registry:
                os.makedirs(a.registry, exist_ok=True)  # explicit --registry: create it
            elif not a.open_id and not os.path.isdir(reg_dir):
                print("error: no registry directory at %r - pass --registry or set "
                      "CALMA_REGISTRY_DIR (the public repo's registry/)" % reg_dir, file=sys.stderr)
                return 2
            seed = attest.load_signing_key(a.key)
            if seed is None:
                print("error: no signing key - run `calma attest keygen` first (publish entries "
                      "are signed with the same key as attestations)", file=sys.stderr)
                return 2
            if a.open_id:
                entry = REG.opened_entry(a.open_id, note=a.note)
            else:
                if not a.run_dir:
                    print("error: pass a run dir (or --open <engagement-id>)", file=sys.stderr)
                    return 2
                bpath = os.path.join(os.path.realpath(a.run_dir), attest.BUNDLE_NAME)
                if not os.path.exists(bpath):
                    print("error: no %s under %s - publish requires attest; run "
                          "`calma attest sign %s` first" % (attest.BUNDLE_NAME, a.run_dir, a.run_dir),
                          file=sys.stderr)
                    return 2
                bundle = json.load(open(bpath))
                bok, bchecks = attest.verify_bundle(bundle)
                if not bok:
                    print("error: the attestation bundle does not verify - refusing to publish:\n%s"
                          % attest.render_verify(bundle, bok, bchecks), file=sys.stderr)
                    return 1
                entry = REG.derive_entry(bundle, engagement=a.engagement, note=a.note)
                if entry.get("verdict") not in ("REFUTED", "MIXED"):
                    print("note: this entry records a %s outcome, not a catch - the registry "
                          "documents both" % entry.get("verdict"))
            fname, wrapper = REG.append_entry(reg_dir, entry, seed)
            e = wrapper["entry"]
            print("published: %s/entries/%s" % (reg_dir, fname))
            print("  kind     %s" % e["kind"])
            if e.get("claim"):
                print("  claim    %s" % e["claim"])
            if e.get("recomputed") is not None:
                print("  recomputed %s" % e["recomputed"])
            print("  verdict  %s\n  id       %s" % (e.get("verdict"), wrapper["id"]))
            print("the entry is redacted (no code, no data), chained to the previous entry, and "
                  "signed; commit it with a signed commit to complete the public record")
            return 0
        if a.cmd == "registry" and a.registry_cmd == "verify":
            import registry as REG
            reg_dir = a.dir or os.environ.get("CALMA_REGISTRY_DIR") or "registry"
            pinned = None
            if a.key:
                pinned = open(a.key).read().strip() if os.path.exists(a.key) else a.key.strip()
            ok, checks, summary = REG.verify_chain(reg_dir, pinned_pub_hex=pinned)
            print(REG.render_verify(ok, checks, summary))
            return 0 if ok else 1
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
