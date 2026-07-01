"""Feature 4 — claim salience / legibility. The P0 ranker is a pure win: it re-orders discovered claims by
how headline they are and adds `salience`/`is_metric_claim`, but it must NEVER change a claim's identity
(metric/value/id) — which is what guarantees verdict- and FCR-invariance with the classifier on or off."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from discovery import salience as SAL  # noqa: E402


def _claims():
    return [
        {"id": "a", "metric": "accuracy", "value": "0.7", "source": "prose", "confidence": 0.7,
         "location": "README.md", "split": "train"},
        {"id": "b", "metric": "accuracy", "value": "0.91", "source": "results-json", "confidence": 0.9,
         "location": "results.json::test.accuracy", "split": "test"},
        {"id": "c", "metric": "f1", "value": "0.8", "source": "table", "confidence": 0.72, "location": "README.md"},
    ]


def test_headline_outranks_train_and_prose():
    ranked = SAL.score_claims(_claims())
    assert ranked[0]["id"] == "b"     # results.json held-out test accuracy = the headline
    assert ranked[-1]["id"] == "a"    # a train-split prose number is least salient
    assert all("salience" in c for c in ranked)


def test_never_mutates_metric_or_value():
    before = {(c["id"], c["metric"], c["value"]) for c in _claims()}
    ranked = SAL.score_claims(_claims())
    after = {(c["id"], c["metric"], c["value"]) for c in ranked}
    assert before == after                      # identity preserved → verdicts + FCR invariant


def test_fcr_invariance_llm_fallback_no_key(monkeypatch):
    """With no API key (conftest drops it) `use_llm=True` must no-op to the P0 ranking — no exception, and the
    same identity set as `use_llm=False`."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a = SAL.score_claims(_claims(), use_llm=False)
    b = SAL.score_claims(_claims(), use_llm=True, model="claude-haiku-4-5")
    assert [c["id"] for c in a] == [c["id"] for c in b]
    assert all(x["value"] == y["value"] for x, y in zip(a, b))


def test_llm_merge_blends_but_preserves_identity(monkeypatch):
    """Stub the model to demote claim b to noise: the merge must lower b's salience and set claim_kind, but
    never touch metric/value."""
    from discovery import claim_classifier as CC

    def _fake_call(context, model):
        return ('{"claims": [{"id": "b", "is_headline": false, "salience": 0.0, "kind": "noise"},'
                ' {"id": "a", "salience": 1.0, "kind": "metric"},'
                ' {"id": "c", "salience": 0.5, "kind": "metric"}]}')
    monkeypatch.setattr(CC, "_call_model", _fake_call)
    claims = _claims()
    SAL.score_claims(claims, use_llm=True)
    by_id = {c["id"]: c for c in claims}
    assert by_id["b"]["claim_kind"] == "noise" and by_id["b"]["is_metric_claim"] is False
    assert by_id["b"]["value"] == "0.91" and by_id["a"]["value"] == "0.7"   # identity untouched


def test_head_returns_top_n():
    ranked = SAL.score_claims(_claims())
    assert [c["id"] for c in SAL.head(ranked, 1)] == ["b"]
    assert len(SAL.head(ranked)) == 3
