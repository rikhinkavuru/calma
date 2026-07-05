"""S4 part 2b — AI "search ALL outputs" (locate_claims). When the deterministic scan finds nothing, an LLM
locates REPORTED metric values the patterns missed. Hermetic: the model call is stubbed. Asserts a valid
located metric becomes a claim, and every anti-hallucination rail holds — a fake file, a non-metric name, and
a non-numeric value are all dropped (a located value is only a CLAIM the recompute still validates independently)."""
import json

import planner as PLAN


def _repo(tmp_path):
    (tmp_path / "eval_output.txt").write_text("Experiment 7 — Final AUROC on the held-out test set: 0.883\n")
    return str(tmp_path)


def _stub(monkeypatch, claims):
    monkeypatch.setattr(PLAN, "_call_model", lambda *a, **k: json.dumps({"claims": claims}))


def test_locates_a_reported_metric_as_a_claim(monkeypatch, tmp_path):
    _stub(monkeypatch, [{"metric": "AUROC", "value": "0.883", "file": "eval_output.txt", "context": "test"}])
    out = PLAN.locate_claims(_repo(tmp_path))
    assert len(out) == 1
    c = out[0]
    assert c["metric"] == "roc_auc" and c["value"] == "0.883" and c["source"] == "ai-located"
    assert c["location"] == "eval_output.txt::AUROC"


def test_drops_hallucinated_file(monkeypatch, tmp_path):
    # cites a file we never showed the model → dropped (it can only reference the haystack we presented).
    _stub(monkeypatch, [{"metric": "AUROC", "value": "0.883", "file": "ghost_results.txt"}])
    assert PLAN.locate_claims(_repo(tmp_path)) == []


def test_drops_non_metric_and_non_numeric(monkeypatch, tmp_path):
    _stub(monkeypatch, [
        {"metric": "learning_rate", "value": "0.001", "file": "eval_output.txt"},   # not an eval metric → map_metric None
        {"metric": "AUROC", "value": "high", "file": "eval_output.txt"},            # not numeric → dropped
    ])
    assert PLAN.locate_claims(_repo(tmp_path)) == []


def test_dedupes_against_existing_claims(monkeypatch, tmp_path):
    _stub(monkeypatch, [{"metric": "AUROC", "value": "0.883", "file": "eval_output.txt"}])
    existing = [{"metric": "roc_auc", "value": "0.883"}]
    assert PLAN.locate_claims(_repo(tmp_path), existing=existing) == []             # already discovered → no dup


def test_empty_when_no_result_files(monkeypatch, tmp_path):
    (tmp_path / "model.py").write_text("print(1)\n")               # no result-ish files → nothing to search
    called = {"n": 0}
    monkeypatch.setattr(PLAN, "_call_model", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or None)
    assert PLAN.locate_claims(str(tmp_path)) == []
    assert called["n"] == 0                                        # never even calls the model with an empty haystack
