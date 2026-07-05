"""S4 part 2 — the BLIND LLM subset-scope proposer. The lexical binder misses a synonym ('minority class' ≠
the value 'rare'); the LLM proposes the column/value from the label semantics WITHOUT seeing the claim's
numeric value (so it can't p-hack), and the SAME deterministic recompute disposes the verdict. Hermetic: the
model call is stubbed; no key/network. Asserts a synonym subset CONFIRMS, a wrong VALUE (label says subset but
the number is the all-rows figure) REFUTES, hallucinated columns/values are rejected, and model=None never
calls the LLM."""
import json

import planner as PLAN
import pipeline
from core import verdict as VD

# rare (rows 0-3): positives label=1 at 0,1 → pred 1,0 → recall 0.50. all 8 rows: recall 4/5 = 0.80.
_CSV = ("label,pred,variant_class\n"
        "1,1,rare\n1,0,rare\n0,0,rare\n0,1,rare\n"
        "1,1,common\n1,1,common\n1,1,common\n0,0,common\n")


def _repo(tmp_path):
    (tmp_path / "benchmark_classifier.csv").write_text(_CSV)
    return str(tmp_path)


def _claim(value, rawname):
    return {"id": "c1", "metric": "recall", "value": value,
            "location": "results.json::%s" % rawname, "source": "results-json", "confidence": 0.6}


def _stub_model(monkeypatch, payload):
    monkeypatch.setattr(PLAN, "_call_model", lambda *a, **k: json.dumps(payload) if payload is not None else None)


# ── propose_scope unit ────────────────────────────────────────────────────────────────────────────────────────
def test_propose_scope_returns_validated_categorical(monkeypatch):
    _stub_model(monkeypatch, {"column": "variant_class", "value": "rare"})
    assert PLAN.propose_scope("recall", "minority class", {"variant_class": ["rare", "common"]}) == ("variant_class", "rare")


def test_propose_scope_boolean_column_returns_none_value(monkeypatch):
    _stub_model(monkeypatch, {"column": "pfam_testable", "value": ""})
    assert PLAN.propose_scope("recall", "testable", {"pfam_testable": ["yes", "no"]}) == ("pfam_testable", None)


def test_propose_scope_rejects_hallucinated_column_and_value(monkeypatch):
    _stub_model(monkeypatch, {"column": "nonexistent", "value": "x"})
    assert PLAN.propose_scope("recall", "minority", {"variant_class": ["rare", "common"]}) is None
    _stub_model(monkeypatch, {"column": "variant_class", "value": "ultrarare"})     # value not in the column
    assert PLAN.propose_scope("recall", "minority", {"variant_class": ["rare", "common"]}) is None


def test_propose_scope_none_when_model_declines(monkeypatch):
    _stub_model(monkeypatch, {"column": "", "value": ""})                            # model: no subset applies
    assert PLAN.propose_scope("recall", "overall", {"variant_class": ["rare", "common"]}) is None


# ── integration through _artifact_verify ──────────────────────────────────────────────────────────────────────
def test_llm_scope_confirms_a_synonym_subset(monkeypatch, tmp_path):
    # 'minority class' doesn't lexically match the value 'rare' → the deterministic binder misses; the blind LLM
    # maps it → variant_class==rare → recompute 0.50 → matches the claim → CONFIRMED (AI-proposed, validated).
    _stub_model(monkeypatch, {"column": "variant_class", "value": "rare"})
    out = pipeline._artifact_verify(_repo(tmp_path), [_claim("0.50", "recall_minority")], model="m")
    rec = out.get("c1")
    assert rec and rec["verdict"] == VD.CONFIRMED and "AI:variant_class==rare" in rec.get("reason", "")


def test_llm_scope_cannot_launder_the_all_rows_value(monkeypatch, tmp_path):
    # the label says a subset ('minority') but the VALUE is the all-rows recall (0.80). The blind proposer picks
    # the right subset (rare, 0.50), and the recompute REFUTES the 0.80 — the proposer can't reach the number.
    _stub_model(monkeypatch, {"column": "variant_class", "value": "rare"})
    out = pipeline._artifact_verify(_repo(tmp_path), [_claim("0.80", "recall_minority")], model="m")
    assert out["c1"]["verdict"] == VD.REFUTED


def test_model_none_never_calls_the_llm(monkeypatch, tmp_path):
    calls = {"n": 0}

    def _counted(*a, **k):
        calls["n"] += 1
        return None
    monkeypatch.setattr(PLAN, "_call_model", _counted)
    pipeline._artifact_verify(_repo(tmp_path), [_claim("0.50", "recall_minority")], model=None)
    assert calls["n"] == 0                                    # LLM path gated off without a model (deterministic only)
