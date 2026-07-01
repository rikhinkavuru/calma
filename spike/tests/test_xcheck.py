"""Feature 17 — differential recompute. Two independent recompute paths must agree to trust the recompute:
disagreement fails closed (degenerate → REPRODUCED-ONLY), agreement changes nothing (never an upgrade)."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from core import catalog as C  # noqa: E402
from core import diff as D  # noqa: E402
from core import tolerance as T  # noqa: E402
from core import verdict as VD  # noqa: E402
from synth import xcheck as X  # noqa: E402


def _acc_call(acc=0.9, n=100):
    correct = round(acc * n)
    yt = [i % 2 for i in range(n)]
    yp = list(yt)
    for i in range(n - correct):
        yp[i] = 1 - yp[i]
    real = sum(1 for a, b in zip(yt, yp) if a == b) / n
    return {"metric": "accuracy", "result": real, "inputs": {"y_true": yt, "y_pred": yp}, "kwargs": {},
            "user_site": True, "captured_full": True, "n": n, "seq": 0,
            "sink": "sklearn.metrics.accuracy_score", "site": "r.py:1"}


def test_crosscheck_agree_and_disagree():
    inputs = {"y_true": [0, 1, 0, 1], "y_pred": [0, 1, 0, 1]}
    agree = X.crosscheck("accuracy", inputs, {}, {"a": C.recompute, "b": C.recompute}, T.close)
    assert agree["agree"] and agree["n_paths"] == 2
    disagree = X.crosscheck("accuracy", inputs, {},
                            {"a": C.recompute, "b": lambda m, i, k: {**C.recompute(m, i, k), "value": 0.1}}, T.close)
    assert not disagree["agree"]


def test_crosscheck_single_path_is_vacuously_agree():
    r = X.crosscheck("accuracy", {"y_true": [0, 1], "y_pred": [0, 1]}, {}, {"a": C.recompute}, T.close)
    assert r["agree"] and r["n_paths"] == 1


def test_reconcile_downgrades_on_disagreement():
    rc = {"value": 0.9, "degenerate": False, "note": "", "terms": {}}
    assert X.reconcile(rc, 0.9, T.close) is rc                    # agreement → unchanged object
    bad = X.reconcile(rc, 0.5, T.close)
    assert bad["degenerate"] and "disagree" in bad["note"]


def test_diff_shadow_disagreement_downgrades_confirm():
    call = _acc_call(0.9)
    claim = {"metric": "accuracy", "value": "%.4f" % call["result"]}
    runs = [[call], [dict(call)]]
    assert D.diff_claim(claim, runs)["verdict"] == VD.CONFIRMED
    buggy = lambda m, i, k: {**C.recompute(m, i, k), "value": C.recompute(m, i, k)["value"] + 0.1}  # noqa: E731
    rec = D.diff_claim(claim, runs, shadow=buggy)
    assert rec["verdict"] != VD.CONFIRMED and rec["xcheck"]["agree"] is False


def test_diff_shadow_agreement_preserves_confirm():
    call = _acc_call(0.9)
    claim = {"metric": "accuracy", "value": "%.4f" % call["result"]}
    rec = D.diff_claim(claim, [[call], [dict(call)]], shadow=C.recompute)
    assert rec["verdict"] == VD.CONFIRMED and rec["xcheck"]["agree"] is True
