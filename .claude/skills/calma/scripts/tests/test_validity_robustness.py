"""Adversarial-robustness regressions for the two new validity families + the kernels they call (edge-case
audit findings). The fail-soft rails must NEVER raise (Overflow/Attribute/Arithmetic all caught -> abstain),
the per-block liquidation locator must be ROW-ORDER-INDEPENDENT (else ledger_sha256 drifts for byte-identical
input - the determinism invariant), and validate_contract must reject non-finite declarations. Pure stdlib.
Run: python3 test_validity_robustness.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import draft_contract as DC  # noqa: E402
import embargo_checks as EMB  # noqa: E402
import numeric as N  # noqa: E402
import simulation_assumptions_checks as SAC  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


_DIR = tempfile.mkdtemp(prefix="calma_rob_")


def _write(name, rows):
    p = os.path.join(_DIR, name)
    with open(p, "w", newline="") as f:
        for r in rows:
            f.write(",".join(str(x) for x in r) + "\n")
    return name


# ---- BUG B: huge-but-finite cells must not OverflowError the kernel or the embargo rail ----------------
_huge = N.numerai_corr_series([1e250, 2e250, 3e250], [1e250, 2e250, 3e250])  # raises pre-fix (OverflowError)
truth(_huge != _huge, "numerai_corr_series on huge-finite cells -> NaN (overflow caught, not a crash)")  # NaN != NaN
_write("preds_huge.csv", [["era", "prediction", "target"]] + [["era0001", 1e250, 2e250]] * 3 + [["era0002", 3e250, 1e250]] * 3)
emb_huge = {"embargo": {"era_col": "era", "horizon_days": 20, "val": "preds_huge.csv"},
            "metrics": [{"metric_id": "numerai_corr", "artifact": "preds_huge.csv",
                         "binding": {"prediction": "prediction", "target": "target", "era": "era"},
                         "headline": True}]}
try:
    EMB.run_checks(emb_huge, _DIR, "c1", "validation corr")
    truth(True, "embargo.run_checks on huge-finite cells does NOT raise (fail-soft)")
except Exception as e:  # noqa: BLE001
    truth(False, "embargo.run_checks raised %s on huge cells" % type(e).__name__)

# ---- BUG C: a non-finite horizon must not OverflowError _required_purge / run_checks -------------------
truth(EMB._required_purge({"horizon_days": float("inf")}) <= 100000,
      "_required_purge clamps a non-finite horizon_days (no OverflowError)")
truth(EMB._required_purge({"purge_eras": float("inf")}) <= 100000, "_required_purge clamps inf purge_eras")
try:
    EMB.run_checks({"embargo": {"horizon_days": float("inf"), "train": "preds_huge.csv", "val": "preds_huge.csv",
                                "era_col": "era"}}, _DIR, "c1", "validation")
    truth(True, "embargo.run_checks with horizon_days=inf does NOT raise")
except Exception as e:  # noqa: BLE001
    truth(False, "embargo.run_checks raised %s on inf horizon" % type(e).__name__)

# ---- BUG A: a wrong-typed `var` (a list) must not AttributeError the sim rail --------------------------
try:
    out = SAC.run_checks({"simulation_assumptions": {"firm": "chaos", "var": ["nope"]}}, _DIR, "c1", "VaR")
    truth(out == [], "sim.run_checks with var=[list] -> [] (no AttributeError)")
except Exception as e:  # noqa: BLE001
    truth(False, "sim.run_checks raised %s on var=[list]" % type(e).__name__)

# ---- DETERMINISM: check_liquidation_per_block's named example is row-order-independent -----------------
# two accounts each liquidated twice (a tie on count=2); the total-order tie-break must pick the same one
# regardless of row order, so the locator string is byte-stable.
def _liq_contract(name):
    return {"simulation_assumptions": {"firm": "chaos", "event_log": name},
            "metrics": [{"metric_id": "value_at_risk", "artifact": name, "binding": {"return": "loss"},
                         "claimed_value": 1.0, "headline": True}]}


_write("ev_order1.csv", [["account", "block", "event"], ["0xB", 5, "liquidation"], ["0xB", 5, "liquidation"],
                         ["0xA", 2, "liquidation"], ["0xA", 2, "liquidation"]])
_write("ev_order2.csv", [["account", "block", "event"], ["0xA", 2, "liquidation"], ["0xA", 2, "liquidation"],
                         ["0xB", 5, "liquidation"], ["0xB", 5, "liquidation"]])
f1 = SAC.check_liquidation_per_block(_liq_contract("ev_order1.csv"), _DIR, "c1")
f2 = SAC.check_liquidation_per_block(_liq_contract("ev_order2.csv"), _DIR, "c1")
truth(f1 and f2 and f1["locator"] == f2["locator"],
      "determinism: the liquidation locator is identical across row orderings (ledger_sha256 stable)")
truth(f1 and "0xA" in f1["locator"], "determinism: the tie-break names the lexicographically-first account (0xA)")

# ---- apply_validity tolerates findings=None -----------------------------------------------------------
try:
    EMB.apply_validity([{"headline": True, "verdict": "CONFIRMED"}], None, {}, "x")
    SAC.apply_validity([{"headline": True, "verdict": "CONFIRMED"}], None, {}, "x")
    truth(True, "apply_validity(findings=None) does not raise (both families)")
except Exception as e:  # noqa: BLE001
    truth(False, "apply_validity raised %s on findings=None" % type(e).__name__)

# ---- validate_contract rejects non-finite declarations ------------------------------------------------
bad_emb = DC.validate_contract({"run": {"entrypoint": "x"}, "artifacts": [], "metrics": [],
                                "embargo": {"horizon_days": float("inf")}})
truth(any("finite" in e for e in bad_emb), "validate: embargo.horizon_days=inf rejected (finite required)")
bad_sa = DC.validate_contract({"run": {"entrypoint": "x"}, "artifacts": [], "metrics": [],
                               "simulation_assumptions": {"close_factor_max": float("inf")}})
truth(any("finite" in e for e in bad_sa), "validate: simulation_assumptions.close_factor_max=inf rejected")

print("validity_robustness: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
