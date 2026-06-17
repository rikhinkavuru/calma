"""P3.3 acceptance tests -- the cross-recipe constraint DB (ConVer). Pure, no LLM.

The DB shapes the PROPOSER only (relevant() conditions every synthesize() prompt); the gate is never
consulted here and never changes. (The convergence-acceleration claim -- a second same-family metric
admits in fewer iterations once the first's lessons are in the DB -- is observed at the fleet KPI level
over runs in P3.5; here we unit-test the DB contract that makes it possible.)
"""
import os

from edges.synth import constraints as C
from edges.synth.spec import Spec


def _spec(metric_id="cv", family="analytics"):
    return Spec(metric_id=metric_id, family=family, description="d",
                oracle_call="scipy.stats.variation", oracle_args=["value"], oracle_kwargs={"ddof": 1})


def test_kernels_extracted_from_nested_program():
    program = {"expr": {"op": "/", "args": [
        {"call": "fstd", "args": [{"col": "value"}], "scalars": {"ddof": 1}},
        {"op": "sqrt", "args": [{"len": {"col": "value"}}]}]}}
    assert C._kernels_of(program) == ["fstd"]

    program2 = {"expr": {"op": "/", "args": [
        {"call": "col_std", "args": [{"col": "v"}]},
        {"call": "col_mean", "args": [{"col": "v"}]}]}}
    assert C._kernels_of(program2) == ["col_mean", "col_std"]


def test_relevant_prioritizes_implication_and_family(tmp_path):
    db = os.path.join(str(tmp_path), "constraints.jsonl")
    sp = _spec(family="analytics")
    C.record_implication("analytics", ["col_std"], "kernel col_std ddof must match the oracle ddof", db=db)
    C.record_positive(sp, {"program": {"expr": {"call": "col_std", "args": []}}}, db=db)
    C.record_negative(sp, {"program": {"expr": {"call": "col_std", "args": []}}},
                      {"stage": "differential", "oracle": "o", "seed": 0, "n": 3,
                       "expected": "1", "got": "2", "inputs": {}}, db=db)
    # an UNRELATED family negative must be excluded
    C.record_negative(_spec(family="quant"), {"program": {}},
                      {"stage": "metamorphic", "relation": "scale", "index": 0, "seed": 0, "n": 3,
                       "expected": "1", "got": "2"}, db=db)

    rel = C.relevant(sp, db=db)
    assert all(r["family"] == "analytics" for r in rel)        # only the same family
    assert rel[0]["kind"] == "implication"                     # implication first
    kinds = [r["kind"] for r in rel]
    assert kinds.index("implication") < kinds.index("positive") < kinds.index("negative")


def test_taxonomy_ranks_most_common_stage_first(tmp_path):
    db = os.path.join(str(tmp_path), "constraints.jsonl")
    sp = _spec(family="stats")
    diff_ce = {"stage": "differential", "oracle": "o", "seed": 0, "n": 3,
               "expected": "1", "got": "2", "inputs": {}}
    meta_ce = {"stage": "metamorphic", "relation": "scale", "index": 0, "seed": 0, "n": 3,
               "expected": "1", "got": "2"}
    for _ in range(3):
        C.record_negative(sp, {"program": {}}, diff_ce, db=db)
    C.record_negative(sp, {"program": {}}, meta_ce, db=db)

    tax = C.taxonomy("stats", db=db)["stats"]
    assert tax[0][0] == "differential" and tax[0][1] == 3     # most common stage ranks first
    block = C.taxonomy_prompt_block("stats", db=db)
    assert "differential" in block and "stats" in block


def test_relevant_dedups_by_lesson(tmp_path):
    db = os.path.join(str(tmp_path), "constraints.jsonl")
    sp = _spec(family="finance")
    ce = {"stage": "differential", "oracle": "o", "seed": 0, "n": 3,
          "expected": "1", "got": "2", "inputs": {}}
    C.record_negative(sp, {"program": {}}, ce, db=db)
    C.record_negative(sp, {"program": {}}, ce, db=db)         # identical lesson
    rel = C.relevant(sp, db=db)
    lessons = [r["lesson"] for r in rel]
    assert len(lessons) == len(set(lessons))                  # deduped
