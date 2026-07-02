"""The FCR firewall for the repo-assessment orchestrator (build plan §0, §7 Phase 0). Mirrors the
edges/core and known-value firewall discipline: the orchestrator may only change HOW a repo is made runnable
and run — it can NEVER touch a claim value, the captured computation, the binding, the recompute, or the
verdict. This is enforced structurally and checked here, so every reviewer can verify the one sentence that
makes handing an LLM agent a toolbox safe for a correctness product.

Three structural assertions:
  1. No module under ``orchestrator/`` imports ``core.verdict`` / ``core.diff`` (it hands off typed data; the
     unchanged pipeline runs the diff).
  2. The live tool registry contains zero verdict-affecting tools, and ``register`` refuses to create one.
  3. The typed hand-off (``RunApproach`` / ``RunResult``) exposes no verdict / binding / recompute channel —
     if it isn't in ``RunResult.runs`` (the repo's OWN captured computations) it cannot reach a verdict.
"""
import ast
import importlib
import os
import pkgutil
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

import orchestrator  # noqa: E402
from orchestrator import registry as REG  # noqa: E402
from orchestrator import types as TY  # noqa: E402

_ORCH_DIR = os.path.join(_SPIKE, "orchestrator")
_FORBIDDEN_IMPORTS = {"core.verdict", "core.diff"}


def _orchestrator_py_files():
    for root, _dirs, files in os.walk(_ORCH_DIR):
        for fn in files:
            if fn.endswith(".py"):
                yield os.path.join(root, fn)


def _imported_paths(py_path):
    """Every dotted module path a file imports (both `import a.b` and `from a.b import c` → 'a.b' and 'a.b.c')."""
    try:
        tree = ast.parse(open(py_path, errors="replace").read(), py_path)
    except (OSError, SyntaxError):
        return set()
    paths = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                paths.add(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            paths.add(node.module)
            for a in node.names:
                paths.add(node.module + "." + a.name)
    return paths


def _import_all_orchestrator_submodules():
    """Force every @register decorator to run so the registry reflects the whole package, not just what a
    prior test happened to import."""
    for _finder, name, _ispkg in pkgutil.iter_modules(orchestrator.__path__, "orchestrator."):
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001 — an optional-dep tool module that won't import is fine here; the
            pass          # firewall only cares about what DID register, and about source-level imports.


def test_no_orchestrator_module_imports_the_verdict_core():
    for py in _orchestrator_py_files():
        imported = _imported_paths(py)
        bad = imported & _FORBIDDEN_IMPORTS
        assert not bad, "%s imports the verdict core %r — the orchestrator must hand off typed data, not " \
                        "run the diff/verdict (FCR firewall §0)" % (os.path.relpath(py, _SPIKE), sorted(bad))


def test_registry_has_zero_verdict_affecting_tools():
    _import_all_orchestrator_submodules()
    for t in REG.tools():
        assert t.touches_verdict is False, "registered tool %r declares touches_verdict=True" % t.name
        assert t.kind in REG.KINDS, "tool %r has bad kind %r" % (t.name, t.kind)
        low = t.name.lower()
        for bad in REG._VERDICT_VOCAB:
            assert bad not in low, "tool %r name collides with verdict vocabulary %r" % (t.name, bad)


def test_register_structurally_refuses_a_verdict_tool():
    import pytest

    # touches_verdict=True is rejected at registration — it can never reach runtime.
    with pytest.raises(ValueError):
        REG.register("harmless_static", kind="static", cost="free", summary="x", touches_verdict=True)(lambda: None)
    # a verdict-named tool is rejected even with touches_verdict False.
    with pytest.raises(ValueError):
        REG.register("compute_verdict", kind="static", cost="free", summary="x")(lambda: None)
    with pytest.raises(ValueError):
        REG.register("do_binding", kind="exec", cost="cheap", summary="x")(lambda: None)


def test_call_gateway_never_executes_an_unknown_name():
    import pytest

    # the agent proposes a NAME; the gateway refuses anything not in the registry (no arbitrary execution).
    with pytest.raises(KeyError):
        REG.call("definitely_not_a_registered_tool_" + "x" * 8)


def test_run_approach_has_no_verdict_or_binding_field():
    fields = set(TY.RunApproach.__dataclass_fields__)
    assert fields == {"runner", "builder", "entry", "deps", "capture_targets", "env", "notes", "confidence"}
    for banned in ("verdict", "binding", "recomputed", "recompute", "claimed", "produced", "value"):
        assert banned not in fields, "RunApproach must not carry a %r channel" % banned


def test_run_result_carries_only_run_artifacts_no_verdict():
    fields = set(TY.RunResult.__dataclass_fields__)
    assert fields == {"ran_ok", "runs", "meta", "cost", "source_modified", "approach", "trace"}
    for banned in ("verdict", "binding", "recomputed", "confirmed", "claim"):
        assert banned not in fields, "RunResult must not carry a %r channel (it feeds runs → the diff)" % banned
    # the hand-off dict the pipeline consumes exposes no verdict key either.
    d = TY.RunResult(ran_ok=True, runs=[[]]).to_run_dict()
    for banned in ("verdict", "binding", "recomputed", "confirmed"):
        assert banned not in d


def test_run_approach_from_dict_drops_unknown_and_injected_keys():
    # an injected extra field (e.g. a smuggled "verdict") is silently dropped, never set.
    a = TY.RunApproach.from_dict({"runner": "local", "entry": ["eval.py"], "verdict": "CONFIRMED",
                                  "touches_verdict": True})
    assert not hasattr(a, "verdict")
    assert a.entry == ["eval.py"]
    # a bad shape raises SchemaError (treated like a failed run upstream, never a crash).
    import pytest
    with pytest.raises(TY.SchemaError):
        TY.RunApproach.from_dict({"runner": "not-a-runner"})
