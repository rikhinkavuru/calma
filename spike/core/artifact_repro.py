"""core.artifact_repro — artifact-reproduction verification (the "re-run the paper" mode).

The beachhead eval found the gap: an eval/benchmark repo that ships a `reproduce.py` + committed result files
(a leaderboard CSV, a metrics JSON) derives those numbers with CUSTOM code (not a hookable sklearn call), so
Calma's capture-and-recompute path verifies nothing. But there is a check that needs NO capture, NO binding,
and NO disambiguation: **re-run the repro entrypoint, then diff the regenerated result files against the
committed ones.** Deterministic file-level reproduction —
  - every committed numeric cell regenerates within tolerance  → the committed results REPRODUCE,
  - a cell differs                                              → that committed number does NOT reproduce,
naming the exact file + cell. This opens the reproducible-research companion-repo niche.

This module is PURE (stdlib only, no engine/verdict imports) so it stays outside the FCR firewall by
construction — it produces a structured reproduction report; it never authors a CONFIRMED/REFUTED verdict
itself (the caller decides how to surface it, gated behind an opt-in flag). Snapshot the committed artifacts
BEFORE the run (the run overwrites them), then diff against what the run regenerated.

Telemetry cells (runtime/timestamp/…) are excluded — they legitimately change every run and are not results.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re

# result-file discovery (mirrors runner.build's conventions; kept local so this module stays self-contained)
_ARTIFACT_DIRS = ("results", "result", "output", "outputs", "artifacts", "reports", "eval", "evaluation")
_ARTIFACT_ROOT_NAMES = ("results.json", "metrics.json", "result.json", "scores.json", "eval.json",
                        "results.csv", "metrics.csv", "leaderboard.csv", "leaderboard.json", "summary.json")
_ARTIFACT_EXTS = (".csv", ".tsv", ".json")            # parquet needs pyarrow — kept out of the stdlib core
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".ipynb_checkpoints"}
_MAX_FILES = 60
_MAX_BYTES = 5_000_000
_MAX_CELLS = 20_000

# Numeric cells that are execution TELEMETRY, not results — they change every run, so diffing them yields
# spurious "not reproduced". Matched against the cell key (JSON path / CSV column), case-insensitive.
_TELEMETRY = re.compile(
    r"runtime|elapsed|duration|second|_secs?\b|latency|wall|timestamp|_time\b|\btime\b|date|"
    r"created|updated|memory|_ram\b|cpu_|_ms\b|throughput|speed|epoch_time", re.I)


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _num(s):
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _csv_cells(path: str, delim: str) -> dict:
    """Numeric cells of a CSV/TSV → {key: value}. Key is `<row-id>|<col>` when the first column is a
    non-numeric label (model/dataset name — stable under row reorder), else `<row-index>|<col>`."""
    out: dict = {}
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.reader(fh, delimiter=delim)
            rows = list(reader)
    except (OSError, csv.Error):
        return out
    if not rows:
        return out
    header = rows[0]
    id_col = 0 if (len(rows) > 1 and _num(rows[1][0] if rows[1] else "") is None) else None
    for i, row in enumerate(rows[1:]):
        rid = row[id_col] if (id_col is not None and id_col < len(row)) else str(i)
        for j, cell in enumerate(row):
            if id_col is not None and j == id_col:
                continue
            v = _num(cell)
            if v is None:
                continue
            col = header[j] if j < len(header) else "c%d" % j
            key = "%s|%s" % (rid, col)
            if not _TELEMETRY.search(key):
                out[key] = v
            if len(out) >= _MAX_CELLS:
                return out
    return out


def _json_cells(path: str) -> dict:
    """Numeric leaves of a JSON doc → {dotted.path: value}. Telemetry paths skipped."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    out: dict = {}

    def walk(node, prefix):
        if len(out) >= _MAX_CELLS:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, "%s.%s" % (prefix, k) if prefix else str(k))
        elif isinstance(node, list):
            for idx, v in enumerate(node):
                walk(v, "%s[%d]" % (prefix, idx))
        elif _is_num(node):
            if not _TELEMETRY.search(prefix):
                out[prefix] = float(node)

    walk(doc, "")
    return out


def _read_artifact(path: str) -> dict:
    low = path.lower()
    if low.endswith(".json"):
        return _json_cells(path)
    if low.endswith(".tsv"):
        return _csv_cells(path, "\t")
    if low.endswith(".csv"):
        return _csv_cells(path, ",")
    return {}


def find_artifacts(repo_dir: str) -> list[str]:
    """Repo-relative paths of committed result files (bounded). Root-level canonical names + anything under a
    results/ output/ reports/ eval/ dir with a result extension."""
    found: list[str] = []
    for name in _ARTIFACT_ROOT_NAMES:
        p = os.path.join(repo_dir, name)
        if os.path.isfile(p):
            found.append(name)
    for d in _ARTIFACT_DIRS:
        dd = os.path.join(repo_dir, d)
        if not os.path.isdir(dd):
            continue
        for root, dirs, files in os.walk(dd):
            dirs[:] = [x for x in dirs if x not in _SKIP_DIRS]
            for fn in sorted(files):
                if not fn.lower().endswith(_ARTIFACT_EXTS):
                    continue
                fp = os.path.join(root, fn)
                try:
                    if os.path.getsize(fp) > _MAX_BYTES:
                        continue
                except OSError:
                    continue
                rel = os.path.relpath(fp, repo_dir)
                if rel not in found:
                    found.append(rel)
                if len(found) >= _MAX_FILES:
                    return found
    return found


def snapshot(repo_dir: str, rels: list[str] | None = None) -> dict:
    """{relpath: {cellkey: value}} for the committed result artifacts. Pass `rels` to snapshot a specific set
    (e.g. the same files after a run); default discovers them."""
    rels = rels if rels is not None else find_artifacts(repo_dir)
    snap: dict = {}
    for rel in rels:
        cells = _read_artifact(os.path.join(repo_dir, rel))
        if cells:
            snap[rel] = cells
    return snap


def _close(a: float, b: float, rtol: float, atol: float) -> bool:
    return abs(a - b) <= atol + rtol * abs(b)


def diff(before: dict, after: dict, *, rtol: float = 1e-6, atol: float = 1e-9) -> dict:
    """Compare a committed snapshot (`before`) to a regenerated one (`after`). Reproduction is per numeric
    cell, float-tolerant. Returns a structured report; `status` is:
      - 'reproduced'     — every committed cell that was regenerated matches within tolerance,
      - 'not-reproduced' — at least one committed cell regenerated to a different value,
      - 'incomplete'     — no committed artifact / nothing regenerated to compare against (fail-closed).
    A cell present in `before` but absent from `after` (the run didn't regenerate that file/cell) is counted
    as `not_regenerated`, never as a mismatch — we only claim non-reproduction on a value that changed."""
    changed: list[dict] = []
    n_match = n_changed = n_missing = 0
    compared_files = 0
    for rel, cells in before.items():
        after_cells = after.get(rel)
        if not after_cells:
            n_missing += len(cells)
            continue
        compared_files += 1
        for key, bval in cells.items():
            if key not in after_cells:
                n_missing += 1
                continue
            if _close(bval, after_cells[key], rtol, atol):
                n_match += 1
            else:
                n_changed += 1
                if len(changed) < 200:
                    changed.append({"file": rel, "cell": key, "committed": bval,
                                    "regenerated": after_cells[key]})
    compared = n_match + n_changed
    if compared == 0:
        status = "incomplete"
    elif n_changed == 0:
        status = "reproduced"
    else:
        status = "not-reproduced"
    return {"status": status, "n_files": compared_files, "n_compared": compared, "n_match": n_match,
            "n_changed": n_changed, "n_not_regenerated": n_missing, "changed": changed}
