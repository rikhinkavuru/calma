"""V4 model-process leakage: featurization fit on train+test, and validation-reuse / selection-on-test.
Each must FIRE on the planted leak and stay SILENT on a clean pipeline; the INVALIDATED promotion is
scope-guarded on a "no leakage / held-out" claim. Pure stdlib. Run: python3 test_model_leakage_checks.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import ledger as LED  # noqa: E402
import model_leakage_checks as MLC  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def _contract(**extra):
    c = {"metrics": [{"metric_id": "accuracy", "artifact": "preds.csv",
                      "binding": {"pred": "p", "label": "y"}, "claimed_value": 0.94, "headline": True,
                      "binding_status": "independently-bound"}]}
    c.update(extra)
    return c


# --- featurization: a transform fit on train+test -> fires ---
f = MLC.check_featurization(_contract(pipeline={"fit_on": "train+test", "transform": "StandardScaler"}), ".")
truth(f and f["dimension"] == "model-leakage" and "featurization leakage" in f["locator"],
      "featurization: a scaler fit on train+test fires a model-leakage finding")
# with a leaked-vs-train-only gap -> the gap quantifies the leak
fg = MLC.check_featurization(_contract(pipeline={"fit_on": "all", "transform": "target encoder",
                                                 "leaked_metric": 0.94, "train_only_metric": 0.78}), ".")
truth(fg and "0.78" in fg["locator"] and "leakage" in fg["locator"], "featurization: the train-only re-run gap is in the reason")
# a clean pipeline (fit on train only) -> SILENT
truth(MLC.check_featurization(_contract(pipeline={"fit_on": "train", "transform": "scaler"}), ".") is None,
      "featurization: a transform fit on train only is SILENT (no false alarm)")
# leaked metric not actually higher than train-only -> the leak isn't load-bearing -> SILENT
truth(MLC.check_featurization(_contract(pipeline={"fit_on": "all", "leaked_metric": 0.90,
                                                  "train_only_metric": 0.905}), ".") is None,
      "featurization: no improvement from the leak -> SILENT")

# --- selection-on-test: K configs on the same held-out set -> fires ---
fs = MLC.check_selection(_contract(sweep={"configs": 30, "held_out": "test"}), ".")
truth(fs and fs["dimension"] == "model-leakage" and "selection-on-test" in fs["locator"]
      and "30" in fs["locator"], "selection: 30 configs on the same held-out set fires")
# with a declared t-stat, the V2 multiple-testing haircut is reported
fst = MLC.check_selection(_contract(sweep={"configs": 50, "held_out": "val", "t_stat": 3.46}), ".")
truth(fst and "haircut" in fst["locator"] and "t=" in fst["locator"],
      "selection: a declared t-stat is haircut by the config count (reuses V2)")
# a single config -> SILENT
truth(MLC.check_selection(_contract(sweep={"configs": 1}), ".") is None, "selection: a single config is SILENT")
# no pipeline/sweep block -> ABSTAIN
truth(MLC.run_checks(_contract(), ".", "c1") == [], "ABSTAINS without a pipeline/sweep block")


# --- promotion (scope-guarded on a no-leakage / held-out claim) ---
def _confirmed_claim():
    vi = {"gap": 0.0, "effective_budget": 1e-9, "binding_status": "independently-bound",
          "determinism_mode": "controlled-to-bit", "container_present": True, "band_coverage_ok": True,
          "sufficient_k": True, "exit_codes": [0], "claim_confirmed_target": True}
    return {"id": "c1", "headline": True, "metric": "accuracy", "claimed_value": 0.94,
            "recomputed_value": 0.94, "verdict": V.verdict(vi),
            "input_binding_status": "independently-bound", "headline_confidence": 0.9,
            "verdict_inputs": vi, "verdict_status": "stable", "waivable": False, "reason": "ok"}


def _promote(contract, claim_text):
    claims = [_confirmed_claim()]
    findings = MLC.run_checks(contract, ".", "c1", claim_text)
    MLC.apply_validity(claims, findings, contract, claim_text, base=".")
    return claims[0], findings


def _ledger_valid(claims, findings):
    led = {"schema": "calma/ledger@1", "claims": claims, "findings": findings,
           "scope": {"isolation_tier": "tier0", "determinism_mode": "controlled-to-bit",
                     "families": {}, "not_verified": []}, "repo_verdict": None}
    led["repo_verdict"] = LED.compute_repo_verdict(led)
    return LED.validate_obj(led)


pc = _contract(pipeline={"fit_on": "train+test", "transform": "StandardScaler",
                         "leaked_metric": 0.94, "train_only_metric": 0.79})
hc, hf = _promote(pc, "no data leakage, properly held-out accuracy 0.94")
truth(hc["verdict"] == V.INVALIDATED and hc.get("driving_dimension") == "model-leakage",
      "promote: featurization leak + a no-leakage claim -> INVALIDATED('model-leakage')")
truth(_ledger_valid([hc], hf)[0] in (0, 1), "model-leakage INVALIDATED ledger validates")
nc, _ = _promote(pc, "accuracy 0.94")
truth(nc["verdict"] == V.CAVEATS, "scope-guard: a bare accuracy (no no-leakage claim) -> CAVEATS")
# selection path also invalidates under a held-out claim
sc, sf = _promote(_contract(sweep={"configs": 40, "held_out": "test"}),
                  "held-out, leak-free accuracy 0.94")
truth(sc["verdict"] == V.INVALIDATED, "promote: selection-on-test + a held-out claim -> INVALIDATED")

truth(MLC.family_status(_contract(), []) == "not-applicable", "family_status: not-applicable without a block")
truth(MLC.family_status(pc, hf) == "flagged", "family_status: flagged when a finding fired")

print("model_leakage_checks: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
