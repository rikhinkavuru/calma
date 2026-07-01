"""The capture ladder (guide §B.1): Tier 1 (sys.monitoring) closes the __main__ capture gap the import-
patch tier can't reach, catches threaded metrics, and the whole thing stays fail-closed. Tier 2 (AST
decorator-append + __main__ exec) is the portable fallback with a round-trip determinism guard.

The franchise angle: a missed capture must fail CLOSED (no capture → INCONCLUSIVE), never a false confirm;
and a capture that reaches CONFIRMED must recompute to the claimed value from the REAL captured inputs.
"""
import sys

import pytest

import ast_capture  # noqa: E402  (capture/ on sys.path via conftest)
from runner.local_runner import run_local

_TARGETS = [{"target": "eval.my_metric", "metric": "accuracy",
             "inputs": {"y_true": "arg0", "y_pred": "arg1"}}]

_MAIN = (
    "def my_metric(y_true, y_pred):\n"
    "    return sum(1 for a, b in zip(y_true, y_pred) if a == b) / len(y_true)\n"
    "y_true = [0, 1, 1, 0, 1, 0, 1, 0]\n"
    "y_pred = [0, 1, 0, 0, 1, 0, 1, 1]\n"          # 6/8 correct
    "print('accuracy', my_metric(y_true, y_pred))\n"
)


def _repo(tmp_path, src):
    (tmp_path / "eval.py").write_text(src)
    return str(tmp_path)


@pytest.mark.skipif(sys.version_info < (3, 12), reason="sys.monitoring needs 3.12+")
def test_tier1_captures_main_defined_metric(tmp_path):
    """The core §B.1 fix: a metric defined+called in __main__ is captured by Tier 1 with its REAL inputs."""
    res = run_local(_repo(tmp_path, _MAIN), ["eval.py"], k=1, hooks="", targets=_TARGETS)
    assert res["meta"][0]["returncode"] == 0, res["meta"]
    calls = res["runs"][0]
    assert len(calls) == 1 and calls[0]["metric"] == "accuracy"
    assert calls[0]["inputs"]["y_true"] == [0, 1, 1, 0, 1, 0, 1, 0]
    assert calls[0]["inputs"]["y_pred"] == [0, 1, 0, 0, 1, 0, 1, 1]
    assert abs(calls[0]["result"] - 0.75) < 1e-9
    assert (res["hooks_armed"] or {}).get("target_tier") == "monitoring"


def test_legacy_import_patch_misses_main_defined_metric_but_fails_closed(tmp_path):
    """A/B: forcing the pre-3.12 import-patch tier, the __main__ function is unreachable — nothing is
    captured. The gap Tier 1 closes; critically it fails CLOSED (no capture), never a wrong number."""
    res = run_local(_repo(tmp_path, _MAIN), ["eval.py"], k=1, hooks="", targets=_TARGETS,
                    env_extra={"CALMA_CAPTURE_NOMON": "1"})
    assert res["meta"][0]["returncode"] == 0
    assert res["n_calls"][0] == 0                       # missed — exactly the documented gap
    assert (res["hooks_armed"] or {}).get("target_tier") == "import-patch"


@pytest.mark.skipif(sys.version_info < (3, 12), reason="sys.monitoring needs 3.12+")
def test_tier1_input_param_named_n_not_dropped(tmp_path):
    """Regression (code-review): a metric param named `n` (or site/sink/metric/...) must land in the captured
    inputs, not collide with record()'s reserved `n` sample-count param and get silently dropped."""
    src = (
        "def score(y_true, y_pred, n):\n"
        "    return sum(1 for a, b in zip(y_true, y_pred) if a == b) / n\n"
        "print('acc', score([0, 1, 1, 0], [0, 1, 0, 0], 4))\n"
    )
    specs = [{"target": "eval.score", "metric": "accuracy"}]    # NO inputs mapping → keyed by the repo's param names
    res = run_local(_repo(tmp_path, src), ["eval.py"], k=1, hooks="", targets=specs)
    assert res["n_calls"][0] == 1, res["meta"]
    inp = res["runs"][0][0]["inputs"]
    assert inp.get("n") == 4 and inp.get("y_true") == [0, 1, 1, 0]   # the `n` input survived (no collision drop)


@pytest.mark.skipif(sys.version_info < (3, 12), reason="sys.monitoring needs 3.12+")
def test_tier1_captures_threaded_metric(tmp_path):
    """sys.monitoring is per-interpreter (not per-thread like settrace), so a metric computed in a worker
    thread is still captured — the case settrace silently misses."""
    src = (
        "import threading\n"
        "def my_metric(y_true, y_pred):\n"
        "    return sum(1 for a, b in zip(y_true, y_pred) if a == b) / len(y_true)\n"
        "box = {}\n"
        "def work():\n"
        "    box['v'] = my_metric([0, 1, 1, 0], [0, 1, 1, 1])\n"
        "t = threading.Thread(target=work); t.start(); t.join()\n"
        "print('accuracy', box['v'])\n"
    )
    res = run_local(_repo(tmp_path, src), ["eval.py"], k=1, hooks="", targets=_TARGETS)
    assert res["n_calls"][0] == 1
    assert res["runs"][0][0]["metric"] == "accuracy"
    assert abs(res["runs"][0][0]["result"] - 0.75) < 1e-9


# ---- Tier 2: AST decorator-append + __main__ exec + round-trip guard ------------------------------
def test_ast_transform_appends_decorator_only_to_targets():
    src = "def foo(a, b):\n    return a + b\n\ndef bar():\n    return 1\n"
    tree, wrapped = ast_capture.transform(src, "<t>", {"foo"})
    assert wrapped == ["foo"]
    import ast as _ast
    fns = {n.name: n for n in _ast.walk(tree) if isinstance(n, _ast.FunctionDef)}
    assert len(fns["foo"].decorator_list) == 1 and not fns["bar"].decorator_list


def test_ast_run_transformed_captures_main_defined(tmp_path):
    p = tmp_path / "e.py"
    p.write_text("def acc(y_true, y_pred):\n    return sum(a == b for a, b in zip(y_true, y_pred)) / len(y_true)\n"
                 "print(acc([0, 1, 1, 0], [0, 1, 0, 0]))\n")
    caps = []
    specs = [{"target": "e.acc", "metric": "accuracy", "inputs": {"y_true": "arg0", "y_pred": "arg1"}}]
    ast_capture.run_transformed(str(p), specs, lambda m, v, sink=None, **i: caps.append((m, v, i)))
    assert caps and caps[0][0] == "accuracy" and caps[0][2]["y_true"] == [0, 1, 1, 0]


def test_ast_guard_passes_deterministic_discards_nondeterministic(tmp_path):
    specs = [{"target": "e.acc", "metric": "accuracy", "inputs": {"y_true": "arg0", "y_pred": "arg1"}}]
    det = tmp_path / "det.py"
    det.write_text("def acc(y_true, y_pred):\n    return sum(a == b for a, b in zip(y_true, y_pred)) / len(y_true)\n"
                   "print('%.4f' % acc([0, 1, 1, 0], [0, 1, 0, 0]))\n")
    caps, ok = ast_capture.capture_guarded(str(det), specs)
    assert ok and len(caps) == 1 and caps[0]["metric"] == "accuracy"
    nd = tmp_path / "nd.py"
    nd.write_text("import random\ndef acc(y_true, y_pred):\n    return random.random()\n"
                  "print(acc([0], [0]))\n")            # unseeded → two runs diverge → discard
    caps2, ok2 = ast_capture.capture_guarded(str(nd), specs)
    assert not ok2 and caps2 == []
