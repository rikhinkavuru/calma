"""Predictions-synthesis fallback (opt-in): when NO entrypoint captures a number, synthesize a predict-and-dump
driver and recompute the metric INDEPENDENTLY from the predictions it writes. FCR: the driver is a source
modification → verdict capped at REPRODUCED-ONLY; a synthesized harness can never CONFIRM."""
import json
import os

import planner
from orchestrator import orchestrate as ORCH
from orchestrator.types import RunResult


# ── planner.plan_predictions: validation gates ────────────────────────────────────────────────────────────────
def _stub_model(monkeypatch, payload):
    monkeypatch.setattr(planner, "_call_model",
                        lambda *a, **k: None if payload is None else json.dumps(payload))


def test_plan_predictions_returns_driver(tmp_path, monkeypatch):
    (tmp_path / "model.py").write_text("x = 1\n")
    _stub_model(monkeypatch, {"driver": "open('calma_predictions.csv','w').write('y_true,y_pred\\n1,1\\n')",
                              "metric": "accuracy", "confidence": 0.8})
    out = planner.plan_predictions(str(tmp_path))
    assert out and out["metric"] == "accuracy" and out["confidence"] == 0.8
    assert "calma_predictions.csv" in out["driver"]


def test_plan_predictions_rejects_driver_that_never_writes_predictions(tmp_path, monkeypatch):
    (tmp_path / "model.py").write_text("x = 1\n")
    _stub_model(monkeypatch, {"driver": "print('hello')", "metric": "accuracy", "confidence": 0.9})
    assert planner.plan_predictions(str(tmp_path)) is None      # must write calma_predictions.csv


def test_plan_predictions_rejects_runaway_driver(tmp_path, monkeypatch):
    (tmp_path / "model.py").write_text("x = 1\n")
    big = "calma_predictions.csv" + "#" * 9000
    _stub_model(monkeypatch, {"driver": big, "metric": "f1", "confidence": 0.9})
    assert planner.plan_predictions(str(tmp_path)) is None


def test_plan_predictions_none_when_model_unavailable(tmp_path, monkeypatch):
    (tmp_path / "model.py").write_text("x = 1\n")
    _stub_model(monkeypatch, None)
    assert planner.plan_predictions(str(tmp_path)) is None


# ── orchestrate synthesis wiring: writes the driver, runs it, caps via source_modified ──────────────────────────
def _profile(tmp_path):
    from orchestrator.assess import assess
    return assess(str(tmp_path))


def test_synthesis_off_by_default(tmp_path, monkeypatch):
    """Default (synthesize=False): no driver written, no planner call — the heuristic path is untouched."""
    called = {"n": 0}
    monkeypatch.setattr(planner, "plan_predictions", lambda *a, **k: called.__setitem__("n", called["n"] + 1))

    def fake_effector(appr):
        return RunResult(ran_ok=False, runs=[], meta=[{"returncode": 1}], approach=appr, source_modified=[])

    ORCH.orchestrate(str(tmp_path), fake_effector, use_llm=False)   # synthesize defaults False
    assert called["n"] == 0
    assert not os.path.exists(os.path.join(tmp_path, "calma_eval.py"))


def test_synthesis_writes_driver_and_marks_source_modified(tmp_path, monkeypatch):
    """synthesize=True + nothing captured → driver written, run, and recorded in source_modified (the cap)."""
    (tmp_path / "model.py").write_text("x = 1\n")
    monkeypatch.setattr(planner, "plan_predictions",
                        lambda *a, **k: {"driver": "open('calma_predictions.csv','w').close()",
                                         "metric": "accuracy", "confidence": 0.9})

    def fake_effector(appr):
        # the synthesized driver "ran" and produced predictions (captured nothing itself — that's expected)
        return RunResult(ran_ok=True, runs=[[]], meta=[{"returncode": 0}], approach=appr, source_modified=[])

    res = ORCH.orchestrate(str(tmp_path), fake_effector, use_llm=False, synthesize=True)
    assert os.path.exists(os.path.join(tmp_path, "calma_eval.py"))
    assert "calma_eval.py" in res.source_modified              # guarantees REPRODUCED-ONLY cap downstream
    assert res.approach is not None and res.approach.entry == ["calma_eval.py"]


def test_synthesis_skipped_when_low_confidence(tmp_path, monkeypatch):
    (tmp_path / "model.py").write_text("x = 1\n")
    monkeypatch.setattr(planner, "plan_predictions",
                        lambda *a, **k: {"driver": "open('calma_predictions.csv','w').close()",
                                         "metric": "accuracy", "confidence": 0.3})   # below 0.5 gate

    def fake_effector(appr):
        return RunResult(ran_ok=False, runs=[], meta=[{"returncode": 1}], approach=appr, source_modified=[])

    res = ORCH.orchestrate(str(tmp_path), fake_effector, use_llm=False, synthesize=True)
    assert not os.path.exists(os.path.join(tmp_path, "calma_eval.py"))
    assert not res.ran_ok


def test_synthesis_not_reached_when_a_number_was_captured(tmp_path, monkeypatch):
    """If a real entrypoint already captured a number, synthesis must NOT fire (no wasted driver / no cap)."""
    (tmp_path / "run.py").write_text("print(1)\n")
    called = {"n": 0}
    monkeypatch.setattr(planner, "plan_predictions", lambda *a, **k: called.__setitem__("n", called["n"] + 1))

    def fake_effector(appr):
        return RunResult(ran_ok=True, runs=[[{"result": 0.9}]], meta=[{"returncode": 0}],
                         approach=appr, source_modified=[])

    res = ORCH.orchestrate(str(tmp_path), fake_effector, use_llm=False, synthesize=True)
    assert called["n"] == 0                                     # captured → synthesis skipped
    assert "calma_eval.py" not in (res.source_modified or [])


def test_synthesis_skipped_when_repo_commits_predictions(tmp_path, monkeypatch):
    """A repo that already commits a real predictions file must be verified against its OWN artifact — synthesis
    would waste a run AND cap the legitimate CONFIRMED to REPRODUCED-ONLY (source_modified caps all affirmatives)."""
    (tmp_path / "model.py").write_text("x = 1\n")
    (tmp_path / "predictions.csv").write_text("y_true,y_pred\n1,1\n0,0\n")   # a genuine committed artifact
    called = {"n": 0}
    monkeypatch.setattr(planner, "plan_predictions", lambda *a, **k: called.__setitem__("n", called["n"] + 1))

    def fake_effector(appr):
        return RunResult(ran_ok=False, runs=[], meta=[{"returncode": 1}], approach=appr, source_modified=[])

    ORCH.orchestrate(str(tmp_path), fake_effector, use_llm=False, synthesize=True)
    assert called["n"] == 0                                     # committed predictions present → synthesis skipped
    assert not os.path.exists(os.path.join(tmp_path, "calma_eval.py"))


def test_purge_reserved_drops_stale_artifacts(tmp_path):
    """Reserved Calma artifacts left by a prior synthesis run on a REUSED checkout are purged at orchestrate
    start, so a later non-synthesis run can never read a stale calma_predictions.csv as a committed artifact."""
    (tmp_path / "calma_eval.py").write_text("# stale\n")
    (tmp_path / "calma_predictions.csv").write_text("y_true,y_pred\n1,0\n")   # stale AI output from a prior run

    def fake_effector(appr):
        return RunResult(ran_ok=False, runs=[], meta=[{"returncode": 1}], approach=appr, source_modified=[])

    ORCH.orchestrate(str(tmp_path), fake_effector, use_llm=False)   # synthesize off → must not consume stale files
    assert not os.path.exists(os.path.join(tmp_path, "calma_eval.py"))
    assert not os.path.exists(os.path.join(tmp_path, "calma_predictions.csv"))
