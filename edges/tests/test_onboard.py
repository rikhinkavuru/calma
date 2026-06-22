"""M4 acceptance -- the bespoke-metric onboarding loop: methodology + firm reference vectors ->
LLM PROPOSES a DSL program -> compiler.admit() DISPOSES against the firm's vectors + metamorphic +
degeneracy + bit-stability -> frozen recipe. THE GATE NEVER MOVES.

The proposer LLM is MOCKED here (a deterministic wrong-then-right sequence), so the suite needs no
ANTHROPIC_API_KEY and no network. compiler.admit() runs for REAL -- it is the deterministic gate -- and
the reference-vector path needs NO reference venv (the firm's numbers are the oracle), so these tests run
anywhere. Every onboard() call freezes to a TMP registry so the committed assets are never mutated.

The live end-to-end proof (a real LLM converging in one run) is edges/synth/demo_onboard.py.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                                 ".claude", "skills", "calma", "scripts")))
import compiler  # noqa: E402
import dsl  # noqa: E402

from edges.synth import feedback, onboard  # noqa: E402

METHODOLOGY = ("Acme reports a 'load factor' for each strategy's exposure series: the average exposure "
               "divided by the peak (maximum) exposure. Exposures are always positive. It lies between 0 "
               "and 1, is invariant to the units exposure is measured in, and ignores observation order.")

# the firm's ground truth, computed INDEPENDENTLY (plain mean/max, no calma kernel)
_RAW = [[10, 20, 30, 40], [1, 3, 5, 7, 9], [100, 50, 25, 25], [7, 7, 7], [3, 1, 4, 1, 5, 9, 2, 6]]
REF_VECTORS = [{"inputs": {"value": xs}, "expected": (sum(xs) / len(xs)) / max(xs)} for xs in _RAW]


def _program(denom="col_max"):
    return {"schema": "calma/recipe-dsl@1", "inputs": {"value": "list"},
            "expr": {"op": "/", "args": [{"call": "fmean", "args": [{"col": "value"}]},
                                        {"call": denom, "args": [{"col": "value"}]}]}}


def _model_draft(denom="col_max", mm=None):
    """What the proposer (mocked) emits: a recipe-draft@1 WITHOUT oracle / reference_vectors (the harness
    injects the firm vectors). metric_id/family are overridden by onboard(), so they can be placeholders."""
    return {"schema": "calma/recipe-draft@1", "metric_id": "x", "family": "analytics",
            "description": "average exposure over peak exposure", "program": _program(denom),
            "generators": {"value": {"kind": "positive", "scale": 100.0}},
            "metamorphic": mm or [{"relation": "permutation", "expect": "equal"},
                                  {"relation": "scale", "factor": 3.0, "expect": "equal"},
                                  {"relation": "bounds", "min": 0.0, "max": 1.0}],
            "edge_cases": {"empty": "nan", "single": 1.0, "constant": 1.0, "nan": "nan"}}


def _tmp_paths(tmp_path):
    return dict(compiled_path=os.path.join(str(tmp_path), "compiled_recipes.json"),
                drafts_log=os.path.join(str(tmp_path), "onboard_drafts.jsonl"),
                constraints_db=os.path.join(str(tmp_path), "constraints.jsonl"))


class _Proposer:
    """A deterministic stand-in for llm.structured: yields the queued drafts in order, repeating the
    last one once exhausted (so an 'always-wrong' proposer is just a one-element queue)."""
    def __init__(self, *drafts):
        self.drafts, self.calls = list(drafts), 0

    def __call__(self, prompt, *, schema, **kw):
        d = self.drafts[min(self.calls, len(self.drafts) - 1)]
        self.calls += 1
        return d


def test_onboard_converges_from_a_wrong_first_draft(tmp_path, monkeypatch):
    # attempt 1: mean/MIN (wrong) -> reference counterexample; attempt 2: mean/MAX (right) -> admit
    monkeypatch.setattr(onboard.llm, "structured",
                        _Proposer(_model_draft("col_min"), _model_draft("col_max")))
    res = onboard.onboard("acme_load_factor", "analytics", METHODOLOGY, REF_VECTORS,
                          budget=5, **_tmp_paths(tmp_path))
    assert res.admitted is True
    assert res.iterations == 2                      # it did NOT admit on attempt 1
    assert res.trace[0]["ok"] is False and res.trace[0]["stage"] == "reference"
    assert res.trace[-1]["ok"] is True
    assert res.program_sha256 and len(res.vectors) == len(REF_VECTORS)


def test_onboarded_recipe_freezes_and_revalidates(tmp_path, monkeypatch):
    monkeypatch.setattr(onboard.llm, "structured", _Proposer(_model_draft("col_max")))
    paths = _tmp_paths(tmp_path)
    res = onboard.onboard("acme_load_factor", "analytics", METHODOLOGY, REF_VECTORS, budget=3, **paths)
    assert res.admitted is True
    book = json.load(open(paths["compiled_path"]))
    entry = next((r for r in book["recipes"] if r["metric_id"] == "acme_load_factor"), None)
    assert entry is not None
    # re-validates EXACTLY as recipes._load_compiled would (hash + dsl.validate), with no named oracle
    assert dsl.program_hash(entry["program"]) == entry["program_sha256"]
    assert dsl.validate(entry["program"]) == []
    assert entry.get("oracle") is None and entry["admitted"]["ground_truth"] == "reference-vectors"
    # the frozen program reproduces the firm's independent numbers to tolerance
    for vec in REF_VECTORS:
        assert compiler._close(dsl.execute(entry["program"], vec["inputs"]), vec["expected"])


def test_false_metamorphic_never_admits(tmp_path, monkeypatch):
    # the program fits all 5 reference points but declares shift-invariance (which avg/peak lacks):
    # the independent metamorphic gate keeps it out forever (no overfit-to-vectors admission).
    bad_mm = [{"relation": "permutation", "expect": "equal"},
              {"relation": "shift", "delta": 5.0, "expect": "equal"}]
    monkeypatch.setattr(onboard.llm, "structured", _Proposer(_model_draft("col_max", mm=bad_mm)))
    paths = _tmp_paths(tmp_path)
    res = onboard.onboard("acme_load_factor", "analytics", METHODOLOGY, REF_VECTORS, budget=3, **paths)
    assert res.admitted is False
    assert res.last_stage == "metamorphic"
    assert not os.path.exists(paths["compiled_path"])     # NOTHING frozen on a miss


def test_onboard_requires_reference_vectors():
    with pytest.raises(AssertionError):
        onboard.onboard("acme_load_factor", "analytics", METHODOLOGY, [])


def test_cli_main_onboards_from_a_vectors_file(tmp_path, monkeypatch):
    # exercises the `python -m edges.synth.onboard` entry: methodology text + a vectors FILE -> admitted,
    # frozen to a tmp registry (the CLI path the `calma onboard` subcommand shells out to).
    monkeypatch.setattr(onboard.llm, "structured", _Proposer(_model_draft("col_max")))
    vpath = tmp_path / "vectors.json"
    vpath.write_text(json.dumps(REF_VECTORS))
    cp = str(tmp_path / "compiled.json")
    rc = onboard.main(["--metric-id", "acme_load_factor", "--family", "analytics",
                       "--methodology", METHODOLOGY, "--vectors", str(vpath),
                       "--metamorphic-hint", "scale-invariant", "--compiled-path", cp,
                       "--budget", "3", "--json"])
    assert rc == 0
    book = json.load(open(cp))
    assert any(r["metric_id"] == "acme_load_factor" for r in book["recipes"])


def test_reference_counterexample_localizes_the_fix():
    # a mean/min program vs the firm's mean/max vectors -> a reference counterexample with a hypothesis
    bad = {"schema": "calma/recipe-draft@1", "metric_id": "x", "family": "analytics",
           "description": "x", "program": _program("col_min"),
           "generators": {"value": {"kind": "positive", "scale": 100.0}},
           "metamorphic": [{"relation": "permutation", "expect": "equal"}],
           "edge_cases": {"empty": "nan"}, "reference_vectors": REF_VECTORS}
    ok, result = compiler.admit(bad, venv_python=None, write=False)
    assert ok is False
    ce = result["counterexamples"][0]
    assert ce["stage"] == "reference"
    msg = feedback.format_counterexample(ce)
    assert "REFERENCE-VECTOR mismatch" in msg and "firm expected" in msg and "HYPOTHESIS" in msg
