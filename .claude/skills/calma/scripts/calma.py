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
import stat
import sys
from dataclasses import dataclass, fields, replace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attest
import autonomy as AUT
import backtest_checks as BC
import pit_checks as PIT
import data_snooping_checks as DSC
import regime_checks as RGC
import model_leakage_checks as MLC
import distribution_shift_checks as DShC
import leakage_checks as LC
import overfitting_checks as OC
import realism_checks as RLC
import contamination_checks as CNC
import plausibility_checks as PLC
import infer_validity as INF
import embargo_checks as EMB
import simulation_assumptions_checks as SAC
import cross_engine as CE
import compare as CMP
import draft_contract as DC
import intake as INTAKE
import ledger as LED
import recipes as RCP
import recompute as RC
import report as REP
import run_hermetic as H
import suggest as SUGG
import verdict as V

__version__ = "0.12.0"

QUANT_METRICS = {"total_return", "sharpe", "max_drawdown"}
DEFAULT_TIMEOUT_S = 120
# the verified-tier gate is defined ONCE in calma.tiers; re-exported here for back-compat callers.
import tiers as _tiers  # noqa: E402 - sibling leaf module (imports nothing)
VERIFIED_TIERS = _tiers.VERIFIED_TIERS


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


def _stderr_color():
    """NO_COLOR-respecting style gate for the stderr trace + spinner (no-color.org: NO_COLOR drops
    ALL added style, not just stdout's). Progress still shows under NO_COLOR - just without dim."""
    return sys.stderr.isatty() and not os.environ.get("NO_COLOR")


class _Spinner:
    """A single self-updating stderr line ('⠹ label (Ns)') during a long step, so re-execution
    doesn't look like a frozen terminal. Active only on an interactive stderr (never in pipes/CI/
    --json, and off when CALMA_TRACE=0); a no-op otherwise. Cleared on exit, leaving no trace."""
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label):
        self.label = label
        self._on = _trace_enabled() and sys.stderr.isatty()
        self._color = _stderr_color()  # dim styling only when NO_COLOR is unset
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
                body = "  %s %s (%.0fs)" % (self.FRAMES[i % len(self.FRAMES)], self.label,
                                            _t.time() - t0)
                if self._color:
                    body = "\x1b[2m%s\x1b[0m" % body
                sys.stderr.write("\r" + body + "\x1b[K")   # \r + erase-to-EOL are control, not color
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
    if _stderr_color():
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


def _article(word):
    """'a' / 'an' by the leading sound (good enough for metric ids: 'an auc metric', 'a sharpe')."""
    return "an" if str(word)[:1].lower() in "aeiou" else "a"


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
            "unblock": "add %s %s metric to verify.yaml, or move/remove verify.yaml to auto-detect"
                       % (_article(user_metric), user_metric),
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
    mid = target_m.get("metric_id")
    if committed_v is None:
        # M6a: a drafted/binding-only contract commits no claim value of its own - say that plainly
        # instead of the clunky "committed claim value (None) is not what is being verified".
        return ("checking YOUR claim (%s %g) - the contract pins the bindings but commits no claim "
                "value of its own (expected for a drafted contract)" % (mid, cv)), None
    return ("checking YOUR claim (%s %g) - it differs from the contract's committed value (%g); "
            "YOUR claim is the one being verified" % (mid, cv, committed_v)), None


def _not_verified(metric_ids, leakage_status=None, overfitting_status=None,
                  realism_status=None, contamination_status=None, backtest_status=None,
                  pit_status=None, snoop_status=None, regime_status=None, modelleak_status=None,
                  shift_status=None, embargo_status=None, simassume_status=None):
    """Honest 'what we did NOT check' list. Leakage / overfitting / realism / contamination / backtest-
    soundness are now real families: each is listed as a gap ONLY when it was NOT-APPLICABLE (nothing to
    assess) - never claimed as a gap once it ran, and never called 'roadmap' now that it exists."""
    out = []
    if leakage_status in (None, "not-applicable"):
        out.append("data leakage (no train/test split or keys declared)")
    # model-process leakage (V4): featurization-on-train+test / selection-on-test. Listed when the
    # pipeline/sweep surface isn't declared (sibling of the row/id/temporal leakage line above).
    if modelleak_status in (None, "not-applicable"):
        out.append("model-process leakage (no pipeline/sweep declared: featurization-fit / selection-on-test)")
    # covariate/target distributional shift (V5): KS / PSI between train and test, checked only under
    # an in-distribution / generalizes claim (else a shift on a split used for another purpose isn't ours).
    if shift_status in (None, "not-applicable"):
        out.append("covariate/target distribution shift (checked only under an in-distribution/generalizes claim)")
    if overfitting_status in (None, "not-applicable"):
        out.append("overfitting / deflated-Sharpe / PBO (no trials:N or grid-search log declared)")
    if realism_status in (None, "not-applicable") and any(m in QUANT_METRICS for m in metric_ids):
        out.append("execution realism (no frictions declared)")
    if contamination_status in (None, "not-applicable"):
        out.append("eval/benchmark contamination (no corpus declared)")
    # backtest soundness (V0): survivorship / cherry-picked window / omitted costs. Listed as a gap only
    # when NOT-APPLICABLE (no costs/window/survivors-only universe declared) and a quant metric is in
    # play - the point-in-time VENDOR-DATA deepening (rebuild the universe with delisted names) is V1's
    # frontier, so we still note it isn't auto-verified absent a declared universe.
    if backtest_status in (None, "not-applicable") and any(m in QUANT_METRICS for m in metric_ids):
        out.append("backtest soundness (no costs / window / survivors-only universe declared)")
    # point-in-time / look-ahead (V1): rigorous survivorship (membership attrition) + the +1-period-lag
    # look-ahead probe. Listed only when NOT-APPLICABLE (no universe-membership / availability block).
    if pit_status in (None, "not-applicable") and any(m in QUANT_METRICS for m in metric_ids):
        out.append("point-in-time / look-ahead (no universe-membership or availability block declared)")
    # study-wide multiple-testing / HLZ haircut (V2): listed only when NOT-APPLICABLE (no study block).
    if snoop_status in (None, "not-applicable") and any(m in QUANT_METRICS for m in metric_ids):
        out.append("study-wide multiple-testing / HLZ haircut (no study:{trials,...} block declared)")
    # walk-forward / regime robustness (V3): listed only when NOT-APPLICABLE (no windows block declared
    # and the claim made no robustness assertion to auto-window the series).
    if regime_status in (None, "not-applicable") and any(m in QUANT_METRICS for m in metric_ids):
        out.append("walk-forward / regime robustness (no windows block or robustness claim)")
    # era-embargo / purged-CV leakage (WS-C i): listed only when NOT-APPLICABLE (no embargo block declared).
    if embargo_status in (None, "not-applicable"):
        out.append("era-embargo / purged-CV leakage (no embargo:{horizon_days,train,...} block declared)")
    # risk-sim assumptions (WS-C ii): listed only when NOT-APPLICABLE (no simulation_assumptions block).
    if simassume_status in (None, "not-applicable"):
        out.append("risk-sim assumptions (no simulation_assumptions:{firm,event_log,...} block declared)")
    return out


def _metric_suggestions(target, claim, k=4):
    """For the genuinely-unclear case ONLY: when calma cannot bind a metric, rank the recipes
    the user most likely meant from their claim text + the data's own column/file names, so
    verify can ask 'did you mean...?' instead of bare-refusing. Suggestion-only and fail-open:
    never raises, never affects a verdict, never runs when a metric was determined."""
    try:
        scan = DC._scan_csvs(target)
    except Exception:  # noqa: BLE001
        scan = []
    # which binding tags can the data actually supply? lets suggest() demote recipes whose
    # inputs aren't present (an inequality claim over one numeric column isn't balanced_accuracy).
    avail = set()
    for a in scan:
        for col in (a.get("columns") or {}).values():
            if isinstance(col, dict) and col.get("tag"):
                avail.add(col["tag"])
    tags = avail or None
    try:
        # the claim is the user's stated intent - the strongest, cleanest signal. Use it alone
        # when present; the data's column/file names are noisier (a "balance" column wrongly
        # pulls "balanced_accuracy"), so fall back to them ONLY when there is no claim text.
        if claim and claim.strip():
            hit = SUGG.suggest(claim, k=k, available_tags=tags)
            if hit:
                return hit
        bits = []
        for a in scan:
            bits.append(os.path.basename(a.get("path", "")).rsplit(".", 1)[0].replace("_", " "))
            bits.extend(str(c).replace("_", " ") for c in (a.get("columns") or {}))
        return SUGG.suggest(" ".join(b for b in bits if b), k=k, available_tags=tags) if bits else []
    except Exception:  # noqa: BLE001  - suggestion gathering is best-effort, never load-bearing
        return []


def _suggest_unblock(sugg):
    """Render ranked suggestions as a one-line 'did you mean' addendum for a finding's unblock."""
    if not sugg:
        return ""
    return ("  Did you mean: %s? Re-run with --metric <id>, or tell me which number you calculated."
            % "; ".join("%s (%s)" % (s["metric_id"], s["family"]) for s in sugg))


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


def _assemble_ledger(contract, diff, run_res, claim_text=None):
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
            "reason": m.get("reason"), "recompute_error": m.get("recompute_error"),
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
                # _redact_home: when calma.py is invoked by ABSOLUTE path (as SKILL.md documents and
                # the hook does), _invocation() carries it - and this command ships inside the signed,
                # counterparty-facing bundle. $HOME must never enter a bundle (see _redact_home).
                "command": _redact_home("%s replay %s" % (_invocation(), _rd)),
                "manifest_ref": run_res.get("manifest_ref", "sha256:unavailable"),
                "expected": "recomputed differs from claimed beyond the calibrated budget",
            }
            findings.append({
                "id": "f-%s-mm" % cid, "claim_id": cid, "dimension": "metric-mismatch",
                "severity": "blocker", "status": "open", "confidence": "deterministic",
                "fixable_by": "author",
                "locator": "claimed %s but the code recomputes %s"
                           % (REP.fmt_value(m["claimed"], m["metric_id"]),
                              REP.fmt_value(m["recomputed"], m["metric_id"])),
                "reverify": {"kind": "requires-reexecution", "source": m.get("metric_id"),
                             "expected": "recomputed within budget of claimed"},
            })
        claims.append(claim)
    # FLAKY: two identical re-executions disagreed -> blocking finding. The message reads as a
    # measurement (which artifacts drifted, and by how much on the headline metric) and the unblock
    # names the LIKELY source + the exact knob to pin - rigor, not a generic failure.
    recheck = run_res.get("determinism_recheck")
    if recheck and not recheck.get("stable", True):
        var = recheck.get("variance")
        locator = ("the counterparty's code does not reproduce run-to-run (identical inputs, "
                   "different outputs): %s" % ", ".join(recheck.get("differing_artifacts", [])[:4]))
        if var:
            locator += ("; %s moved %s -> %s across two runs (Δ %s)"
                        % (var["metric_id"], REP.fmt_value(var["v1"], var["metric_id"]),
                           REP.fmt_value(var["v2"], var["metric_id"]),
                           REP.fmt_value(var["spread"], var["metric_id"])))
        hint = _nondeterminism_hint(run_res.get("determinism_note"))
        unblock = ("make the run reproducible, then re-verify: set a fixed seed, pin thread counts "
                   "(OMP_NUM_THREADS=1), and write outputs without timestamps")
        if hint:
            unblock = "likely source: %s. Then re-run calma verify." % hint
        findings.append({
            "id": "f-flaky", "claim_id": claims[0]["id"] if claims else None,
            "dimension": "reproducibility", "severity": "blocker", "status": "open",
            "confidence": "deterministic", "fixable_by": "author",
            "locator": locator, "unblock": unblock,
            "reverify": {"kind": "requires-reexecution", "source": "run",
                         "expected": "identical artifacts across re-runs"},
        })
    # a failed re-execution is itself a blocking finding (the verdict guard already forced INCONCLUSIVE)
    rc = run_res.get("exit_code", 0)
    if rc not in (0, 3, 4):
        stderr_tail = run_res.get("stderr_tail") or ""
        missing_dep = any(s in stderr_tail for s in
                          ("ModuleNotFoundError", "No module named", "ImportError"))
        unblock = "make the entrypoint run to completion (exit 0), then re-run calma verify"
        if missing_dep:
            unblock = ("a dependency is missing in the network-off sandbox - re-run with --restore to "
                       "install the repo's pinned deps (requirements.txt) into .calma_venv (network is "
                       "used only in that phase); else make the entrypoint run to completion, then re-verify")
        findings.append({
            "id": "f-run-fail", "claim_id": claims[0]["id"] if claims else None,
            "dimension": "reproducibility", "severity": "blocker", "status": "open",
            "confidence": "deterministic", "fixable_by": "author",
            "locator": "the entrypoint exited non-zero - the result was NOT reproduced"
                       + ((" | stderr: " + stderr_tail.strip()[-200:]) if stderr_tail else ""),
            "unblock": unblock,
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
    # Validity families (leakage / overfitting / realism / contamination / backtest-soundness) - additive
    # findings off the bound artifact + contract. Only when the run actually reproduced (exit 0) and there
    # is a claim to judge; deck-vs-code mismatch is already handled above by the recompute+verdict path.
    # Each family promotes the (reproduced) headline DOWN only (INVALIDATED / CAN'T-CONFIRM / CAVEAT),
    # scope-guarded; none can inflate a verdict.
    leak_fam = over_fam = real_fam = cont_fam = bt_fam = pit_fam = ds_fam = reg_fam = ml_fam = None
    shift_fam = plaus_fam = emb_fam = sim_fam = infer_fam = None
    if claims and run_res.get("exit_code", 0) == 0:
        _base = run_res.get("base") or (
            os.path.dirname(os.path.dirname(run_res["run_dir"])) if run_res.get("run_dir") else None)
        if _base:
            # WS-leakage: additive leakage findings, then promote the (reproduced) headline verdict per
            # the findings + the claim scope (INVALIDATED / CAN'T-CONFIRM / CAVEAT). Never manufactures
            # REFUTED - that stays the gap-gated recompute path (+ the leakage-corrected re-run, Step 4).
            findings.extend(LC.run_checks(contract, _base, claims[0]["id"]))
            LC.apply_validity(claims, findings, contract, claim_text, base=_base)
            leak_fam = LC.family_status(contract, findings)
            # WS-overfitting: silent unless a multiple-testing search signal is present; same scope-guarded
            # promotion (INVALIDATED / CAN'T-CONFIRM / CAVEAT). N is never guessed.
            findings.extend(OC.run_checks(contract, _base, claims[0]["id"], claim_text=claim_text))
            OC.apply_validity(claims, findings, contract, claim_text)
            over_fam = OC.family_status(contract, _base, findings, claim_text)
            # WS-realism: execution-realism deflators (transaction cost / slippage / borrow / square-root
            # market impact). Silent unless a `frictions` block is declared; same scope-guarded promotion -
            # REFUTED via the friction-deflated recompute (net claim), INVALIDATED (uninvestable at size),
            # CAN'T-CONFIRM (declare net vs gross), or CAVEAT (gross / soft fill).
            findings.extend(RLC.run_checks(contract, _base, claims[0]["id"], claim_text=claim_text))
            RLC.apply_validity(claims, findings, contract, claim_text, base=_base)
            real_fam = RLC.family_status(contract, findings)
            # WS-contamination: eval-set / benchmark contamination (corpus hash overlap + near-dup minhash).
            # Silent unless a `corpus` block is declared; INVALIDATED on exact eval-in-corpus for a
            # held-out / uncontaminated claim, CAVEAT for near-dup, CAN'T-CONFIRM for indeterminate scope.
            findings.extend(CNC.run_checks(contract, _base, claims[0]["id"], claim_text=claim_text))
            CNC.apply_validity(claims, findings, contract, claim_text)
            cont_fam = CNC.family_status(contract, findings)
            # WS-backtest-soundness (V0): omitted-costs / cherry-picked window / survivorship. Additive
            # findings + the same scope-guarded promotion - INVALIDATED only under a claim asserting the
            # clean property (net / representative-window / point-in-time), else a CAVEAT. Runs LAST so
            # the four ML-validity families above take precedence on the driving dimension; backtest only
            # promotes a still-clean headline (apply_validity returns early once it is non-clean).
            findings.extend(BC.run_checks(contract, _base, claims[0]["id"], claim_text=claim_text))
            BC.apply_validity(claims, findings, contract, claim_text, base=_base)
            bt_fam = BC.family_status(contract, findings)
            # WS-point-in-time (V1): rigorous survivorship (point-in-time membership / attrition) +
            # look-ahead (availability_date <= effective_date, and the +1-period-lag robustness probe).
            # INVALIDATED only under a point-in-time / forward / out-of-sample claim, else a CAVEAT.
            findings.extend(PIT.run_checks(contract, _base, claims[0]["id"], claim_text=claim_text))
            PIT.apply_validity(claims, findings, contract, claim_text, base=_base)
            pit_fam = PIT.family_status(contract, findings)
            # WS-data-snooping (V2): study-wide multiple-testing / the HLZ haircut (t>3.0). Silent
            # unless a `study` block is declared; INVALIDATED under a significance/genuine-factor claim
            # whose adjusted t falls below 3.0, else CAVEAT (or CAN'T-CONFIRM when N is undisclosed).
            findings.extend(DSC.run_checks(contract, _base, claims[0]["id"], claim_text=claim_text))
            DSC.apply_validity(claims, findings, contract, claim_text, base=_base)
            ds_fam = DSC.family_status(contract, findings)
            # WS-regime (V3): walk-forward / regime robustness. Silent unless a `windows` block is
            # declared OR the claim asserts robustness/walk-forward; INVALIDATED when the in-sample edge
            # collapses out-of-sample under such a claim, else a CAVEAT.
            findings.extend(RGC.run_checks(contract, _base, claims[0]["id"], claim_text=claim_text))
            RGC.apply_validity(claims, findings, contract, claim_text, base=_base)
            reg_fam = RGC.family_status(contract, findings)
            # WS-model-leakage (V4): ML-process leakage - featurization fit on train+test, or
            # validation-reuse / selection-on-test. Silent unless a `pipeline`/`sweep` block is declared;
            # INVALIDATED under a "no leakage / held-out" claim, else a CAVEAT.
            findings.extend(MLC.run_checks(contract, _base, claims[0]["id"], claim_text=claim_text))
            MLC.apply_validity(claims, findings, contract, claim_text, base=_base)
            ml_fam = MLC.family_status(contract, findings)
            # WS-distribution-shift (V5): covariate/target shift between the train and test split (KS /
            # PSI). Silent unless a readable train+test split is declared; INVALIDATED under an
            # in-distribution/generalizes claim, else a CAVEAT.
            findings.extend(DShC.run_checks(contract, _base, claims[0]["id"], claim_text=claim_text))
            DShC.apply_validity(claims, findings, contract, claim_text, base=_base)
            shift_fam = DShC.family_status(contract, findings)
            # WS-era-embargo (WS-C i): purged-CV / era-embargo leakage. Silent unless an `embargo` block is
            # declared. Detection A (deterministic gate): min_val_era - max_train_era <= required purge ->
            # INVALIDATED under a validation/OOS/leaderboard claim. Detection B: the leading-era CORR
            # inflation (the leakage premium) as severity; standalone (no train range) -> a soft CAVEAT.
            findings.extend(EMB.run_checks(contract, _base, claims[0]["id"], claim_text=claim_text))
            EMB.apply_validity(claims, findings, contract, claim_text, base=_base)
            emb_fam = EMB.family_status(contract, findings)
            # WS-simulation-assumptions (WS-C ii): risk-firm (Chaos/Gauntlet) per-block invariants -
            # <=1 liquidation/account/block, VaR-percentile mis-statement, calibration look-ahead,
            # close-factor bound. Silent unless a `simulation_assumptions` block is declared; INVALIDATED
            # under a VaR/risk/methodology claim, else a CAVEAT (or a soft 'not auditable' finding).
            findings.extend(SAC.run_checks(contract, _base, claims[0]["id"], claim_text=claim_text))
            SAC.apply_validity(claims, findings, contract, claim_text, base=_base)
            sim_fam = SAC.family_status(contract, findings)
            # WS-plausibility (V6 + B1): thin-input statistical smells that need NO declared block.
            # Return series: implausibly-high Sharpe, too-smooth curve, regime drift (first/second-half
            # KS). ML/tabular result: undeclared-split leakage (inferred split + real row overlap) and a
            # train/test loss gap. SOFT-ONLY: degrades a reproduced number to a CAVEAT (never INVALIDATED /
            # REFUTED) and surfaces a precise "what to declare" finding. Runs LAST so every authoritative
            # family keeps precedence; `findings` is passed so the regime smell defers to the
            # authoritative regime family when that one already fired.
            findings.extend(PLC.run_checks(contract, _base, claims[0]["id"], claim_text=claim_text,
                                           findings=findings))
            PLC.apply_validity(claims, findings, contract, claim_text, base=_base)
            plaus_fam = PLC.family_status(contract, findings)
            # M-8b.2: PROMOTE an inferred smell to FLAG_FOR_DECLARATION when the evidence is strong + multi-
            # signal AND nothing was declared (the kill-shot hole: declaring nothing while the data screams
            # train/test leak / a strong regime break / an undeclared trials matrix). Runs AFTER plausibility
            # so a soft CAVEAT is in place first; the flag overrides it (FLAG > CAVEAT). NEVER manufactures
            # INVALIDATED — it is a demand to declare, not a verdict flip. `findings` is passed so a detector
            # defers to its authoritative family when that one already fired.
            findings.extend(INF.run_checks(contract, _base, claims[0]["id"], claim_text=claim_text,
                                           findings=findings))
            INF.apply_validity(claims, findings, contract, claim_text, base=_base)
            infer_fam = INF.family_status(contract, findings)
    # reconcile a claim's human reason with its FINAL verdict_inputs after any family promotion
    # (leakage/realism/overfitting/contamination): the promotion changes the verdict but not the
    # compare-time reason, which would otherwise read a stale "matches within budget" under a
    # REFUTED/INVALIDATED. Reason TEXT only - the gate re-derives the LABEL from verdict_inputs.
    for _c in claims:
        if _c.get("driving_dimension") and _c.get("verdict_inputs"):
            _c["reason"] = V.verdict_with_reason(_c["verdict_inputs"])[1]
    # every broken stamp must be reproducible. A family-promoted REFUTED/INVALIDATED (leakage / realism /
    # overfitting / contamination) carries the family's artifact-recheck reproduction but no runnable
    # command - attach the same offline `replay` command the core REFUTED path uses, so a counterparty
    # can re-derive the verdict byte-for-byte from the run dir.
    _rd = run_res.get("run_dir")
    if _rd:
        try:
            _rel = os.path.relpath(_rd)
            _rd_disp = _rel if not _rel.startswith("..") else _rd
        except ValueError:
            _rd_disp = _rd
        _replay = _redact_home("%s replay %s" % (_invocation(), _rd_disp))
        for c in claims:
            if c.get("verdict") in V.CATCH_VERDICTS:
                rep = c.get("reproduction_or_reverify") or {}
                if not rep.get("command"):
                    rep["command"] = _replay
                    rep.setdefault("manifest_ref", run_res.get("manifest_ref", "sha256:unavailable"))
                    c["reproduction_or_reverify"] = rep
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
                         "baseline": "checked" if bl else "not-applicable",
                         **({"leakage": leak_fam} if leak_fam else {}),
                         **({"overfitting": over_fam} if over_fam else {}),
                         **({"realism": real_fam} if real_fam else {}),
                         **({"contamination": cont_fam} if cont_fam else {}),
                         **({"backtest": bt_fam} if bt_fam else {}),
                         **({"point-in-time": pit_fam} if pit_fam else {}),
                         **({"data-snooping": ds_fam} if ds_fam else {}),
                         **({"regime": reg_fam} if reg_fam else {}),
                         **({"model-leakage": ml_fam} if ml_fam else {}),
                         **({"distribution-shift": shift_fam} if shift_fam else {}),
                         **({"era-embargo": emb_fam} if emb_fam else {}),
                         **({"simulation-assumptions": sim_fam} if sim_fam else {}),
                         **({"plausibility": plaus_fam} if plaus_fam else {}),
                         **({"inferred-flags": infer_fam} if infer_fam else {})},
            "not_verified": _not_verified(metric_ids, leak_fam, over_fam, real_fam, cont_fam,
                                          bt_fam, pit_fam, ds_fam, reg_fam, ml_fam, shift_fam, emb_fam,
                                          sim_fam),
        },
        "repo_verdict": None,
    }
    led["repo_verdict"] = LED.compute_repo_verdict(led)
    return led


def _input_fingerprint(target, contract, isolation=None):
    """Content-address everything the verdict depends on: the contract (minus draft notes, but incl.
    env.trust), the entrypoint bytes, every bound artifact's bytes, and an EXPLICIT isolation choice.
    Same fingerprint => the prior verdict is the verdict (re-verification re-derives it from identical
    inputs). An explicit --isolation (not auto) is part of the key so a request for a different tier
    re-runs instead of serving a result achieved under another tier (a weaker one would understate
    isolation)."""
    h = hashlib.sha256()
    # the verifier's own version and the interpreter line are part of the key: upgrading either
    # invalidates the cache (a different verifier run is a different computation). A default (auto)
    # isolation appends nothing, so existing cache entries keep their fingerprint.
    iso = isolation if isolation not in (None, "auto") else ""
    h.update(("calma-cache@2|calma=%s|py=%d.%d%s\n"
              % (__version__, sys.version_info[0], sys.version_info[1],
                 ("|iso=" + iso) if iso else "")).encode())
    h.update(json.dumps({k: v for k, v in contract.items() if not str(k).startswith("_")},
                        sort_keys=True).encode())
    rt = os.path.realpath(target)
    # Content-address the WHOLE input tree, not just the entrypoint + the declared OUTPUT
    # artifacts: a config file, an imported sibling module, or an input dataset the entrypoint
    # reads is just as load-bearing on the verdict. Hashing only the outputs let an edit to any
    # of those collide on the same fingerprint -> a STALE CONFIRMED served for a now-different
    # number (the cache's whole job is to skip a re-execution that would have caught the change).
    # Skips calma's own run state + regenerable/vendored caches; a very large file falls back to
    # (size, mtime) so a giant dataset can't make fingerprinting pathologically slow - a spurious
    # cache MISS only re-runs, it can never serve a stale verdict.
    SKIP = {".calma", ".calma_venv", ".calma_httpcache", ".git", ".hg", ".svn",
            "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache",
            ".ipynb_checkpoints", ".gstack", ".venv", "venv"}
    BIG = 64 * 1024 * 1024
    entries = []
    for dp, dns, fns in os.walk(rt):
        dns[:] = [d for d in dns
                  if d not in SKIP and not os.path.islink(os.path.join(dp, d))]
        for fn in fns:
            full = os.path.join(dp, fn)
            entries.append((os.path.relpath(full, rt), full))
    for rel, full in sorted(entries):
        h.update(rel.encode() + b"\x00")
        try:
            st = os.stat(full)
            if not stat.S_ISREG(st.st_mode):
                # a FIFO / socket / device in the tree must NOT be open()ed - reading a writer-less
                # FIFO blocks forever and hangs the verifier. Hash a structural marker instead.
                h.update(("special:%o" % stat.S_IFMT(st.st_mode)).encode())
            elif st.st_size > BIG:
                h.update(("big:%d:%d" % (st.st_size, int(st.st_mtime))).encode())
            else:
                with open(full, "rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        h.update(chunk)
        except OSError:
            h.update(b"<unreadable>")
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


def _reproduce_command(run_dir):
    """`<invocation> replay <run_dir>`, shown cwd-relative when the run dir is under cwd (no $HOME
    leak) else home-redacted - the same form the fresh-run path emits (lines ~356/565). Used to
    RE-POINT a cached ledger's reproduce line at the run dir actually being served."""
    if not run_dir:
        return None
    try:
        rel = os.path.relpath(run_dir)
        disp = rel if not rel.startswith("..") else run_dir
    except ValueError:
        disp = run_dir
    return _redact_home("%s replay %s" % (_invocation(), disp))


def _cached_result(target, fingerprint, why=False):
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
    if led.get("repo_verdict") not in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "MIXED", "INVALIDATED", "FLAG_FOR_DECLARATION"):
        return None
    # re-point the reproduce line at the run dir we are ACTUALLY serving: a ledger can be served from a
    # relocated/copied tree (the fingerprint matches by content), in which case its stored command still
    # names the ORIGINAL absolute path. Rewrite it to this target's run dir so `calma replay <...>` works.
    repro = _reproduce_command(run_dir)
    if repro:
        for c in led.get("claims", []):
            rep = c.get("reproduction_or_reverify")
            if isinstance(rep, dict) and rep.get("command"):
                rep["command"] = repro
    prefix = ("(cached - code, data, and claim unchanged since the last run; "
              "--force re-executes)\n")
    rendered = prefix + REP.render(led)                                        # full record
    display = prefix + REP.render(led, color=_color_enabled(), why=why)        # terminal (collapsed)
    return {"gate_exit": code, "gate": summary, "repo_verdict": led["repo_verdict"],
            "report": rendered, "display": display, "teardown": REP.teardown_card(led),
            "run_dir": run_dir, "ledger": led, "cached": True}


def _store_cache(target, fingerprint, run_id, repo_verdict):
    if repo_verdict not in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "MIXED", "INVALIDATED", "FLAG_FOR_DECLARATION"):
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


def _metric_variance(rec1, rec2):
    """The swing on the first finite headline metric between two re-runs: {metric_id, v1, v2, spread}.
    Quantifies HOW non-reproducible the result is, so the FLAKY message reads as a measurement."""
    by2 = {m["metric_id"]: m for m in (rec2.get("metrics") or [])}
    for m in rec1.get("metrics") or []:
        v1 = m.get("value")
        v2 = (by2.get(m["metric_id"]) or {}).get("value")
        if isinstance(v1, float) and isinstance(v2, float) and v1 == v1 and v2 == v2 and v1 != v2:
            return {"metric_id": m["metric_id"], "v1": v1, "v2": v2, "spread": abs(v1 - v2)}
    return None


# map the static determinism note to a concrete, human cause + the specific knob to pin.
_NONDET_HINTS = [
    ("torch", "a GPU/ML framework (torch) - set torch.manual_seed and torch.use_deterministic_algorithms(True), and pin CUBLAS_WORKSPACE_CONFIG"),
    ("tensorflow", "a GPU/ML framework (tensorflow) - set tf.random.set_seed and enable deterministic ops"),
    ("random", "Python's random module - call random.seed(<n>) before use"),
    ("numpy", "numpy RNG / BLAS - set np.random.seed(<n>) and pin OMP_NUM_THREADS=1 / MKL_NUM_THREADS=1"),
    ("uuid", "uuid generation - derive ids deterministically instead of uuid4()"),
    ("time", "wall-clock time - stop writing timestamps into the output (or pin them)"),
    ("datetime", "datetime.now() - pin the date or read it from declared input data"),
    ("threading", "thread scheduling - pin the worker/thread count and avoid order-dependent reductions"),
    ("multiprocessing", "process scheduling - fix the pool size and the reduction order"),
]


def _nondeterminism_hint(det_note):
    """The likely source of run-to-run drift, from the static determinism note (best-effort)."""
    note = (det_note or "").lower()
    for needle, hint in _NONDET_HINTS:
        if needle in note:
            return hint
    return None


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
        if not os.path.isfile(full):
            out[a["path"]] = "<not-a-regular-file>"  # FIFO/device: never open() (would block)
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


@dataclass(frozen=True)
class VerifyOptions:
    """The single carrier for verify()'s run-MODE flags (H2). Verdict inputs (target/claim/metric/
    run_id) stay positional on verify(); everything that governs HOW the run executes lives here so a
    new feature adds one field instead of re-bumping the signature + two dispatch sites (the root
    cause of the dropped-flag bug: the old --run-only dispatch silently omitted cross_engine /
    check_determinism). Frozen + a fixed field set => a typo or a dropped flag fails loud."""
    force: bool = False
    check_determinism: bool = False
    run_only: bool = False
    cross_engine: bool = False
    trust: str = "own-code"
    isolation: "str | None" = None
    timeout: "int | None" = None
    restore: bool = False
    why: bool = False    # terminal verbosity: expand the full 'not verified' list (report.txt stays full)

    @classmethod
    def from_args(cls, a):
        """Build one options object from a parsed argparse namespace, in ONE place (so the dispatch
        can't drop a flag). To vary one field for a follow-on call, use dataclasses.replace(opts, ...)
        (the auto-retry does: replace(opts, force=True, restore=True))."""
        return cls(force=getattr(a, "force", False),
                   check_determinism=getattr(a, "check_determinism", False),
                   run_only=getattr(a, "run_only", False),
                   cross_engine=getattr(a, "cross_engine", False),
                   trust=getattr(a, "trust", "own-code"),
                   isolation=getattr(a, "isolation", None),
                   timeout=getattr(a, "timeout", None),
                   restore=getattr(a, "restore", False),
                   why=getattr(a, "why", False))


_OPT_FIELDS = frozenset(f.name for f in fields(VerifyOptions))


def verify(target, claim=None, metric=None, run_id="run", opts=None):
    # H2: run-mode flags travel in ONE VerifyOptions object - opts= is the ONLY way to pass them. Every
    # callsite (production AND tests) constructs a VerifyOptions, so there is exactly one entry shape; a
    # frozen, fixed-field options object means a typo or a dropped flag fails loud at construction instead
    # of being silently swallowed as a loose kwarg (the root cause of the old dropped-flag bug). Verdict
    # inputs (target/claim/metric/run_id) stay positional.
    if opts is None:
        opts = VerifyOptions()
    # unpack into locals so the (large) body below reads unchanged - opts is the source of truth.
    force, check_determinism = opts.force, opts.check_determinism
    run_only, cross_engine = opts.run_only, opts.cross_engine
    trust, isolation, timeout, restore = opts.trust, opts.isolation, opts.timeout, opts.restore
    target = os.path.realpath(target)
    if trust not in ("own-code", "third-party"):
        raise ValueError("--trust must be own-code or third-party (got %r)" % trust)
    if isolation not in (None, "auto", "seatbelt", "bwrap", "docker", "firecracker", "e2b"):
        raise ValueError("--isolation must be auto/seatbelt/bwrap/docker/firecracker/e2b (got %r)" % isolation)
    if metric and RCP.get(metric) is None:
        # unknown/unclear metric id -> rank the recipes it most likely meant (semantic, not just
        # string-edit distance). Replaces difflib: alias/description-aware, same engine as `suggest`.
        sugg = [s["metric_id"] for s in SUGG.suggest(metric.replace("_", " "), k=3)]
        # common slip: passing a binding TAG ("return", "prediction") instead of a recipe id
        tag_hits = sorted(m for m in RCP.ids()
                          if metric in (RCP.get(m).manifest.get("required_tags") or []))[:4]
        hint = ("did you mean: %s?" % ", ".join(sugg)) if sugg else ""
        if tag_hits:
            hint = ("%r is a binding tag, not a recipe - recipes that bind it: %s. %s"
                    % (metric, ", ".join(tag_hits), hint)).strip()
        if hint:
            raise ValueError("no recipe named %r. %s (full list: calma recipes)" % (metric, hint))
        raise ValueError("no recipe named %r - run `calma recipes` for the full list" % metric)
    if not os.path.isdir(target):
        raise ValueError("target directory does not exist: %s" % target)
    if not any(n for n in os.listdir(target) if n not in (".calma", ".DS_Store")):
        raise ValueError("nothing to verify: %s is empty (expected code + machine-readable outputs)" % target)
    calma_dir = os.path.join(target, ".calma")
    if os.path.islink(calma_dir):
        # a target shipping .calma as a SYMLINK would make calma write all its own verdict state
        # (cache, ledgers, run dirs) THROUGH the link to an attacker-chosen location - and dodge the
        # sandbox write-confinement that keys on the literal .calma path. Refuse: calma's state dir
        # must be a real directory inside the target.
        raise ValueError(".calma in %s is a symlink - refusing. calma's state directory must be a "
                         "real directory (a symlinked .calma can redirect verdict state outside the "
                         "target); remove or rename it." % target)
    run_dir = os.path.join(calma_dir, run_id)
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
        if block_finding is not None and run_only and metric:
            # M2: --run-only is a no-verdict / no-gate DEBUG view ("let me just see my Sharpe"),
            # so there is no verdict integrity to protect. Let --metric explore a metric the
            # committed contract does not pin: re-bind the requested metric over the same repo,
            # KEEPING the committed run block (entrypoint/network/cwd). Artifacts may only exist
            # post-run, so binding is finished by the existing post-run re-draft below - we just
            # clear the block and move off the committed contract. No verdict is ever emitted.
            drafted = DC.draft(target, claim=claim, metric=metric)
            drafted["run"] = contract.get("run", drafted.get("run"))
            # carry the committed env (the drafter always creates one, so setdefault was a no-op);
            # committed keys win so PYTHONHASHSEED / ecosystem overrides survive the run-only re-draft
            drafted["env"] = {**(drafted.get("env") or {}), **(contract.get("env") or {})}
            contract = drafted
            contract_path = os.path.join(run_dir, "verify.yaml")
            json.dump(contract, open(contract_path, "w"), indent=2)
            claim_note = ("run-only debug: exploring %s (the committed contract pins a different "
                          "metric; no verdict, no gate)" % metric)
            block_finding = None
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
    if block_finding is None and not force and not check_determinism and not run_only and not cross_engine:
        hit = _cached_result(target, _input_fingerprint(target, contract, isolation), opts.why)
        if hit:
            _trace("cache", "code+data+claim unchanged -> prior verdict (--force re-executes)")
            if claim_note:
                hit["claim_note"] = claim_note
                hit["report"] = "note: %s\n\n%s" % (claim_note, hit["report"])
            return hit

    diff = None
    cross = None        # B2: the cross-engine correctness block (only when --cross-engine is set)
    refused = killed = False
    entry = contract.get("run", {}).get("entrypoint")
    if run_only and (block_finding is not None or entry == "MANUAL"):
        # run-only NEVER emits a verdict (its invariant). When there's nothing to execute/recompute -
        # a metric the committed contract doesn't pin and couldn't be re-bound, or no entrypoint -
        # return an empty no-verdict debug view, not an INCONCLUSIVE verdict ledger.
        why = ("the committed contract pins a different metric and it couldn't be re-bound here"
               if block_finding is not None else
               "no entrypoint detected (name your script main.py/run.py, or set run.entrypoint)")
        return {"run_only": True, "target": os.path.basename(target), "run_dir": run_dir,
                "isolation_tier": "n/a", "determinism_mode": "n/a", "metrics": [], "note": why}
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
        # intake/restore (WS3): this is the ONE phase that may use the network - it runs BEFORE the
        # verified, network-denied re-execution. --restore pins the repo's declared deps into
        # <target>/.calma_venv (run_hermetic then runs under that interpreter); always capture the
        # interpreter, declared sources, and data bindings (by content hash) into intake.json.
        intake_report = None
        try:
            intake_report = INTAKE.intake(target, contract, do_restore=restore, timeout=eff_timeout)
            json.dump(intake_report, open(os.path.join(run_dir, "intake.json"), "w"), indent=2)
            if restore:
                rr = intake_report.get("restore") or {}
                _trace("intake", "restore %s (%s; %d pinned)"
                       % ("ok" if intake_report.get("restored") else "incomplete",
                          rr.get("method") or "no declared deps", rr.get("installed_count", 0)))
        except (OSError, ValueError) as _e:
            _trace("intake", "intake skipped: %s" % _e)
        _trace("re-run", "executing %s in the sandbox (network off)..."
               % contract.get("run", {}).get("entrypoint"))
        _t0 = _time.time()
        with _Spinner("re-executing %s" % contract.get("run", {}).get("entrypoint")):
            run_res = H.run(contract_path, base=target, timeout=eff_timeout,
                            trust_override=("untrusted-third-party" if trust == "third-party"
                                            else None),
                            isolation=(None if isolation in (None, "auto") else isolation))
        run_res["run_dir"] = run_dir
        for _tail in ("stdout_tail", "stderr_tail"):
            if run_res.get(_tail):
                run_res[_tail] = _redact_home(run_res[_tail])
        _trace("re-run", "exit %s in %.1fs | isolation %s | determinism %s"
               % (run_res.get("exit_code"), _time.time() - _t0,
                  run_res.get("isolation_tier"), run_res.get("determinism_mode")))
        first_run_notice = _first_run_notice(target, run_res.get("isolation_tier"))
        if run_res.get("exit_code") in (3, 4) and run_only:
            # COR-1: run-only NEVER emits a verdict. A refused (3) / killed (4) run has nothing to
            # recompute, so return a no-verdict debug view instead of an INCONCLUSIVE verdict ledger.
            why = ("the run timed out after %ds (raise --timeout)" % eff_timeout
                   if run_res.get("exit_code") == 4 else
                   "execution was refused (no verified sandbox for this trust posture)")
            return {"run_only": True, "target": os.path.basename(target), "run_dir": run_dir,
                    "isolation_tier": run_res.get("isolation_tier"), "determinism_mode": "n/a",
                    "metrics": [], "note": why}
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
            # FLAKY check (WS5): re-execute once more and diff the artifact bytes. Identical inputs
            # that produce different outputs is a verdict-BLOCKING finding (G1c) -> CAN'T-CONFIRM,
            # never a false-confirm of a number that won't reproduce. We pay for the 2nd run exactly
            # when it matters: the caller asked (--check-determinism), it's untrusted counterparty
            # code (third-party), OR bit-determinism could NOT be proven statically (measured-band/
            # uncontrolled) AND a claim is being judged. A controlled-to-bit run is provably stable.
            det_mode = run_res.get("determinism_mode", "uncontrolled")
            # PERF: the recompute kernels are PURE (numeric.py) - re-running one on the same fixed columns
            # is bit-identical, so the k>1 intra-recompute spread is provably 0 on the controlled-to-bit
            # path. Run the recipe ONCE there (k=3 is wasted work that scales with artifact size - a 3x
            # cost on large pilot datasets). measured-band / uncontrolled keep k=3 (there the SANDBOX run,
            # not the kernel, is what's being sampled, and k_spread is meaningful).
            _rk = 1 if det_mode == "controlled-to-bit" else 3
            any_claim_value = any(m.get("claimed_value") is not None
                                  for m in contract.get("metrics", []))
            do_recheck = run_res.get("exit_code") == 0 and (
                check_determinism or trust == "third-party"
                or (det_mode != "controlled-to-bit" and any_claim_value))
            outputs_unstable = False
            if do_recheck:
                h1 = _artifact_hashes(target, contract)
                rec1 = RC.recompute_contract(contract_path, base=target, k=_rk)  # run-1 metric values
                run2 = H.run(contract_path, base=target, timeout=eff_timeout,
                             trust_override=("untrusted-third-party" if trust == "third-party"
                                             else None),
                             isolation=(None if isolation in (None, "auto") else isolation))
                variance = None
                if run2.get("exit_code") == 0:
                    h2 = _artifact_hashes(target, contract)
                    unstable_paths = sorted(p for p in set(h1) | set(h2) if h1.get(p) != h2.get(p))
                    if unstable_paths:  # quantify the swing on the headline metric (reads as rigor)
                        variance = _metric_variance(rec1, RC.recompute_contract(contract_path, base=target, k=_rk))
                else:
                    unstable_paths = ["<second run exited %s>" % run2.get("exit_code")]
                outputs_unstable = bool(unstable_paths)
                run_res["determinism_recheck"] = {
                    "reruns": 2, "stable": not outputs_unstable,
                    "differing_artifacts": unstable_paths, "variance": variance,
                    "trigger": ("--check-determinism" if check_determinism else
                                "third-party-auto" if trust == "third-party" else
                                "static-nondeterminism-auto"),
                }
            rec = RC.recompute_contract(contract_path, base=target, k=_rk)
            json.dump(rec, open(os.path.join(run_dir, "recompute.json"), "w"), indent=2)
            for _rm in rec.get("metrics", []):
                if not _rm.get("degenerate"):
                    _trace("recompute", "%s rebuilt from raw %s: %s (deterministic kernels, "
                           "%dx identical)"
                           % (_rm.get("metric_id"), _rm.get("artifact", "outputs"),
                              REP.fmt_value(_rm.get("value"), _rm.get("metric_id")),
                              _rm.get("k", 1)))
            # B2 (opt-in --cross-engine): recompute each metric through an INDEPENDENT second kernel and
            # diff. ADDITIVE - it attaches a cross_engine block + writes cross_engine.json, and NEVER
            # touches the verdict/ledger (the primary numeric.py recompute stays authoritative). Fail-soft.
            if cross_engine:
                try:
                    cross = CE.cross_check_contract(contract, target, rec)
                    json.dump(cross, open(os.path.join(run_dir, "cross_engine.json"), "w"), indent=2)
                    if cross.get("n_checked"):
                        _trace("cross-engine", "%d %s recomputed on a 2nd independent kernel: %s"
                               % (cross["n_checked"],
                                  "metric" if cross["n_checked"] == 1 else "metrics",
                                  "DIVERGENCE" if cross.get("any_divergence")
                                  else "agree to %g" % CE.ABS_FLOOR))
                except (OSError, ValueError, KeyError, TypeError):
                    cross = None
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
            if run_only:
                # --run-only / calma_debug: re-run + recompute + diff, then emit the binding +
                # recomputed value + gap and STOP - no verdict, no gate, no ledger/cache/attest. Lets an
                # agent iterate mid-task ("what does the code actually compute, and how far off is my
                # claim?") without a pass/fail. recompute.json + diff.json are already written; this just
                # shapes a no-verdict view. Guarded by run_only, so the normal verdict path is untouched.
                _bind = {m.get("metric_id"): (m.get("binding") or {}) for m in contract.get("metrics", [])}
                dbg = []
                for dm in diff.get("metrics", []):
                    cl, rcv = dm.get("claimed"), dm.get("recomputed")
                    num = (isinstance(cl, (int, float)) and not isinstance(cl, bool)
                           and isinstance(rcv, (int, float)) and not isinstance(rcv, bool))
                    dbg.append({"metric": dm.get("metric_id"), "binding": _bind.get(dm.get("metric_id")),
                                "claimed": cl, "recomputed": rcv,
                                "gap": (abs(cl - rcv) if num else None), "reason": dm.get("reason")})
                return {"run_only": True, "target": os.path.basename(target), "run_dir": run_dir,
                        "isolation_tier": run_res.get("isolation_tier"),
                        "determinism_mode": run_res.get("determinism_mode"), "metrics": dbg,
                        "cross_engine": cross}  # COR-5: surface --cross-engine in run-only too
            led = _assemble_ledger(contract, diff, run_res, claim_text=claim)
            # M3: carry the cross-engine result INTO the ledger so the report renders it right under
            # the verdict (not buried below a not-verified dump + the exit line). Additive only.
            if cross is not None:
                led["cross_engine"] = cross
            # calma AUTO-PICKED the metric (producer didn't pin it) and it didn't confirm -> the
            # ask was unclear. Offer ranked alternatives from the claim + data columns and let the
            # user pick, instead of silently standing on a guessed metric. Only here: a confirmed
            # auto-pick, or a user-pinned --metric, never triggers this. Fail-open.
            if (led.get("scope", {}).get("binding_note")
                    and led.get("repo_verdict") not in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS")):
                _sugg = _metric_suggestions(target, claim)
                if _sugg:
                    led["suggestions"] = _sugg
                    led["scope"]["binding_note"] += _suggest_unblock(_sugg)
            if not diff["metrics"]:
                # P1-5: a committed contract that pins NO artifacts next to recomputable outputs is
                # the cause - name verify.yaml in the fix instead of asking for files that exist
                candidates = []
                if contract_path == committed and not contract.get("artifacts"):
                    candidates = [a["path"] for a in DC._scan_csvs(target)
                                  if any(s["tag"] for s in a["columns"].values())]
                # genuinely unclear what to compute -> auto-rank likely metrics from the claim +
                # the data's columns and ask the user to pick or explain (no `calma suggest` needed)
                sugg = _metric_suggestions(target, claim)
                if candidates:
                    led["findings"].append({
                        "id": "f-no-metric", "claim_id": None, "dimension": "contract-grounding",
                        "severity": "major", "status": "open", "confidence": "deterministic",
                        "fixable_by": "author",
                        "locator": "verify.yaml pins no artifacts, but recomputable outputs exist (%s)"
                                   % ", ".join(candidates[:3]),
                        "unblock": "your verify.yaml lists no artifacts - add %s (with its columns) "
                                   "to verify.yaml, or delete verify.yaml to auto-detect%s"
                                   % (candidates[0], _suggest_unblock(sugg)),
                        "suggestions": sugg,
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
                                   "(e.g. predictions.csv with y_true,y_pred / returns.csv with strat_return)"
                                   + _suggest_unblock(sugg),
                        "suggestions": sugg,
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
    rendered = REP.render(led, diff)                                  # plain, FULL - for report.txt + callers
    # terminal: collapse the long 'not verified' list to a one-line summary unless --why (report.txt
    # keeps the full record either way, and --json carries the full scope.not_verified).
    display = REP.render(led, diff, color=_color_enabled(), why=opts.why)
    if claim_note:
        rendered = "note: %s\n\n%s" % (claim_note, rendered)
        display = "note: %s\n\n%s" % (claim_note, display)
    open(os.path.join(run_dir, "report.txt"), "w").write(rendered)
    card = REP.teardown_card(led)
    if card:
        open(os.path.join(run_dir, "teardown.txt"), "w").write(card)
    _store_cache(target, _input_fingerprint(target, contract, isolation), run_id, led["repo_verdict"])
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
            "teardown": card, "run_dir": run_dir, "ledger": led, "cross_engine": cross,
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
                 run_id=os.path.basename(run_dir) + "-replay", opts=VerifyOptions(force=True))
    same_verdict = res["repo_verdict"] == prior.get("repo_verdict")
    pc = (prior.get("claims") or [{}])[0]
    nc = (res["ledger"].get("claims") or [{}])[0]
    pv, nv = pc.get("recomputed_value"), nc.get("recomputed_value")
    same_value = (pv is None and nv is None) or \
        (isinstance(pv, float) and isinstance(nv, float) and abs(pv - nv) <= 1e-9 + 1e-6 * abs(pv))
    # Reproduction is about the NUMBER. A bit-identical recompute reproduced even if the verdict
    # LABEL drifted on the conclusiveness axis (CONFIRMED<->INCONCLUSIVE because the isolation tier
    # differs on this host, or because a later verify into the shared run dir overwrote the stored
    # label - the prior is read from a MUTABLE ledger.json). A CONFIRMED<->REFUTED flip can only
    # happen WITH a value change, so gating on same_value never calls a real non-reproduction
    # "reproduced". Verdict-label drift is reported as a note, not a failure.
    ok = same_value
    lines = ["CALMA REPLAY  -  %s" % prior.get("target", os.path.basename(target)),
             "  prior:    %s  (recomputed %s)" % (prior.get("repo_verdict"), pv),
             "  replayed: %s  (recomputed %s)" % (res["repo_verdict"], nv)]
    if not ok:
        lines.append("  DID NOT REPRODUCE - the recomputed number changed")
    elif same_verdict:
        lines.append("  REPRODUCED - the verdict holds under re-execution")
    else:
        lines.append("  REPRODUCED - the recomputed number is identical; the verdict LABEL differs "
                     "(%s -> %s), reflecting a changed environment (e.g. isolation tier), not the "
                     "computation" % (prior.get("repo_verdict"), res["repo_verdict"]))
    return ok, "\n".join(lines)


def report(run_dir, out=None, pdf=True, sign=True):
    """WS2 deliverable: render a branded HTML report (prints to PDF) and build a self-contained,
    offline replay bundle that re-derives the verdict byte-for-byte. If a signing key exists the run
    is signed first (idempotent) so the report carries authoritative integrity hashes and the bundle
    is signature-verifiable. Returns {html, pdf, replay_dir, signed, repo_verdict}."""
    run_dir = os.path.realpath(run_dir)
    led_path = os.path.join(run_dir, "ledger.json")
    if not os.path.exists(led_path):
        raise ValueError("no ledger.json under %s - run `calma verify` first, then point `calma "
                         "report` at the .calma/<run-id> dir it printed" % run_dir)
    led = json.load(open(led_path))
    diff = None
    dpath = os.path.join(run_dir, "diff.json")
    if os.path.exists(dpath):
        try:
            diff = json.load(open(dpath))
        except (OSError, ValueError):
            diff = None
    bundle = None
    bpath = os.path.join(run_dir, attest.BUNDLE_NAME)
    if sign and not os.path.exists(bpath) and attest.load_signing_key() is not None:
        try:
            bundle, _ = attest.sign_run(run_dir)
        except (OSError, ValueError):
            bundle = None
    if os.path.exists(bpath):
        try:
            bundle = json.load(open(bpath))
        except (OSError, ValueError):
            bundle = None
    html = REP.render_html(led, diff, bundle, run_dir)
    rd_report = os.path.join(run_dir, "report.html")
    with open(rd_report, "w") as fh:
        fh.write(html)
    out = out or rd_report
    if os.path.realpath(out) != os.path.realpath(rd_report):
        with open(out, "w") as fh:
            fh.write(html)
    # the replay bundle reads run_dir/report.html (written above), so build it after the report.
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    replay_dir = REP.write_replay_bundle(run_dir, scripts_dir)
    pdf_path = REP.to_pdf(out) if pdf else None
    return {"html": out, "pdf": pdf_path, "replay_dir": replay_dir,
            "signed": bundle is not None, "repo_verdict": led.get("repo_verdict")}


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
    for v in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "MIXED", "INVALIDATED",
              "FLAG_FOR_DECLARATION", "INCONCLUSIVE"):
        if counts.get(v):
            lines.append("  %-24s %d" % (v, counts[v]))
    catches = [r for r in verifs if r.get("verdict") in V.CATCH_VERDICTS]
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


def _json_finite(obj):
    """Recursively replace non-finite floats (NaN/Inf) with None so `--json` is STRICT JSON.
    Python's json.dumps emits bare NaN/Infinity by default, which JavaScript's JSON.parse rejects
    and jq silently coerces to wrong values - both bad for the agents that consume `--json`. A NaN
    recomputed value (a degenerate recompute) becomes null; its verdict is already INCONCLUSIVE."""
    if isinstance(obj, float):
        return obj if (obj == obj and obj not in (float("inf"), float("-inf"))) else None
    if isinstance(obj, dict):
        return {k: _json_finite(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_finite(v) for v in obj]
    return obj


def _json_result(res):
    """The agent-consumable structured verdict (stable shape; no prose parsing needed). The top-level
    metric/claimed/recomputed mirror the FIRST claim for back-compat; `metrics` carries ALL of them so
    a multi-metric contract's every verdict is reachable without parsing the ledger."""
    led = res["ledger"]
    claims = led.get("claims") or [{}]
    c0 = claims[0]
    # the process exit is overridden to 3 (refused) / 4 (killed); reflect that in the JSON so an
    # agent keying on gate_exit sees the same code the shell does (not the pre-override gate value).
    eff_exit = 3 if res.get("refused") else 4 if res.get("killed") else res["gate_exit"]
    return {
        "verdict": res["repo_verdict"],
        "clean": eff_exit == 0,
        "gate_exit": eff_exit,
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
        # CAN'T-CONFIRM -> a structured demand (None unless INCONCLUSIVE): what could not be verified +
        # exactly what to provide to resolve it. Turns the gap into leverage agents/diligence can act on.
        "needs": REP.needs_demand(led),
        "note": res.get("claim_note"),
        "isolation_tier": led.get("scope", {}).get("isolation_tier"),
        "determinism_mode": led.get("scope", {}).get("determinism_mode"),
        # the full 'what we did NOT check' list (the terminal report collapses this to a one-line
        # summary unless --why; machine consumers always get the complete set here).
        "not_verified": led.get("scope", {}).get("not_verified", []),
        "run_dir": res["run_dir"],
        # B2: present only when --cross-engine ran; agents key on cross_engine.any_divergence
        **({"cross_engine": res["cross_engine"]} if res.get("cross_engine") else {}),
    }


def _ai_draft_subprocess(target, *, budget=3, model=None, timeout=600):
    """Best-effort AI draft via the edges A2 seam, run as a SUBPROCESS - the core never imports edges
    (firewall), exactly like the MCP server shelling out to `python -m edges.extract`. `python -m
    edges.contract` is launched from the repo root so the `edges` package resolves; edges.contract.draft
    self-bootstraps the core scripts dir onto its own sys.path. Returns {"ok": bool, ...}."""
    import subprocess
    # scripts -> calma -> skills -> .claude -> <repo root> (the dir that contains the edges/ package)
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    argv = [sys.executable, "-m", "edges.contract", target, "--json", "--budget", str(budget)]
    if model:
        argv += ["--model", model]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=repo_root)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": "could not launch the AI drafter: %s" % e}
    if p.returncode != 0:
        tail = (p.stderr or "").strip().splitlines()
        return {"ok": False, "error": tail[-1] if tail else "edges.contract exited %d" % p.returncode}
    try:
        return {"ok": True, **json.loads(p.stdout)}
    except ValueError:
        return {"ok": False, "error": "the AI drafter produced no JSON"}


def init_cmd(framework, target=".", *, force=False, list_fw=False):
    """Scaffold a framework-tuned starter verify.yaml so a quant/ML team adopts on its own stack without
    learning the contract format. Emits a runnable SKELETON (the right entrypoint hint, artifact layout,
    headline metric + binding, and validity-block hints) the user fills in, then runs `calma verify`.
    M1: `--list` shows the frameworks; on an EXISTING repo whose artifacts don't match the template,
    init refuses and steers to `calma draft` (which binds what's actually on disk) instead of writing
    a contract that points at paths that don't exist."""
    import textwrap
    import frameworks as FW
    if list_fw:
        print("frameworks: %s" % ", ".join(FW.list_frameworks()))
        print("aliases:    %s" % ", ".join("%s -> %s" % (a, t)
                                            for a, t in sorted(FW.ALIASES.items())))
        print("usage: calma init <framework> [dir]   (then `calma verify`, or `calma draft` for an "
              "existing repo)")
        return 0
    if not framework:
        print("name a framework (or `calma init --list`). Available: %s"
              % ", ".join(FW.list_frameworks()), file=sys.stderr)
        return 2
    contract = FW.starter_contract(framework)
    if contract is None:
        print("unknown framework %r. Available: %s (or `calma init --list` for aliases)"
              % (framework, ", ".join(FW.list_frameworks())), file=sys.stderr)
        return 2
    target = os.path.abspath(target)
    if not os.path.isdir(target):
        print("not a directory: %s" % target, file=sys.stderr)
        return 2
    dest = os.path.join(target, "verify.yaml")
    if os.path.exists(dest) and not force:
        print("%s already exists - pass --force to overwrite, or edit it directly" % dest, file=sys.stderr)
        return 2
    # M1: detect a template/repo mismatch BEFORE writing a trap. If the template's declared artifacts
    # don't exist but the repo DOES carry data files, the contract would just fail on missing paths.
    declared = [a.get("path") for a in (contract.get("artifacts") or []) if a.get("path")]
    missing = [p for p in declared if not os.path.exists(os.path.join(target, p))]
    if declared and missing and not force:
        try:
            found = DC._scan_csvs(target)
        except (OSError, ValueError):
            found = []
        if found:
            present = ", ".join("%s (%s)" % (a["path"], ", ".join(
                c for c, s in a["columns"].items() if s.get("tag")) or "?") for a in found[:3])
            print("the %s template expects %s, which this repo doesn't have."
                  % (framework, ", ".join(missing)), file=sys.stderr)
            print("  but it DOES have: %s" % present, file=sys.stderr)
            print("  -> run `calma draft` to bind what's actually here, or "
                  "`calma init %s --force` to write the skeleton anyway." % framework, file=sys.stderr)
            return 2
    note = contract.pop("_note", None)   # printed for the human; not written into the contract file
    json.dump(contract, open(dest, "w"), indent=2)
    m = (contract.get("metrics") or [{}])[0]
    print("wrote %s  (%s starter contract)" % (dest, framework))
    print("  entrypoint: %s   metric: %s over %s"
          % ((contract.get("run") or {}).get("entrypoint"), m.get("metric_id"), m.get("artifact")))
    if note:
        print(textwrap.fill(note, 94, initial_indent="  next: ", subsequent_indent="        "))
    return 0


def draft_cmd(target, *, ai=False, budget=3, model=None, force=False, as_json=False):
    """Generate <target>/verify.yaml so you can point Calma at a messy repo and get a runnable contract.
    Heuristic (pure-stdlib DC.draft) by default; --ai shells out to the edges A2 drafter (an LLM draft +
    a counterexample repair loop), FALLING BACK to the heuristic when the edges deps / API key are
    unavailable. Prints what was detected + what still needs human confirmation before you trust it."""
    target = os.path.abspath(target)
    if not os.path.isdir(target):
        print("not a directory: %s" % target, file=sys.stderr)
        return 2
    dest = os.path.join(target, "verify.yaml")
    if os.path.exists(dest) and not force:
        print("%s already exists - pass --force to overwrite, or edit it directly" % dest, file=sys.stderr)
        return 2

    ai_note, source, trace = None, "heuristic", None
    if ai:
        out = _ai_draft_subprocess(target, budget=budget, model=model)
        if out.get("ok"):
            source, trace = "ai", out.get("trace")
            contract = DC.load_contract(dest)   # the edges subprocess already wrote verify.yaml
        else:
            ai_note = out.get("error")
    if source != "ai":
        contract = DC.draft(target)
        json.dump(contract, open(dest, "w"), indent=2)

    notes = contract.get("_draft_notes") or {}
    mets = contract.get("metrics") or []
    if as_json:
        print(json.dumps({"source": source, "ai_fell_back": bool(ai_note), "verify_yaml": dest,
                          "contract": contract, "trace": trace}, indent=2))
        return 0
    if ai_note:
        print("AI drafting unavailable (%s) - wrote a heuristic draft instead." % ai_note)
    print("wrote %s  (%s draft - review before relying on it)"
          % (dest, "AI" if source == "ai" else "heuristic"))
    print("  entrypoint: %s" % ((contract.get("run", {}) or {}).get("entrypoint") or "(none)"))
    if mets:
        for m in mets:
            print("  metric:     %s over %s  (binding %s, %s)"
                  % (m.get("metric_id"), m.get("artifact"),
                     ", ".join(map(str, (m.get("binding") or {}).values())) or "?",
                     m.get("binding_status", "ungraded")))
    else:
        print("  metric:     (none detected - pass --metric/--claim when you verify)")
    for d in notes.get("detected_blocks") or []:
        print("  detected:   %s" % d)
    for sug in notes.get("suggested_blocks") or []:
        print("  to add:     %s" % sug)
    if notes.get("needs_confirmation"):
        print("  confirm:    %s" % ", ".join(notes["needs_confirmation"]))
    if notes.get("warning"):
        print("  warning:    %s" % notes["warning"])
    if source == "ai" and trace:
        print("  repair:     resolved=%s in %s round(s)"
              % (trace.get("resolved"), trace.get("iterations_used")))
    print("  next:       review the bindings, then  calma verify %s \"<your claim>\"" % target)
    return 0


def _onboard_subprocess(args, *, timeout=900):
    """Run the edges onboarding proposer as a SUBPROCESS - the core never imports edges (firewall),
    exactly like draft --ai shells out to `python -m edges.contract`. `python -m edges.synth.onboard`
    is launched from the repo root so the `edges` package resolves. Returns the parsed --json result
    (or {"ok": False, "error": ...} when the edges deps / API key are unavailable)."""
    import subprocess
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    argv = [sys.executable, "-m", "edges.synth.onboard"] + args + ["--json"]
    try:
        p = subprocess.run(argv, cwd=repo_root, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": str(e)}
    try:
        return {"ok": True, **json.loads(p.stdout)}
    except ValueError:
        tail = (p.stderr or p.stdout or "").strip().splitlines()
        return {"ok": False, "error": tail[-1] if tail else "edges.synth.onboard produced no JSON"}


def onboard_cmd(metric_id, family, methodology, vectors, *, hints=None, budget=6, model=None,
                compiled_path=None, as_json=False):
    """Onboard a firm's BESPOKE metric (one with no published oracle) from a methodology + the firm's
    own reference numbers: an LLM proposes the pure-stdlib recipe, and the deterministic gate admits it
    ONLY when it reproduces every reference vector + holds the declared metamorphic relations + degrades
    on edge cases + is bit-stable -- the SAME gate the built-in recipes clear. AI proposes; determinism
    disposes. Needs the edges deps + an API key (the gate itself is offline)."""
    args = ["--metric-id", metric_id, "--family", family, "--methodology", methodology,
            "--vectors", vectors, "--budget", str(budget)]
    for h in (hints or []):
        args += ["--metamorphic-hint", h]
    if model:
        args += ["--model", model]
    if compiled_path:
        args += ["--compiled-path", compiled_path]
    out = _onboard_subprocess(args)
    if not out.get("ok"):
        print("onboarding unavailable (%s) - it needs the edges deps + an API key (ANTHROPIC_API_KEY); "
              "the gate itself is offline." % out.get("error"))
        return 2
    if as_json:
        print(json.dumps({k: out[k] for k in ("admitted", "metric_id", "iterations",
                                              "program_sha256", "last_stage", "trace") if k in out}))
        return 0 if out.get("admitted") else 1
    print("onboarding %r (%s) - AI proposes, the deterministic gate disposes:" % (metric_id, family))
    for t in out.get("trace", []):
        if t.get("ok"):
            print("  attempt %d: ADMITTED" % t["attempt"])
        else:
            print("  attempt %d: rejected at the %-11s stage -> counterexample fed back"
                  % (t["attempt"], t.get("stage")))
    if out.get("admitted"):
        print("\nADMITTED %r in %d attempt(s)  (program_sha256 %s)"
              % (metric_id, out.get("iterations"), (out.get("program_sha256") or "")[:16]))
        print("  frozen + gated by the SAME admission as the built-in recipes; it re-validates on load.")
        print("  next:  calma verify <your repo> \"<%s claim>\" --metric %s" % (metric_id, metric_id))
        return 0
    print("\nNOT admitted within budget (last failing stage: %s) - the gate rejected every draft, so "
          "NOTHING was frozen. A bespoke metric the gate can't admit never emits a verdict."
          % out.get("last_stage"))
    return 1


def _repair_subprocess(run_dir, *, budget=4, model=None, apply=False, timeout=900):
    """Run the edges A4 repair proposer as a SUBPROCESS - the core never imports edges (firewall),
    exactly like `draft --ai` -> edges.contract and `onboard` -> edges.synth.onboard. Launched from the
    repo root so the `edges` package resolves. Returns the parsed --json result (or {"ok": False, ...}
    when the edges deps / API key are unavailable)."""
    import subprocess
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    argv = [sys.executable, "-m", "edges.repair", run_dir, "--budget", str(budget), "--json"]
    if model:
        argv += ["--model", model]
    if apply:
        argv += ["--apply"]
    try:
        p = subprocess.run(argv, cwd=repo_root, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "returncode": -1, "error": str(e)}
    try:
        # exit 0 (accepted) or 1 (ran, no accepted patch) both emit the JSON result; only exit 2
        # (not a catch) and the import/key failures emit no JSON.
        return {"ok": True, "returncode": p.returncode, **json.loads(p.stdout)}
    except ValueError:
        tail = (p.stderr or p.stdout or "").strip().splitlines()
        return {"ok": False, "returncode": p.returncode,
                "error": tail[-1] if tail else "edges.repair produced no JSON"}


def repair_cmd(run_dir, *, budget=4, model=None, apply=False, as_json=False):
    """A4: repair a REFUTED/INVALIDATED catch. The model PROPOSES a minimal patch; Calma re-verifies the
    PATCHED code FROM SCRATCH in an isolated clone (the working tree is never touched) and only ACCEPTS a
    patch that genuinely flips the verdict to clean WITH the goalposts immutable + the anti-test-hacking
    review gate passing. AI proposes; determinism disposes. Needs the edges deps + an API key (the
    re-verify gate itself is offline). --apply writes the accepted patch to the working tree."""
    out = _repair_subprocess(run_dir, budget=budget, model=model, apply=apply)
    if not out.get("ok"):
        # exit 2 from the seam = the run is not a REFUTED/INVALIDATED catch (nothing to repair) - a
        # legitimate, clean outcome, NOT a missing-deps failure. Report the two honestly distinct.
        if out.get("returncode") == 2:
            # the seam already prefixes "nothing to repair: ..." / "not a run dir: ..." - print verbatim.
            print(out.get("error"))
            print("  repair acts on a REFUTED/INVALIDATED catch - point it at that run's .calma/<run-id>.")
            return 2
        print("repair unavailable (%s) - it needs the edges deps + an API key (ANTHROPIC_API_KEY); the "
              "re-verify gate itself is offline." % out.get("error"))
        return 2
    if as_json:
        print(json.dumps({k: out[k] for k in ("accepted", "one_shot", "before_verdict", "after_verdict",
              "metric_id", "patch", "hypotheses", "applied") if k in out}, indent=2))
        return 0 if out.get("accepted") else 1
    if out.get("accepted"):
        print("repaired %s -> %s%s  (AI proposed the patch; Calma re-verified the patched code)"
              % (out.get("before_verdict"), out.get("after_verdict"),
                 " [one-shot]" if out.get("one_shot") else ""))
        for h in out.get("hypotheses", []):
            if h.get("accepted"):
                print("  cause: %s" % h.get("cause"))
                print("  files: %s" % (", ".join(h.get("target_files") or []) or "?"))
        print("\n%s" % (out.get("patch") or ""))
        if apply:
            print("applied to working tree: %s" % ("yes - re-run calma verify to confirm"
                  if out.get("applied") else "FAILED (apply the diff above manually)"))
        else:
            print("re-verified in an isolated clone - your files are untouched. apply it:  %s repair %s --apply"
                  % (_invocation(), run_dir))
        return 0
    print("no accepted patch within budget - the verdict stands. what was tried:")
    for h in out.get("hypotheses", []):
        print("  #%d %-58s -> %s (gap_closed=%s, reviewers=%s)"
              % (h.get("index"), (h.get("cause") or "")[:58], h.get("after_verdict"),
                 h.get("gap_closed"), h.get("reviewers_passed")))
    print("a patch Calma can't re-verify to a clean verdict is never applied - the catch stands honestly.")
    return 1


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
        if not os.path.isfile(manifest):  # a FIFO/device manifest would block the read forever
            raise ValueError("--manifest %r is not a regular file" % manifest)
        for ln_no, line in enumerate(open(manifest), 1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = [p.strip() for p in line.split("\t")]
            if len(parts) > 3:
                # a claim with an embedded tab would silently shift the metric column - fail loud
                raise ValueError("manifest line %d has %d tab-separated fields (max 3: "
                                 "path<TAB>claim<TAB>metric); a claim cannot contain a tab"
                                 % (ln_no, len(parts)))
            if not parts[0]:
                raise ValueError("manifest line %d has an empty path" % ln_no)
            jobs.append((parts[0], parts[1] if len(parts) > 1 and parts[1] else None,
                         parts[2] if len(parts) > 2 and parts[2] else None))
    # dedupe identical (path, claim, metric) jobs - they would render as indistinguishable rows and (for a
    # repeated dir) overwrite each other's run dir on disk. ALSO: when a path is given BOTH as a bare
    # positional (no claim - a reproduction) AND in the manifest (with a claim), the MANIFEST row wins; the
    # bare reproduction is redundant and would silently double-count the dir in the roll-up.
    claimed = {os.path.realpath(j[0]) for j in jobs if j[1] is not None}
    seen, uniq = set(), []
    for j in jobs:
        rp = os.path.realpath(j[0])
        if j[1] is None and rp in claimed:
            continue  # a bare positional superseded by a manifest claim for the same path
        key = (rp, j[1], j[2])
        if key not in seen:
            seen.add(key)
            uniq.append(j)
    return uniq


def run_batch(targets, manifest=None, fail_on="not-clean", timeout=None, force=False):
    """Verify many targets; return a list of per-target result rows (for the summary + roll-up)."""
    rows = []
    for path, claim, met in _batch_jobs(targets, manifest):
        try:
            res = verify(path, claim=claim, metric=met, run_id="batch",
                         opts=VerifyOptions(force=force, timeout=timeout))
        except Exception as e:
            rows.append({"target": os.path.basename(os.path.normpath(path)), "verdict": "ERROR",
                         "metric": None, "claimed": None, "recomputed": None,
                         "clean": False, "error": str(e)[:140]})
            continue
        led = res["ledger"]
        c0 = (led.get("claims") or [{}])[0]
        clean = res["gate_exit"] == 0 if fail_on == "not-clean" \
            else res["repo_verdict"] not in V.CATCH_VERDICTS
        rows.append({"target": os.path.basename(os.path.normpath(path)),
                     "verdict": res["repo_verdict"], "metric": c0.get("metric"),
                     "claimed": c0.get("claimed_value"), "recomputed": c0.get("recomputed_value"),
                     "clean": clean, "run_dir": res["run_dir"]})
    return rows


def _render_batch(rows, color=False):
    """A single scannable summary table for N targets + a roll-up line."""
    n = len(rows)
    refuted = sum(1 for r in rows if r["verdict"] in V.CATCH_VERDICTS)
    confirmed = sum(1 for r in rows if r["verdict"] in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS"))
    inconcl = sum(1 for r in rows if r["verdict"] in ("INCONCLUSIVE", "ERROR"))
    # pre-format claimed/recomputed so column widths fit the ACTUAL strings (a value like
    # "147.0x (+14,698%)" is 17 chars and used to overflow a fixed %12s, shoving RECOMPUTED out
    # from under its header - the one thing a scannable table must never do)
    for r in rows:
        r["_c"] = REP.fmt_value(r["claimed"], r["metric"]) if r["claimed"] is not None else "-"
        r["_r"] = REP.fmt_value(r["recomputed"], r["metric"]) if r["recomputed"] is not None else "-"
    tw = max([len(str(r["target"])) for r in rows] + [6])
    mw = max([len(str(r["metric"] or "-")) for r in rows] + [6])
    cw = max([len(r["_c"]) for r in rows] + [len("CLAIMED")])
    rw = max([len(r["_r"]) for r in rows] + [len("RECOMPUTED")])
    head = "CALMA BATCH  -  %d target%s  -  %d REFUTED, %d confirmed, %d can't-confirm" \
        % (n, "" if n == 1 else "s", refuted, confirmed, inconcl)
    out = ["", head, "-" * max(len(head), 60),
           "  %-*s  %-*s  %*s  %*s  %s"
           % (tw, "TARGET", mw, "METRIC", cw, "CLAIMED", rw, "RECOMPUTED", "VERDICT")]
    for r in rows:
        sym = REP._SYMBOL.get(r["verdict"], "·")
        if color and r["verdict"] in REP._ANSI:
            sym = "\x1b[%sm%s\x1b[0m" % (REP._ANSI[r["verdict"]], sym)
        # M6b: a clean verdict with NO claimed number is a REPRODUCTION check, not a claim-confirm -
        # label it so the two don't read identically (mirrors the single-run report's scope=reproduction)
        word = REP.display(r["verdict"]) if r["verdict"] != "ERROR" else "ERROR"
        if (r["verdict"] in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS")
                and r.get("claimed") is None and r.get("recomputed") is not None):
            word += " (reproduction)"
        out.append("  %-*s  %-*s  %*s  %*s  %s %s"
                   % (tw, r["target"], mw, (r["metric"] or "-"), cw, r["_c"], rw, r["_r"],
                      sym, word))
    out.append("-" * max(len(head), 60))
    return "\n".join(out)


def _offline_enabled(cli_offline, base):
    """M4: whether auto-mode should skip the ONE network step (the RFC 3161 timestamp). --offline >
    env CALMA_OFFLINE > .calma/config.json {"autonomy":{"offline":true}} > default off."""
    if cli_offline:
        return True
    env = str(os.environ.get("CALMA_OFFLINE", "")).strip().lower()
    if env in ("1", "on", "true", "yes"):
        return True
    if env in ("0", "off", "false", "no"):
        return False
    cfg = AUT._config(base)
    au = cfg.get("autonomy") if isinstance(cfg.get("autonomy"), dict) else {}
    return bool(au.get("offline", False))


def _emit_otel_result(a, res):
    """Emit the finished verdict as an OTel GenAI evaluation result (the P2-M7a distribution wedge). Best-
    effort: an OTLP failure NEVER changes the verdict or the exit code (the engine already decided). Reads
    the endpoint from --emit-otel's value or $OTEL_EXPORTER_OTLP_ENDPOINT; --otel-dual selects native mirrors."""
    led = res.get("ledger")
    if not led:
        return
    endpoint = (a.emit_otel or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip() or None
    dual = [b for b in (getattr(a, "otel_dual", "") or "").split(",") if b.strip()]
    try:
        import otel_eval as OE
        out = OE.emit_verdict(led, endpoint=endpoint, dual_emit=dual, engine_version=__version__,
                              run_url=res.get("run_url"), dry_run=not endpoint)
    except Exception as e:                                   # noqa: BLE001 - the wedge must never break verify
        if not a.as_json:
            print("  otel: emit skipped (%s)" % e)
        return
    if a.as_json:
        return
    if out["emitted"]:
        print("  otel: emitted gen_ai.evaluation.result -> %s (status %s)" % (endpoint, out["status"][0]))
    else:
        print("  otel: built gen_ai.evaluation.result (dry-run) - set --emit-otel URL or "
              "$OTEL_EXPORTER_OTLP_ENDPOINT to POST it")


def _autonomy_followup(res, mode, base, quiet=False, offline=False):
    """The post-verdict ACTION for the active mode on a catch verdict. The verdict is already final
    and deterministic; this only governs what Calma DOES next. auto -> append to the LOCAL
    catch-record AND add an RFC 3161 timestamp to the already-signed bundle; suggest -> print the
    `seal` command; ask -> nothing. Fail-open. M4: --offline skips the timestamp (the only network
    step); the local catch-record still accrues."""
    run_dir = res.get("run_dir")
    if not run_dir or res.get("repo_verdict") not in V.CATCH_VERDICTS:
        return
    decision = AUT.gate(mode, "seal", outward=False, base=base)
    if decision == "skip":
        return
    disp = _redact_home(run_dir)
    if decision == "suggest":
        if not quiet:
            print("  suggest (mode=suggest): %s seal %s   # sign + timestamp + a counterparty proof"
                  % (_invocation(), disp))
        AUT.log(base, mode, "seal", "suggest")
        return
    # D1 credibility flywheel: append the REDACTED verdict to the operator's LOCAL catch-record FIRST,
    # so the local history accrues INDEPENDENT of the network timestamp below (M4). LOCAL-ONLY (a dir
    # on this machine) - NOT the gated outward push to a SHARED/public registry or Rekor, which still
    # needs the explicit `auto_publish` opt-in. Opt out: .calma/config.json
    # {"autonomy": {"local_catch_record": false}}.
    _auto_local_publish(res, mode, base, quiet=quiet)
    # execute (auto): verify already signed the bundle when a key exists; add the trusted timestamp.
    bpath = os.path.join(run_dir, attest.BUNDLE_NAME)
    if not os.path.exists(bpath):
        if not quiet:
            print("  auto: no signing key yet - run `%s attest keygen` once to enable signed proofs"
                  % _invocation())
        AUT.log(base, mode, "seal", "skip", "no-key")
        return
    if offline:
        # M4: the signed bundle + the local catch-record stand; skip the ONE network step (the TSA).
        if not quiet:
            print("  auto: signed the verdict (offline - RFC 3161 timestamp skipped) -> %s" % disp)
        AUT.log(base, mode, "seal", "execute", "offline-no-timestamp")
        return
    try:
        import rfc3161
        bundle = json.load(open(bpath))
        rfc3161.timestamp_bundle(bundle, rfc3161.DEFAULT_TSA)
        json.dump(bundle, open(bpath, "w"), indent=2)
        if not quiet:
            print("  auto: signed + RFC 3161 timestamped the verdict -> %s" % disp)
        AUT.log(base, mode, "seal", "execute", "timestamped")
    except (OSError, ValueError) as e:  # offline / TSA down: fail-open, the signed bundle still stands
        if not quiet:
            print("  auto: signed the verdict (timestamp skipped, %s) -> %s" % (type(e).__name__, disp))
        AUT.log(base, mode, "seal", "execute", "timestamp-failed")


def _local_catch_record_enabled(base):
    """Whether auto-mode appends catches to the local catch-record (default ON). Local-only; never the
    outward/shared publish (that stays behind auto_publish)."""
    cfg = AUT._config(base)
    au = cfg.get("autonomy") if isinstance(cfg.get("autonomy"), dict) else {}
    return au.get("local_catch_record", True) is not False


def _local_catch_record_dir():
    """The operator's local catch-record: $CALMA_REGISTRY_DIR, else ~/.calma/registry. Local to this
    machine - the seed of a public record the operator later chooses to deploy (calma registry site)."""
    return os.environ.get("CALMA_REGISTRY_DIR") or os.path.join(os.path.expanduser("~"), ".calma", "registry")


def _auto_local_publish(res, mode, base, quiet=False):
    """Append the run's REDACTED verdict to the LOCAL catch-record (auto mode, default on). Reuses the
    same hash-chained, SSHSIG-signed registry as `calma publish` - the redaction whitelist is identical,
    so nothing but claim/verdict/gap/hashes is ever written. Fail-open: a registry hiccup never breaks
    the verdict path."""
    if not _local_catch_record_enabled(base):
        return
    bpath = os.path.join(res.get("run_dir", ""), attest.BUNDLE_NAME)
    seed = attest.load_signing_key()
    if seed is None or not os.path.exists(bpath):
        return  # no key -> no signed entry (the local record stays signature-consistent)
    try:
        import registry as REG
        reg_dir = _local_catch_record_dir()
        os.makedirs(reg_dir, exist_ok=True)
        bundle = json.load(open(bpath))
        entry = REG.derive_entry(bundle, note="auto: local catch-record")
        fname, wrapper = REG.append_entry(reg_dir, entry, seed)
        if not quiet:
            print("  auto: appended to the local catch-record -> %s (deploy: calma registry site %s)"
                  % (_redact_home(os.path.join(reg_dir, "entries", fname)), _redact_home(reg_dir)))
        AUT.log(base, mode, "local_catch_record", "execute", wrapper["entry"].get("verdict"))
    except (OSError, ValueError, KeyError) as e:
        AUT.log(base, mode, "local_catch_record", "skip", type(e).__name__)


# ---- OPTIONAL Rekor transparency-log backing (publish/seal) -------------------

def _add_rekor_publish_args(p):
    """The shared --rekor* flags for `publish` and `seal --publish`. Backing is strictly opt-in;
    the default is NONE."""
    p.add_argument("--rekor", metavar="URL", default=None,
                   help="OPTIONAL: also log each entry to a Sigstore Rekor transparency log "
                        "(self-hostable, Apache-2.0) so third parties can verify the append-only "
                        "property OFFLINE with rekor-cli or `calma registry verify` "
                        "(default: none, or $CALMA_REKOR_URL). Fail-closed unless --rekor-optional")
    p.add_argument("--rekor-optional", action="store_true",
                   help="fail-open: if transparency logging fails, still write the entry WITHOUT a "
                        "proof rather than aborting (the safe default is fail-closed - a requested "
                        "log that fails means no entry is written)")
    p.add_argument("--rekor-log-key", metavar="PATH_OR_HEX", default=None,
                   help="pin the Rekor log's Ed25519 checkpoint key (hex or a file) to anchor the "
                        "inclusion proof's root in the post-publish self-check")
    p.add_argument("--rekor-v1", action="store_true",
                   help="target a pinned self-hosted Rekor v1 (default assumes v2, which supports "
                        "only the hashedrekord + dsse entry types)")


def _rekor_config(a):
    """The Rekor config dict from flags + env, or None when no endpoint is set (the opt-in default).
    Logging happens strictly AFTER the verdict and signing - see registry.append_entry."""
    url = getattr(a, "rekor", None) or os.environ.get("CALMA_REKOR_URL")
    if not url:
        return None
    return {"url": url,
            "version": "v1" if getattr(a, "rekor_v1", False) else "v2",
            "optional": bool(getattr(a, "rekor_optional", False))}


def _rekor_log_pub(a):
    """The pinned Rekor log public key (hex), from --rekor-log-key (a file path or a hex string)."""
    val = getattr(a, "rekor_log_key", None)
    if not val:
        return None
    return open(val).read().strip() if os.path.exists(val) else val.strip()


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
    ap.add_argument("--version", action="version", version="calma %s" % __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="re-run + recompute + diff against the claim")
    v.add_argument("target", nargs="?", default=None,
                   help="folder containing the code and its outputs")
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
                        "under the verified sandbox; third-party auto-escalates to the container "
                        "tier and REFUSES (exit 3) if no verified container/VM tier is live")
    v.add_argument("--isolation",
                   choices=["auto", "seatbelt", "bwrap", "docker", "firecracker", "e2b"],
                   default="auto",
                   help="isolation backend: auto (default - seatbelt for own-code, container for "
                        "third-party), seatbelt (host macOS sandbox), bwrap (Linux bubblewrap, "
                        "no daemon), docker (network-denied Linux container), e2b (remote Firecracker "
                        "microVM - E2B cloud OR self-hosted; runs --trust third-party with NO Docker, "
                        "network denied in-guest), or firecracker (local microVM, not built yet). "
                        "Explicit choices fail loud if the backend is unavailable - never a silent "
                        "host fallback")
    v.add_argument("--timeout", type=int, default=None, metavar="SECONDS",
                   help="re-execution wall-clock budget in seconds, clamped to [1, 86400] (default "
                        "120, or run.timeout in verify.yaml); on overrun the run is killed (exit 4)")
    v.add_argument("--force", action="store_true",
                   help="re-execute even if code, data, and claim are unchanged since the last verification")
    v.add_argument("--restore", action="store_true",
                   help="restore + PIN the repo's declared deps into <target>/.calma_venv before the "
                        "run (uses the network in this phase only; the run itself stays network-denied)")
    v.add_argument("--check-determinism", action="store_true",
                   help="re-execute TWICE and require identical artifacts (catches FLAKY results)")
    v.add_argument("--mode", choices=["ask", "suggest", "auto"], default=None,
                   help="autonomy: ask (default; verdict + report only), suggest (also print the next "
                        "command), or auto (also run safe follow-ons: seal/timestamp on a catch, and "
                        "retry a missing dependency under --restore). Verdicts are ALWAYS deterministic; "
                        "the mode governs only follow-on ACTIONS. Also CALMA_MODE / .calma/config.json")
    v.add_argument("--json", action="store_true", dest="as_json",
                   help="print a machine-readable verdict object instead of the report")
    v.add_argument("--why", action="store_true",
                   help="expand the full 'not verified' scope list (every undeclared validity family) "
                        "instead of the one-line summary. The saved report.txt + --json always carry "
                        "the full list either way")
    v.add_argument("--offline", action="store_true",
                   help="auto mode only: skip the ONE network step (the RFC 3161 timestamp) so a catch "
                        "is signed + appended to the LOCAL catch-record with zero network. Also "
                        "CALMA_OFFLINE / .calma/config.json {\"autonomy\":{\"offline\":true}}")
    v.add_argument("--run-only", action="store_true",
                   help="DEBUG/iterate: re-run + recompute + show the binding, recomputed value, and gap "
                        "vs the claim, with NO verdict and NO gate (always exits 0) - for an agent to see "
                        "what the code actually computes mid-task. Pair with --json for the structured view")
    v.add_argument("--cross-engine", action="store_true", dest="cross_engine",
                   help="CROSS-ENGINE correctness: recompute each metric through an INDEPENDENT second "
                        "kernel and diff (quantifies the implementation uncertainty single-engine results "
                        "leave unmeasured). Additive - reports agreement, never changes the verdict")
    v.add_argument("--emit-otel", nargs="?", const="", metavar="OTLP_ENDPOINT", dest="emit_otel",
                   help="emit the verdict as a standard OpenTelemetry GenAI evaluation result (the "
                        "distribution wedge): POST a gen_ai.evaluation.result span to OTLP_ENDPOINT or "
                        "$OTEL_EXPORTER_OTLP_ENDPOINT, so any agent-obs backend (Braintrust/LangSmith/"
                        "Langfuse/Phoenix) ingests Calma as a drop-in deterministic eval source. Self-emit "
                        "from your own CI is free; redaction-by-construction (no raw data leaves)")
    v.add_argument("--otel-dual", default="", metavar="BACKENDS", dest="otel_dual",
                   help="with --emit-otel: comma-separated backends to also emit native attrs for "
                        "(braintrust,langsmith) - for backends that don't yet read gen_ai.* natively")
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
    rpt = sub.add_parser("report", help="render a branded HTML report (prints to PDF) + a self-"
                                        "contained offline replay bundle")
    rpt.add_argument("run_dir", help="a .calma/<run-id> dir from a previous verify")
    rpt.add_argument("--out", help="HTML output path (default <run_dir>/report.html)")
    rpt.add_argument("--no-pdf", action="store_true",
                     help="skip the headless-browser PDF attempt (HTML still prints to PDF from a browser)")
    rpt.add_argument("--no-sign", action="store_true",
                     help="do not sign the run (the report's integrity hashes then come from files, "
                          "not a verifiable bundle)")
    s = sub.add_parser("stats", help="summarize this target's verification history")
    s.add_argument("target", help="folder whose .calma verification history to summarize")
    s.add_argument("--json", action="store_true", dest="as_json",
                   help="print the summary as machine-readable JSON")
    dm = sub.add_parser("demo", help="watch calma catch a real inflated backtest "
                                     "(bundled fixture; offline, a few seconds)")
    dm.add_argument("--keep", action="store_true",
                    help="keep the temp copy of the fixture (prints its path)")
    sg = sub.add_parser("suggest", help="unclear what to verify? rank the recipes a free-text "
                                        "ask most likely means (suggestion only - never verifies)")
    sg.add_argument("text", nargs="+", help="the ask, e.g. \"my risk-adjusted return looked strong\"")
    sg.add_argument("-k", "--top", type=int, default=5, help="how many candidates to show (default 5)")
    sg.add_argument("--json", action="store_true", dest="as_json",
                    help="print ranked candidates as JSON")
    rc = sub.add_parser("recipes", help="list every built-in metric recipe, grouped by family")
    rc.add_argument("--json", action="store_true", dest="as_json",
                    help="print {family: [metric ids]} as JSON")
    ini = sub.add_parser("init", help="scaffold a starter verify.yaml for an ML/quant framework "
                                      "(backtrader/vectorbt/zipline/pytorch/xgboost/sklearn)")
    ini.add_argument("framework", nargs="?", default=None,
                     help="backtrader | vectorbt | zipline | pytorch | xgboost | sklearn "
                          "(aliases: torch, xgb, scikit-learn). Omit with --list to see them all")
    ini.add_argument("target", nargs="?", default=".", help="dir to write verify.yaml into (default: .)")
    ini.add_argument("--list", action="store_true", dest="list_fw",
                     help="list the available frameworks + aliases and exit")
    ini.add_argument("--force", action="store_true",
                     help="overwrite an existing verify.yaml, or write the skeleton even when the "
                          "repo's artifacts don't match the template (init normally steers to draft)")
    dr = sub.add_parser("draft", help="generate a verify.yaml for a repo (point it at a messy repo); "
                                      "heuristic by default, --ai adds the LLM drafter + repair loop")
    dr.add_argument("target", help="the repo/dir to draft a verify.yaml for")
    dr.add_argument("--ai", action="store_true",
                    help="use the LLM drafter + counterexample repair loop (needs the edges deps + an "
                         "API key); falls back to the heuristic draft if unavailable")
    dr.add_argument("--budget", type=int, default=3, help="max model draft+repair rounds for --ai (default 3)")
    dr.add_argument("--model", default=None, help="advisory model tier for --ai")
    dr.add_argument("--force", action="store_true", help="overwrite an existing verify.yaml")
    dr.add_argument("--json", action="store_true", dest="as_json", help="print the drafted contract as JSON")
    ob = sub.add_parser("onboard", help="onboard a BESPOKE metric (no published oracle) from a "
                                        "methodology + reference vectors: an LLM proposes the recipe, the "
                                        "deterministic gate admits it (needs edges deps + an API key)")
    ob.add_argument("--metric-id", required=True, dest="metric_id", help="^[a-z][a-z0-9_]*$")
    ob.add_argument("--family", required=True,
                    help="quant|classification|regression|analytics|engineering|retrieval|llm-eval|"
                         "stats|finance|forecasting")
    ob.add_argument("--methodology", required=True, help="the metric definition (text, or @path-to-file)")
    ob.add_argument("--vectors", required=True,
                    help="reference vectors: a JSON file path or inline JSON "
                         "[{\"inputs\":{tag:[..]},\"expected\":<n>}, ...]")
    ob.add_argument("--metamorphic-hint", action="append", default=[], dest="hints",
                    help="a plain-language invariant the metric obeys (repeatable)")
    ob.add_argument("--budget", type=int, default=6, help="max CEGIS attempts (default 6)")
    ob.add_argument("--model", default=None, help="proposer model (use a cheap one)")
    ob.add_argument("--compiled-path", default=None, dest="compiled_path",
                    help="freeze target registry (default: the production compiled_recipes.json)")
    ob.add_argument("--json", action="store_true", dest="as_json", help="machine-readable result")
    rp = sub.add_parser("repair", help="REFUTED catch? An LLM proposes a minimal patch and Calma "
                                       "re-verifies the patched code from scratch - it accepts the fix "
                                       "ONLY if the recompute flips it to clean (needs edges deps + an API key)")
    rp.add_argument("run_dir", help="the .calma/<run-id> of a REFUTED/INVALIDATED verification "
                                    "(the path in the 'reproduce:' line)")
    rp.add_argument("--budget", type=int, default=4, help="max diagnosis hypotheses to try (default 4)")
    rp.add_argument("--model", default=None, help="advisory diagnosis model tier")
    rp.add_argument("--apply", action="store_true",
                    help="apply the accepted patch to the working tree (default: propose only, never mutate)")
    rp.add_argument("--json", action="store_true", dest="as_json", help="machine-readable repair result")
    mo = sub.add_parser("modes", help="show or set Calma's autonomy: the verify scope "
                        "(off/headline/all) + the action mode (ask/suggest/auto)")
    mo.add_argument("--verify", choices=AUT.VERIFY_SCOPES, default=None,
                    help="set the VERIFY SCOPE: how aggressively the zero-touch hook auto-verifies")
    mo.add_argument("--mode", choices=AUT.MODES, default=None,
                    help="set the ACTION MODE: what Calma does after a catch (seal/timestamp/restore)")
    mo.add_argument("--global", dest="glob", action="store_true",
                    help="write to ~/.calma/config.json (everywhere) instead of ./.calma/config.json")
    mo.add_argument("--dir", default=".", help="the project dir to read/write config for (default .)")
    mo.add_argument("--json", action="store_true", dest="as_json", help="print the active modes as JSON")
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
    av.add_argument("bundle", help="path to attestation.bundle.json (or the run/project dir containing it)")
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
    sl.add_argument("--evidence", nargs="?", const=True, default=None, metavar="DIR",
                    help="also export an ALLOCATOR evidence bundle (verified result + input lineage + "
                         "runtime digests + replay, mapped to GIPS-2026 / ODD) to DIR "
                         "(default: <run_dir>/evidence)")
    _add_rekor_publish_args(sl)
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
    _add_rekor_publish_args(pb)
    rg = sub.add_parser("registry", help="audit the catch-history registry chain offline")
    rgsub = rg.add_subparsers(dest="registry_cmd", required=True)
    rgv = rgsub.add_parser("verify", help="re-hash every entry, walk the chain, check every signature")
    rgv.add_argument("dir", nargs="?", default=None,
                     help="registry directory (default: $CALMA_REGISTRY_DIR, then ./registry)")
    rgv.add_argument("--key", help="pin the signer: hex public key, or a path to the .pub file")
    rgv.add_argument("--min-seq", type=int, default=None, metavar="N",
                     help="rollback anchor: fail unless the chain reached at least sequence N. Use a "
                          "floor you know out-of-band (a prior audit, or git history) to catch a "
                          "consistent tail-truncation that the files alone cannot reveal")
    rgv.add_argument("--rekor-log-key", metavar="PATH_OR_HEX", default=None,
                     help="pin the Rekor log's Ed25519 checkpoint key (hex or a file) to ANCHOR each "
                          "stored inclusion proof's root; without it proofs still re-verify offline "
                          "but the root is reported self-asserted")
    rgs = rgsub.add_parser("site", help="render the registry into a self-contained, deployable static "
                                        "site (index.html + the raw re-verifiable registry)")
    rgs.add_argument("dir", nargs="?", default=None,
                     help="registry directory (default: $CALMA_REGISTRY_DIR, then ./registry)")
    rgs.add_argument("--out", default=None, metavar="DIR",
                     help="output dir for the site (default: <registry>/site)")
    rgp = rgsub.add_parser("proof", help="emit a self-contained, offline-re-verifiable .proof bundle "
                                         "(RFC 6962 inclusion proof + a signed checkpoint) for one entry")
    rgp.add_argument("ref", help="the entry to prove: its seq number, or a content-address id / prefix")
    rgp.add_argument("dir", nargs="?", default=None,
                     help="registry directory (default: $CALMA_REGISTRY_DIR, then ./registry)")
    rgp.add_argument("--key", help="the signing key (hex seed or a path); default ~/.calma/keys")
    rgp.add_argument("--out", default=None, metavar="FILE", help="write the .proof bundle here (default: stdout)")
    rgpv = rgsub.add_parser("verify-proof", help="re-verify a .proof bundle OFFLINE (no calma server)")
    rgpv.add_argument("proof", help="path to the .proof bundle JSON")
    rgpv.add_argument("--log-key", metavar="PATH_OR_HEX", default=None,
                      help="pin the calma log's Ed25519 checkpoint key to ANCHOR the root (else self-asserted)")
    rgpv.add_argument("--witness", metavar="PATH_OR_HEX", action="append", default=None,
                      help="pin an external witness key (repeatable); >=1 cosignature -> the witnessed tier")
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
            if a.target is None:
                # bare `calma verify` is the most common first fumble: point at the zero-setup demo
                # and the suggester instead of a raw argparse "the following arguments are required".
                inv = _invocation()
                print("calma verify needs a folder to check. Try:\n"
                      "  %s demo                          watch it catch a real inflated backtest "
                      "(offline, no setup)\n"
                      "  %s verify <folder> \"<claim>\"      e.g. %s verify ./out \"accuracy 0.87\"\n"
                      "  %s suggest \"<what you measured>\"   unsure which metric? get ranked candidates"
                      % (inv, inv, inv, inv), file=sys.stderr)
                return 2
            # H2: ONE options object for every dispatch below - run-only, normal, and the auto retry
            # all run through the same VerifyOptions, so no path can silently drop a flag (the bug
            # that left --run-only without cross_engine / check_determinism).
            opts = VerifyOptions.from_args(a)
            if opts.run_only:
                # DEBUG path: re-run + recompute + gap, NO verdict / NO gate. Always exit 0.
                res = verify(a.target, a.claim_text or a.claim, a.metric, a.run_id, opts=opts)
                if not res.get("run_only"):
                    # the run could not complete (refused / killed / no entrypoint / no metric): nothing
                    # to recompute, so surface the engine's reason - still exit 0 (debug, never a gate).
                    print(json.dumps(_json_finite(_json_result(res)), indent=2) if a.as_json
                          else (res.get("display") or res.get("report") or "run-only: nothing to recompute"))
                    return 0
                if a.as_json:
                    print(json.dumps(_json_finite(res), indent=2))
                else:
                    print("run-only (no verdict) - %s  [isolation %s · determinism %s]"
                          % (res.get("target"), res.get("isolation_tier"), res.get("determinism_mode")))
                    for m in res.get("metrics", []):
                        cl, rcv = m.get("claimed"), m.get("recomputed")
                        extra = (("  (claimed %s, gap %s)"
                                  % (REP.fmt_value(cl, m.get("metric")), REP.fmt_value(m.get("gap"), m.get("metric"))))
                                 if cl is not None else "")
                        print("  %-16s recomputed %s%s" % (m.get("metric"), REP.fmt_value(rcv, m.get("metric")), extra))
                    if not res.get("metrics"):
                        print("  nothing to recompute: %s" % (res.get("note")
                              or "the run produced no output for the requested metric "
                                 "(check the metric / binding)"))
                    _ce = res.get("cross_engine")  # COR-5: surface cross-engine in run-only too
                    if _ce and _ce.get("n_checked"):
                        print("  " + REP._cross_engine_line(_ce))
                    print("  proof + raw outputs: %s" % res.get("run_dir"))
                return 0
            res = verify(a.target, a.claim_text or a.claim, a.metric, a.run_id, opts=opts)
            _base = os.path.realpath(a.target)
            mode = AUT.resolve_mode(a.mode, _base)
            # autonomy (auto): transparently retry a missing-dependency failure under --restore
            if mode == "auto" and not a.restore \
                    and "re-run with --restore" in (res.get("report") or res.get("display") or ""):
                AUT.log(_base, mode, "restore-retry", "execute")
                if not a.as_json:
                    print("  auto: a dependency was missing - retrying once with --restore ...")
                res = verify(a.target, a.claim_text or a.claim, a.metric, a.run_id,
                             opts=replace(opts, force=True, restore=True))
            # OTel-eval distribution wedge (P2-M7a): on request, emit the verdict as a standard
            # gen_ai.evaluation.result span so any agent-obs backend ingests Calma as a deterministic eval
            # source. Best-effort + firewalled (consumes the finished verdict; never changes it / the exit).
            if getattr(a, "emit_otel", None) is not None:
                _emit_otel_result(a, res)
            if a.fail_on == "refuted":
                exit_code = 1 if res["repo_verdict"] in V.CATCH_VERDICTS else 0
            else:
                exit_code = res["gate_exit"]
            # refusal/kill outcomes get their own exit codes (documented in the README table):
            # 3 = execution refused (trust posture), 4 = killed (timeout) - regardless of policy
            if res.get("refused"):
                exit_code = 3
            elif res.get("killed"):
                exit_code = 4
            if a.as_json:
                print(json.dumps(_json_finite(_json_result(res)), indent=2))
            else:
                # M3: the cross-engine line is now rendered INSIDE the report, right under the verdict
                # (see report._cross_engine_line) - no longer appended here below the not-verified dump.
                print(res.get("display") or res["report"])
                # (the cross-engine line + the host-availability hint now render INSIDE the report,
                # under the verdict - see report._cross_engine_line; no orphan line down here)
                # the trust footnote prints AFTER the verdict (dimmed on a tty), never above it
                note = res.get("first_run_notice")
                if note:
                    # one-time dim footnote; left on a single line on purpose - it carries a copy-able
                    # "--trust third-party" flag that hard-wrapping would split (and it's short)
                    print(("\x1b[2m%s\x1b[0m" if _color_enabled() else "%s") % ("  " + note))
                # human vocabulary on the exit line: INCONCLUSIVE displays as CAN'T-CONFIRM.
                rv = res["repo_verdict"]
                label = REP.display(rv)
                if rv in ("REFUTED", "MIXED"):
                    # a REFUTED is the catch working, not a misconfiguration - say so on the exit line
                    tail = " - claim refuted (the catch; --fail-on sets exit behavior)"
                elif rv == "INVALIDATED":
                    # the catch working in a different shape: the number reproduces, but it isn't valid
                    tail = " - result invalidated (reproduces, but not a valid result; --fail-on sets exit)"
                elif rv == "FLAG_FOR_DECLARATION":
                    # the catch working as a demand: undeclared structure could invalidate the headline -
                    # resolvable by declaring the named block (then the authoritative family runs)
                    tail = " - flagged for declaration (reproduces, but undeclared structure could invalidate it; declare the block; --fail-on sets exit)"
                elif exit_code == 0:
                    tail = ""
                else:
                    if label.startswith("CONFIRMED") and res.get("gate_exit") != 0:
                        label += ", with caveat findings"
                    tail = " - see --fail-on for the exit policy"
                print("\n[exit %d (%s)%s]" % (exit_code, label, tail))
            _autonomy_followup(res, mode, _base, quiet=a.as_json,
                               offline=_offline_enabled(a.offline, _base))
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
                print(json.dumps(_json_finite(rows), indent=2, default=str))
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
            print(res.get("display") or res["report"])
            if a.keep:
                print("\n[fixture copy kept at %s]" % dst)
            print("\nthat was a real inflated backtest. now try your own:  "
                  "%s verify <folder> \"<claim>\"" % _invocation())
            return 0 if res["repo_verdict"] == "REFUTED" else 1
        if a.cmd == "suggest":
            text = " ".join(a.text)
            results = SUGG.suggest(text, k=a.top)
            if a.as_json:
                print(json.dumps({"query": text, "candidates": results}, indent=2))
                return 0 if results else 1
            print(SUGG.render(text, results, invocation=_invocation()))
            # interactive numbered pick when a human is at the terminal - print the exact command
            # to run for the chosen recipe (never auto-runs; non-TTY/agent use just sees the list)
            if results and sys.stdin.isatty():
                try:
                    raw = input("\nPick a number to get its exact command (Enter to skip): ").strip()
                except (EOFError, KeyboardInterrupt):
                    raw = ""
                if raw.isdigit() and 1 <= int(raw) <= len(results):
                    mid = results[int(raw) - 1]["metric_id"]
                    print("\n  %s verify <folder> \"<your claim>\" --metric %s"
                          % (_invocation(), mid))
            return 0 if results else 1
        if a.cmd == "recipes":
            fams = {}
            for mid in RCP.ids():
                fams.setdefault(RCP.get(mid).manifest.get("family") or "other", []).append(mid)
            if a.as_json:
                print(json.dumps(fams, indent=2, sort_keys=True))
                return 0
            import shutil
            import textwrap
            # wrap to the terminal width (bounded), not a hardcoded 88 that overflows a narrow term.
            # get_terminal_size honors $COLUMNS, then the tty, then falls back to 88 when piped.
            wrap_w = max(40, min(shutil.get_terminal_size((88, 24)).columns, 100) - 4)
            print("CALMA RECIPES - %d metrics. Pin one with: "
                  "calma verify <folder> \"<claim>\" --metric <id>" % len(RCP.ids()))
            for fam in sorted(fams):
                print("\n  %s (%d)" % (fam, len(fams[fam])))
                for ln in textwrap.wrap(", ".join(fams[fam]), width=wrap_w):
                    print("    " + ln)
            return 0
        if a.cmd == "init":
            return init_cmd(a.framework, a.target, force=a.force, list_fw=a.list_fw)
        if a.cmd == "draft":
            return draft_cmd(a.target, ai=a.ai, budget=a.budget, model=a.model,
                             force=a.force, as_json=a.as_json)
        if a.cmd == "onboard":
            return onboard_cmd(a.metric_id, a.family, a.methodology, a.vectors, hints=a.hints,
                               budget=a.budget, model=a.model, compiled_path=a.compiled_path,
                               as_json=a.as_json)
        if a.cmd == "repair":
            return repair_cmd(a.run_dir, budget=a.budget, model=a.model, apply=a.apply,
                              as_json=a.as_json)
        if a.cmd == "teardown":
            res = verify(a.target, a.claim_text or a.claim, a.metric, "teardown",
                         opts=VerifyOptions(force=a.force))
            print(res.get("teardown") or "(no teardown: the result is clean or inconclusive, not broken)")
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
        if a.cmd == "report":
            res = report(a.run_dir, out=a.out, pdf=not a.no_pdf, sign=not a.no_sign)
            print("report   %s" % res["html"])
            if res["pdf"]:
                print("pdf      %s" % res["pdf"])
            elif not a.no_pdf:
                print("pdf      open report.html in a browser -> Print -> Save as PDF "
                      "(no headless renderer found on this host)")
            print("replay   %s/" % res["replay_dir"])
            print("         one command, fully offline: sh %s/replay.sh" % res["replay_dir"])
            print("signed   %s" % ("DSSE + SSHSIG (integrity hashes embedded in the report)"
                                   if res["signed"] else
                                   "no signing key - run `calma attest keygen` for a signed bundle"))
            return 0
        if a.cmd == "stats":
            data, rendered = stats(a.target)
            print(json.dumps(data, indent=2) if a.as_json else rendered)
            return 0
        if a.cmd == "modes":
            base = os.path.realpath(a.dir or ".")
            cfg_path = (os.path.join(os.path.expanduser("~"), ".calma", "config.json") if a.glob
                        else os.path.join(base, ".calma", "config.json"))
            if a.verify is not None or a.mode is not None:   # SET: merge into config.json (preserve other keys)
                try:
                    cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
                    cfg = cfg if isinstance(cfg, dict) else {}
                except (OSError, ValueError):
                    cfg = {}
                if a.verify is not None:
                    cfg["verify"] = a.verify
                if a.mode is not None:
                    cfg["mode"] = a.mode
                os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
                json.dump(cfg, open(cfg_path, "w"), indent=2)
            scope = AUT.resolve_verify_scope(base=base)   # SHOW the EFFECTIVE state (env/config/default)
            mode = AUT.resolve_mode(None, base)
            if a.as_json:
                print(json.dumps({"verify": scope, "mode": mode, "config_path": cfg_path,
                                  "verify_choices": list(AUT.VERIFY_SCOPES),
                                  "mode_choices": list(AUT.MODES)}, indent=2))
                return 0
            print("Calma autonomy - a mode changes what Calma DOES, never what it DECIDES.\n")
            print("  VERIFY SCOPE   %-9s  how aggressively the zero-touch hook auto-verifies your numbers"
                  % scope)
            print("                 off = never   |   headline = the one headline claim (default)   |   "
                  "all = every checkable claim this turn")
            print("  ACTION MODE    %-9s  what Calma does AFTER a catch (the verdict is unaffected)"
                  % mode)
            print("                 ask = report only   |   suggest = print the next command   |   "
                  "auto = seal + timestamp, restore-retry")
            print("\n  choose (this project):  calma modes --verify all --mode auto")
            print("  choose (everywhere):    calma modes --verify all --global")
            print("  per-run override:       CALMA_VERIFY=all CALMA_MODE=auto calma ...")
            print("  config file:            %s" % cfg_path)
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
                bpath = a.bundle
                if os.path.isdir(bpath):
                    # convenience: accept a run dir (or a project dir) and find the bundle inside,
                    # so a counterparty can `calma attest verify <folder>` like every other command.
                    cands = [os.path.join(bpath, attest.BUNDLE_NAME),
                             os.path.join(bpath, ".calma", "run", attest.BUNDLE_NAME)]
                    found = next((c for c in cands if os.path.isfile(c)), None)
                    if found is None:
                        d = bpath.rstrip(os.sep)
                        print("error: no %s found in %s (looked in %s/ and %s/.calma/run/)"
                              % (attest.BUNDLE_NAME, bpath, d, d), file=sys.stderr)
                        return 2
                    bpath = found
                try:
                    bundle = json.load(open(bpath))
                except (OSError, ValueError) as e:
                    print("error: cannot read bundle: %s" % e, file=sys.stderr)
                    return 2
                pinned = None
                if a.key:
                    pinned = open(a.key).read().strip() if os.path.exists(a.key) else a.key.strip()
                ok, checks = attest.verify_bundle(bundle, pinned_pub_hex=pinned)
                print(attest.render_verify(bundle, ok, checks))
                if ok and a.replay:
                    rok, text = replay(os.path.dirname(os.path.realpath(bpath)))
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
                # Rekor (when configured) logs strictly AFTER the bundle above is signed + verified
                fname, wrapper = REG.append_entry(a.publish, entry, seed, rekor=_rekor_config(a))
                print("published   %s/entries/%s (%s)"
                      % (a.publish, fname, wrapper["entry"].get("verdict")))
                if wrapper.get("rekor"):
                    rk = wrapper["rekor"]
                    print("rekor       logged to %s (index %s, tree size %s) - inclusion proof "
                          "stored for OFFLINE verification" % (rk.get("log_url"),
                          rk.get("log_index"), rk.get("tree_size")))
                elif wrapper.get("rekor_error"):
                    print("rekor       NOT logged (%s); written anyway (--rekor-optional)"
                          % wrapper["rekor_error"])
                print("            to make it PUBLIC: commit registry/ with a signed commit "
                      "and push - the site rebuilds itself")
            if a.evidence is not None:
                import evidence_bundle as EV
                ev_out = None if a.evidence is True else a.evidence
                try:
                    out = EV.build_evidence(run_dir, ev_out)
                    print("evidence    %s/EVIDENCE.md  (+ evidence.json + carried proof)" % out)
                    print("            allocator/ODD pack: verified result + input lineage + runtime "
                          "digests + replay, mapped to GIPS-2026 / ODD")
                    # L3: it is NOT a redacted public registry entry - say so at the point of creation
                    print("            note: carries input lineage + target name (private handoff, "
                          "NOT registry-grade redaction - share under NDA)")
                except (OSError, ValueError) as e:
                    print("evidence    SKIPPED (%s)" % e)
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
                if entry.get("verdict") not in V.CATCH_VERDICTS:
                    print("note: this entry records a %s outcome, not a catch - the registry "
                          "documents both" % entry.get("verdict"))
            # Rekor (when configured via --rekor / $CALMA_REKOR_URL) logs strictly AFTER the bundle
            # above is verified and the entry is chained+signed - fail-closed unless --rekor-optional
            fname, wrapper = REG.append_entry(reg_dir, entry, seed, rekor=_rekor_config(a))
            e = wrapper["entry"]
            print("published: %s/entries/%s" % (reg_dir, fname))
            print("  kind     %s" % e["kind"])
            if e.get("claim"):
                print("  claim    %s" % e["claim"])
            if e.get("recomputed") is not None:
                print("  recomputed %s" % REP.fmt_value(e["recomputed"], e.get("metric")))
            print("  verdict  %s\n  id       %s" % (e.get("verdict"), wrapper["id"]))
            if wrapper.get("rekor"):
                rk = wrapper["rekor"]
                ok_rk, tier, det = REG.RK.verify_inclusion_offline(
                    rk, expected_digest=wrapper["id"], log_pub_hex=_rekor_log_pub(a))
                print("  rekor    logged to %s (index %s, tree size %s); offline proof %s [%s]"
                      % (rk.get("log_url"), rk.get("log_index"), rk.get("tree_size"),
                         "VERIFIES" if ok_rk else "FAILED", tier))
            elif wrapper.get("rekor_error"):
                print("  rekor    NOT logged (%s); entry written anyway (--rekor-optional)"
                      % wrapper["rekor_error"])
            print("the entry is redacted (no code, no data), chained to the previous entry, and "
                  "signed; commit it with a signed commit to complete the public record")
            return 0
        if a.cmd == "registry" and a.registry_cmd == "verify":
            import registry as REG
            reg_dir = a.dir or os.environ.get("CALMA_REGISTRY_DIR") or "registry"
            if not os.path.isdir(reg_dir):
                # a typo'd path must not read as a green "VERIFIED - 0 entries" (mirrors publish)
                print("error: no registry directory at %r - pass a path or set CALMA_REGISTRY_DIR"
                      % reg_dir, file=sys.stderr)
                return 2
            pinned = None
            if a.key:
                pinned = open(a.key).read().strip() if os.path.exists(a.key) else a.key.strip()
            ok, checks, summary = REG.verify_chain(reg_dir, pinned_pub_hex=pinned, min_seq=a.min_seq,
                                                   rekor_log_pub_hex=_rekor_log_pub(a))
            print(REG.render_verify(ok, checks, summary))
            return 0 if ok else 1
        if a.cmd == "registry" and a.registry_cmd == "site":
            import registry_site as RS
            reg_dir = a.dir or os.environ.get("CALMA_REGISTRY_DIR") or "registry"
            if not os.path.isdir(reg_dir):
                print("error: no registry directory at %r - pass a path or set CALMA_REGISTRY_DIR"
                      % reg_dir, file=sys.stderr)
                return 2
            out = RS.build_site(reg_dir, a.out)
            print("site        %s/index.html" % out)
            print("            raw re-verifiable registry copied to %s/registry/" % out)
            print("            deploy: any static host (GitHub Pages / S3 / Netlify), or open index.html")
            print("            rebuild after publishing new catches: calma registry site %s --out %s"
                  % (reg_dir, out))
            return 0
        if a.cmd == "registry" and a.registry_cmd == "proof":
            import merkle as MK
            reg_dir = a.dir or os.environ.get("CALMA_REGISTRY_DIR") or "registry"
            if not os.path.isdir(reg_dir):
                print("error: no registry directory at %r - pass a path or set CALMA_REGISTRY_DIR"
                      % reg_dir, file=sys.stderr)
                return 2
            seed = attest.load_signing_key(a.key)  # signs the checkpoint (the tree head)
            if not isinstance(seed, (bytes, bytearray)) or len(seed) != 32:
                raise ValueError("no usable 32-byte signing key - run `calma attest keygen`, or pass a "
                                 "valid --key (a hex seed or an OpenSSH ed25519 private key)")
            bundle = MK.build_proof_bundle(reg_dir, a.ref, seed)
            text = json.dumps(bundle, indent=2)
            if a.out:
                with open(a.out, "w") as fh:
                    fh.write(text)
                print("proof       %s  (entry index=%s of a %d-leaf log)" % (a.out, bundle["index"], bundle["size"]))
                print("            re-verify OFFLINE: %s registry verify-proof %s --log-key <calma.pub>"
                      % (_invocation(), a.out))
            else:
                print(text)
            return 0
        if a.cmd == "registry" and a.registry_cmd == "verify-proof":
            import merkle as MK

            def _key(v):
                return open(v).read().strip() if v and os.path.exists(v) else (v.strip() if v else None)
            bundle = json.load(open(a.proof))
            ok, tier, detail = MK.verify_proof_bundle(
                bundle, log_pub_hex=_key(a.log_key),
                witness_pub_hexes=[_key(w) for w in (a.witness or [])] or None)
            print("%s proof %s  (tier: %s)" % ("✓" if ok else "✗",
                                               "VERIFIES OFFLINE" if ok else "FAILED", tier))
            print("  %s" % detail)
            if isinstance(bundle.get("entry"), dict):
                e = bundle["entry"]
                print("  entry: seq %s · %s %s" % (e.get("seq"), e.get("verdict"), e.get("claim") or ""))
            return 0 if ok else 1
    except (ValueError, OSError) as e:
        # ValueError = bad input/contract; OSError = a file path that can't be read/written
        # (--out to a missing dir, --key pointing at a directory, a missing bundle). Both are
        # user-actionable input errors - print the message, never a raw traceback. In --json mode
        # ALSO emit a {"error": ...} object on STDOUT so an agent that parses stdout (the documented
        # --json contract) gets valid JSON instead of a JSONDecodeError on an empty stream.
        print("error: %s" % e, file=sys.stderr)
        # Full traceback to STDERR (never to the --json stdout contract). A bare message like a
        # UnicodeDecodeError ("can't decode byte 0xa3 ...") hides WHERE it came from; the host captures
        # this stream (runs.stderr_tail) so a control-plane failure is diagnosable without a live repro.
        import traceback as _tb
        _tb.print_exc()
        if getattr(a, "as_json", False):
            print(json.dumps({"ok": False, "error": str(e)}))
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
