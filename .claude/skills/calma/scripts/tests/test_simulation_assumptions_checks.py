"""WS-C(ii) risk-firm simulation-assumption invariants. Each of the four checks must FIRE on the planted
violation and stay SILENT on a clean log; the INVALIDATED promotion is scope-guarded on a VaR/risk/
methodology claim. The VaR-percentile check catches a number labeled p99 that is really the p95 of the loss
vector. Pure stdlib. Run: python3 test_simulation_assumptions_checks.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import draft_contract as DC  # noqa: E402
import numeric as N  # noqa: E402
import simulation_assumptions_checks as SAC  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


_DIR = tempfile.mkdtemp(prefix="calma_sa_")


def _write(name, header, rows):
    with open(os.path.join(_DIR, name), "w", newline="") as f:
        f.write(",".join(header) + "\n")
        for r in rows:
            f.write(",".join(str(x) for x in r) + "\n")
    return name


# event log with a DOUBLE liquidation of 0xA in block 100 (close factors all <= 0.5, so only check 1 fires)
_write("events_dup.csv", ["account", "block", "event", "repaid", "pre_debt"],
       [("0xA", 100, "liquidation", 40, 100), ("0xA", 100, "liquidation", 30, 60),
        ("0xB", 101, "liquidation", 20, 100)])
# clean event log (no dup, close factors in bound)
_write("events_clean.csv", ["account", "block", "event", "repaid", "pre_debt"],
       [("0xA", 100, "liquidation", 40, 100), ("0xB", 101, "liquidation", 20, 100),
        ("0xA", 102, "liquidation", 30, 80)])
# close-factor violation: 80/100 = 0.8 > 0.5 (no dup, so only check 4 fires)
_write("events_cf.csv", ["account", "block", "event", "repaid", "pre_debt"],
       [("0xA", 100, "liquidation", 80, 100), ("0xB", 101, "liquidation", 20, 100)])
# a loss vector 1..100; p95 and p99 are distinct, known quantiles
_write("losses.csv", ["loss"], [(x,) for x in range(1, 101)])
_P95 = N.quantile([float(x) for x in range(1, 101)], 0.95)
_P99 = N.quantile([float(x) for x in range(1, 101)], 0.99)


def _contract(event_log=None, var=None, calibration=None, firm="chaos", metric_val=None):
    sa = {"firm": firm}
    if event_log:
        sa["event_log"] = event_log
    if var is not None:
        sa["var"] = var
    if calibration is not None:
        sa["calibration"] = calibration
    return {"simulation_assumptions": sa,
            "metrics": [{"metric_id": "value_at_risk", "artifact": "losses.csv",
                         "binding": {"return": "loss"},
                         "claimed_value": metric_val if metric_val is not None else _P99, "headline": True}]}


# ---- check 1: <=1 liquidation per account per block --------------------------------------------------
f1 = SAC.check_liquidation_per_block(_contract(event_log="events_dup.csv"), _DIR, "c1")
truth(f1 and f1["dimension"] == "simulation-assumptions" and f1["simassume_kind"] == "liquidation-per-block"
      and "0xA" in f1["locator"] and "block 100" in f1["locator"],
      "check1: a double liquidation of one account in one block FIRES")
truth(SAC.check_liquidation_per_block(_contract(event_log="events_clean.csv"), _DIR, "c1") is None,
      "check1: a clean log (<=1 liquidation/account/block) is SILENT")

# ---- check 2: VaR percentile recompute + mis-statement -----------------------------------------------
# reported VaR is the p95 of the loss vector but declared/firm percentile is p99 -> mis-stated
f2 = SAC.check_var_percentile(_contract(var={"loss_log": "losses.csv", "reported": _P95}), _DIR, "c1")
truth(f2 and f2["simassume_kind"] == "var-percentile-misstated" and "p95" in f2["locator"]
      and "p99" in f2["locator"], "check2: a VaR labeled p99 that is really the p95 FIRES (mis-statement)")
# reported VaR equals the declared p99 -> consistent, SILENT
truth(SAC.check_var_percentile(_contract(var={"loss_log": "losses.csv", "reported": _P99}), _DIR, "c1") is None,
      "check2: the reported VaR == the declared p99 of the loss vector is SILENT")
# declared percentile != the firm's published constant (Gauntlet p95) -> firm-mismatch
f2b = SAC.check_var_percentile(_contract(firm="gauntlet",
                                         var={"loss_log": "losses.csv", "percentile": 0.99,
                                              "reported": _P99}), _DIR, "c1")
truth(f2b and f2b["simassume_kind"] == "var-percentile-firm",
      "check2: a declared p99 under Gauntlet (p95 methodology) FIRES (firm constant mismatch)")

# ---- check 3: calibration-window look-ahead ----------------------------------------------------------
f3 = SAC.check_calibration_lookahead(_contract(calibration={"window_end": "2024-01-05",
                                                            "sim_start": "2024-01-02"}), _DIR, "c1")
truth(f3 and f3["simassume_kind"] == "calibration-lookahead" and f3["validity_class"] == "authoritative",
      "check3: a calibration window ending after sim-start FIRES (look-ahead)")
truth(SAC.check_calibration_lookahead(_contract(calibration={"window_end": "2024-01-01",
                                                             "sim_start": "2024-01-02"}), _DIR, "c1") is None,
      "check3: a window ending strictly before sim-start is SILENT")
f3na = SAC.check_calibration_lookahead(_contract(calibration={"method": "GARCH"}), _DIR, "c1")
truth(f3na and f3na["simassume_kind"] == "calibration-not-auditable" and f3na["validity_class"] == "soft",
      "check3: a calibration with no window dates -> soft 'not auditable'")

# ---- check 4: close-factor bound ---------------------------------------------------------------------
f4 = SAC.check_close_factor(_contract(event_log="events_cf.csv"), _DIR, "c1")
truth(f4 and f4["simassume_kind"] == "close-factor" and "0.8" in f4["locator"],
      "check4: a liquidation repaying 0.8 of debt (> 0.5 close factor) FIRES")
truth(SAC.check_close_factor(_contract(event_log="events_clean.csv"), _DIR, "c1") is None,
      "check4: close factors within (0, 0.5] are SILENT")


# ---- promotion: scope-guarded INVALIDATED ------------------------------------------------------------
def _confirmed_claim():
    vi = {"gap": 0.0, "effective_budget": 1e-9, "binding_status": "independently-bound",
          "determinism_mode": "controlled-to-bit", "container_present": True, "band_coverage_ok": True,
          "sufficient_k": True, "exit_codes": [0], "claim_confirmed_target": True}
    return {"id": "c1", "headline": True, "metric": "value_at_risk", "claimed_value": _P95,
            "recomputed_value": _P95, "verdict": V.verdict(vi), "input_binding_status": "independently-bound",
            "headline_confidence": 0.9, "verdict_inputs": vi, "verdict_status": "stable",
            "waivable": False, "reason": "ok"}


def _promote(contract, claim_text):
    claims = [_confirmed_claim()]
    findings = SAC.run_checks(contract, _DIR, "c1", claim_text)
    SAC.apply_validity(claims, findings, contract, claim_text, base=_DIR)
    return claims[0], findings


hc, hf = _promote(_contract(event_log="events_dup.csv"), "p99 VaR 95.05 is conservative")
truth(hc["verdict"] == V.INVALIDATED and hc.get("driving_dimension") == "simulation-assumptions",
      "promote: a double-liquidation under a VaR/risk claim -> INVALIDATED('simulation-assumptions')")
bc, _ = _promote(_contract(event_log="events_dup.csv"), "the figure is 95.05")
truth(bc["verdict"] == V.CAVEATS, "scope-guard: a bare figure (no VaR/risk/methodology scope) -> CAVEATS")
nc, nf = _promote(_contract(calibration={"method": "GARCH"}), "p99 VaR 99 is sound")
truth(nc["verdict"] == V.CAVEATS and any(f["simassume_kind"] == "calibration-not-auditable" for f in nf),
      "promote: a soft 'not auditable' finding -> CAVEATS, never INVALIDATED")

# ---- family_status + abstention ----------------------------------------------------------------------
truth(SAC.family_status({}, []) == "not-applicable", "family_status: not-applicable without a block")
truth(SAC.family_status(_contract(event_log="events_dup.csv"), hf) == "flagged", "family_status: flagged when fired")
truth(SAC.run_checks({}, _DIR, "c1") == [], "ABSTAINS entirely without a simulation_assumptions block")

# ---- contract validation -----------------------------------------------------------------------------
ok = DC.validate_contract({"run": {"entrypoint": "x"}, "artifacts": [], "metrics": [],
                           "simulation_assumptions": {"firm": "chaos", "event_log": "e.csv",
                                                      "var": {"loss_log": "l.csv", "percentile": 0.99},
                                                      "calibration": {"window_end": "2024-01-01",
                                                                      "sim_start": "2024-01-02"}}})
truth(ok == [], "validate: a well-formed simulation_assumptions block is accepted")
bad = DC.validate_contract({"run": {"entrypoint": "x"}, "artifacts": [], "metrics": [],
                            "simulation_assumptions": {"var": {"percentile": 1.5}}})
truth(any("percentile must be a number in (0,1)" in e for e in bad), "validate: percentile out of (0,1) is rejected")
bad2 = DC.validate_contract({"run": {"entrypoint": "x"}, "artifacts": [], "metrics": [],
                             "simulation_assumptions": {"firmm": "chaos"}})
truth(any("not a recognized key" in e for e in bad2), "validate: an unknown sim-assumptions key (typo) is rejected")

print("simulation_assumptions_checks: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
