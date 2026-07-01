"""Feature 8 — the inline red-team overlay. The gate is a second, independent screen of every CONFIRMED,
wired downgrade-only through verdict.monotone. These pin its two load-bearing properties: it can NEVER raise
a verdict (so FCR=0 is preserved by construction), and it is a no-op on honest CONFIRMEDs (so it is not a
false-REFUTE machine)."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from core import redteam_gate as RTG  # noqa: E402
from core import verdict as VD  # noqa: E402
import pipeline as P  # noqa: E402

_VERDICTS = list(VD.ALL) + ["DISCOVERED"]


def _call(metric, result, inputs, user_site=True, seq=0):
    return {"metric": metric, "result": result, "inputs": inputs, "kwargs": {},
            "user_site": user_site, "captured_full": True, "seq": seq,
            "n": len(next(iter(inputs.values()))), "site": "r.py:%d" % (1 + seq),
            "sink": "sklearn.metrics.%s_score" % metric}


def test_monotone_never_upgrades_to_confirmed():
    """Property over every (old, proposed) pair incl. None: the result is CONFIRMED only when old already was,
    is one of the two operands, and never strengthens."""
    for old in _VERDICTS:
        for proposed in _VERDICTS + [None]:
            r = VD.monotone(old, proposed)
            if r == VD.CONFIRMED:
                assert old == VD.CONFIRMED, (old, proposed, r)
            assert proposed is None or r in (old, proposed)
            assert VD._STRENGTH.get(r, 0) <= VD._STRENGTH.get(old, 0), (old, proposed, r)


def test_screen_flags_single_class():
    c = _call("accuracy", 1.0, {"y_true": [1] * 10, "y_pred": [1] * 10})
    proposed, reason = RTG.screen("accuracy", c)
    assert proposed == VD.INVALIDATED and "single class" in reason


def test_screen_flags_trivial_baseline():
    # 90/10 majority; produced 0.90 == the majority-class baseline (a constant predictor matches it).
    c = _call("accuracy", 0.90, {"y_true": [0] * 90 + [1] * 10, "y_pred": [0] * 100})
    proposed, reason = RTG.screen("accuracy", c)
    assert proposed == VD.INVALIDATED and "baseline" in reason


def test_screen_flags_chance_auc_and_zero_r2():
    a = _call("roc_auc", 0.5, {"y_true": [0, 1, 0, 1], "y_score": [0.1, 0.2, 0.3, 0.4]})
    assert RTG.screen("roc_auc", a)[0] == VD.INVALIDATED
    r = _call("r2", 0.0, {"y_true": [1.0, 2.0, 3.0], "y_pred": [2.0, 2.0, 2.0]})
    assert RTG.screen("r2", r)[0] == VD.INVALIDATED


def test_screen_flags_degenerate_inputs():
    mism = _call("accuracy", 0.9, {"y_true": [0, 1, 0, 1, 1], "y_pred": [0, 1, 0, 1]})
    assert RTG.screen("accuracy", mism)[0] == VD.INCONCLUSIVE
    nan = _call("roc_auc", 0.95, {"y_true": [0, 1, 0, 1], "y_score": [0.1, 0.2, float("nan"), 0.4]})
    assert RTG.screen("roc_auc", nan)[0] == VD.INCONCLUSIVE


def test_screen_does_not_downgrade_legit_multi_split():
    """Regression (code-review finding): a repo that computes the SAME metric on train AND test (two distinct
    user-site values) must NOT be downgraded by the gate — binding already disambiguated the bound claim by
    split. The value-coincidence screen was removed precisely because it false-downgraded this common case."""
    test_call = _call("accuracy", 0.95, {"y_true": [0, 1] * 10, "y_pred": ([0, 1] * 9) + [1, 0]}, seq=0)
    train_call = _call("accuracy", 0.99, {"y_true": [0, 1] * 10, "y_pred": [0, 1] * 10}, seq=1)
    assert RTG.screen("accuracy", test_call, [test_call, train_call]) == (None, None)


def test_honest_confirmed_survives_screen():
    # balanced 2-class y_true (majority 0.5), produced 0.90 well above baseline, clean equal-length inputs.
    c = _call("accuracy", 0.90, {"y_true": [0, 1] * 10, "y_pred": ([0, 1] * 9) + [1, 0]})
    assert RTG.screen("accuracy", c) == (None, None)


def test_overlay_downgrades_a_regressed_confirm():
    """Simulate a primary-path regression: a CONFIRMED record sitting on a single-class computation. The
    overlay must catch and downgrade it."""
    claim = {"id": "c0", "metric": "accuracy", "value": "1.0"}
    c = _call("accuracy", 1.0, {"y_true": [1] * 10, "y_pred": [1] * 10})
    rec = {"id": "c0", "metric": "accuracy", "verdict": VD.CONFIRMED, "reason": "(regressed)",
           "validity": {"invalidating": [], "advisory": []}}
    P._apply_redteam_gate([rec], [claim], [[c]])
    assert rec["verdict"] == VD.INVALIDATED
    assert rec.get("redteam", {}).get("downgraded_from") == VD.CONFIRMED


def test_overlay_is_noop_on_honest_confirm():
    claim = {"id": "c0", "metric": "accuracy", "value": "0.9"}
    c = _call("accuracy", 0.90, {"y_true": [0, 1] * 10, "y_pred": ([0, 1] * 9) + [1, 0]})
    rec = {"id": "c0", "metric": "accuracy", "verdict": VD.CONFIRMED, "reason": "ok",
           "validity": {"invalidating": [], "advisory": []}}
    P._apply_redteam_gate([rec], [claim], [[c]])
    assert rec["verdict"] == VD.CONFIRMED and "redteam" not in rec
