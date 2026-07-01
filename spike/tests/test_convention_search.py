"""Convention-search: convention-sensitive metrics (Sharpe: annualization √periods, sample-vs-population
stdev) must CONFIRM when the repo used a recognized convention, and must STAY not-confirmed when the number
is reproducible under NO standard convention. The second half is the franchise invariant — convention-search
may only rescue genuine numbers, never confirm a wrong one."""
from core import catalog as C
from core import diff as D
from core import verdict as VD

# a fixed daily return series; the repo annualizes (periods_per_year=252) with population stdev (ddof=0) — a
# STANDARD convention the default recompute (periods=1, ddof=1) does NOT use.
_RETURNS = [0.004, -0.002, 0.006, 0.003, -0.001, 0.005, 0.002, -0.003, 0.004, 0.001,
            0.003, -0.002, 0.005, 0.002, 0.004, -0.001, 0.003, 0.006, -0.002, 0.004]


def _call(result):
    # kwargs EMPTY on purpose: the repo's convention lives in its own code (`* sqrt(252)`, np.std ddof=0) and
    # is not captured — exactly the case that makes a single-convention recompute falsely disagree.
    return {"metric": "sharpe", "result": result, "inputs": {"returns": _RETURNS}, "kwargs": {},
            "captured_full": True}


def test_convention_valid_sharpe_confirms():
    """A Sharpe computed with a standard-but-non-default convention reproduces under convention-search → CONFIRMED
    (without it, this correct number would be falsely INVALIDATED as 'cheating')."""
    true_val = C.recompute("sharpe", {"returns": _RETURNS}, {"periods_per_year": 252, "ddof": 0})["value"]
    # sanity: the DEFAULT recompute genuinely disagrees (so the search is what does the work)
    assert C.recompute("sharpe", {"returns": _RETURNS}, {})["value"] != true_val
    call = _call(true_val)
    rec = D.diff_claim({"metric": "sharpe", "value": "%.4f" % true_val}, [[call], [dict(call)]])
    assert rec["verdict"] == VD.CONFIRMED, rec


def test_wrong_sharpe_stays_uncofirmed():
    """FCR: a value reproducible under NO standard convention is never rescued — stays out of POSITIVE."""
    bad = _call(42.0)                                              # the returns give ~0.70..~11.5, never 42
    rec = D.diff_claim({"metric": "sharpe", "value": "42.0"}, [[bad], [dict(bad)]])
    assert rec["verdict"] not in VD.POSITIVE, rec


def test_convention_search_only_touches_convention_metrics():
    """An unambiguous metric (accuracy) has no convention grid → a produced-vs-recompute disagreement is still a
    hard INVALIDATED; convention-search must not soften it."""
    assert "accuracy" not in C.CONVENTIONS
    call = {"metric": "accuracy", "result": 0.99, "captured_full": True,
            "inputs": {"y_true": [1, 0, 1, 0, 1, 1], "y_pred": [1, 0, 1, 0, 1, 0]}}  # true acc = 5/6 ≈ 0.833
    rec = D.diff_claim({"metric": "accuracy", "value": "0.99"}, [[call], [dict(call)]])
    assert rec["verdict"] not in VD.POSITIVE, rec
