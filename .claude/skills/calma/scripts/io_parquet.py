"""calma.io_parquet - WS-A: the OPTIONAL columnar (parquet) ingestion adapter (`pip install calma[parquet]`).

THE INVARIANT THIS PROTECTS: the pure-stdlib, zero-install core never imports pyarrow. This module does a
LAZY `import pyarrow.parquet` INSIDE the functions, so `import io_parquet` (and the whole recompute core)
pulls zero third-party modules; only an actual .parquet read triggers the import, and a missing pyarrow is
a clean "install calma[parquet]" message, never an ImportError traceback. A CI test asserts the core import
graph stays pyarrow-free (tests/test_parquet_io.py).

Why pyarrow only (research-settled, roadmap 6.1): it is reference-grade + spec-complete (all codecs/types),
has native column-projection + row-group streaming, and is the engine behind pandas.read_parquet. The pure-
python readers are read-only/unmaintained and still need a C snappy ext; fastparquet is retired; polars/
duckdb are large query runtimes with an accidentally-quadratic wide-file path. The cost (a bundled C++
runtime) is exactly why it lives in an EXTRA, not the core.

The two ICP traps it handles:
  - Numerai v5: `id` is the DataFrame INDEX (exposed here when requested - a stored pandas index level is a
    readable column); features are int8 and a naive float64 promotion bloats memory ~10x and loses the
    integer - so values are projected and stringified via the integer path, never coerced to float here.
    Project only [era, target, <prediction>] - full width is rarely needed to verify a metric.
  - CrunchDAO ADIA-Lab: `X` is an (id, time) MultiIndex - both levels are read as columns; flatten to
    [id, time, value, period] and join predictions to `y` on id.

Memory is bounded by a ROW-COUNT guard (not the on-disk size: column projection means a 500 MB / 1000-col
file costs only rows x projected-cols in memory), so the file-size artifact cap does not apply to parquet.

Library:
  read_columns(path, columns=None) -> {col: [str, ...]}   # the drop-in for the CSV column-dict
  iter_batches(path, columns=None, row_groups=None)        # constant-memory streaming (future fold)
  flatten_numerai(path, prediction="prediction") / flatten_crunch(path)  # ICP convenience projections
CLI:  python3 io_parquet.py FILE.parquet [--columns era,prediction,target] [--out data.csv]
"""
import argparse
import csv
import os
import sys

# bound the in-memory expansion: rows x projected-cols cells. A Numerai validation parquet is ~1M rows; a
# hostile file with billions of rows would OOM the host verifier even projected to a few columns. Generous
# vs any real tournament file; override with CALMA_MAX_PARQUET_ROWS.
_MAX_PARQUET_ROWS = int(float(os.environ.get("CALMA_MAX_PARQUET_ROWS", "20000000")))

_INSTALL_HINT = ("reading .parquet needs the optional dependency: pip install 'calma[parquet]' (pyarrow). "
                 "The pure-stdlib core never imports it; only an actual parquet read does.")


def _import_pq():
    """Lazy import of pyarrow.parquet, with a clean install hint (never a raw ImportError traceback)."""
    try:
        import pyarrow.parquet as pq  # noqa: PLC0415 - intentionally lazy (the load-bearing firewall)
        return pq
    except ImportError as e:
        raise ImportError(_INSTALL_HINT) from e


def _stringify(v):
    """Match the CSV reader's {col: [str]} contract WITHOUT a float promotion: an int8 stays an integer
    string (not '1.0'), None/NaN -> '' (the recompute NA path), everything else -> str."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float) and v != v:  # NaN
        return ""
    return str(v)


def _row_count(pf):
    try:
        return pf.metadata.num_rows
    except (AttributeError, OSError):
        return None


def read_columns(path, columns=None):
    """Read a parquet file into a {column: [str, ...]} dict (the drop-in for the stdlib CSV column-dict).
    `columns` projects to just those names (the rest of the wide file is never materialized); a requested
    name absent from the schema is skipped. Raises ImportError (install hint) without pyarrow, ValueError
    on a row count over the guard."""
    pq = _import_pq()
    pf = pq.ParquetFile(path)
    names = list(pf.schema_arrow.names)
    n = _row_count(pf)
    proj = [c for c in columns if c in names] if columns else names
    ncols = max(len(proj), 1)
    if n is not None and n * ncols > _MAX_PARQUET_ROWS * ncols and n > _MAX_PARQUET_ROWS:
        raise ValueError("parquet %s has %d rows, over the %d-row guard (raise CALMA_MAX_PARQUET_ROWS for a "
                         "genuinely large file, or stream it)" % (os.path.basename(path), n, _MAX_PARQUET_ROWS))
    table = pq.read_table(path, columns=proj) if proj else pq.read_table(path)
    out = {}
    for name in table.column_names:
        out[name] = [_stringify(v) for v in table.column(name).to_pylist()]
    return out


def iter_batches(path, columns=None, row_groups=None, batch_size=65536):
    """Constant-memory streaming over row groups (feeds the future streaming recompute fold). Yields
    {column: [str, ...]} batches. `columns` projects; `row_groups` restricts to specific groups."""
    pq = _import_pq()
    pf = pq.ParquetFile(path)
    names = list(pf.schema_arrow.names)
    proj = [c for c in columns if c in names] if columns else None
    for batch in pf.iter_batches(batch_size=batch_size, columns=proj, row_groups=row_groups):
        d = batch.to_pydict()
        yield {k: [_stringify(v) for v in vals] for k, vals in d.items()}


def flatten_numerai(path, prediction="prediction"):
    """Numerai v5 convenience: project [era, target, <prediction>] (the columns a metric needs), exposing
    the id index column if present. Returns the {col: [str]} dict."""
    cols = read_columns(path, columns=["id", "__index_level_0__", "era", "target", prediction])
    if "__index_level_0__" in cols and "id" not in cols:  # an unnamed stored index = the id
        cols["id"] = cols.pop("__index_level_0__")
    return cols


def flatten_crunch(path):
    """CrunchDAO ADIA-Lab convenience: read the (id, time, value, period) panel (both MultiIndex levels are
    columns) plus any structural_breakpoint/score label columns present. Returns the {col: [str]} dict."""
    return read_columns(path, columns=["id", "time", "value", "period", "structural_breakpoint", "score"])


def to_csv(path, out_csv, columns=None):
    """Materialize a (projected) parquet as a flat CSV - the 'no hand-flattening' on-ramp for a contract
    that points at a CSV. Returns the number of rows written."""
    cols = read_columns(path, columns=columns)
    names = list(cols)
    n = len(cols[names[0]]) if names else 0
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(names)
        for i in range(n):
            w.writerow([cols[c][i] for c in names])
    return n


def main():
    ap = argparse.ArgumentParser(description="Flatten a .parquet artifact to a CSV calma can recompute "
                                             "(optional dep: pip install 'calma[parquet]').")
    ap.add_argument("file")
    ap.add_argument("--columns", help="comma-separated columns to project (default: all)")
    ap.add_argument("--out", help="write a flat CSV here (default: print the projected column names + row count)")
    a = ap.parse_args()
    cols = a.columns.split(",") if a.columns else None
    if a.out:
        n = to_csv(a.file, a.out, columns=cols)
        print("wrote %d rows x %d cols -> %s" % (n, len(read_columns(a.file, columns=cols)), a.out))
    else:
        d = read_columns(a.file, columns=cols)
        print("columns: %s" % ", ".join(d))
        print("rows: %d" % (len(next(iter(d.values()))) if d else 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
