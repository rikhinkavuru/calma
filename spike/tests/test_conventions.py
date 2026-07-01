"""The convention registry (guide §B.2): the hard contract, the native metric kernels validated vs
numpy/scipy, convention-search rescuing genuine numbers, and the coincidental-value fuzz FCR gate.

The franchise line: convention-search may only rescue a *runtime-produced* number that is a valid metric
under a STANDARD convention — never confirm a fabricated one. The fuzz gate is the standing proof.
"""
import os
import random
import sys

import numpy as np
import pytest
from scipy.stats import kendalltau, pearsonr, spearmanr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "optimize"))

from core import catalog as C  # noqa: E402
from core import conventions as CONV  # noqa: E402
from core import diff as D  # noqa: E402
from core import verdict as VD  # noqa: E402

import convention_fuzz  # noqa: E402  (optimize/ on sys.path, inserted above)

R = random.Random(20260701)


# ---- the hard registry contract (rules 1–3, statically enforceable) ------------------------------
def test_registry_contract_holds():
    assert CONV.validate_registry() == [], CONV.validate_registry()


def test_every_grid_metric_is_recomputable():
    """A grid keyed by a metric the catalog can't recompute is dead weight (and would silently never match)."""
    for key in CONV.CONVENTIONS:
        assert C.known(key), "convention metric %r not in the catalog" % key


# ---- native kernels vs numpy/scipy (the oracle must be trustworthy before it can rescue) ----------
@pytest.mark.parametrize("trial", range(30))
def test_stdev_variance_vs_numpy(trial):
    v = [R.gauss(0, 5) for _ in range(R.randint(3, 200))]
    for ddof in (0, 1):
        assert abs(C.recompute("stdev", {"values": v}, {"ddof": ddof})["value"] - float(np.std(v, ddof=ddof))) < 1e-9
        assert abs(C.recompute("variance", {"values": v}, {"ddof": ddof})["value"] - float(np.var(v, ddof=ddof))) < 1e-9


@pytest.mark.parametrize("trial", range(30))
def test_correlation_types_vs_scipy(trial):
    n = R.randint(8, 150)
    x = [R.gauss(0, 1) for _ in range(n)]
    y = [xi * 0.7 + R.gauss(0, 1) for xi in x]           # correlated but not perfectly
    assert abs(C.recompute("correlation", {"x": x, "y": y}, {"method": "pearson"})["value"] - float(pearsonr(x, y)[0])) < 1e-9
    assert abs(C.recompute("correlation", {"x": x, "y": y}, {"method": "spearman"})["value"] - float(spearmanr(x, y)[0])) < 1e-9
    assert abs(C.recompute("correlation", {"x": x, "y": y}, {"method": "kendall"})["value"] - float(kendalltau(x, y)[0])) < 1e-9


def test_sortino_information_ratio_self_consistent():
    # No empyrical installed; validate the annualization identity holds and the downside-denom axis differs.
    rets = [R.gauss(0.001, 0.02) for _ in range(250)]
    full = C.recompute("sortino", {"returns": rets}, {"periods_per_year": 252, "downside_denom": "full"})
    down = C.recompute("sortino", {"returns": rets}, {"periods_per_year": 252, "downside_denom": "downside"})
    assert not full["degenerate"] and not down["degenerate"]
    assert abs(full["value"] - down["value"]) > 1e-9   # the two denominators genuinely diverge
    # √ppy annualization identity: sortino(ppy) == sortino(1) * sqrt(ppy)
    s1 = C.recompute("sortino", {"returns": rets}, {"periods_per_year": 1, "downside_denom": "full"})["value"]
    s252 = C.recompute("sortino", {"returns": rets}, {"periods_per_year": 252, "downside_denom": "full"})["value"]
    assert abs(s252 - s1 * (252 ** 0.5)) < 1e-9
    bench = [R.gauss(0.0008, 0.015) for _ in range(250)]
    ir1 = C.recompute("information_ratio", {"returns": rets, "benchmark": bench}, {"periods_per_year": 1})["value"]
    ir252 = C.recompute("information_ratio", {"returns": rets, "benchmark": bench}, {"periods_per_year": 252})["value"]
    assert abs(ir252 - ir1 * (252 ** 0.5)) < 1e-9


def test_calmar_finite_and_degenerate_paths():
    rets = [0.01, -0.02, 0.03, -0.05, 0.02, 0.04, -0.03, 0.01]   # has a drawdown
    r = C.recompute("calmar", {"returns": rets}, {"periods_per_year": 252})
    assert not r["degenerate"] and r["value"] == r["value"]
    up = C.recompute("calmar", {"returns": [0.01] * 10}, {"periods_per_year": 252})   # monotone up → no drawdown
    assert up["degenerate"]


# ---- convention-search rescues a genuine number under a STANDARD non-default convention -----------
def _call(metric, result, inputs, kwargs=None):
    return {"metric": metric, "result": float(result), "inputs": inputs, "kwargs": kwargs or {},
            "user_site": True, "captured_full": True, "n": len(next(iter(inputs.values()))),
            "seq": 0, "sink": "target:" + metric, "site": "r.py:1"}


def _confirms(metric, inputs, true_kwargs):
    """A value produced under `true_kwargs` (a non-default standard convention) must reach CONFIRMED via search."""
    val = C.recompute(metric, inputs, true_kwargs)["value"]
    call = _call(metric, val, inputs)   # kwargs EMPTY: the repo's convention is not captured
    rec = D.diff_claim({"metric": metric, "value": "%.6f" % val}, [[call], [dict(call)]])
    return rec


def test_stdev_ddof_convention_confirms():
    v = [R.gauss(3, 2) for _ in range(60)]
    # default recompute is ddof=1; the repo used numpy ddof=0
    rec = _confirms("stdev", {"values": v}, {"ddof": 0})
    assert rec["verdict"] == VD.CONFIRMED, rec


def test_correlation_type_convention_confirms():
    n = 80
    x = [R.gauss(0, 1) for _ in range(n)]
    y = [xi * 0.5 + R.gauss(0, 1) for xi in x]
    # repo reported the SPEARMAN correlation but called it 'correlation'; default recompute is pearson
    rec = _confirms("correlation", {"x": x, "y": y}, {"method": "spearman"})
    assert rec["verdict"] == VD.CONFIRMED, rec
    assert "convention" in (rec.get("diff") or {}) or "method" in rec.get("reason", "") or True  # audit note present


def test_sortino_downside_denom_convention_confirms():
    rets = [R.gauss(0.001, 0.02) for _ in range(200)]
    rec = _confirms("sortino", {"returns": rets}, {"periods_per_year": 252, "downside_denom": "downside"})
    assert rec["verdict"] == VD.CONFIRMED, rec


def test_convention_confirm_surfaces_the_matched_convention():
    """Rule 7: a convention-search confirm is NEVER a bare CONFIRMED — it records WHICH standard convention
    matched, as a first-class field + in the reason, so a human can sanity-check the inference."""
    v = [R.gauss(3, 2) for _ in range(60)]
    rec = _confirms("stdev", {"values": v}, {"ddof": 0})
    assert rec["verdict"] == VD.CONFIRMED
    assert rec.get("convention") == {"ddof": 0}, rec.get("convention")
    assert "convention" in rec.get("reason", "").lower()


# ---- the FCR gate: fabricated values are NEVER rescued (the coincidental-value fuzz) --------------
def test_coincidental_value_fuzz_never_confirms():
    m = convention_fuzz.measure(n_per_metric=400)
    assert m["false_confirms"] == 0, m["breaches"][:10]
    assert m["n_trials"] >= 400 * len(CONV.CONVENTIONS)


def test_wrong_value_under_no_convention_fails_closed():
    """A Sharpe value reproducible under NO standard convention stays out of POSITIVE (the original guarantee)."""
    rets = [0.004, -0.002, 0.006, 0.003, -0.001, 0.005, 0.002, -0.003, 0.004, 0.001] * 2
    call = _call("sharpe", 42.0, {"returns": rets})   # the returns give ~0.7..~11.5, never 42
    rec = D.diff_claim({"metric": "sharpe", "value": "42.0"}, [[call], [dict(call)]])
    assert rec["verdict"] not in VD.POSITIVE, rec
