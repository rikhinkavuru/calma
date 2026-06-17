"""P1.1 — Artifact ingestion adapters.

Turn any artifact (Jupyter .ipynb, PDF/report, CSV/parquet) into a normalized ArtifactBundle of
(a) text spans WITH provenance, and (b) the raw data files Calma will recompute over -- verbatim,
never rewritten. Pure stdlib parsing: no model, no network, no randomness. The only hard rule is
that a data file is left byte-identical so the engine's loader still parses it.
"""
from __future__ import annotations

import csv
import io  # noqa: F401  (kept per the P1.1 adapter signature; reserved for in-memory text buffers)
import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

# allow a large-but-BOUNDED CSV field (the stdlib default 128 KB raises csv.Error on an embedded
# JSON/base64 cell and would otherwise crash ingestion). 16 MB caps memory while parsing real-world cells.
try:
    csv.field_size_limit(16 * 1024 * 1024)
except (OverflowError, ValueError):                            # pragma: no cover - platform clamp
    csv.field_size_limit(2 ** 27)


@dataclass
class Span:
    text: str                                   # the literal text of this span
    provenance: dict                            # {document, section, page, element_type}
    bbox: Optional[list] = None                 # [x0,y0,x1,y1] for PDF blocks, else None
    source_kind: str = "text"                   # "code" | "output" | "markdown" | "pdf" | "data"

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class ArtifactBundle:
    root: str                                   # the artifact path (file) or dir
    spans: list = field(default_factory=list)   # list[Span]
    data_files: list = field(default_factory=list)  # absolute paths to recompute-able files
    kind: str = "unknown"                        # "notebook" | "pdf" | "csv" | "dir"
    figure_blocks: list = field(default_factory=list)  # PDF image-block bboxes (later VLM hook)

    def to_json(self) -> dict:
        return {"root": self.root, "kind": self.kind,
                "spans": [s.to_json() for s in self.spans],
                "data_files": list(self.data_files)}


# a printed/written value anywhere -> a fast existence test so a span with no value is dropped
_NUM = re.compile(r"[-+]?\$?\d[\d,]*\.?\d*%?|\.\d+")
# df.to_csv("x.csv") / .to_parquet('y.parquet') / np.savetxt("z.csv", ...) -> a written data file
_WRITE = re.compile(r"""\.to_(?:csv|parquet)\(\s*["']([^"']+)["']|savetxt\(\s*["']([^"']+)["']""")


def has_number(text: str) -> bool:
    return bool(_NUM.search(text or ""))


def _numeric_tokens(line: str) -> list:
    """Whitespace-separated tokens that are wholly a number ('1.85', '2024', '-3,000', '12%')."""
    return [t for t in (line or "").split() if _NUM.fullmatch(t)]


def _resolve_written(root_dir: str, name: str) -> Optional[str]:
    """Resolve a written-file name relative to the artifact's dir; return the abs path iff it now
    exists on disk (the run already produced it). Never invent a path that isn't there."""
    cand = name if os.path.isabs(name) else os.path.join(root_dir, name)
    cand = os.path.abspath(cand)
    return cand if os.path.isfile(cand) else None


def _output_text(out: dict) -> str:
    """Flatten one notebook output to text: a stream's text, an execute_result/display_data's
    text/plain, or an error's joined traceback. nbformat stores these as str OR list[str]."""
    ot = out.get("output_type")
    if ot == "stream":
        t = out.get("text", "")
        return "".join(t) if isinstance(t, list) else (t or "")
    if ot in ("execute_result", "display_data"):
        t = (out.get("data", {}) or {}).get("text/plain", "")
        return "".join(t) if isinstance(t, list) else (t or "")
    if ot == "error":
        tb = out.get("traceback", [])
        return "\n".join(tb) if isinstance(tb, list) else (tb or "")
    return ""


def ingest_notebook(path: str) -> ArtifactBundle:
    """Each code cell -> one 'code' Span (section='cell N'); each output -> an 'output' Span; each
    markdown cell -> a 'markdown' Span. Scan EVERY cell's source for written-file references ->
    _resolve_written -> data_files (dedup, order-preserving). Drop spans with no number EXCEPT
    markdown (it may caption a downstream number)."""
    with open(path, encoding="utf-8") as fh:
        nb = json.load(fh)
    root_dir = os.path.dirname(os.path.abspath(path))
    spans, data_files, seen = [], [], set()
    for i, cell in enumerate(nb.get("cells", [])):
        src = "".join(cell.get("source", []))
        ctype = cell.get("cell_type")
        for m in _WRITE.finditer(src):
            written = m.group(1) or m.group(2)
            full = _resolve_written(root_dir, written)
            if full and full not in seen:
                seen.add(full)
                data_files.append(full)
        if ctype == "code":
            if has_number(src):
                spans.append(Span(src, {"document": path, "section": "cell %d" % i,
                                        "page": None, "element_type": "code"},
                                  source_kind="code"))
            for out in cell.get("outputs", []):
                text = _output_text(out)
                if text and has_number(text):
                    spans.append(Span(text, {"document": path, "section": "cell %d" % i,
                                             "page": None, "element_type": "output"},
                                      source_kind="output"))
        elif ctype == "markdown":
            spans.append(Span(src, {"document": path, "section": "cell %d" % i,
                                    "page": None, "element_type": "markdown"},
                              source_kind="markdown"))
    return ArtifactBundle(path, spans, data_files, kind="notebook")


def _pdf_element_type(line_texts: list, *, page_has_figure: bool) -> str:
    """A block whose lines form a grid (>=2 lines that each carry >=2 numeric tokens) is a 'table';
    a single short line on a page that also holds a figure is a 'caption'; otherwise 'paragraph'."""
    grid_lines = sum(1 for ln in line_texts if len(_numeric_tokens(ln)) >= 2)
    if grid_lines >= 2:
        return "table"
    if page_has_figure and len(line_texts) == 1 and len(line_texts[0].strip()) <= 60:
        return "caption"
    return "paragraph"


def ingest_pdf(path: str) -> ArtifactBundle:
    """PyMuPDF text+bbox pass (PlotPick pattern). Each text block -> a Span whose text joins the
    block's lines, bbox=[x0,y0,x1,y1], page=1-based; element_type by the grid/caption heuristic.
    Image blocks are recorded on bundle.figure_blocks for a later VLM pass (no model called here).
    Spans with no number are dropped; a PDF carries no recompute-able file (data_files stays empty)."""
    import fitz  # lazy: the module imports without PyMuPDF; only PDF ingestion needs it
    try:
        doc = fitz.open(path)
    except Exception:                                          # malformed / encrypted / zero-byte PDF
        return ArtifactBundle(path, [], [], kind="pdf")        # a bad PDF yields nothing, never raises
    spans, figure_blocks = [], []
    try:
        for pno in range(doc.page_count):
            page = doc[pno]
            d = page.get_text("dict")
            blocks = d.get("blocks", [])
            page_has_figure = any(b.get("type") == 1 for b in blocks)
            for blk in blocks:
                if blk.get("type") != 0:                       # image / non-text block
                    figure_blocks.append({"page": pno + 1, "bbox": list(blk.get("bbox", []))})
                    continue
                line_texts = ["".join(sp.get("text", "") for sp in ln.get("spans", []))
                              for ln in blk.get("lines", [])]
                text = "\n".join(line_texts).strip()
                if not has_number(text):
                    continue
                et = _pdf_element_type(line_texts, page_has_figure=page_has_figure)
                bbox = [float(x) for x in blk.get("bbox", [])] or None
                spans.append(Span(text, {"document": path, "section": None, "page": pno + 1,
                                         "element_type": et}, bbox=bbox, source_kind="pdf"))
    finally:
        doc.close()
    b = ArtifactBundle(path, spans, [], kind="pdf")
    b.figure_blocks = figure_blocks
    return b


def _csv_summary(path: str, sample_cap: int = 200) -> str:
    """A compact, deterministic one-line description the extractor can read (mirrors the engine's
    own CSV loader: header row then rows via csv.reader). Counts ALL rows for the shape but only
    samples up to sample_cap rows for the dtype/min..max guess. No row data leaves -- summary only."""
    name = os.path.basename(path)
    with open(path, newline="") as fh:
        rd = csv.reader(fh)
        header = next(rd, None)
        if header is None:
            return "%s: empty (no header row)" % name
        samples = [[] for _ in header]
        nrows = 0
        for row in rd:
            nrows += 1
            if nrows <= sample_cap:
                for idx in range(len(header)):
                    samples[idx].append(row[idx] if idx < len(row) else "")
    parts = []
    for idx, col in enumerate(header):
        parts.append("%s(%s)" % (col, _describe_column(samples[idx])))
    return "%s: %d rows x %d cols; columns: %s" % (name, nrows, len(header), ", ".join(parts))


# the same NA tokens the engine's loader treats as missing (kept in sync by mirroring its list)
_NA_TOKENS = ("", "nan", "na", "null", "none")


def _describe_column(values: list) -> str:
    """Cheap dtype guess + min..max over a column's sampled cells (int-like / float / string)."""
    nums, all_int, any_num = [], True, False
    for v in values:
        s = (v or "").strip()
        if s == "" or s.lower() in _NA_TOKENS:
            continue
        try:
            f = float(s)
        except ValueError:
            return "string"
        any_num = True
        nums.append(f)
        if "." in s or "e" in s.lower():
            all_int = False
    if not any_num:
        return "string"
    lo, hi = min(nums), max(nums)
    # 'inf'/'-inf'/'nan' parse as floats with no '.'/'e', so all_int can stay True -> int(inf) would
    # raise OverflowError and crash ingest. Only take the int path when both ends are finite.
    finite = lo == lo and hi == hi and lo not in (float("inf"), float("-inf")) \
        and hi not in (float("inf"), float("-inf"))
    if all_int and finite:
        return "int %d..%d" % (int(lo), int(hi))
    return "float %g..%g" % (lo, hi)   # %g renders inf/nan without crashing


def ingest_csv(path: str) -> ArtifactBundle:
    """The file itself is a data_file (untouched). Emit ONE 'data' summary Span. parquet: read the
    schema only (pyarrow if present, else dtype 'unknown')."""
    abspath = os.path.abspath(path)
    text = _parquet_summary(abspath) if path.lower().endswith(".parquet") else _csv_summary(abspath)
    # source_kind is 'data'; element_type uses the nearest provenance-enum bucket ('table'), since
    # 'data' is not an element_type value.
    span = Span(text, {"document": path, "section": None, "page": None,
                       "element_type": "table"}, source_kind="data")
    return ArtifactBundle(path, [span], [abspath], kind="csv")


def _parquet_summary(path: str) -> str:
    """Schema-only summary for a parquet file. pyarrow if present, else dtype 'unknown'."""
    name = os.path.basename(path)
    try:
        import pyarrow.parquet as pq
    except Exception:
        return "%s: parquet (schema unknown -- pyarrow not installed)" % name
    pf = pq.ParquetFile(path)
    schema = pf.schema_arrow
    nrows = pf.metadata.num_rows if pf.metadata is not None else 0
    cols = ["%s(%s)" % (schema.field(i).name, schema.field(i).type) for i in range(len(schema))]
    return "%s: %d rows x %d cols; columns: %s" % (name, nrows, len(cols), ", ".join(cols))


_SUFFIX_DISPATCH = {".ipynb": "notebook", ".pdf": "pdf", ".csv": "csv", ".parquet": "csv"}


def ingest(path: str) -> ArtifactBundle:
    """Dispatch by suffix: .ipynb->notebook, .pdf->pdf, .csv/.parquet->csv. A DIRECTORY -> walk it
    (sorted, deterministic), ingest each recognized file, MERGE spans, UNION data_files, kind='dir'.
    Unknown suffix -> an empty bundle (kind='unknown') -- never raise on a stray file."""
    if os.path.isdir(path):
        spans, data_files, seen = [], [], set()
        for dp, dirnames, names in os.walk(path):
            dirnames.sort()
            for n in sorted(names):
                if n.startswith("."):
                    continue
                suf = os.path.splitext(n)[1].lower()
                if suf not in _SUFFIX_DISPATCH:
                    continue
                try:
                    sub = ingest(os.path.join(dp, n))         # one malformed file must not lose the rest
                except Exception:                             # noqa: BLE001 - "never raise on a stray file"
                    continue
                spans.extend(sub.spans)
                for f in sub.data_files:
                    if f not in seen:
                        seen.add(f)
                        data_files.append(f)
        return ArtifactBundle(path, spans, data_files, kind="dir")

    suf = os.path.splitext(path)[1].lower()
    kind = _SUFFIX_DISPATCH.get(suf)
    if kind == "notebook":
        return ingest_notebook(path)
    if kind == "pdf":
        return ingest_pdf(path)
    if kind == "csv":
        return ingest_csv(path)
    return ArtifactBundle(path, [], [], kind="unknown")


# The ArtifactBundle JSON Schema (what ingest(...).to_json() emits) -- the P1.1 contract.
ARTIFACT_BUNDLE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "ArtifactBundle",
    "type": "object",
    "required": ["root", "kind", "spans", "data_files"],
    "additionalProperties": False,
    "properties": {
        "root": {"type": "string"},
        "kind": {"enum": ["notebook", "pdf", "csv", "dir", "unknown"]},
        "data_files": {"type": "array", "items": {"type": "string"}},
        "spans": {"type": "array", "items": {
            "type": "object",
            "required": ["text", "provenance", "source_kind"],
            "additionalProperties": False,
            "properties": {
                "text": {"type": "string"},
                "source_kind": {"enum": ["code", "output", "markdown", "pdf", "data"]},
                "bbox": {"oneOf": [{"type": "null"},
                         {"type": "array", "items": {"type": "number"},
                          "minItems": 4, "maxItems": 4}]},
                "provenance": {
                    "type": "object",
                    "required": ["document", "element_type"],
                    "additionalProperties": False,
                    "properties": {
                        "document": {"type": "string"},
                        "section": {"type": ["string", "null"]},
                        "page": {"type": ["integer", "null"]},
                        "element_type": {"enum": ["code", "output", "markdown", "paragraph",
                                                  "table", "caption", "figure"]},
                    },
                },
            },
        }},
    },
}
