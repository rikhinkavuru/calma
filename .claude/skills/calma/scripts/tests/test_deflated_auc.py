"""Deflated-AUC selection-overfit (the Sharpe DSR transplanted onto ROC-AUC). The kernels reuse the
existing Gumbel E[max] + DeLong SE; the overfitting rail fires when a reported AUC does not clear the
best-of-N no-skill bar (1 - DAUC > 0.05) and stays silent when it does. N is never guessed; AUC=1.0
(DeLong SE -> 0) is guarded as degenerate. Pure stdlib. Run: python3 test_deflated_auc.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import numeric as N  # noqa: E402
import overfitting_checks as OC  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# ---- kernels: expected_max_auc + deflated_auc --------------------------------------------------------
truth(N.expected_max_auc(2, 0.05) > 0.5, "expected_max_auc: best-of-2 no-skill bar > 0.5")
truth(N.expected_max_auc(100, 0.05) > N.expected_max_auc(10, 0.05) > N.expected_max_auc(2, 0.05),
      "expected_max_auc: the bar rises monotonically with the trial count N")
truth(N.expected_max_auc(50, 0.0) != N.expected_max_auc(50, 0.0), "expected_max_auc: se<=0 -> NaN (degenerate)")
# DAUC: an AUC far above the bar -> ~1; an AUC at the bar -> ~0.5; below -> <0.5
bar = N.expected_max_auc(50, 0.03)
truth(N.deflated_auc(bar + 0.20, 0.03, 50) > 0.99, "deflated_auc: AUC well above the bar -> DAUC ~ 1 (skill)")
truth(abs(N.deflated_auc(bar, 0.03, 50) - 0.5) < 1e-9, "deflated_auc: AUC exactly at the bar -> DAUC = 0.5")
truth(N.deflated_auc(bar - 0.05, 0.03, 50) < 0.5, "deflated_auc: AUC below the bar -> DAUC < 0.5 (overfit)")
truth(N.deflated_auc(1.0, 0.0, 50) != N.deflated_auc(1.0, 0.0, 50), "deflated_auc: se=0 (AUC=1.0) -> NaN guard")
truth(N.deflated_auc(0.8, 0.05, 1) != N.deflated_auc(0.8, 0.05, 1), "deflated_auc: N<2 -> NaN (no search)")


# ---- the overfitting rail, AUC cross-trial path (explicit AUC-values artifact) -----------------------
_DIR = tempfile.mkdtemp(prefix="calma_dauc_")


def _write_aucs(name, best):
    """39 noise AUCs around 0.50 (deterministic spread) + one SELECTED best."""
    vals = [0.50 + 0.02 * ((i % 5) - 2) for i in range(39)] + [best]
    with open(os.path.join(_DIR, name), "w", newline="") as f:
        f.write("auc\n")
        for v in vals:
            f.write("%.6f\n" % v)
    return vals


def _auc_contract(trials_artifact):
    # headline binds {score,label} that AREN'T present in the AUC-values file -> sl=None -> the vec path
    # supplies auc_val = max(vec). trials_artifact is the explicit per-trial AUC vector.
    return {"trials_artifact": trials_artifact,
            "metrics": [{"metric_id": "auc", "artifact": trials_artifact,
                         "binding": {"score": "score", "label": "label"}, "convention": "roc-auc",
                         "claimed_value": 0.58, "headline": True}]}


leaky_vals = _write_aucs("aucs_leaky.csv", 0.58)
gen_vals = _write_aucs("aucs_genuine.csv", 0.80)
# self-consistent expectation: the rail must fire iff the kernel says 1 - DAUC > 0.05
se_l = N.fstd(leaky_vals, ddof=1)
dauc_l = N.deflated_auc(max(leaky_vals), se_l, len(leaky_vals))
se_g = N.fstd(gen_vals, ddof=1)
dauc_g = N.deflated_auc(max(gen_vals), se_g, len(gen_vals))
truth((1.0 - dauc_l) > 0.05, "fixture: the best-of-40 AUC=0.58 is genuinely within selection reach (leaky)")
truth((1.0 - dauc_g) <= 0.05, "fixture: the best-of-40 AUC=0.80 genuinely clears the bar")

fl = OC.run_checks(_auc_contract("aucs_leaky.csv"), _DIR, "c1", "best AUC of the grid search")
truth(any(f["overfit_kind"] == "auc-selection" and f["validity_class"] == "authoritative" for f in fl),
      "rail: a leaky best-of-40 AUC under a search FIRES auc-selection (authoritative)")
truth(any("DAUC=" in f["locator"] and "selection bar" in f["locator"] for f in fl),
      "rail: the finding reports DAUC + the best-of-N bar")
fg = OC.run_checks(_auc_contract("aucs_genuine.csv"), _DIR, "c1", "best AUC of the grid search")
truth(fg == [], "rail: a genuine best-of-40 AUC clears the bar -> SILENT")

# ---- scope-guarded promotion -------------------------------------------------------------------------
def _confirmed_claim():
    vi = {"gap": 0.0, "effective_budget": 1e-9, "binding_status": "independently-bound",
          "determinism_mode": "controlled-to-bit", "container_present": True, "band_coverage_ok": True,
          "sufficient_k": True, "exit_codes": [0], "claim_confirmed_target": True}
    return {"id": "c1", "headline": True, "metric": "auc", "claimed_value": 0.58, "recomputed_value": 0.58,
            "verdict": V.verdict(vi), "input_binding_status": "independently-bound", "headline_confidence": 0.9,
            "verdict_inputs": vi, "verdict_status": "stable", "waivable": False, "reason": "ok"}


def _promote(contract, claim_text):
    claims = [_confirmed_claim()]
    findings = OC.run_checks(contract, _DIR, "c1", claim_text)
    OC.apply_validity(claims, findings, contract, claim_text)
    return claims[0], findings


hc, _ = _promote(_auc_contract("aucs_leaky.csv"), "the best AUC of the grid search generalizes out-of-sample")
truth(hc["verdict"] == V.INVALIDATED and hc.get("driving_dimension") == "overfitting",
      "promote: leaky AUC + a generalizes/OOS claim -> INVALIDATED('overfitting')")
bc, _ = _promote(_auc_contract("aucs_leaky.csv"), "AUC 0.58")
truth(bc["verdict"] == V.CAVEATS, "scope-guard: a bare AUC (no selection/OOS scope) -> CAVEATS")

# ---- uncountable: selection language but no countable N ----------------------------------------------
unc = OC.run_checks({"metrics": [{"metric_id": "auc", "artifact": "p.csv",
                                  "binding": {"score": "s", "label": "y"}, "claimed_value": 0.7,
                                  "headline": True}]}, _DIR, "c1", "the optimized model's AUC")
truth(any(f["overfit_kind"] == "uncountable-auc" for f in unc),
      "uncountable: AUC selection language with no trials:N -> 'declare trials:N' finding")

# ---- DeLong + declared-N path is self-consistent with the kernel -------------------------------------
with open(os.path.join(_DIR, "preds.csv"), "w", newline="") as f:
    f.write("score,label\n")
    rows = [(0.30, 0), (0.40, 0), (0.45, 0), (0.50, 0), (0.55, 0), (0.42, 0),
            (0.52, 1), (0.58, 1), (0.62, 1), (0.66, 1), (0.70, 1), (0.75, 1)]
    for s, y in rows:
        f.write("%.2f,%d\n" % (s, y))
scores = [r[0] for r in rows]
labels = [r[1] for r in rows]
auc_v, se_v = N.auc(scores, labels), N.auc_delong_se(scores, labels)
dauc_v = N.deflated_auc(auc_v, se_v, 500)
delong_contract = {"trials": 500,
                   "metrics": [{"metric_id": "auc", "artifact": "preds.csv",
                                "binding": {"score": "score", "label": "label"}, "convention": "roc-auc",
                                "claimed_value": auc_v, "headline": True}]}
fd = OC.run_checks(delong_contract, _DIR, "c1", "best of 500 configs")
fired = any(f["overfit_kind"] == "auc-selection" for f in fd)
truth(fired == ((1.0 - dauc_v) > 0.05),
      "DeLong path: the rail fire-decision matches the kernel (1 - deflated_auc(auc, delong_se, 500) > 0.05)")

print("deflated_auc: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
