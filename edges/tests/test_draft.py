"""P2.1 acceptance tests -- the LLM contract drafter for messy real repos.

The SONNET draft is replayed from a recorded fixture (conftest forces replay), so the suite needs no
ANTHROPIC_API_KEY. The drafter emits the contract schema ONLY; it never emits a grade or verdict, and
_sanitize drops out-of-vocab metric_ids / tags / phantom artifacts. The load-bearing behavior: the model
binds the in-range probability column (p_hat), not the same-named logit decoy (raw_score).
"""
import os

import pytest

from edges.contract import draft as D
from edges.contract.schema import CONTRACT_SCHEMA

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "repos", "sklearn_messy")


@pytest.fixture
def contract(tmp_path):
    return D.llm_draft(FIX, drafts_log=os.path.join(str(tmp_path), "drafts.jsonl"))


def _auc(c):
    return next(m for m in c["metrics"] if m["metric_id"] == "auc")


# === ACCEPTANCE: the evidence packet is assembled (pure, no LLM) ===============================
def test_assemble_inputs_has_heads_and_heuristic():
    inp = D.assemble_inputs(FIX)
    assert any("p_hat" in h["header"] for h in inp["data_file_heads"])
    assert "metrics" in inp["heuristic_draft"]
    assert "sklearn" in inp["framework_signatures"]
    assert any(e["path"] == "main.py" for e in inp["entrypoint_candidates"])


# === ACCEPTANCE: the model binds the in-range probability, not the logit decoy =================
def test_llm_draft_binds_probability_not_logit(contract):
    auc = _auc(contract)
    score_col = auc["binding"].get("score") or auc["binding"].get("prob")   # score-role (prob aliases score)
    assert score_col == "p_hat"                          # bound the in-[0,1] column...
    assert "raw_score" not in auc["binding"].values()    # ...NOT the same-named logit decoy
    assert auc["binding"].get("label") == "y"
    assert auc.get("headline") is True


# === ACCEPTANCE: the draft is schema-valid and validate_contract accepts it ====================
def test_draft_is_schema_valid_and_validates(contract):
    from jsonschema import validate
    validate(instance=contract, schema=CONTRACT_SCHEMA)
    import draft_contract as DC
    assert DC.validate_contract(contract) == []


# === ACCEPTANCE: no grade or verdict leaks ====================================================
def test_no_grade_or_verdict_leaks(contract):
    for m in contract["metrics"]:
        assert "binding_status" not in m and "claim_confirmed" not in m
        assert m.get("claimed_precision") is None        # never set by the model
    for k in ("verdict", "confidence", "binding_status", "claim_confirmed"):
        assert k not in contract


# === ACCEPTANCE: _sanitize drops an out-of-vocab metric_id (a real one survives) ===============
def test_out_of_vocab_metric_is_dropped():
    inputs = D.assemble_inputs(FIX)
    raw = {
        "run": {"entrypoint": "main.py"},
        "artifacts": [{"path": "out/preds.csv",
                       "columns": {"p_hat": {"tag": "prob"}, "y": {"tag": "label"}}}],
        "metrics": [
            {"metric_id": "made_up_metric", "artifact": "out/preds.csv",
             "binding": {"prob": "p_hat", "label": "y"}, "binding_status": "independently-bound"},
            {"metric_id": "auc", "artifact": "out/preds.csv",
             "binding": {"prob": "p_hat", "label": "y"}, "headline": True},
        ],
    }
    clean = D._sanitize(raw, inputs)
    ids = [m["metric_id"] for m in clean["metrics"]]
    assert "made_up_metric" not in ids and "auc" in ids
    # the smuggled grade was stripped
    assert all("binding_status" not in m for m in clean["metrics"])


def test_sanitize_nulls_unknown_tag_and_drops_phantom_artifact():
    inputs = D.assemble_inputs(FIX)
    raw = {
        "run": {"entrypoint": "main.py"},
        "artifacts": [
            {"path": "out/preds.csv", "columns": {"p_hat": {"tag": "not_a_real_tag"}}},
            {"path": "ghost/none.csv", "columns": {"z": {"tag": "score"}}},   # phantom file
        ],
        "metrics": [{"metric_id": "auc", "artifact": "out/preds.csv",
                     "binding": {"prob": "p_hat", "label": "y"}, "headline": True}],
    }
    clean = D._sanitize(raw, inputs)
    paths = [a["path"] for a in clean["artifacts"]]
    assert "ghost/none.csv" not in paths                 # phantom artifact dropped
    cols = clean["artifacts"][0]["columns"]
    assert cols["p_hat"]["tag"] is None                  # unknown tag -> untagged, never invented
