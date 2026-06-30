"""scope-the-claim: an ambiguous binding exposes the candidate computations by SITE (semantic identity,
never value), and re-verifying with bind={site} binds exactly that one. The franchise guarantee: you can't
'confirm' a misreport by picking the computation whose value matches — picking the wrong one REFUTES.
"""
from core import diff as D
from core import verdict as VD


def _acc_inputs(n, correct):
    yt = [i % 2 for i in range(n)]            # balanced 2-class (majority baseline 0.5, no validity flag)
    yp = list(yt)
    for i in range(n - correct):
        yp[i] = 1 - yp[i]
    return {"y_true": yt, "y_pred": yp}


def _call(site, n, correct, seq):
    return {"metric": "accuracy", "result": correct / n, "inputs": _acc_inputs(n, correct), "kwargs": {},
            "user_site": True, "captured_full": True, "n": n, "seq": seq,
            "sink": "sklearn.metrics.accuracy_score", "site": site}


def _runs():
    train = _call("model.py:10", 200, 180, 0)   # train accuracy 0.90
    test = _call("model.py:20", 50, 48, 1)       # held-out accuracy 0.96
    return [[train, test], [dict(train), dict(test)]]


def test_ambiguous_exposes_scope_options_by_site_without_values():
    rec = D.diff_claim({"metric": "accuracy", "value": "0.96"}, _runs())
    assert rec["verdict"] == VD.INCONCLUSIVE
    opts = rec["binding"]["candidates"]
    assert {o["site"] for o in opts} == {"model.py:10", "model.py:20"}
    # the franchise: options carry SEMANTIC identity (site/sink/n) but NEVER a value/result to cheat with
    assert all("value" not in o and "result" not in o for o in opts)


def test_scoping_to_the_right_site_confirms_wrong_site_refutes():
    runs = _runs()
    # the claim is about the held-out eval (model.py:20, 0.96): scope there -> CONFIRMED
    assert D.diff_claim({"metric": "accuracy", "value": "0.96", "bind": {"site": "model.py:20"}},
                        runs)["verdict"] == VD.CONFIRMED
    # scope to the TRAIN computation (0.90): claim 0.96 != produced 0.90 -> REFUTED (no cheating by picking)
    assert D.diff_claim({"metric": "accuracy", "value": "0.96", "bind": {"site": "model.py:10"}},
                        runs)["verdict"] == VD.REFUTED


def test_no_scope_options_when_unique():
    # a single computation needs no scoping
    one = [[_call("m.py:1", 100, 90, 0)], [_call("m.py:1", 100, 90, 0)]]
    rec = D.diff_claim({"metric": "accuracy", "value": "0.90"}, one)
    assert rec["verdict"] == VD.CONFIRMED
    assert not rec["binding"].get("candidates")
