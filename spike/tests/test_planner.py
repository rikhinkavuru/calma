"""AI run-plan pre-stage: it proposes how to RUN a repo, and the proposal is validated before use. The model
call is stubbed — no network, no key needed. The load-bearing checks are the guardrails: a hallucinated
entrypoint is dropped, and the plan never reaches the recompute/verdict path."""
import json
import sys


import planner as PLAN
import pipeline as PIPE
from core import verdict as VD


def _stub(monkeypatch, payload):
    """Make the model return a fixed JSON plan (or None), with no SDK / network."""
    monkeypatch.setattr(PLAN, "_call_model",
                        lambda ctx, model: None if payload is None else json.dumps(payload))


def test_valid_plan_is_parsed_and_entry_kept_when_it_exists(tmp_path, monkeypatch):
    (tmp_path / "run_benchmark.py").write_text("print('hi')\n")
    _stub(monkeypatch, {"entrypoint": ["run_benchmark.py", "--all"], "pip_install": ["numpy", "lightgbm"],
                        "python_version": "3.11", "data_needed": "genomic_benchmarks (auto-downloaded)",
                        "notes": "k-mer + LightGBM genomics benchmark", "confidence": 0.9})
    plan = PLAN.plan_repo(str(tmp_path))
    assert plan["entry"] == ["run_benchmark.py", "--all"]        # exists → trusted
    assert plan["pip_install"] == ["numpy", "lightgbm"]
    assert plan["python_version"] == "3.11" and plan["confidence"] == 0.9


def test_hallucinated_entrypoint_is_dropped(tmp_path, monkeypatch):
    """THE guardrail: an entrypoint the model invented that doesn't exist in the repo must NOT be trusted —
    it's dropped so the deterministic detector takes over. A made-up entry is worse than none."""
    (tmp_path / "eval.py").write_text("print('hi')\n")
    _stub(monkeypatch, {"entrypoint": ["totally_made_up.py"], "pip_install": [], "python_version": "",
                        "data_needed": "", "notes": "x", "confidence": 0.8})
    plan = PLAN.plan_repo(str(tmp_path))
    assert plan["entry"] is None                                  # dropped → caller keeps its heuristics


def test_module_entrypoint_form_accepted(tmp_path, monkeypatch):
    _stub(monkeypatch, {"entrypoint": ["-m", "pkg.eval"], "pip_install": [], "python_version": "",
                        "data_needed": "", "notes": "x", "confidence": 0.5})
    assert PLAN.plan_repo(str(tmp_path))["entry"] == ["-m", "pkg.eval"]


def test_no_key_or_error_returns_none(tmp_path, monkeypatch):
    _stub(monkeypatch, None)                                       # e.g. no ANTHROPIC_API_KEY
    assert PLAN.plan_repo(str(tmp_path)) is None                   # → pipeline falls back to heuristics


def test_malformed_model_output_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(PLAN, "_call_model", lambda ctx, model: "not json at all")
    assert PLAN.plan_repo(str(tmp_path)) is None


def test_pipeline_uses_the_proposed_entrypoint(tmp_path, monkeypatch):
    """End-to-end: the plan's entrypoint drives the run. Two scripts, no README/known name — the heuristic
    would not reliably pick the eval; the plan points straight at it and the number CONFIRMS. Proves the plan
    is consumed by the run path — and only there (the verdict still comes from the deterministic recompute)."""
    (tmp_path / "helper.py").write_text("if __name__ == '__main__':\n    print('nothing useful')\n")
    (tmp_path / "the_eval.py").write_text(
        "import numpy as np\nfrom sklearn.metrics import accuracy_score\n"
        "rng = np.random.default_rng(0)\ny = rng.integers(0,2,200)\n"
        "p = np.where(rng.random(200) < 0.2, 1-y, y)\nprint('accuracy=%.4f' % accuracy_score(y,p))\n")
    monkeypatch.setattr(PLAN, "plan_repo", lambda repo_dir: {
        "entry": ["the_eval.py"], "pip_install": None, "python_version": None,
        "data_needed": "", "notes": "seeded accuracy eval", "confidence": 0.95})

    res = PIPE.verify_repo(str(tmp_path), PIPE.VerifyOptions(
        deep=True, runner="local", discover=True, plan=True,
        venvs_dir=str(tmp_path / "venvs"), base_python=sys.executable))
    assert "the_eval.py" in (res["run"]["entry"] or "")           # the plan's entry drove the run
    acc = [c for c in res["claims"] if c["metric"] == "accuracy"]
    assert acc and acc[0]["verdict"] == VD.CONFIRMED              # verdict still from the deterministic recompute


def test_targets_are_shape_validated(tmp_path, monkeypatch):
    """The planner's capture targets (custom metric fns for non-sklearn domains) are kept only if well-formed:
    dotted path + a metric. Malformed / hallucinated-shape entries are dropped — the shim would fail-soft-skip
    a bad path anyway, and a target never touches the verdict (value is captured live + recomputed)."""
    _stub(monkeypatch, {"entrypoint": [], "pip_install": [], "python_version": "", "data_needed": "",
                        "notes": "x", "confidence": 0.5, "targets": [
                            {"target": "metrics.sharpe_ratio", "metric": "sharpe",
                             "inputs": [{"name": "returns", "ref": "arg0"}]},
                            {"target": "src.eval.compute_ndcg", "metric": "ndcg"},        # no inputs → still kept
                            {"target": "no_dot_here", "metric": "x"},                     # not dotted → dropped
                            {"target": "bad;path", "metric": "x"},                        # bad chars → dropped
                            {"target": "mod.fn", "metric": ""},                           # empty metric → dropped
                            "not a dict"]})                                               # wrong type → dropped
    tg = PLAN.plan_repo(str(tmp_path))["targets"]
    assert [t["target"] for t in tg] == ["metrics.sharpe_ratio", "src.eval.compute_ndcg"]
    assert tg[0]["inputs"] == {"returns": "arg0"} and "inputs" not in tg[1]   # array → {name: ref} dict for the shim


def test_plan_targets_flow_to_the_run(tmp_path, monkeypatch):
    """End-to-end: an AI-planned target reaches the runner's capture targets (opts is unset, plan supplies it)."""
    (tmp_path / "eval.py").write_text("print('accuracy=0.5')\n")
    captured = {}
    monkeypatch.setattr(PLAN, "plan_repo", lambda repo_dir: {
        "entry": ["eval.py"], "pip_install": None, "python_version": None, "data_needed": "", "notes": "x",
        "confidence": 0.9, "targets": [{"target": "m.sharpe", "metric": "sharpe"}]})
    monkeypatch.setattr(PIPE, "run_local",   # pipeline does `from runner.local_runner import run_local`
                        lambda *a, **k: captured.update(targets=k.get("targets")) or
                        {"runs": [[]], "meta": [], "ran_ok": True, "hooks_armed": None, "n_calls": [], "cost": {}})
    PIPE.verify_repo(str(tmp_path), PIPE.VerifyOptions(deep=True, runner="local", plan=True,
                     venvs_dir=str(tmp_path / "venvs"), base_python=sys.executable))
    assert captured["targets"] == [{"target": "m.sharpe", "metric": "sharpe"}]


def test_plan_off_skips_the_stage(tmp_path, monkeypatch):
    """plan=False must not even call the planner (opt-out is real)."""
    called = {"n": 0}
    monkeypatch.setattr(PLAN, "plan_repo", lambda repo_dir: called.__setitem__("n", called["n"] + 1) or None)
    (tmp_path / "eval.py").write_text("print('accuracy=0.5')\n")
    PIPE.verify_repo(str(tmp_path), PIPE.VerifyOptions(deep=True, runner="local", plan=False,
                     venvs_dir=str(tmp_path / "venvs"), base_python=sys.executable))
    assert called["n"] == 0
