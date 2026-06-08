"""M2 calibration regression: FP-guard corpus stays at zero false-REFUTED, the determinism band covers
nominal, the calibration.json artifact exists, the gate is unlocked, and the precision + convention
budget terms behave. Pure stdlib. Run: python3 test_m2.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
CAL = os.path.join(SCR, "..", "calibration")
sys.path.insert(0, SCR)
sys.path.insert(0, CAL)
import calibrate as CB  # noqa: E402
import compare as CMP  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# 1) FP-guard corpus: zero false-REFUTED, every true positive caught
ok, fp, missed, detail = CB.run_corpus(CB.fp_corpus())
truth(not fp, "FP-guard corpus: zero false-REFUTED (%s)" % fp)
truth(not missed, "FP-guard corpus: every true positive caught (%s)" % missed)

# 2) determinism band realized coverage >= nominal
band = CB.determinism_band(CB._series(900, 0.0003, 0.03))
truth(band["realized_coverage_total_return"] >= band["nominal"], "band covers nominal (total_return)")
truth(band["realized_coverage_sharpe"] >= band["nominal"], "band covers nominal (sharpe)")
truth(band["min_k_9595"] == 59, "min-K for (0.95,0.95) is 59")

# 3) calibration.json artifact exists and is well-formed; gate is unlocked
calib_path = os.path.join(SCR, "..", "assets", "calibration.json")
truth(os.path.exists(calib_path), "calibration.json written")
calib = json.load(open(calib_path))
for k in ("abs_floor", "rel_floor", "conv_ratio", "min_k_9595", "fp_guard"):
    truth(k in calib, "calibration.json has %s" % k)
truth(calib["fp_guard"]["false_refuted"] == 0, "published FP == 0")
truth(bool(CMP._load_calibration()), "compare loads calibration (M2 unlocked)")


def cmp1(rec_val, claimed, **env):
    rec = {"metrics": [{"metric_id": env.pop("mid", "total_return"), "value": rec_val, "terms": env.pop("terms", {}),
                        "k_spread": env.pop("k_spread", 0.0), "degenerate": False, "near_zero_vol": False,
                        "path_dependent": env.pop("pd", False)}], "baselines": []}
    m = {"metric_id": rec["metrics"][0]["metric_id"], "artifact": "x", "binding": {},
         "convention": env.pop("convention", None), "claimed_value": claimed, "headline": True,
         "binding_status": "independently-bound", "claim_confirmed": True}
    if "precision" in env:
        m["claimed_precision"] = env.pop("precision")
    return CMP.compare(rec, {"metrics": [m], "baselines": []}, **env)["metrics"][0]["verdict"]


# 4) measured-band run with coverage+K now REFUTES (the gate the whole milestone unlocks)
truth(cmp1(0.40, 2.10, mid="sharpe", terms={"sampling_se": 0.05}, isolation_tier="container",
           determinism_mode="measured-band", sufficient_k=True) == V.REFUTED,
      "measured-band + coverage+K -> REFUTED (gate unlocked)")

# 5) precision term: a rounded claim does NOT REFUTE
truth(cmp1(0.4237, 0.42, isolation_tier="tier0", determinism_mode="controlled-to-bit") != V.REFUTED,
      "rounded claim 0.42 vs 0.4237 -> not REFUTED (precision term)")
# but a true fraud-grade gap still REFUTES despite precision
truth(cmp1(-0.324, 146.98, isolation_tier="tier0", determinism_mode="controlled-to-bit") == V.REFUTED,
      "fraud-grade gap still REFUTES")

# 6) convention cap: declared in-set convention within ratio -> CAVEAT, not REFUTE
truth(cmp1(1.57, 1.90, mid="sharpe", convention="252", terms={"sampling_se": 0.12},
           isolation_tier="tier0", determinism_mode="controlled-to-bit") == V.CAVEATS,
      "declared in-set convention -> CONFIRMED-WITH-CAVEATS, not REFUTED")

# 7) served-fraction: both self-contained fixtures verify and correctly REFUTE
sys.path.insert(0, os.path.join(SCR, "..", "calibration"))
import served_fraction as SF  # noqa: E402
A = os.path.join(SCR, "..", "assets")
btc = SF.assess(os.path.join(A, "btc"), label="btc")
truth(btc["served"] and btc["verdict"] == V.REFUTED, "served-fraction: BTC served + REFUTED")
leak = SF.assess(os.path.join(A, "leakage"), label="leakage")
truth(leak["served"] and leak["verdict"] == V.REFUTED, "served-fraction: leakage served + REFUTED")
truth(leak["determinism"] == "measured-band", "leakage runs on the M2-unlocked measured-band path")
import shutil
for d in ("btc", "leakage"):
    shutil.rmtree(os.path.join(A, d, ".calma"), ignore_errors=True)

print("m2: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
