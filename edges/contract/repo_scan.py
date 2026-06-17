"""Pure-stdlib repo fingerprint / inputs assembly for A2 (no LLM, no network). Everything is sorted and
deterministic so the model's evidence packet -- hence the recorded LLM request hash -- is reproducible
across runs and checkouts (paths are repo-relative; no absolute path leaks into the packet)."""
import csv
import os
import re

try:
    csv.field_size_limit(16 * 1024 * 1024)                     # bounded; default 128 KB crashes on big cells
except (OverflowError, ValueError):                            # pragma: no cover
    csv.field_size_limit(2 ** 27)

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".calma", ".calma_venv",
              ".pytest_cache", ".mypy_cache", "venv", ".idea", ".vscode"}
_READ_CAP = 1_000_000                                          # per-file source read cap (fingerprint scan)

# framework -> import/dependency token regex (scanned over .py sources + requirement/dep manifests)
_FRAMEWORKS = {
    "sklearn": r"\bsklearn\b|scikit-learn",
    "lightgbm": r"\blightgbm\b",
    "xgboost": r"\bxgboost\b",
    "pytorch": r"\btorch\b|pytorch",
    "tensorflow": r"\btensorflow\b|\bkeras\b",
    "statsmodels": r"\bstatsmodels\b",
    "backtrader": r"\bbacktrader\b",
    "dbt": r"\bdbt\b",
    "pandas": r"\bpandas\b",
    "numpy": r"\bnumpy\b",
    "scipy": r"\bscipy\b",
    "polars": r"\bpolars\b",
}

_ENTRY_HINT_FILES = ("run.sh", "main.py", "gen_fixture.py", "Makefile", "run.py", "app.py",
                     "train.py", "evaluate.py", "pipeline.py")


def _walk_files(repo_path, *, cap=2000):
    out = []
    for dp, dirs, names in os.walk(repo_path):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        for n in sorted(names):
            out.append(os.path.relpath(os.path.join(dp, n), repo_path))
            if len(out) >= cap:
                return sorted(out)                            # sort even at the cap (determinism contract)
    return sorted(out)


def _read_capped(path):
    """Read at most _READ_CAP bytes of a source file, closing the handle (no leak, bounded memory)."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.read(_READ_CAP)
    except OSError:
        return None


def file_tree(repo_path, *, cap=400):
    """Repo-relative paths (dirs as 'name/'), sorted, capped, skipping vcs/cache noise. The WALK is also
    bounded (stop accumulating well past cap) so a millions-of-files repo can't materialize every path."""
    entries = []
    for dp, dirs, names in os.walk(repo_path):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        rel_dir = os.path.relpath(dp, repo_path)
        for d in dirs:
            p = d + "/" if rel_dir == "." else os.path.join(rel_dir, d) + "/"
            entries.append(p)
        for n in sorted(names):
            entries.append(n if rel_dir == "." else os.path.join(rel_dir, n))
        if len(entries) >= cap * 20:                          # bound the work; deterministic break point
            break
    entries = sorted(set(entries))
    return entries[:cap]


def fingerprint(repo_path):
    """Detected framework signatures (sorted), from import/dependency scans over the repo's sources."""
    found = set()
    for rel in _walk_files(repo_path):
        if not (rel.endswith((".py", ".txt", ".toml", ".cfg", ".r", ".R")) or
                os.path.basename(rel) in ("requirements.txt", "pyproject.toml", "setup.cfg")):
            continue
        src = _read_capped(os.path.join(repo_path, rel))
        if src is None:
            continue
        for fw, pat in _FRAMEWORKS.items():
            if re.search(pat, src):
                found.add(fw)
    return sorted(found)


def entrypoint_candidates(repo_path):
    """Ranked runnable-looking files: known entrypoint names first, then any .py with a __main__ guard."""
    cands, seen = [], set()

    def add(path, why):
        if path not in seen and os.path.isfile(os.path.join(repo_path, path)):
            seen.add(path)
            cands.append({"path": path, "why": why})

    files = _walk_files(repo_path)
    for rel in files:
        if os.path.basename(rel) in _ENTRY_HINT_FILES:
            add(rel, "a conventional entrypoint name (%s)" % os.path.basename(rel))
    for rel in files:
        if rel.endswith(".py"):
            src = _read_capped(os.path.join(repo_path, rel))
            if src is None:
                continue
            if "__main__" in src or re.search(r"^\s*def main\b", src, re.M):
                add(rel, "has a __main__ / main() entry")
    return cands


def scan_csv_heads(repo_path, *, max_files=40, preview_rows=8):
    """Every CSV the engine could recompute from: header + first ~8 raw data rows + shape, sorted by path.
    A malformed CSV (e.g. an over-limit field) is SKIPPED, not fatal -- one bad file must not abort the
    whole repo scan."""
    out = []
    for rel in _walk_files(repo_path):
        if not rel.lower().endswith(".csv"):
            continue
        path = os.path.join(repo_path, rel)
        try:
            with open(path, newline="", encoding="utf-8", errors="ignore") as fh:
                rd = csv.reader(fh)
                header = next(rd, None)
                if header is None:
                    continue
                rows, nrows = [], 0
                for row in rd:
                    nrows += 1
                    if nrows <= preview_rows:
                        rows.append(row)
        except (OSError, csv.Error):
            continue
        out.append({"path": rel, "header": header, "rows_preview": rows,
                    "n_cols": len(header), "approx_rows": nrows})
        if len(out) >= max_files:
            break
    return out
