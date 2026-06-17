"""P1.4 acceptance tests -- join every engine verdict back to its source span, render the catch with
its provenance, and package the A4 handoff.

Like P1.3, this edge is PURE and deterministic: render() does string assembly over verify_graph()'s
already-fetched engine --json + ledger, and makes NO LLM call. So the suite needs NO record/replay
fixtures and stays green with no ANTHROPIC_API_KEY. The "fixture" is the btc_like TARGET from P1.3
(runs/oos/*.csv): OOS returns compound to ~ -32%, so a "+14,698%" total-return claim is REFUTED while
accuracy (0.90) and auc (1.0) reproduce. Each test runs in a fresh tmp copy so the engine's .calma run
dirs never land in the repo; engine.verify subprocesses to system python3, so the runtime is available
even under the edges venv.

DEVIATION FROM THE PROMPT (matched to the engine's real behavior, as the gate instructs and as P1.3
did): for a clean value-mismatch REFUTED the engine emits fix=None (no unblock/recompute_error/reason
match). The prompt's "rep.fix is non-null" cannot hold for this fixture, so we instead assert that
render copies fix VERBATIM from the engine output (the real invariant) -- here that value is None.
"""
import os
import shutil

import pytest

from edges.extract import reconcile as RC
from edges.extract import to_contract as TC

FIXT_TARGET = os.path.join(os.path.dirname(__file__), "fixtures", "targets", "btc_like")


# --- claim/graph builders (mirror test_to_contract.py) -----------------------------------------
def _span(quote, section, element_type="output", page=None, bbox=None):
    return {"quote": quote, "section": section, "element_type": element_type,
            "page": page, "bbox": bbox}


def _claim(measure, value_text, confidence, *, file=None, column=None, quote="",
           section="cell 0", element_type="output"):
    return {
        "value": 0.0, "value_text": value_text, "measure": measure, "subject": "",
        "claimed_provenance": {"file": file, "column": column, "cell": section,
                               "computation": None, "formula_hint": None},
        "source_span": _span(quote or value_text, section, element_type),
        "confidence": confidence,
    }


def _three_claim_graph():
    """accuracy (CONFIRMED) + auc (CONFIRMED) + total_return (REFUTED, highest conf -> headline)."""
    return {"claims": [
        _claim("accuracy", "0.90", 0.90, file="preds.csv",
               quote="accuracy = 0.90", section="cell 12"),
        _claim("auc", "1.0", 0.85, file="preds.csv",
               quote="AUC: 1.0", section="cell 13"),
        _claim("total_return", "+14,698%", 0.95, file="returns.csv",
               quote="+14,698% backtest", section="cell 14", element_type="code"),
    ]}


def _mixed_graph():
    """accuracy (CONFIRMED, highest conf -> headline) + total_return (REFUTED, non-headline) -> a
    non-headline REFUTED rolls the repo up to MIXED (ledger.compute_repo_verdict)."""
    return {"claims": [
        _claim("accuracy", "0.90", 0.95, file="preds.csv",
               quote="accuracy = 0.90", section="cell 12"),
        _claim("total_return", "+14,698%", 0.60, file="returns.csv",
               quote="+14,698% backtest", section="cell 14", element_type="code"),
    ]}


@pytest.fixture
def btc_like(tmp_path):
    dst = os.path.join(str(tmp_path), "btc_like")
    shutil.copytree(FIXT_TARGET, dst)
    return dst


def _by_metric(report, mid):
    return next((c for c in report.claims if c.metric_id == mid), None)


# --- acceptance tests --------------------------------------------------------------------------
def test_refuted_sorts_first_with_provenance_citation(btc_like):
    graph = _three_claim_graph()
    out = TC.verify_graph(graph, btc_like)
    rep = RC.render(graph, out)

    assert rep.repo_verdict in ("REFUTED", "MIXED")          # headline REFUTED -> repo REFUTED here
    # the catch sorts FIRST
    first = rep.claims[0]
    assert first.metric_id == "total_return"
    assert first.verdict in RC.CATCH_VERDICTS

    # CLARIESG citation: the source cell + BOTH numbers, rendered exactly as the engine prints them
    cit = first.citation
    assert "cell 14" in cit
    assert "+14,698%" in cit                                 # the claimed, fmt_value('147.0x (+14,698%)')
    assert "%" in cit and "31" in cit                        # the recomputed, fmt_value('-31.6%')
    assert RC._fmt(first.recomputed, "total_return") in cit  # verbatim engine formatting

    # the verdict word + numbers are copied VERBATIM from the engine (never paraphrased)
    eng_tr = next(m for m in out["engine"]["metrics"] if m["metric"] == "total_return")
    assert first.verdict == eng_tr["verdict"]
    assert first.claimed == eng_tr["claimed"] and first.recomputed == eng_tr["recomputed"]

    # fix is copied verbatim from the engine (DEVIATION: None for this value-mismatch REFUTED) -- pin the
    # premise (the engine really does emit None here) so the verbatim-copy invariant isn't vacuously true
    assert out["engine"]["fix"] is None
    assert rep.fix == out["engine"]["fix"]
    assert rep.target.endswith("btc_like")
    assert "3 numbers checked" in rep.summary


def test_multi_claim_mix_no_span_crosstalk(btc_like):
    graph = _mixed_graph()
    out = TC.verify_graph(graph, btc_like)
    rep = RC.render(graph, out)

    assert rep.repo_verdict == "MIXED"                       # non-headline REFUTED -> MIXED

    acc = _by_metric(rep, "accuracy")
    tr = _by_metric(rep, "total_return")
    assert acc is not None and tr is not None

    # each ClaimReport cites its OWN cell -- no span cross-talk
    assert acc.span["section"] == "cell 12" and "cell 12" in acc.citation
    assert tr.span["section"] == "cell 14" and "cell 14" in tr.citation
    assert "cell 14" not in acc.citation                     # accuracy never borrows the return's cell
    assert "cell 12" not in tr.citation

    # the catch still sorts ahead of the clean claim
    assert rep.claims[0].metric_id == "total_return"
    assert acc.verdict == "CONFIRMED" and tr.verdict == "REFUTED"


def test_handoff_mode_packages_original_claimed_value(btc_like):
    graph = _three_claim_graph()
    out = TC.verify_graph(graph, btc_like)
    result = RC.render(graph, out, mode="fix")

    assert isinstance(result, tuple) and len(result) == 2
    rep, handoffs = result
    assert isinstance(rep, RC.Report)

    # exactly one handoff (only the REFUTED total_return); the CONFIRMEDs are not handed off
    assert len(handoffs) == 1
    h = handoffs[0]
    assert h.metric_id == "total_return"
    assert os.path.isdir(h.run_dir)                          # the engine run dir really exists
    assert abs(h.claimed_value - 146.98) < 0.01             # the ORIGINAL claimed +14,698%, NOT -0.32
    assert h.claimed_value > 0                               # never the recomputed (negative) value
    assert h.span["section"] == "cell 14"                    # the refuted claim's own span


# --- unit coverage of the deterministic renderer -----------------------------------------------
def test_citation_templates_per_element_type():
    nb = RC._citation("accuracy", 0.94, 0.71,
                      {"element_type": "output", "section": "cell 14", "page": None})
    assert nb == "cell 14 says 0.94 -> recomputes to 0.71 [notebook cell 14]"

    pdf = RC._citation("sharpe", 1.85, 0.90,
                       {"element_type": "table", "section": "Table 2, Row 5", "page": 3})
    assert "p.3" in pdf and "Table 2, Row 5" in pdf and "sharpe" in pdf
    assert "claims" in pdf and "recomputes to" in pdf

    fb = RC._citation("row_count", 1000, 900,
                      {"element_type": "data", "section": None, "page": None})
    assert fb == "row_count: claimed 1,000 -> recomputed 900"


def test_render_to_json_matches_schema(btc_like):
    from jsonschema import validate
    graph = _three_claim_graph()
    rep = RC.render(graph, TC.verify_graph(graph, btc_like))
    validate(instance=rep.to_json(), schema=RC.REPORT_SCHEMA)   # raises on any drift
    # every per-claim verdict is a real engine enum (no invented words)
    for c in rep.claims:
        assert c.verdict in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED",
                             "INVALIDATED", "INCONCLUSIVE")


def test_join_routes_each_verdict_to_its_own_claim(btc_like):
    graph = _three_claim_graph()
    out = TC.verify_graph(graph, btc_like)
    pairs = RC._join(graph, out["engine"]["metrics"])
    by_mid = {em["metric"]: claim for em, claim in pairs}
    assert by_mid["accuracy"]["source_span"]["section"] == "cell 12"
    assert by_mid["auc"]["source_span"]["section"] == "cell 13"
    assert by_mid["total_return"]["source_span"]["section"] == "cell 14"
