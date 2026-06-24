"""One path-containment guard, shared by every reader that joins a CONTRACT-supplied relative path
onto a base dir. A counterparty verify.yaml is untrusted input: `split.train: ../../etc/passwd`
must never resolve to a read outside the contract's base. Symlinks are resolved (realpath) so a
symlinked escape is caught too. Pure stdlib.

Usage:  path = safe_join(base, contract["split"]["train"])   # raises ValueError on escape
"""
import csv
import os

# The artifact byte-cap (also the recompute reference cap). An artifact is emitted by the UNTRUSTED
# entrypoint and then read by the HOST verifier OUTSIDE the sandbox; a hostile multi-GB CSV must not OOM
# the verifier, and a FIFO/socket/device must never be open()'d (it would block forever). Generous vs any
# real artifact (Numerai/Gauntlet datasets are a few MB); override with CALMA_MAX_ARTIFACT_MB.
MAX_ARTIFACT_BYTES = int(float(os.environ.get("CALMA_MAX_ARTIFACT_MB", "256")) * 1024 * 1024)

# The streaming path's row wall + per-field cap. The 256 MB byte cap above stays the guard for the EAGER
# (whole-file) read; a streaming reader keeps the DoS property differently — constant memory, a bounded row
# count, and a per-field byte cap so a pathological no-newline multi-GB line raises instead of OOMing. Both
# are generous vs any real tournament file (Numerai v5 validation ~1M rows). Override via env.
MAX_STREAM_ROWS = int(float(os.environ.get("CALMA_MAX_STREAM_ROWS", "200000000")))
MAX_CSV_FIELD_BYTES = int(float(os.environ.get("CALMA_MAX_CSV_FIELD_MB", "16")) * 1024 * 1024)


def within_cap(path, max_bytes=None):
    """True iff `path` is a REGULAR file within the artifact byte-cap. The one shared guard every detector
    reader uses to fail-soft (abstain / return empty) instead of OOMing the host verifier on a hostile
    multi-GB CSV or blocking forever on a planted FIFO/device. Missing/non-regular/over-cap -> False (the
    reader's existing fail-soft path). max_bytes defaults to MAX_ARTIFACT_BYTES."""
    try:
        if not os.path.isfile(path):  # follows symlinks; False for missing/dir/FIFO/socket/device
            return False
        cap = MAX_ARTIFACT_BYTES if max_bytes is None else max_bytes
        return os.path.getsize(path) <= cap
    except OSError:
        return False


def iter_csv_chunks(path, columns=None, chunksize=65536, max_rows=None):
    """Stream a CSV in constant memory as {col: [str, ...]} chunks of `chunksize` rows — the streaming
    counterpart to the eager `recompute._load_cols`, used for genuinely-large (over-byte-cap) artifacts.
    Keeps the hostile-file DoS property WITHOUT the 256 MB cap: a regular-file check (no FIFO/device/dir
    that would block or isn't a file), a per-field byte cap (a no-newline multi-GB line raises instead of
    OOMing), and a cumulative row wall (MAX_STREAM_ROWS). `columns=None` reads every column; a list projects
    to that subset (others are not retained). Raises ValueError on a non-regular file, an empty/header-less
    file, a requested column absent from the header, or an over-wall row count."""
    if not os.path.isfile(path):    # follows symlinks; False for missing/dir/FIFO/socket/device
        raise ValueError("artifact %s is not a regular file" % os.path.basename(path))
    wall = MAX_STREAM_ROWS if max_rows is None else max_rows
    prev_limit = csv.field_size_limit(MAX_CSV_FIELD_BYTES)
    try:
        with open(path, newline="") as fh:
            rd = csv.reader(fh)
            header = next(rd, None)
            if header is None:
                raise ValueError("artifact %s is empty (no header row)" % os.path.basename(path))
            proj = [h for h in header if (columns is None or h in columns)]
            if columns is not None and not proj:
                raise ValueError("none of the requested columns %r are in artifact %s"
                                 % (list(columns), os.path.basename(path)))
            col_idx = [(h, i) for i, h in enumerate(header) if h in proj]
            chunk = {h: [] for h in proj}
            n_in_chunk = 0
            seen = 0
            for row in rd:
                seen += 1
                if seen > wall:
                    raise ValueError("artifact %s exceeds the %d-row streaming wall (raise "
                                     "CALMA_MAX_STREAM_ROWS for a genuinely larger file)"
                                     % (os.path.basename(path), wall))
                for h, i in col_idx:
                    chunk[h].append(row[i] if i < len(row) else "")
                n_in_chunk += 1
                if n_in_chunk >= chunksize:
                    yield chunk
                    chunk = {h: [] for h in proj}
                    n_in_chunk = 0
            if n_in_chunk:
                yield chunk
    finally:
        csv.field_size_limit(prev_limit)


def safe_join(base, rel):
    """Join `rel` onto `base` and confirm the result stays inside `base` (after resolving symlinks).
    Returns the absolute real path; raises ValueError if `rel` escapes the base."""
    full = os.path.realpath(os.path.join(base, rel))
    rb = os.path.realpath(base)
    if full != rb and not full.startswith(rb + os.sep):
        raise ValueError("path escapes the contract base: %r" % rel)
    return full


def is_contained(base, rel):
    """True iff `rel` joined onto `base` stays inside `base` (no exception form of safe_join)."""
    try:
        safe_join(base, rel)
        return True
    except ValueError:
        return False


def guard_out_dir(out_dir, source_dir):
    """L2: validate a user-supplied --out for a writer (registry site / evidence bundle). Returns the
    resolved real path, or raises ValueError when --out: (a) IS the source dir, or (b) is an ANCESTOR
    of the source - a parent/`..`-traversal that would write up the tree and could clobber or escape
    the source's own location. An arbitrary sibling / absolute target the user names is allowed (the
    writers are designed to deposit a pack anywhere); the guard's job is the parent-traversal the old
    `out != source` check missed. Local / low-severity."""
    out_r = os.path.realpath(out_dir)
    src_r = os.path.realpath(source_dir)
    if out_r == src_r:
        raise ValueError("--out must differ from the source dir itself")
    if src_r == out_r or src_r.startswith(out_r + os.sep):
        raise ValueError("--out %r is an ancestor of the source dir - refusing (a parent-traversal "
                         "that would write up/over the tree)" % out_dir)
    return out_r
