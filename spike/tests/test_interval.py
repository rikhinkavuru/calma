"""Feature 6 — statistical / distribution verification. An unstable but correct repo earns the DISTINCT
CONFIRMED-STOCHASTIC (never the hard CONFIRMED, never in POSITIVE); a claim clearly outside the run-to-run
distribution is REFUTED; and below k_min there is no power so it stays fail-closed. Also pins feature 15's
seed_injected disqualifier."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from core import diff as D  # noqa: E402
from core import interval as I  # noqa: E402
from core import verdict as VD  # noqa: E402
import pipeline as P  # noqa: E402


def _acc_call(acc, n=200):
    correct = max(1, min(n - 1, round(acc * n)))
    yt = [i % 2 for i in range(n)]
    yp = list(yt)
    for i in range(n - correct):
        yp[i] = 1 - yp[i]
    real = sum(1 for a, b in zip(yt, yp) if a == b) / n
    return {"metric": "accuracy", "result": real, "inputs": {"y_true": yt, "y_pred": yp}, "kwargs": {},
            "user_site": True, "captured_full": True, "n": n, "seq": 0,
            "sink": "sklearn.metrics.accuracy_score", "site": "r.py:1"}


def _runs(accs):
    return [[_acc_call(a)] for a in accs]


def test_predict_interval_power_gate():
    assert I.predict_interval([0.8, 0.82])["enough"] is False              # k=2 < k_min
    assert I.predict_interval([0.80, 0.81, 0.83, 0.82, 0.84])["enough"] is True


def test_interval_contains_and_outside():
    iv = I.predict_interval([0.80, 0.81, 0.83, 0.82, 0.84, 0.79])
    assert I.contains(iv, "0.82")
    assert I.outside_by_margin(iv, "0.99")
    assert not I.outside_by_margin(iv, "0.82")


def test_confirmed_stochastic_is_not_a_hard_confirm():
    assert VD.CONFIRMED_STOCHASTIC not in VD.POSITIVE
    assert VD.CONFIRMED_STOCHASTIC in VD.AFFIRMATIVE


def test_in_distribution_claim_confirms_stochastically():
    accs = [0.84, 0.86, 0.85, 0.87, 0.83, 0.85, 0.86, 0.84]
    rec = D.diff_claim({"metric": "accuracy", "value": "0.85"}, _runs(accs))
    assert rec["verdict"] == VD.CONFIRMED_STOCHASTIC


def test_far_claim_is_refuted():
    accs = [0.84, 0.86, 0.85, 0.87, 0.83, 0.85, 0.86, 0.84]
    rec = D.diff_claim({"metric": "accuracy", "value": "0.30"}, _runs(accs))
    assert rec["verdict"] == VD.REFUTED


def test_low_k_unstable_stays_non_deterministic():
    # k=2 has no distribution power, so the point claim-vs-run[0] check governs. With the claim matching run 0
    # (0.84) the only remaining issue is instability → NON-DETERMINISTIC (never CONFIRMED-STOCHASTIC at k<k_min).
    rec = D.diff_claim({"metric": "accuracy", "value": "0.84"}, _runs([0.84, 0.87]))
    assert rec["verdict"] == VD.NON_DETERMINISTIC


def test_stable_runs_still_hard_confirm():
    rec = D.diff_claim({"metric": "accuracy", "value": "0.85"}, _runs([0.85, 0.85]))
    assert rec["verdict"] == VD.CONFIRMED                                   # identical runs → deterministic


def test_wildly_unstable_repo_never_confirms_stochastically():
    # spread ~ the whole [0,1] range → the interval would swallow any in-range claim → too unstable to verify.
    accs = [0.10, 0.90, 0.30, 0.75, 0.20, 0.85, 0.40, 0.60]
    rec = D.diff_claim({"metric": "accuracy", "value": "0.50"}, _runs(accs))
    assert rec["verdict"] not in VD.AFFIRMATIVE            # never CONFIRMED / CONFIRMED-STOCHASTIC (fail-closed)


def test_seed_injected_caps_below_confirmed():
    rec = D.diff_claim({"metric": "accuracy", "value": "0.85"}, _runs([0.85, 0.85]), seed_injected=True)
    assert rec["verdict"] == VD.REPRODUCED_ONLY                             # a seeded run verifies a different number


def test_bare_integer_overclaim_does_not_confirm_stochastically():
    """FCR review finding 1: the repo produces ~0.90-0.96 unstable; the author over-claims a PERFECT "1". The
    interval's Gaussian tail can overshoot 1.0, but a bare [0,1] integer must be checked TIGHT against the
    OBSERVED range — so "1" (never actually produced) must not confirm-stochastically."""
    accs = [0.90, 0.94, 0.92, 0.96, 0.91, 0.93, 0.95, 0.92]
    rec = D.diff_claim({"metric": "accuracy", "value": "1"}, _runs(accs))
    assert rec["verdict"] not in VD.AFFIRMATIVE
    # a genuine in-range decimal claim still confirms stochastically
    assert D.diff_claim({"metric": "accuracy", "value": "0.93"}, _runs(accs))["verdict"] == VD.CONFIRMED_STOCHASTIC


def test_agent_modified_cap_also_caps_stochastic_confirm():
    """FCR review finding 2: a source-modifying repair must cap CONFIRMED-STOCHASTIC too, not just CONFIRMED."""
    rec = {"id": "c", "metric": "accuracy", "verdict": VD.CONFIRMED_STOCHASTIC,
           "validity": {"invalidating": [], "advisory": []}}
    P._apply_agent_modified_cap([rec], ["metric.py"])
    assert rec["verdict"] == VD.REPRODUCED_ONLY


def test_redteam_gate_screens_stochastic_confirm():
    """FCR review finding 3: the inline red-team gate must screen CONFIRMED-STOCHASTIC too. A single-class
    computation sitting on a stochastic confirm must be downgraded."""
    claim = {"id": "c0", "metric": "accuracy", "value": "1.0"}
    call = {"metric": "accuracy", "result": 1.0, "inputs": {"y_true": [1] * 10, "y_pred": [1] * 10},
            "kwargs": {}, "user_site": True, "captured_full": True, "n": 10, "seq": 0,
            "sink": "sklearn.metrics.accuracy_score", "site": "r.py:1"}
    rec = {"id": "c0", "metric": "accuracy", "verdict": VD.CONFIRMED_STOCHASTIC,
           "validity": {"invalidating": [], "advisory": []}}
    P._apply_redteam_gate([rec], [claim], [[call]])
    assert rec["verdict"] == VD.INVALIDATED and "redteam" in rec
