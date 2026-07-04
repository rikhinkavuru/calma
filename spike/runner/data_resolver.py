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
import shutil
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


def _url_is_safe(url) -> bool:
    """SSRF/LFI guard for an outbound data fetch derived from search results (not a fixed host). Requires an
    http(s) scheme (blocks file:// local-file reads, ftp/gopher) and rejects any host that resolves to a
    private / loopback / link-local / reserved IP (blocks localhost, 10.x/192.168.x, and the 169.254.169.254
    cloud-metadata endpoint). Not a full DNS-rebinding defense, but it closes the obvious internal-reach paths.
    """
    import ipaddress  # noqa: PLC0415
    import socket  # noqa: PLC0415
    from urllib.parse import urlparse  # noqa: PLC0415
    try:
        p = urlparse(url)
    except (ValueError, AttributeError):
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    try:
        infos = socket.getaddrinfo(p.hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def fetch_to(url, dest, timeout=40, max_bytes=80_000_000):
    """Download a data URL to dest (size-capped, creating parent dirs best-effort). Returns bytes or None.
    Refuses non-http(s) schemes and internal/private hosts (SSRF/LFI guard) — the URL comes from untrusted
    search results, so it is never trusted to reach the local filesystem or an internal service."""
    safe_url = _raw(url)
    if not _url_is_safe(safe_url):
        return None
    try:
        with urllib.request.urlopen(safe_url, timeout=timeout) as fh:  # noqa: S310 - scheme+host validated above
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


def _contained(path, root):
    """True iff the canonical `path` is inside canonical `root` (path-traversal / arbitrary-write guard)."""
    try:
        p = os.path.realpath(path)
        r = os.path.realpath(root)
    except OSError:
        return False
    return p == r or p.startswith(r + os.sep)


def relink_committed_data(repo_dir, missing_path):
    """A run failed reading `missing_path`, but that file's basename IS committed elsewhere in the repo (a
    different subdir than the code reads). Place a copy where the code reads it — supplying the input WITHOUT
    editing the repo's compute, so the verdict stays fully eligible (no source change, no network, no cost).

    Only handles a RELATIVE read path (a real in-repo mismatch: code reads 'data/train.csv', file committed at
    'train.csv'); an ABSOLUTE read (a hardcoded C:\\… or a Colab /content/…) is out of scope here — it needs
    sandbox placement or a source rewrite (which the snapshot rail then caps). Writes ONLY inside repo_dir.
    Returns the placed repo-relative path, or None. Fail-closed: a wrong copy can only produce a mismatch
    (→ REFUTED / INCONCLUSIVE), never a false CONFIRM (the recompute still verifies the value)."""
    raw = str(missing_path or "").replace("\\", "/")
    base = os.path.basename(raw)
    if not base or "." not in base:
        return None
    if raw.startswith("/") or re.match(r"^[a-zA-Z]:", raw):       # absolute — relink can't honor it in-repo
        return None
    src = None
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
        if base in files and os.path.isfile(os.path.join(root, base)):
            src = os.path.join(root, base)
            break
    if not src:
        return None
    dst = os.path.normpath(os.path.join(repo_dir, raw))
    if not _contained(dst, repo_dir) or os.path.abspath(dst) == os.path.abspath(src):
        return None
    try:
        os.makedirs(os.path.dirname(dst) or repo_dir, exist_ok=True)
        if not os.path.exists(dst):
            shutil.copy2(src, dst)
        return os.path.relpath(dst, repo_dir)
    except OSError:
        return None


def _norm(p):
    # backslashes → forward, then COLLAPSE repeats: a traceback shows an escaped 'D:\\a\\b' (double
    # backslash), so a naive replace yields 'D://a//b' — collapse to match the source literal's 'D:/a/b'.
    return re.sub(r"/+", "/", str(p or "").replace("\\", "/")).rstrip("/")


def _find_committed(repo_dir, base):
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
        if base in files and os.path.isfile(os.path.join(root, base)):
            return os.path.join(root, base)
    return None


def _rewrite_notebook(nb_path, forms, new_rel):
    """Replace a hardcoded data path (in any of `forms` — raw/escaped/forward-slash) with `new_rel` inside a
    notebook's code-cell sources. String replace (cells aren't cleanly AST-parseable line-by-line). Returns
    True if it changed anything."""
    try:
        with open(nb_path, errors="replace") as fh:
            nb = json.load(fh)
    except (OSError, ValueError):
        return False
    changed = False
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        srcs = cell.get("source")
        seq = srcs if isinstance(srcs, list) else [srcs or ""]
        out = []
        for line in seq:
            new = line
            for f in forms:
                if f and f in new:
                    new = new.replace(f, new_rel)
            if new != line:
                changed = True
            out.append(new)
        cell["source"] = out if isinstance(srcs, list) else out[0]
    if changed:
        try:
            with open(nb_path, "w") as fh:
                json.dump(nb, fh)
        except OSError:
            return False
    return changed


def rewrite_data_path(repo_dir, missing_path, new_rel):
    """Rewrite the hardcoded data-path STRING LITERAL `missing_path` (an absolute 'C:\\ml\\x.csv' or a Colab
    '/content/x.csv') to `new_rel` in the repo's .py, so the run finds data placed at new_rel. This IS a source
    edit — used only in the orchestrate path, where the surrounding before/after snapshot flags it and the rail
    caps the verdict at REPRODUCED-ONLY (a REFUTED misreport is unaffected). Only the EXACT matching path
    literal is touched (AST-located, single-line span replacement; formatting/comments preserved). Returns the
    list of modified repo-relative files."""
    import ast
    target = _norm(missing_path)                             # forward-single-slash canonical, e.g. D:/a/b.csv
    # every backslash variant the SAME path can take in source (json.load gives the cell value 1 backslash;
    # the traceback text has 2) — built from the canonical so 1-bs, 2-bs and forward-slash all match.
    _forms = sorted({target, target.replace("/", "\\"), target.replace("/", "\\\\")}, key=len, reverse=True)
    modified: list = []
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
        for fn in files:
            if fn.endswith(".ipynb"):
                nbp = os.path.join(root, fn)
                if _rewrite_notebook(nbp, _forms, new_rel):
                    modified.append(os.path.relpath(nbp, repo_dir))
                continue
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            try:
                src = open(path, errors="replace").read()
                tree = ast.parse(src)
            except (OSError, SyntaxError, ValueError):
                continue
            spans = [(n.lineno, n.col_offset, n.end_lineno, n.end_col_offset)
                     for n in ast.walk(tree)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str) and _norm(n.value) == target
                     and getattr(n, "end_col_offset", None) is not None]
            spans = [s for s in spans if s[0] == s[2]]        # single-line literals only
            if not spans:
                continue
            lines = src.split("\n")
            for lineno, c1, _l2, c2 in sorted(spans, reverse=True):
                line = lines[lineno - 1]
                lines[lineno - 1] = line[:c1] + repr(new_rel) + line[c2:]
            try:
                with open(path, "w") as fh:
                    fh.write("\n".join(lines))
                modified.append(os.path.relpath(path, repo_dir))
            except OSError:
                pass
    return modified


# csv basenames that are OUTPUTS, not the input dataset — never the sole-dataset source
_OUTPUT_CSV = ("result", "metric", "score", "pred", "output", "summary", "leaderboard", "submission",
               "sample_submission")
_DATA_SUFFIX = (".csv", ".tsv", ".data", ".xlsx", ".parquet")


def _sole_committed_dataset(repo_dir):
    """The ONE committed input dataset (excluding results/predictions outputs), if EXACTLY one exists — for a
    repo that hardcodes a data path to a differently-named file that is nonetheless its single committed
    dataset. 0 or >1 candidates → ambiguous → None (refuse, never guess between datasets). FCR-safe: a wrong
    dataset can only mismatch the recompute, never manufacture a CONFIRM."""
    cands = []
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
        for fn in files:
            low = fn.lower()
            if low.endswith(_DATA_SUFFIX) and not any(t in low for t in _OUTPUT_CSV):
                cands.append(os.path.join(root, fn))
                if len(cands) > 1:
                    return None
    return cands[0] if len(cands) == 1 else None


def make_data_available(repo_dir, missing_path):
    """Make a missing input available so a run proceeds. Returns (placed_rel, modified_files). Modes:
      • RELATIVE read of a committed basename → relink in place (no source edit → full verdict).
      • ABSOLUTE read (Colab /content, hardcoded C:\\…) → copy the committed file to repo-root/basename AND
        rewrite the literal (source edit → orchestrate snapshot caps it to REPRODUCED-ONLY; REFUTED unaffected).
      • basename not committed, but the missing file is data AND the repo has exactly ONE committed dataset →
        use that (a hardcoded path to a renamed/moved single dataset).
    Committed data only here (no network); a wrong file can only mismatch, never a false CONFIRM."""
    placed = relink_committed_data(repo_dir, missing_path)
    if placed:
        return placed, []
    raw = str(missing_path or "").replace("\\", "/")
    base = os.path.basename(raw)
    if not base or "." not in base:
        return None, []
    is_abs = bool(raw.startswith("/") or re.match(r"^[a-zA-Z]:", str(missing_path or "")))
    src = _find_committed(repo_dir, base)
    if not src and base.lower().endswith(_DATA_SUFFIX):
        src = _sole_committed_dataset(repo_dir)               # differently-named single committed dataset
    if not src:
        return None, []                                       # (a catalog/Exa fetch could place it — separate)
    if is_abs:
        dst = os.path.join(repo_dir, base)
        try:
            if os.path.abspath(dst) != os.path.abspath(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
        except OSError:
            return None, []
        modified = rewrite_data_path(repo_dir, missing_path, base)
        return (base, modified) if modified else (None, [])
    # relative read, basename not committed but a sole dataset found → place it at the exact read path
    dst = os.path.normpath(os.path.join(repo_dir, raw))
    if not _contained(dst, repo_dir):
        return None, []
    try:
        os.makedirs(os.path.dirname(dst) or repo_dir, exist_ok=True)
        if not os.path.exists(dst):
            shutil.copy2(src, dst)
    except OSError:
        return None, []
    return os.path.relpath(dst, repo_dir), []


def resolve_missing_data(repo_dir, missing_path, key=None):
    """Find + fetch the dataset a repo expects at `missing_path` (e.g. '/content/data.csv') via Exa, and place
    it at repo_dir/<basename> — the safe, primary path (the re-run's CWD is repo_dir, so a relative or a
    Colab-style absolute path both resolve there for the common case). `missing_path` is parsed out of the
    REPO'S OWN stderr (missing_data_path's regex over the traceback), so it is attacker-influenced: a crafted
    "FileNotFoundError: '/etc/cron.d/x'" is enough to make this function want to write to an arbitrary host
    path. It never does — a second write is only attempted when `missing_path` (once resolved) is ALSO inside
    repo_dir; any path outside is refused, full stop, no silent redirect. Returns (ok, note). Gated: no key ->
    a clear paid-tier message, never an error."""
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
    if missing_path.startswith("/") and _contained(missing_path, repo_dir):
        fetch_to(url, missing_path)     # best-effort: ALSO place at the absolute path, but only inside repo_dir
    if not n:
        return False, "found %s but the download failed" % url
    return True, "fetched %s (%d bytes) from %s" % (name, n, url)


def resolve_file_url(path, context="", model=None):
    """Resolve the canonical public https download URL for a SPECIFIC missing file (given its exact path — from
    the repo's own error — and context about the repo's datasets), via a small focused model call. Used by the
    reactive acquire resolve loop when the deterministic catalog doesn't cover the file. Returns the URL or None.

    Best-effort + gated: no ANTHROPIC_API_KEY → None. FCR-safe: a wrong URL fetches wrong data, which is capped
    to INCONCLUSIVE downstream (never a false verdict) — so this can propose without risking correctness."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    model = model or os.environ.get("CALMA_PLAN_MODEL", "claude-haiku-4-5")
    try:
        import anthropic
        client = anthropic.Anthropic()
        system = (
            "You resolve public research-dataset download URLs. Given the file path a repository needs and "
            "context about its datasets, output the SINGLE canonical, current, public https:// download URL for "
            "that EXACT file. Output ONLY the URL and nothing else, or an empty response if you do not know the "
            "precise URL. Never invent a URL you aren't confident is real — a wrong URL is worse than none. "
            "For a HuggingFace dataset file use https://huggingface.co/datasets/<org>/<name>/resolve/main/<file>."
        )
        msg = "File the repo needs: %s\nRepo dataset context: %s\nCanonical https download URL:" % (
            path, str(context or "")[:1500])
        resp = client.messages.create(model=model, max_tokens=300, system=system,
                                       messages=[{"role": "user", "content": msg}])
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
    except Exception:  # noqa: BLE001 — resolution is best-effort; any failure → no URL
        return None
    m = re.search(r"https://[^\s'\"<>)]+", text)
    url = m.group(0) if m else None
    return url if (url and len(url) <= 2048) else None
