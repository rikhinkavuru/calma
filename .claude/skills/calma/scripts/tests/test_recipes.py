"""Tests for numeric.py + recipes.py against hand-computed reference values. Pure stdlib.
Run: python3 test_recipes.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numeric as N  # noqa: E402
import recipes as R  # noqa: E402

_n = _fail = 0


def isnan_local(x):
    return isinstance(x, float) and x != x


def approx(got, want, tol, label):
    global _n, _fail
    _n += 1
    if not (abs(got - want) <= tol):
        _fail += 1
        print("  FAIL [%s] got %r want %r (tol %g)" % (label, got, want, tol))


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# total_return: (1+.1)(1-.1)-1 = 1.1*0.9-1 = -0.01
approx(N.total_return([0.1, -0.1]), -0.01, 1e-12, "total_return 2-step")
approx(N.total_return([0.0, 0.0, 0.0]), 0.0, 0.0, "total_return zeros")

# mean/std/sharpe of a known series
xs = [0.01, 0.02, -0.01, 0.03, 0.0]
approx(N.fmean(xs), 0.01, 1e-12, "fmean")
# sample std (ddof=1) of xs: computed by hand/python statistics
import statistics  # noqa: E402
approx(N.fstd(xs), statistics.stdev(xs), 1e-12, "fstd matches statistics.stdev")
sr, nzv = N.sharpe(xs, 252)
approx(sr, (statistics.mean(xs) / statistics.stdev(xs)) * math.sqrt(252), 1e-9, "sharpe annualised")
truth(not nzv, "sharpe not near-zero-vol")
# near-zero vol -> flagged
_, nzv2 = N.sharpe([0.01, 0.01, 0.01], 252)
truth(nzv2, "constant series flags near-zero-vol")

# max_drawdown: equity 1 ->1.1->0.99->... worst dd
approx(N.max_drawdown([0.5, -0.5]), 1.5 * 0.5 / 1.5 - 1.0, 1e-12, "max_drawdown 2-step")
truth(N.max_drawdown([0.1, 0.1, 0.1]) == 0.0, "monotonic up -> 0 drawdown")

# accuracy
approx(N.accuracy([1, 0, 1, 1], [1, 0, 0, 1]), 0.75, 1e-12, "accuracy")

# AUC: perfect separation = 1.0, reversed = 0.0, tie handling
truth(N.auc([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0]) == 1.0, "AUC perfect = 1.0")
truth(N.auc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]) == 0.0, "AUC reversed = 0.0")
# known small case: scores/labels -> AUC computed by hand = 0.75
# pos={0.6,0.4} neg={0.5,0.3}: pairs (.6>.5)=1,(.6>.3)=1,(.4>.5)=0,(.4>.3)=1 -> 3/4 = 0.75
approx(N.auc([0.6, 0.4, 0.5, 0.3], [1, 1, 0, 0]), 0.75, 1e-12, "AUC small case 0.75")
se = N.auc_delong_se([0.6, 0.4, 0.5, 0.3, 0.55, 0.2], [1, 1, 0, 0, 1, 0])
truth(se == se and se > 0, "DeLong SE positive finite")

# recipe registry: both families present
truth(set(R.ids()) >= {"sharpe", "total_return", "max_drawdown", "accuracy", "auc"}, "all M1 recipes registered")
truth(R.get("max_drawdown")({"r": [0.5, -0.5]}, {"return": "r"})["path_dependent"], "max_drawdown flagged path-dependent")
res = R.get("auc")({"s": [0.6, 0.4, 0.5, 0.3], "y": [1, 1, 0, 0]}, {"score": "s", "label": "y"})
approx(res["value"], 0.75, 1e-12, "auc recipe value")
truth(res["terms"]["se_method"] == "delong", "auc recipe carries DeLong SE")

# determinism: same inputs -> identical bits, twice
truth(N.sharpe(xs, 252) == N.sharpe(xs, 252), "sharpe bit-stable across calls")
truth(N.total_return(xs) == N.total_return(xs), "total_return bit-stable across calls")

# regression + analytics + classification-depth families
import math as _m
approx(N.rmse([1.0, 2.0, 3.0], [1.0, 2.0, 4.0]), _m.sqrt(1.0/3.0), 1e-12, "rmse")
approx(N.mae([1.0, 2.0], [2.0, 4.0]), 1.5, 1e-12, "mae")
approx(N.r2([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), 1.0, 0.0, "r2 perfect")
truth(isnan_local(N.r2([1.0, 1.0], [5.0, 5.0])), "r2 zero-variance -> nan")
approx(N.precision([1, 1, 0], [1, 0, 0]), 0.5, 1e-12, "precision")
approx(N.recall([1, 0, 1], [1, 1, 0]), 0.5, 1e-12, "recall")
approx(N.f1([1, 1, 0, 0], [1, 0, 0, 1]), 0.5, 1e-12, "f1")
approx(N.col_sum([1.5, 2.5, 3.0]), 7.0, 1e-12, "col_sum")
approx(N.col_mean([2.0, 4.0, 6.0]), 4.0, 1e-12, "col_mean")
truth(R.get("rmse")({"p": [1.0, 2.0], "t": [1.0, 3.0]}, {"prediction": "p", "target": "t"})["value"] > 0, "rmse recipe runs")
truth(R.get("row_count")({"c": [1, 2, 3, 4]}, {"column": "c"})["value"] == 4.0, "row_count recipe")
truth(set(R.ids()) >= {"rmse", "mae", "r2", "precision", "recall", "f1", "column_sum", "column_mean", "row_count", "brier"}, "new recipe families registered")
approx(N.brier([0.9, 0.1], [1, 0]), (0.01 + 0.01) / 2, 1e-12, "brier score")
truth(isnan_local(N.brier([0.5, float("nan")], [1, 0])), "brier NaN -> nan")
# NaN propagation in new metrics
truth(isnan_local(N.rmse([1.0, float("nan")], [1.0, 2.0])), "rmse NaN -> nan")
truth(isnan_local(N.col_sum([1.0, float("nan")])), "col_sum NaN -> nan")

print("recipes/numeric: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
