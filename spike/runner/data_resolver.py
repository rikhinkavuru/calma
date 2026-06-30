"""runner.data_resolver — opt-in external-data fetch for the run workflow.

Many real repos (especially notebooks) read data they don't ship: a Colab `/content/...` path, a `kaggle
datasets download`, a bare `pd.read_csv("data.csv")`. The run then fails "missing input file". When the
operator/tier enables it, this finds a downloadable MIRROR of that dataset via the Exa API and places it so
the re-run proceeds. Best-effort + gated (a paid-tier capability; free tiers are run/rate-limited instead).

Safety: this only FETCHES data files (size-capped, data extensions) — it never executes anything. The
untrusted repo code still runs in its sandbox; this just supplies the inputs it asked for.

Needs EXA_API_KEY. Pure stdlib (urllib + json).
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

_EXA_SEARCH = "https://api.exa.ai/search"
_DATA_EXT = (".csv", ".tsv", ".data", ".json", ".txt", ".parquet", ".xlsx")
# kaggle slugs / dataset references in code+README that tell us WHAT data the repo wants
_KAGGLE_RE = re.compile(r"(?:datasets download -d\s+|kaggle\.com/datasets/)([\w.-]+/[\w.-]+)")
# the file a "missing input" failure tried to open
_MISSING_RE = re.compile(r"No such file or directory:?\s*'([^']+)'|FileNotFoundError[^']*'([^']+)'")


def missing_data_path(err):
    """The DATA file a 'missing input' failure tried to open (only data extensions are fetchable), else None."""
    if not err:
        return None
    m = _MISSING_RE.search(err)
    p = (m.group(1) or m.group(2)) if m else None
    return p if (p and p.lower().endswith(_DATA_EXT)) else None


def dataset_hints(repo_dir):
    """Dataset identifiers referenced in the repo (kaggle slugs) — used to target the search."""
    hints = set()
    if not os.path.isdir(repo_dir):
        return []
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in files:
            if not fn.endswith((".py", ".md", ".txt", ".ipynb", ".rst")):
                continue
            try:
                text = open(os.path.join(root, fn), errors="replace").read()[:40000]
            except OSError:
                continue
            for m in _KAGGLE_RE.finditer(text):
                hints.add(m.group(1))
    return sorted(hints)


def _exa_search(query, key, n=8, timeout=25):
    body = json.dumps({"query": query, "numResults": n}).encode()
    req = urllib.request.Request(_EXA_SEARCH, data=body, method="POST",
                                 headers={"x-api-key": key, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return [r.get("url") for r in (json.load(fh).get("results") or []) if r.get("url")]


def _raw(url):
    """Normalize a github blob URL to its raw form (directly fetchable)."""
    if "github.com" in url and "/blob/" in url:
        return url.replace("github.com/", "raw.githubusercontent.com/").replace("/blob/", "/")
    return url


def _pick_url(urls):
    """Prefer a directly-fetchable raw data file (raw github + a data extension), then any data-extension URL."""
    norm = [_raw(u) for u in urls]
    raws = [u for u in norm if "raw.githubusercontent.com" in u and u.lower().endswith(_DATA_EXT)]
    if raws:
        return raws[0]
    anydata = [u for u in norm if u.lower().endswith(_DATA_EXT)]
    return anydata[0] if anydata else None


def fetch_to(url, dest, timeout=40, max_bytes=80_000_000):
    """Download a data URL to dest (size-capped, creating parent dirs best-effort). Returns bytes or None."""
    try:
        with urllib.request.urlopen(_raw(url), timeout=timeout) as fh:
            data = fh.read(max_bytes + 1)
    except Exception:  # noqa: BLE001
        return None
    if not data or len(data) > max_bytes:
        return None
    try:
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as out:
            out.write(data)
    except OSError:
        return None
    return len(data)


def resolve_missing_data(repo_dir, missing_path, key=None):
    """Find + fetch the dataset a repo expects at `missing_path` (e.g. '/content/data.csv') via Exa, and place
    it at repo_dir/<basename> AND (best-effort) the absolute path the code used, so the re-run finds it.
    Returns (ok, note). Gated: no key -> a clear paid-tier message, never an error."""
    key = key or os.environ.get("EXA_API_KEY")
    if not key:
        return False, "external-data fetch is a paid-tier feature (no EXA_API_KEY configured)"
    name = os.path.basename(missing_path.rstrip("/")) or "dataset.csv"
    ext = (os.path.splitext(name)[1].lstrip(".") or "csv")
    hints = dataset_hints(repo_dir)
    target = " ".join(hints) if hints else os.path.splitext(name)[0]
    query = ("raw downloadable %s file of the dataset %s, hosted on github raw.githubusercontent.com"
             % (ext, target))
    try:
        urls = _exa_search(query, key)
    except Exception as e:  # noqa: BLE001
        return False, "exa search failed: %s" % str(e)[:120]
    url = _pick_url(urls)
    if not url:
        return False, "no directly-downloadable data file found for %r" % (hints or name)
    n = fetch_to(url, os.path.join(repo_dir, name))
    if missing_path.startswith("/"):
        fetch_to(url, missing_path)                   # best-effort: also place at the absolute path the code used
    if not n:
        return False, "found %s but the download failed" % url
    return True, "fetched %s (%d bytes) from %s" % (name, n, url)
