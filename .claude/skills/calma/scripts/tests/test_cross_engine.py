"""B2: cross-engine correctness. Recompute a metric through an INDEPENDENT second kernel and diff it
against numeric.py under the calibrated tolerance. The second kernel uses a DIFFERENT algorithm
(naive sum / sequential product / Welford), so agreement is a real cross-check (a bug in either
surfaces) and a true divergence is flagged. Additive + soft: it never drives an authoritative verdict.
Pure stdlib, offline. Run: python3 test_cross_engine.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import cross_engine as CE  # noqa: E402
import numeric as N  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- the second-engine kernels AGREE with numeric.py on the same data (genuinely independent code) ---
rets = [0.01, -0.02, 0.013, 0.005, -0.008, 0.021, -0.003, 0.017]
truth(CE._agree(N.total_return(rets), CE._seq_total_return(rets)),
      "cross-engine: sequential product agrees with numeric.py's pairwise total_return")
truth(CE._agree(N.fmean(rets), CE._naive_mean(rets)),
      "cross-engine: naive-fold mean agrees with numeric.py's fsum mean")
truth(CE._agree(N.sharpe(rets, 1)[0], CE._sharpe(rets, 1)),
      "cross-engine: Welford sharpe agrees with numeric.py's two-pass sharpe")
pred, act = [1.0, 2.0, 3.0, 4.0], [1.2, 1.8, 3.3, 3.9]
truth(CE._agree(N.rmse(pred, act), CE._rmse(pred, act)), "cross-engine: independent rmse agrees")
truth(CE._agree(N.mae(pred, act), CE._mae(pred, act)), "cross-engine: independent mae agrees")

# the two kernels are NOT the same code: on a long series the reduction orders differ at ~1e-16 (still
# within the 1e-9 budget) - i.e. they genuinely agree without being identical implementations.
long = [((-1) ** i) * (0.001 * (i % 7 + 1)) for i in range(5000)]
p, s = N.total_return(long), CE._seq_total_return(long)
truth(CE._agree(p, s) and p != s,
      "cross-engine: independent kernels agree to tolerance yet differ in the last bits (truly separate)")

# --- cross_check_metric: structured agreement on an honest value, skip on unknown metric/convention ---
cols = {"r": rets}
ok = CE.cross_check_metric("total_return", cols, {"return": "r"}, None, N.total_return(rets))
truth(ok and ok["agree"] and ok["engine"] == CE.SECOND_ENGINE and ok["abs_diff"] < CE.ABS_FLOOR,
      "cross_check_metric: an honest total_return AGREES (abs_diff within budget)")
truth(CE.cross_check_metric("some_unsupported_metric", cols, {"return": "r"}, None, 0.1) is None,
      "cross_check_metric: a metric with no second-engine kernel -> None (honest skip, never a fake pass)")
truth(CE.cross_check_metric("total_return", cols, {"return": "r"}, "weird-convention", 0.1) is None,
      "cross_check_metric: an unreplicated convention -> None (only diffs the SAME quantity)")

# --- a real DIVERGENCE is detected + flagged (primary value that the data does not support) ---
div = CE.cross_check_metric("total_return", cols, {"return": "r"}, None, 999.0)
truth(div and div["agree"] is False and div["abs_diff"] > 1.0,
      "cross_check_metric: a primary value the raw data contradicts is a DIVERGENCE (not agreement)")
f = CE.finding({"metrics": [div]}, claim_id="c1")
truth(f and f["dimension"] == "cross-engine" and f["severity"] == "minor"
      and f["validity_class"] == "heuristic",
      "finding: a divergence -> a SOFT (minor, heuristic) cross-engine finding, never authoritative")
truth(f and "implementation-dependent" in f["locator"],
      "finding: the locator names the implementation-dependence")
truth(CE.finding({"metrics": [ok]}) is None,
      "finding: full agreement -> NO finding")

# --- cross_check_contract end-to-end over a recompute-shaped result ---
contract = {"metrics": [{"metric_id": "column_sum", "artifact": "data.csv",
                         "binding": {"value": "v"}}]}
# write a tiny artifact + a matching recompute result
import tempfile  # noqa: E402
d = tempfile.mkdtemp()
with open(os.path.join(d, "data.csv"), "w") as fh:
    fh.write("v\n1.5\n2.5\n3.0\n")
rec = {"metrics": [{"metric_id": "column_sum", "artifact": "data.csv", "value": 7.0}]}
cc = CE.cross_check_contract(contract, d, rec)
truth(cc["n_checked"] == 1 and not cc["any_divergence"] and cc["metrics"][0]["second"] == 7.0,
      "cross_check_contract: recomputes column_sum on the 2nd kernel and agrees end-to-end")
truth(isinstance(cc["external_available"], list),
      "cross_check_contract: reports the external engines the host could use")

print("cross_engine: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
