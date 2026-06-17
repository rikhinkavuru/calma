"""P1.2 acceptance tests -- the claim-graph extractor.

The LLM-routed paths replay from recorded fixtures (edges/tests/fixtures/<hash>.json); the suite needs
no ANTHROPIC_API_KEY. Record the fixtures ONCE with the strong/cheap models live:

    CALMA_EDGES_RECORD=1 ANTHROPIC_API_KEY=... \
        PYTHONPATH=. ~/.cache/calma-edges-venv/bin/python edges/tests/test_extract.py --record

(That runs THIS module as a script, not under pytest -- conftest.py pops CALMA_EDGES_RECORD so the
suite never records.) Then `pytest edges/tests/test_extract.py` replays them with the var unset.

Request hashes are deterministic: the prompts embed only span text + provenance (document reduced to a
basename, never a checkout-specific absolute path) + the bootstrap example, so the same bundles always
produce the same fixture keys.
"""
import os

import pytest

from edges.common import llm, record
from edges.extract import extract, ingest

FIXT = os.path.join(os.path.dirname(__file__), "fixtures", "artifacts")
NB = os.path.join(FIXT, "nb_three_metrics.ipynb")


# --- the bundles under test (shared with the recording entrypoint below) -----------------------
def _notebook_bundle():
    return ingest.ingest(NB)


def _routing_bundle():
    """A single pure-`simple` span: must route to the no-LLM heuristic path."""
    sp = ingest.Span("rows=10000", {"document": "ledger.ipynb", "section": "cell 3",
                                    "page": None, "element_type": "code"}, source_kind="code")
    return ingest.ArtifactBundle("ledger.ipynb", [sp], [], kind="notebook")


def _recall_bundle():
    """A simple span with NO metric word -- high recall still extracts it as measure='unknown'."""
    sp = ingest.Span("computed offset 0.0037 for calibration",
                     {"document": "nb.ipynb", "section": "cell 7", "page": None,
                      "element_type": "code"}, source_kind="code")
    return ingest.ArtifactBundle("nb.ipynb", [sp], [], kind="notebook")


def _bootstrap_bundle():
    """Two near-identical table-row spans (each 2 numeric tokens -> `moderate`)."""
    spans = [
        ingest.Span("BTC strategy 1.85 0.32",
                    {"document": "report.pdf", "section": "Table 1", "page": 3,
                     "element_type": "table"}, bbox=[72.0, 120.0, 300.0, 135.0], source_kind="pdf"),
        ingest.Span("ETH strategy 1.40 0.21",
                    {"document": "report.pdf", "section": "Table 1", "page": 3,
                     "element_type": "table"}, bbox=[72.0, 135.0, 300.0, 150.0], source_kind="pdf"),
    ]
    return ingest.ArtifactBundle("report.pdf", spans, [], kind="pdf")


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


def _structured_reqs(seen):
    return [r for r in seen if "tools" in r]


def _plain_reqs(seen):
    return [r for r in seen if "tools" not in r]


# --- acceptance tests --------------------------------------------------------------------------
def test_notebook_extracts_three_metrics_with_provenance():
    bundle = _notebook_bundle()
    g = extract.extract(bundle)
    claims = g["claims"]
    assert len(claims) >= 3

    measures = {c["measure"] for c in claims}
    assert "accuracy" in measures
    assert "auc" in measures
    assert any("f1" in m.lower() for m in measures), measures   # a macro-F1 measure

    # the published graph schema validates (extract() also validates internally)
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(instance=g, schema=extract.GRAPH_SCHEMA)

    real_cells = {s.provenance.get("section") for s in bundle.spans}
    DC = extract._dc()
    for c in claims:
        assert c["source_span"]["section"] in real_cells          # no span cross-talk
        v, _ = DC.parse_claim(c["value_text"])                    # value agrees with value_text
        assert v is not None
        assert abs(v - c["value"]) <= max(1e-9, 1e-6 * abs(v))


def test_high_recall_keeps_unknown_measure():
    g = extract.extract(_recall_bundle())
    assert len(g["claims"]) == 1
    claim = g["claims"][0]
    assert claim["measure"] == "unknown"
    assert abs(claim["value"] - 0.0037) <= 1e-9


def test_simple_span_routes_with_zero_llm_requests(llm_spy):
    g = extract.extract(_routing_bundle())
    assert len(llm_spy) == 0                                        # NO model call on the heuristic path
    assert len(g["claims"]) == 1
    assert g["claims"][0]["measure"] in ("row_count", "unknown")


def test_bootstrap_is_one_strong_call_then_haiku_rows(llm_spy):
    g = extract.extract(_bootstrap_bundle())
    assert len(g["claims"]) >= 2                                    # one claim per table row (>=)

    plain = _plain_reqs(llm_spy)
    structured = _structured_reqs(llm_spy)
    # exactly one strong-model bootstrap_example call ...
    assert len(plain) == 1
    assert plain[0]["model"] == llm.SONNET
    # ... and the per-row extractions are HAIKU structured calls
    assert len(structured) >= 2
    assert all(r["model"] == llm.HAIKU for r in structured)


def test_classify_routing_buckets():
    s = ingest.Span("accuracy = 0.94", {"document": "d", "section": "cell 1", "page": None,
                                        "element_type": "output"}, source_kind="output")
    assert extract.classify(s) == "simple"
    m = ingest.Span("BTC strategy 1.85 0.32", {"document": "d", "section": "t", "page": 1,
                                               "element_type": "table"}, source_kind="pdf")
    assert extract.classify(m) == "moderate"
    c = ingest.Span("as computed above in cell 14, the Sharpe is 1.85",
                    {"document": "d", "section": "cell 20", "page": None,
                     "element_type": "markdown"}, source_kind="markdown")
    assert extract.classify(c) == "complex"


# --- recording entrypoint (NOT pytest; run as a script with CALMA_EDGES_RECORD=1) --------------
def _record_all():
    assert os.environ.get("CALMA_EDGES_RECORD") == "1", \
        "set CALMA_EDGES_RECORD=1 (and ANTHROPIC_API_KEY) to record"
    # Exercise every LLM-routed bundle so its bootstrap + per-span requests are saved as fixtures.
    for build in (_notebook_bundle, _bootstrap_bundle):
        g = extract.extract(build())
        print("recorded %d claims for %s" % (len(g["claims"]), build.__name__))


if __name__ == "__main__":
    _record_all()
