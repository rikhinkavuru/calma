"""Phase 2 — the bounded execute/observe/revise loop + ranking. Fully hermetic: effectors are injected fakes,
no sandbox, no API key (conftest deletes it). Covers the three SOTA hardenings (oscillation, budget-before-
call, C3 honest give-up) and static-first-vs-LLM ranking."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from orchestrator import orchestrate as O  # noqa: E402
from orchestrator.types import RunApproach, RunResult  # noqa: E402


def _run_result(ran_ok=False, captured=False, stderr=""):
    runs = [[{"metric": "accuracy", "result": 0.9}]] if captured else [[]]
    meta = [{"stderr_tail": stderr}]
    return RunResult(ran_ok=ran_ok, runs=runs if ran_ok else [], meta=meta)


# ── success path ──────────────────────────────────────────────────────────────────────────────────────────────
def test_execute_returns_first_captured_success():
    calls = []

    def run_approach(a):
        calls.append(a.entry)
        return _run_result(ran_ok=True, captured=True)

    a = RunApproach(entry=["eval.py"])
    res = O.execute([a], run_approach)
    assert res.ran_ok and res.runs and res.runs[0]
    assert len(calls) == 1                                # stopped at first success
    assert res.approach.entry == ["eval.py"]


# ── revise: missing-module heal ───────────────────────────────────────────────────────────────────────────────
def test_execute_revises_on_missing_module():
    seen = {"n": 0}

    def run_approach(a):
        seen["n"] += 1
        if "scikit-learn" in a.deps:
            return _run_result(ran_ok=True, captured=True)
        return _run_result(ran_ok=False, captured=False,
                           stderr="ModuleNotFoundError: No module named 'sklearn'")

    a = RunApproach(entry=["eval.py"], deps=[])
    res = O.execute([a], run_approach)
    assert res.ran_ok
    assert "scikit-learn" in res.approach.deps            # B4 import→dist heal applied
    assert seen["n"] == 2                                 # failed once, healed, succeeded
    assert any(s.get("event") == "run" for s in res.trace)


# ── C3: honest give-up, never a fabricated entrypoint ─────────────────────────────────────────────────────────
def test_execute_gives_up_honestly_when_nothing_runs():
    def run_approach(a):
        return _run_result(ran_ok=False, captured=False, stderr="some unfixable error")

    res = O.execute([RunApproach(entry=["a.py"]), RunApproach(entry=["b.py"])], run_approach)
    assert res.ran_ok is False
    assert res.runs == []                                 # no fabricated eval.py capture (C3)
    assert res.trace                                       # but a full audit trace


# ── best-effort: ran but captured nothing ─────────────────────────────────────────────────────────────────────
def test_execute_keeps_best_effort_when_ran_without_capture():
    def run_approach(a):
        return _run_result(ran_ok=True, captured=False)   # ran, but nothing hooked

    res = O.execute([RunApproach(entry=["a.py"])], run_approach)
    assert res.ran_ok is True                              # returned the run that at least executed
    assert not (res.runs and res.runs[0])                 # honestly reports no capture (→ DISCOVERED downstream)


# ── oscillation / no-progress detection ───────────────────────────────────────────────────────────────────────
def test_execute_detects_oscillation():
    calls = {"n": 0}

    def run_approach(a):
        calls["n"] += 1
        return _run_result(ran_ok=False, stderr="err")

    # a malicious/looping revise that always proposes the SAME approach
    def revise(result, approach, history):
        return RunApproach(entry=list(approach.entry), deps=list(approach.deps))

    res = O.execute([RunApproach(entry=["a.py"])], run_approach, revise=revise)
    assert res.ran_ok is False
    # the same-key revision is caught: at most the initial run + one revise attempt, never an infinite loop
    assert calls["n"] <= 2
    assert any(s.get("event") in ("oscillation", "no-progress") for s in res.trace)


# ── budget: step cap + checked BEFORE the call ────────────────────────────────────────────────────────────────
def test_budget_checked_before_effector_runs():
    calls = {"n": 0}

    def run_approach(a):
        calls["n"] += 1
        return _run_result(ran_ok=False)

    b = O.Budget(step_cap=0)                               # exhausted before any call
    res = O.execute([RunApproach(entry=["a.py"])], run_approach, budget=b)
    assert calls["n"] == 0                                 # never paid for a step past the ceiling
    assert res.ran_ok is False
    assert any(s.get("event") == "budget-stop" for s in res.trace)


def test_budget_step_cap_bounds_total_work():
    calls = {"n": 0}

    def run_approach(a):
        calls["n"] += 1
        return _run_result(ran_ok=False, stderr="ModuleNotFoundError: No module named 'x%d'" % calls["n"])

    # a revise that always adds a new dep would loop forever without the step cap
    def revise(result, approach, history):
        return RunApproach(entry=list(approach.entry), deps=approach.deps + ["pkg%d" % len(approach.deps)])

    b = O.Budget(step_cap=3, max_approaches=4)
    res = O.execute([RunApproach(entry=["a.py"])], run_approach, revise=revise, budget=b)
    assert calls["n"] <= 3
    assert res.ran_ok is False


def test_budget_wall_deadline():
    def run_approach(a):
        return _run_result(ran_ok=False)
    b = O.Budget(time_left=lambda: -1)                    # already past deadline
    calls = {"n": 0}

    def run(a):
        calls["n"] += 1
        return _run_result(ran_ok=False)
    O.execute([RunApproach(entry=["a.py"])], run, budget=b)
    assert calls["n"] == 0


# ── ranking: static-first vs one LLM turn ─────────────────────────────────────────────────────────────────────
def test_build_static_approaches(tmp_path):
    (tmp_path / "eval.py").write_text("import sklearn\nif __name__=='__main__':\n    print(1)\n")
    (tmp_path / "requirements.txt").write_text("scikit-learn\n")
    from orchestrator.assess import assess
    p = assess(str(tmp_path))
    apps = O.build_static_approaches(p, str(tmp_path))
    assert apps and apps[0].entry == ["eval.py"]
    assert "scikit-learn" in apps[0].deps
    assert apps[0].builder in ("venv-pip", "declared")


def test_rank_static_only_when_unambiguous(tmp_path, monkeypatch):
    (tmp_path / "eval.py").write_text("if __name__=='__main__':\n    print(1)\n")   # single obvious entry
    (tmp_path / "README.md").write_text("Run `python eval.py`.\n")
    from orchestrator.assess import assess
    p = assess(str(tmp_path))
    called = {"planner": 0}
    import planner
    monkeypatch.setattr(planner, "plan_repo", lambda *a, **k: called.__setitem__("planner", 1))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")          # key present, but unambiguous → still no LLM
    ranked = O.rank_approaches(p, str(tmp_path))
    assert called["planner"] == 0
    assert ranked[0].entry == ["eval.py"]


def test_rank_calls_llm_when_ambiguous(tmp_path, monkeypatch):
    # two near-tied scripts, neither an obvious winner → ambiguous → the reused planner turn runs
    (tmp_path / "run_a.py").write_text("import numpy\nif __name__=='__main__':\n    print(1)\n")
    (tmp_path / "run_b.py").write_text("import numpy\nif __name__=='__main__':\n    print(2)\n")
    from orchestrator.assess import assess
    p = assess(str(tmp_path))
    import planner
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(planner, "plan_repo",
                        lambda *a, **k: {"entry": ["run_b.py"], "pip_install": ["numpy"],
                                         "targets": [], "notes": "b is the eval", "confidence": 0.9})
    ranked = O.rank_approaches(p, str(tmp_path))
    assert ranked[0].entry == ["run_b.py"]
    assert ranked[0].notes.startswith("llm-ranked")


# ── orchestrate() attaches the assessment report ──────────────────────────────────────────────────────────────
def test_orchestrate_attaches_report(tmp_path):
    (tmp_path / "eval.py").write_text("import sklearn\nif __name__=='__main__':\n    print(1)\n")

    def run_approach(a):
        return _run_result(ran_ok=True, captured=True)

    res = O.orchestrate(str(tmp_path), run_approach, use_llm=False)
    assert res.ran_ok
    assert isinstance(res.cost.get("assessment"), list) and res.cost["assessment"]
    assert res.cost.get("fingerprint")
