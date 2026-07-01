"""Features 2 / 7 / 10 — the un-foolability cluster, end to end through the in-sandbox re-invocation emitter
(capture.reinvoke) + the host judges (core.formula_diff / core.metamorphic / core.perturb). An honest formula
survives; a wrong formula (F2), an order-sensitive impostor (F7), and a hard-coded constant (F10) are each
caught — and all only ever DOWNGRADE a verdict, never mint one."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)
sys.path.insert(0, os.path.join(_SPIKE, "capture"))
sys.path.insert(0, os.path.join(_SPIKE, "fixtures"))

import pytest  # noqa: E402

import reinvoke  # noqa: E402
from core import diff as D  # noqa: E402
from core import formula_diff as FZ  # noqa: E402
from core import metamorphic as MM  # noqa: E402
from core import perturb as PB  # noqa: E402
from core import verdict as VD  # noqa: E402
from runner.local_runner import run_local  # noqa: E402


def _spec(fn, metric, mapping):
    return {"target": "fuzz_metrics." + fn, "metric": metric, "inputs": mapping}


_LABELS = {"y_true": "arg0", "y_pred": "arg1"}


def _cases(fn, metric, mapping):
    rec = reinvoke.fuzz_target(_spec(fn, metric, mapping), k=16, seed=7)
    assert rec is not None, "fuzz emitter produced no cases for %s" % fn
    return rec["cases"]


def test_honest_formula_is_not_flagged():
    cases = _cases("honest_accuracy", "accuracy", _LABELS)
    assert FZ.differential("accuracy", cases)["diverged"] is False
    assert MM.check_record("accuracy", cases)["invalidating"] is False
    assert PB.fabrication_from_fuzz(cases) is None


def test_wrong_formula_caught_by_differential():
    cases = _cases("wrong_accuracy", "accuracy", _LABELS)
    fd = FZ.differential("accuracy", cases)
    assert fd["diverged"] is True and fd["counterexample"] is not None


def test_hardcoded_constant_caught_by_fabrication():
    cases = _cases("cheat_accuracy", "accuracy", _LABELS)
    note = PB.fabrication_from_fuzz(cases)
    assert note and "does not depend on its inputs" in note
    # the differential also catches it (0.95 rarely equals a random accuracy)
    assert FZ.differential("accuracy", cases)["diverged"] is True


def test_order_sensitive_impostor_caught_by_metamorphic():
    cases = _cases("order_sensitive_accuracy", "accuracy", _LABELS)
    mm = MM.check_record("accuracy", cases)
    assert mm["invalidating"] is True
    assert any(v["tag"] == "perm_samples" for v in mm["violations"])


def test_honest_sharpe_matches_catalog():
    cases = _cases("honest_sharpe", "sharpe", {"returns": "arg0"})
    assert FZ.differential("sharpe", cases)["diverged"] is False
    assert MM.check_record("sharpe", cases)["invalidating"] is False


def _run(metric, produced, inputs, target, seq=0):
    return {"metric": metric, "result": produced, "inputs": inputs, "kwargs": {}, "user_site": True,
            "captured_full": True, "n": len(next(iter(inputs.values()))), "seq": seq,
            "sink": "target:fuzz_metrics." + target, "site": "r.py:%d" % (1 + seq)}


def test_diff_claim_downgrades_a_cheat_only_with_fuzz():
    """On the REAL captured input the cheat happens to be right (19/20 = 0.95), so without fuzz it CONFIRMS.
    The fuzz record proves the function is a constant → INVALIDATED. Demonstrates the downgrade is real."""
    yt = [0, 1] * 10
    yp = list(yt)
    yp[0] = 1 - yp[0]                        # exactly one wrong → accuracy 19/20 = 0.95
    claim = {"id": "c0", "metric": "accuracy", "value": "0.95"}
    call = _run("accuracy", 0.95, {"y_true": yt, "y_pred": yp}, "cheat_accuracy")
    runs = [[call], [dict(call)]]           # k=2 stable → CONFIRMED baseline
    assert D.diff_claim(claim, runs)["verdict"] == VD.CONFIRMED
    fuzz = [reinvoke.fuzz_target(_spec("cheat_accuracy", "accuracy", _LABELS), k=16, seed=7)]
    assert D.diff_claim(claim, runs, fuzz=fuzz)["verdict"] == VD.INVALIDATED


def test_diff_claim_leaves_honest_confirmed_with_fuzz():
    yt = [0, 1] * 10
    yp = list(yt)
    yp[0] = 1 - yp[0]
    claim = {"id": "c0", "metric": "accuracy", "value": "0.95"}
    call = _run("accuracy", 0.95, {"y_true": yt, "y_pred": yp}, "honest_accuracy")
    runs = [[call], [dict(call)]]
    fuzz = [reinvoke.fuzz_target(_spec("honest_accuracy", "accuracy", _LABELS), k=16, seed=7)]
    assert D.diff_claim(claim, runs, fuzz=fuzz)["verdict"] == VD.CONFIRMED


def test_sklearn_bound_claim_ignores_another_targets_fuzz():
    """Regression: a legit sklearn-bound accuracy claim must NOT inherit a hand-rolled cheat target's fuzz
    divergence just because they share the metric name (that would be a false-INVALIDATE)."""
    yt = [0, 1] * 10
    yp = list(yt)
    yp[0] = 1 - yp[0]                        # 0.95 accuracy, legit
    claim = {"id": "c0", "metric": "accuracy", "value": "0.95"}
    sk_call = {"metric": "accuracy", "result": 0.95, "inputs": {"y_true": yt, "y_pred": yp}, "kwargs": {},
               "user_site": True, "captured_full": True, "n": 20, "seq": 0,
               "sink": "sklearn.metrics.accuracy_score", "site": "r.py:1"}   # NOT a target sink
    # a diverging fuzz record for a DIFFERENT (cheat) target of the same metric
    fuzz = [reinvoke.fuzz_target(_spec("wrong_accuracy", "accuracy", _LABELS), k=16, seed=7)]
    rec = D.diff_claim(claim, [[sk_call], [dict(sk_call)]], fuzz=fuzz)
    assert rec["verdict"] == VD.CONFIRMED    # the sklearn claim is untouched by the cheat target's fuzz


def test_unfuzzable_target_leaves_verdict_unchanged():
    assert reinvoke.fuzz_target(_spec("does_not_exist", "accuracy", _LABELS)) is None
    yt = [0, 1] * 10
    yp = list(yt)
    yp[0] = 1 - yp[0]
    claim = {"id": "c0", "metric": "accuracy", "value": "0.95"}
    call = _run("accuracy", 0.95, {"y_true": yt, "y_pred": yp}, "honest_accuracy")
    assert D.diff_claim(claim, [[call], [dict(call)]], fuzz=None)["verdict"] == VD.CONFIRMED


@pytest.mark.skipif(sys.version_info < (3, 12), reason="sys.monitoring needs 3.12+")
def test_end_to_end_runner_emits_and_reads_fuzz(tmp_path):
    """The real path: a __main__-defined constant metric runs in a subprocess, the atexit emitter writes
    `.fuzz`, run_local reads it back, and the host fabrication signal fires — proving the whole plumbing."""
    src = (
        "import random\n"
        "def score(y_true, y_pred):\n"
        "    return 0.8\n"                       # hard-coded constant, ignores inputs
        "rng = random.Random(1)\n"
        "y_true = [rng.randint(0, 1) for _ in range(60)]\n"
        "y_pred = [yt if rng.random() < 0.8 else 1 - yt for yt in y_true]\n"
        "print('accuracy', score(y_true, y_pred))\n"
    )
    (tmp_path / "eval.py").write_text(src)
    targets = [{"target": "eval.score", "metric": "accuracy", "inputs": {"y_true": "arg0", "y_pred": "arg1"}}]
    res = run_local(str(tmp_path), ["eval.py"], k=1, hooks="", targets=targets, fuzz=True)
    assert res["ran_ok"], res["meta"]
    assert res.get("fuzz"), "the .fuzz sibling was not emitted / read back"
    rec = res["fuzz"][0]
    assert rec["metric"] == "accuracy" and rec["target"] == "eval.score"
    assert PB.fabrication_from_fuzz(rec["cases"]) is not None       # constant across all random inputs
    assert FZ.differential("accuracy", rec["cases"])["diverged"] is True
