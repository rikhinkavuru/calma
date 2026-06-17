"""P1.1 acceptance tests — artifact ingestion adapters.

Pure parsing, no API key, no model. Fixtures live in tests/fixtures/artifacts/ and were produced
once by _gen_fixtures.py (committed binaries). The hard invariant under test: ingestion leaves any
recompute-able data file byte-identical.
"""
import os

import pytest

from edges.extract import ingest

FIXT = os.path.join(os.path.dirname(__file__), "fixtures", "artifacts")
NB = os.path.join(FIXT, "nb_three_metrics.ipynb")
PDF = os.path.join(FIXT, "report_one_page.pdf")
CSV = os.path.join(FIXT, "preds.csv")


def _validate(bundle):
    """Every emitted bundle must satisfy the published ArtifactBundle JSON Schema."""
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(instance=bundle.to_json(), schema=ingest.ARTIFACT_BUNDLE_SCHEMA)


def test_dir_walk_survives_a_malformed_file_and_keeps_the_good_ones(tmp_path):
    """The contract is 'never raise on a stray file'. A malformed PDF + an oversized-cell CSV must be
    skipped, not abort the whole bundle and lose the good notebook."""
    import json as _json
    d = str(tmp_path)
    open(os.path.join(d, "bad.pdf"), "w").write("this is not a pdf")
    open(os.path.join(d, "huge.csv"), "w").write("a,b\n" + ("x" * 200000) + ",2\n3,4\n")
    nb = {"cells": [{"cell_type": "code", "source": ["print('acc = 0.91')\n"],
                     "outputs": [{"output_type": "stream", "name": "stdout", "text": ["acc = 0.91\n"]}]}],
          "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    _json.dump(nb, open(os.path.join(d, "good.ipynb"), "w"))

    bundle = ingest.ingest(d)                                  # must not raise
    assert any("0.91" in (s.text or "") for s in bundle.spans)   # the good notebook survived


def test_inf_csv_cell_does_not_crash(tmp_path):
    open(os.path.join(str(tmp_path), "x.csv"), "w").write("revenue,n\ninf,5\n2,6\n")
    bundle = ingest.ingest(str(tmp_path))                      # int(inf) used to crash here
    assert bundle.kind == "dir"


def test_notebook_spans_provenance_and_written_file():
    b = ingest.ingest(NB)
    assert b.kind == "notebook"
    metric_cells = [s for s in b.spans if s.provenance.get("section") in ("cell 12", "cell 13", "cell 14")]
    assert len(metric_cells) >= 3
    assert os.path.abspath(CSV) in b.data_files          # df.to_csv("preds.csv") resolved to disk
    for s in b.spans:
        assert s.provenance.get("document")
        assert s.provenance.get("element_type")
    _validate(b)


def test_notebook_data_files_are_deduped_and_existing_only():
    b = ingest.ingest(NB)
    # only files that actually exist are listed, and never duplicated
    assert b.data_files == list(dict.fromkeys(b.data_files))
    for f in b.data_files:
        assert os.path.isfile(f)


def test_pdf_table_block_carries_bbox_page_and_value():
    pytest.importorskip("fitz")
    p = ingest.ingest(PDF)
    assert p.kind == "pdf"
    tables = [s for s in p.spans
              if s.provenance.get("element_type") == "table"
              and s.bbox is not None and len(s.bbox) == 4
              and "1.85" in s.text and s.provenance.get("page") == 1]
    assert tables, "expected a table span with a 4-tuple bbox, '1.85', and page==1"
    _validate(p)


def test_csv_summary_span_and_byte_identity():
    before = open(CSV, "rb").read()
    c = ingest.ingest(CSV)
    assert c.kind == "csv"
    assert c.data_files == [os.path.abspath(CSV)]
    data_spans = [s for s in c.spans if s.source_kind == "data"]
    assert len(data_spans) == 1
    text = data_spans[0].text
    assert "y_true" in text and "y_pred" in text          # names both columns
    after = open(CSV, "rb").read()
    assert before == after                                # NEVER rewrites a recompute-able file
    _validate(c)


def test_csv_summary_reports_full_row_count():
    c = ingest.ingest(CSV)
    assert "1000 rows" in c.spans[0].text


def test_has_number():
    assert ingest.has_number("no digits here") is False
    assert ingest.has_number("rows=10000") is True


def test_directory_merges_spans_and_unions_data_files():
    d = ingest.ingest(FIXT)
    assert d.kind == "dir"
    # the notebook's spans and the csv's data span both made it in
    assert any(s.source_kind == "data" for s in d.spans)
    assert any(s.provenance.get("section") == "cell 14" for s in d.spans)
    assert os.path.abspath(CSV) in d.data_files
    assert d.data_files == list(dict.fromkeys(d.data_files))   # unioned, no dups
    _validate(d)


def test_unknown_suffix_is_empty_bundle_not_an_error(tmp_path):
    stray = tmp_path / "notes.txt"
    stray.write_text("hello 123")
    b = ingest.ingest(str(stray))
    assert b.kind == "unknown"
    assert b.spans == [] and b.data_files == []


def test_resolve_written_drops_absent_targets(tmp_path):
    # a written-file reference whose target does not exist must NOT be fabricated into data_files
    assert ingest._resolve_written(str(tmp_path), "does_not_exist.csv") is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
