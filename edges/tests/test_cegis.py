"""P3.1 acceptance tests -- the CEGIS driver: draft -> admit(dry) -> counterexample -> re-draft ->
admit(freeze). THE GATE NEVER MOVES.

The synthesizer LLM is REPLAYED from recorded fixtures (conftest forces replay), so the suite needs no
ANTHROPIC_API_KEY. compiler.admit() runs for real (it is the deterministic gate): its differential stage
executes the named oracle in the reference venv, so these tests skip gracefully when no ref venv is
resolvable. Every synthesize() here freezes to a TMP registry (compiled_path=) so the committed
assets/compiled_recipes.json is never mutated -- the gate's verdict is identical, only the write target
moves.

Record the sem fixtures ONCE:
    CALMA_EDGES_RECORD=1 ANTHROPIC_API_KEY=... CALMA_REF_VENV=~/.calma/ref-venv/bin/python \
        PYTHONPATH=. ~/.cache/calma-edges-venv/bin/python  (drive synthesize('sem', ...))
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                                 ".claude", "skills", "calma", "scripts")))
import compiler  # noqa: E402
import dsl  # noqa: E402

from edges.synth import cegis  # noqa: E402
from edges.synth.spec import Spec  # noqa: E402

REF_VENV = compiler.DEFAULT_VENV
needs_venv = pytest.mark.skipif(not os.path.exists(REF_VENV),
                                reason="no reference venv at %s (set CALMA_REF_VENV)" % REF_VENV)

SEM_SPEC = Spec(metric_id="sem", family="stats",
                description="standard error of the mean of a sample.",
                oracle_call="scipy.stats.sem", oracle_args=["value"], oracle_kwargs={"ddof": 1},
                inputs_hint={"value": "list"},
                aliases_seed=["sem", "standard error of the mean", "std error of the mean",
                              "sampling error of the average", "mean standard error"])


def _tmp_paths(tmp_path):
    return dict(compiled_path=os.path.join(str(tmp_path), "compiled_recipes.json"),
                desc_path=os.path.join(str(tmp_path), "recipe_descriptions.json"),
                constraints_db=os.path.join(str(tmp_path), "constraints.jsonl"),
                drafts_log=os.path.join(str(tmp_path), "drafts.jsonl"))


def _frozen_entry(compiled_path, metric_id):
    book = json.load(open(compiled_path))
    return next((r for r in book.get("recipes", []) if r.get("metric_id") == metric_id), None)


def _sem_draft(ddof):
    return {"schema": "calma/recipe-draft@1", "metric_id": "sem", "family": "stats",
            "description": "standard error of the mean.",
            "program": {"schema": "calma/recipe-dsl@1", "inputs": {"value": "list"},
                        "expr": {"op": "/", "args": [
                            {"call": "fstd", "args": [{"col": "value"}], "scalars": {"ddof": ddof}},
                            {"op": "sqrt", "args": [{"len": {"col": "value"}}]}]}},
            "generators": {"value": {"kind": "uniform", "lo": -5.0, "hi": 10.0}},
            "oracle": {"call": "scipy.stats.sem", "args": ["value"], "kwargs": {"ddof": 1}},
            "metamorphic": [{"relation": "permutation", "expect": "equal"}],
            "edge_cases": {"empty": "nan", "single": "nan", "constant": 0, "nan": "nan"}}


# === ACCEPTANCE: the loop admits sem within budget; the frozen entry re-validates on reload ======
@needs_venv
def test_admits_sem_within_budget(tmp_path):
    paths = _tmp_paths(tmp_path)
    res = cegis.synthesize("sem", SEM_SPEC, venv_python=REF_VENV, budget=6, model=cegis.llm.SONNET,
                           run_def_of_done=False, **paths)
    assert res.admitted is True
    assert res.iterations <= 6
    assert res.program_sha256 and len(res.vectors) >= 5
    assert res.enrichment_written is True

    # the frozen entry re-validates EXACTLY as recipes._load_compiled would (hash + dsl.validate)
    entry = _frozen_entry(paths["compiled_path"], "sem")
    assert entry is not None
    assert dsl.program_hash(entry["program"]) == entry["program_sha256"]
    assert dsl.validate(entry["program"]) == []
    # re-running admit(dry) on the frozen program is still (True, ...) -- the gate is reproducible
    ok, _ = compiler.admit({**_sem_draft(1), "program": entry["program"]},
                           venv_python=REF_VENV, write=False)
    assert ok is True


# === ACCEPTANCE: the loop converges from a failing first draft (real recording) ================
@needs_venv
def test_converges_from_a_failing_first_draft(tmp_path):
    res = cegis.synthesize("sem", SEM_SPEC, venv_python=REF_VENV, budget=6, model=cegis.llm.SONNET,
                           run_def_of_done=False, **_tmp_paths(tmp_path))
    assert res.admitted is True
    assert res.iterations > 1                                 # it did NOT admit on attempt 1
    assert res.trace[0]["ok"] is False                        # the first draft was rejected by the gate
    assert res.trace[-1]["ok"] is True                        # a later draft admitted


# === the differential->ddof localization the feedback provides (deterministic, no LLM) ==========
@needs_venv
def test_differential_ddof_counterexample_localizes_the_fix(tmp_path):
    # a population-std (ddof=0) sem program vs the ddof=1 oracle -> a DIFFERENTIAL counterexample
    ok, result = compiler.admit(_sem_draft(0), venv_python=REF_VENV,
                                compiled_path=os.path.join(str(tmp_path), "c.json"), write=False)
    assert ok is False
    ce = result["counterexamples"][0]
    assert ce["stage"] == "differential"
    from edges.synth import feedback
    assert "ddof" in feedback.format_counterexample(ce)

    # the corrected ddof=1 program admits (the gate is the same; only the kernel scalar changed)
    ok2, _ = compiler.admit(_sem_draft(1), venv_python=REF_VENV,
                            compiled_path=os.path.join(str(tmp_path), "c.json"), write=False)
    assert ok2 is True


# === ACCEPTANCE: a structural reject is not a verdict; the loop never freezes/raises ============
def test_structural_reject_is_not_a_verdict(tmp_path, monkeypatch):
    bad = _sem_draft(1)
    bad["program"]["expr"]["args"][0]["call"] = "std"        # not whitelisted -> structural reject
    monkeypatch.setattr(cegis.llm, "structured", lambda *a, **k: bad)

    paths = _tmp_paths(tmp_path)
    res = cegis.synthesize("sem", SEM_SPEC, venv_python=REF_VENV, budget=1, run_def_of_done=False,
                           write_enrichment=False, **paths)
    assert res.admitted is False
    assert res.last_stage == "structural"
    assert not os.path.exists(paths["compiled_path"])        # NOTHING frozen on a structural miss


# === ACCEPTANCE: no partial write on a miss (the dry-run/write split) ===========================
def test_no_partial_write_on_miss(tmp_path, monkeypatch):
    bad = _sem_draft(1)
    bad["program"]["expr"]["args"][0]["call"] = "std"
    monkeypatch.setattr(cegis.llm, "structured", lambda *a, **k: bad)

    paths = _tmp_paths(tmp_path)
    # seed an existing registry so we can assert it is byte-UNCHANGED across the miss
    book0 = {"schema": "calma/compiled-recipes@1", "recipes": []}
    json.dump(book0, open(paths["compiled_path"], "w"))
    before = open(paths["compiled_path"], "rb").read()

    res = cegis.synthesize("sem", SEM_SPEC, venv_python=REF_VENV, budget=1, run_def_of_done=False,
                           write_enrichment=False, **paths)
    assert res.admitted is False
    assert open(paths["compiled_path"], "rb").read() == before   # registry byte-unchanged
