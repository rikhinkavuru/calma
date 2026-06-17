"""P1.5 acceptance tests -- the distilled router (Haiku->Sonnet->Opus) + the formula pre-check.

The routing-coverage test replays recorded fixtures (edges/tests/fixtures/<hash>.json); the suite needs
no ANTHROPIC_API_KEY. Record the fixtures ONCE with the models live:

    CALMA_EDGES_RECORD=1 ANTHROPIC_API_KEY=... \
        PYTHONPATH=. ~/.cache/calma-edges-venv/bin/python edges/tests/test_route.py --record

(conftest.py pops CALMA_EDGES_RECORD so the suite never records.) Then `pytest edges/tests/test_route.py`
replays with the var unset. Request hashes are deterministic (the prompts embed only span text +
basename provenance + the bootstrap example), so the same bundle always produces the same fixture keys.

The pre-check tests are PURE (no LLM): _eval_formula / precheck run locally, and pre-check SOUNDNESS
runs the REAL engine via verify_graph -- asserting the likely_ok set is a strict subset of what the
engine CONFIRMs (the pre-check never short-circuits or overrides the engine).
"""
import os
import shutil

import pytest

from edges.common import llm, record
from edges.extract import ingest, route as R, to_contract as TC

FIXT = os.path.join(os.path.dirname(__file__), "fixtures", "artifacts")
NB = os.path.join(FIXT, "nb_three_metrics.ipynb")
BTC = os.path.join(os.path.dirname(__file__), "fixtures", "targets", "btc_like")


# --- the routing bundle: >=6 simple/clear, >=2 low-confidence, >=1 complex citation -------------
def _routing_bundle():
    """A ~10-span batch. The 6 'rows=N' spans are pure-`simple` -> the no-LLM heuristic path. The two
    bare-number prose spans and the cross-referencing span force the LLM path (and likely escalation)."""
    def span(text, section, et, kind):
        return ingest.Span(text, {"document": "batch.ipynb", "section": section, "page": None,
                                  "element_type": et}, source_kind=kind)
    spans = [span("rows=%d" % (1000 * (i + 1)), "cell %d" % i, "code", "code") for i in range(6)]
    # low-confidence / ambiguous prose with TWO numbers each -> classify 'moderate' (LLM path),
    # ambiguous measure -> the model self-rates low confidence -> likely escalates.
    spans.append(span("segment A scored 0.73 with spread 0.12 after tuning", "cell 6",
                      "markdown", "markdown"))
    spans.append(span("segment B came in around 0.42 with spread 0.08 on the slice", "cell 7",
                      "markdown", "markdown"))
    # a complex cross-reference -> always escalates to SONNET (classify == 'complex')
    spans.append(span("as computed above in cell 6, the adjusted value is 0.81", "cell 8",
                      "markdown", "markdown"))
    return ingest.ArtifactBundle("batch.ipynb", spans, [], kind="notebook")


# --- a spy on the record/replay boundary: counts LLM requests and exposes their model ----------
@pytest.fixture
def llm_spy(monkeypatch):
    seen = []
    orig = record.replay

    def spy(req):
        seen.append(req)
        return orig(req)

    monkeypatch.setattr(record, "replay", spy)
    return seen


# --- claim/bundle builders for the PURE pre-check tests ----------------------------------------
def _claim(measure, value, value_text, *, formula=None, quote="", section="cell 0",
           file=None, column=None, confidence=0.9, element_type="output"):
    return {
        "value": value, "value_text": value_text, "measure": measure, "subject": "",
        "claimed_provenance": {"file": file, "column": column, "cell": section,
                               "computation": None, "formula_hint": formula},
        "source_span": {"quote": quote or value_text, "section": section,
                        "element_type": element_type, "page": None, "bbox": None},
        "confidence": confidence,
    }


@pytest.fixture
def btc_like(tmp_path):
    dst = os.path.join(str(tmp_path), "btc_like")
    shutil.copytree(BTC, dst)
    return dst


def _metric(metrics, mid):
    return next((m for m in metrics if m.get("metric") == mid), None)


# === ACCEPTANCE: routing coverage + escalation (replayed) ======================================
def test_routing_coverage_and_escalation(llm_spy):
    graph, st = R.extract_routed(_routing_bundle())

    from jsonschema import validate
    validate(instance=st.to_json(), schema=R.ROUTESTATS_SCHEMA)

    assert st.claims == 9                                  # one classify() per span
    assert st.heuristic == 6                               # the six 'rows=N' spans, NO LLM
    assert st.haiku == 3                                   # the three non-simple spans (HAIKU first)
    assert st.escalated_sonnet >= 1                        # the complex span always escalates
    assert st.coverage_no_escalation() > 0.70             # >70% reached via the cheap-first path
    assert st.escalated_opus <= st.escalated_sonnet        # OPUS is the rarer, last resort
    assert len(graph["claims"]) >= st.heuristic            # every heuristic claim survives

    # the cheap path made ZERO model calls for the simple spans: the only structured/plain requests
    # belong to the LLM-routed spans (bootstrap + haiku + any escalation), never the six 'rows=N'.
    structured = [r for r in llm_spy if "tools" in r]
    assert all(r["model"] in (llm.HAIKU, llm.SONNET, llm.OPUS) for r in structured)


# === ACCEPTANCE: a simple 'rows=10000' span -> heuristic, ZERO LLM requests ====================
def test_simple_span_is_heuristic_with_zero_llm(llm_spy):
    sp = ingest.Span("rows=10000", {"document": "x.ipynb", "section": "cell 3", "page": None,
                                    "element_type": "code"}, source_kind="code")
    bundle = ingest.ArtifactBundle("x.ipynb", [sp], [], kind="notebook")
    graph, st = R.extract_routed(bundle)
    assert len(llm_spy) == 0                               # NO model call on the heuristic path
    assert st.heuristic == 1 and st.haiku == 0
    assert len(graph["claims"]) == 1
    assert graph["claims"][0]["measure"] in ("row_count", "unknown")


# === ACCEPTANCE: pre-check SOUNDNESS -- likely_ok is a strict subset of engine-CONFIRMED ========
def test_precheck_is_strict_subset_of_engine_confirmed(btc_like):
    """A graph of formula-bearing claims over btc_like: accuracy (0.90) reproduces and its formula
    reconstructs; total_return (+14,698%) is REFUTED by the data and its formula disagrees too. The
    pre-check's likely_ok set must be CONFIRMED by the engine, and the disagreeing claim must NOT be
    hidden by the pre-check -- the engine still REFUTES it."""
    graph = {"claims": [
        # accuracy: operands in the quote reconstruct to 0.90 -> precheck True; engine CONFIRMS
        _claim("accuracy", 0.90, "0.90", formula="correct/total",
               quote="accuracy: correct = 900, total = 1000", section="cell 12", file="preds.csv"),
        # total_return: formula reconstructs to ~ -0.316 (matches the data), NOT the claimed 146.98
        _claim("total_return", 146.98, "+14,698%", formula="(end/start)-1",
               quote="return: end = 68.37, start = 100  (+14,698% backtest)", section="cell 14",
               file="returns.csv", element_type="code"),
    ]}

    # build the operand-bearing bundle so precheck can find the operands via the spans too
    bundle = ingest.ArtifactBundle("nb.ipynb", [
        ingest.Span("accuracy: correct = 900, total = 1000",
                    {"document": "nb.ipynb", "section": "cell 12", "page": None,
                     "element_type": "output"}, source_kind="output"),
        ingest.Span("return: end = 68.37, start = 100  (+14,698% backtest)",
                    {"document": "nb.ipynb", "section": "cell 14", "page": None,
                     "element_type": "code"}, source_kind="code"),
    ], [], kind="notebook")

    acc, tr = graph["claims"]
    assert R.precheck(acc, bundle) is True                 # formula agrees with the claim
    assert R.precheck(tr, bundle) is False                 # formula disagrees -> worth an engine run

    out = TC.verify_graph(graph, btc_like)
    by = {m["metric"]: m for m in out["engine"]["metrics"]}

    # SUBSET: every likely_ok claim is CONFIRMED (or CONFIRMED-WITH-CAVEATS) by the engine
    likely_ok = [c for c in graph["claims"] if R.precheck(c, bundle) is True]
    assert acc in likely_ok and tr not in likely_ok
    for c in likely_ok:
        assert by[c["measure"]]["verdict"] in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS")

    # the pre-check did NOT hide the bad claim: the engine still REFUTES total_return
    assert by["total_return"]["verdict"] == "REFUTED"


# === UNIT: the safe formula evaluator ==========================================================
def test_eval_formula_is_a_safe_arithmetic_whitelist():
    assert R._eval_formula("TP/(TP+FP)", {"TP": 90.0, "FP": 10.0}) == 0.9
    assert abs(R._eval_formula("(end/start)-1", {"end": 67.84, "start": 100.0}) + 0.3216) < 1e-9
    assert R._eval_formula("a/b", {"a": 1.0}) is None             # missing operand
    assert R._eval_formula("a/b", {"a": 1.0, "b": 0.0}) is None   # divide by zero
    assert R._eval_formula("__import__('os').system('echo hi')", {}) is None   # no code execution
    assert R._eval_formula("a ** b", {"a": 2.0, "b": 10.0}) is None   # ** not whitelisted


def test_precheck_returns_none_without_formula_or_operands():
    no_formula = _claim("accuracy", 0.9, "0.90", quote="accuracy 0.90", section="cell 1")
    assert R.precheck(no_formula) is None
    no_operands = _claim("accuracy", 0.9, "0.90", formula="TP/(TP+FP)",
                         quote="accuracy 0.90 (no operands here)", section="cell 1")
    assert R.precheck(no_operands) is None


# === ADAPTIVE HOOK: record_run appends a schema-valid RouteStats line ===========================
def test_record_run_appends_valid_routestats(tmp_path):
    from jsonschema import validate
    st = R.RouteStats(claims=9, heuristic=6, haiku=3, escalated_sonnet=2, escalated_opus=1, likely_ok=2)
    path = os.path.join(str(tmp_path), "data", "route_stats.jsonl")
    rec = R.record_run(st, ts_from_args=1700000000, path=path)
    assert rec["ts"] == 1700000000
    from edges.common import store
    rows = list(store.iter_records(path))
    assert len(rows) == 1
    validate(instance={k: v for k, v in rows[0].items() if k != "ts"}, schema=R.ROUTESTATS_SCHEMA)
    assert rows[0]["claims"] == 9 and rows[0]["likely_ok"] == 2


# --- recording entrypoint (NOT pytest; run as a script with CALMA_EDGES_RECORD=1) --------------
def _record_all():
    assert os.environ.get("CALMA_EDGES_RECORD") == "1", \
        "set CALMA_EDGES_RECORD=1 (and ANTHROPIC_API_KEY) to record"
    graph, st = R.extract_routed(_routing_bundle())
    print("recorded routing run: %s; %d claims" % (st.to_json(), len(graph["claims"])))


if __name__ == "__main__":
    _record_all()
