"""calma.spike.discovery.extract — claim discovery (rebuild guide §3 Stage-1 MAP, §5 "Discover claims").

Turn a repo into a list of **(metric, value, location)** claims — the canonical TDMR tuple — with NO
hand-specification. SOTA finding (guide §5): models nail Task/Dataset/Metric but struggle with the VALUE, so
the work is in robust value parsing + mapping the metric name onto the trusted catalog. This is the "free =
auto-discover" path; "paid = the user states the claim" simply skips this stage (and dissolves its errors).

Sources, most-structured first (structured = higher confidence):
  1. results.json / metrics.json / *_results.json — a flat/nested dict of name → number (wandb/mlflow-ish).
  2. README / markdown tables + "Metric: value" / "Metric = value" lines.
  3. captured stdout from the run ("accuracy=0.83").

A discovered claim carries a confidence and, when the name has a split prefix (test_/val_/train_), a split
hint the binder/verifier can use. Pure stdlib.
"""
from __future__ import annotations

import json
import os
import re

from core import catalog as C

# split prefixes a metric name may carry — strip them to find the metric, keep them as a binding hint
_SPLITS = ("test", "testing", "val", "valid", "validation", "holdout", "heldout", "eval", "dev", "oos",
           "train", "training")
# normalise the split token to a canonical form for downstream binding
_SPLIT_CANON = {"testing": "test", "valid": "val", "validation": "val", "heldout": "holdout",
                "training": "train"}

# keyword → catalog metric, for names the alias table doesn't catch verbatim
_KEYWORDS = [
    (("roc", "auc"), "roc_auc"), (("auroc",), "roc_auc"), (("auc",), "roc_auc"),
    (("balanced", "acc"), "balanced_accuracy"), (("accuracy",), "accuracy"), (("acc",), "accuracy"),
    (("macro", "f1"), "f1"), (("micro", "f1"), "f1"), (("f1",), "f1"), (("fscore",), "f1"),
    (("precision",), "precision"), (("recall",), "recall"),
    (("rmse",), "rmse"), (("mae",), "mae"), (("mse",), "mse"),
    (("r2",), "r2"), (("rsquared",), "r2"),
    (("sharpe",), "sharpe"),
    # metrics outside the curated catalog — discoverable, then verified via the synth/store flywheel
    (("mcc",), "mcc"), (("matthews",), "mcc"), (("brier",), "brier"),
    (("cohen", "kappa"), "cohen_kappa"), (("kappa",), "cohen_kappa"), (("spearman",), "spearman"),
    # IR/ranking: "nDCG@5 (linear)"-style labels carry extra @k / qualifier tokens the exact-alias match
    # can't absorb (found in e2e testing on a real repo) — reachable only via the keyword fallback.
    (("ndcg",), "ndcg"),
    # NB: mean/sum/average are intentionally NOT greedy keywords — they over-match column names like
    # "auroc_mean"/"peak_ram_mb_mean". They stay reachable via an exact alias (a column literally "mean").
]


def map_metric(name: str):
    """(canonical_metric or None, split_hint or None, confidence). Tries the catalog alias table first
    (high confidence), then keyword tokens (medium)."""
    raw = (name or "").strip().lower()
    if not raw:
        return None, None, 0.0
    # detect + strip a split prefix/suffix token
    tokens = re.split(r"[^a-z0-9]+", raw)
    split = next((t for t in tokens if t in _SPLITS), None)
    if split is not None:
        split = _SPLIT_CANON.get(split, split)
    core_tokens = [t for t in tokens if t and t not in _SPLITS]
    core = "_".join(core_tokens)
    cid = C.canonical(core) or C.canonical(raw)
    if cid:
        return cid, split, 0.9
    tokset = set(core_tokens)
    for keys, metric in _KEYWORDS:
        if all(k in tokset for k in keys):
            return metric, split, 0.6
    return None, None, 0.0


def _value_str(v) -> str | None:
    """Render a discovered numeric value as the string a producer would have written (preserve precision)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int,)):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return v.strip()
    return None


def _flatten(obj, prefix=""):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_flatten(v, "%s.%s" % (prefix, k) if prefix else str(k)))
    elif isinstance(obj, list):
        # a list of homogeneous result dicts (e.g. [{"model": "resnet", "accuracy": 0.9}, ...]) — index it so
        # the path stays unique; a row's own id fields become that cell's context downstream.
        for i, v in enumerate(obj):
            out.extend(_flatten(v, "%s.%d" % (prefix, i) if prefix else str(i)))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.append((prefix, obj))
    return out


def _metric_in_path(components):
    """A nested results.json encodes a leaderboard: {"resnet": {"cifar10": {"accuracy": 0.9}}} or the
    transpose {"accuracy": {"cifar10": 0.9}}. Find WHICH path component is the metric (prefer the leaf, then
    search inward) — the rest are the cell's context (dataset/model/split labels). Returns
    (metric_idx, cid, split, conf) or (None, None, None, 0.0). This is what lets a nested leaderboard bind
    per-cell instead of collapsing to one ambiguous metric."""
    for idx in range(len(components) - 1, -1, -1):
        cid, split, conf = map_metric(components[idx])
        if cid:
            return idx, cid, split, conf
    return None, None, None, 0.0


def from_results_json(path) -> list[dict]:
    try:
        with open(path) as fh:
            data = json.loads(fh.read(8_000_000))   # bounded read — a giant results file can't OOM the API
    except (OSError, ValueError):
        return []
    claims = []
    for name, val in _flatten(data):
        components = name.split(".")
        idx, cid, split, conf = _metric_in_path(components)
        if not cid:
            continue
        vs = _value_str(val)
        if vs is None:
            continue
        # every path component other than the metric one labels this cell — join as context so the
        # context-aware binder can pin each leaderboard entry to its own computation (SAFE: names, never value)
        ctx = " ".join(c for i, c in enumerate(components) if i != idx and not c.isdigit())[:90]
        claim = {"metric": cid, "value": vs, "location": "%s::%s" % (os.path.basename(path), name),
                 "source": "results-json", "confidence": conf}
        if ctx:
            claim["context"] = ctx
        if split:
            claim["split"] = split
        claims.append(claim)
    return claims


# "Accuracy: 0.83", "test AUC = 0.91", "F1 0.72", "Accuracy: 96.67%", "nDCG@5 (linear): 0.947" (a real repo
# shape found in e2e testing — @k and a parenthetical qualifier are common on ranking/retrieval metric labels)
_KV_RE = re.compile(r"([A-Za-z][A-Za-z0-9 _\-/@()]{1,40}?)\s*[:=]\s*([-+]?\d*\.?\d+%?)")
# markdown table row: | Accuracy | 0.83 |
_ROW_RE = re.compile(r"\|\s*([A-Za-z][A-Za-z0-9 _\-/@()]{1,40}?)\s*\|\s*([-+]?\d*\.?\d+%?)\s*\|")

# PROSE forms the "Metric: value" patterns miss (the SOTA value-parse weak spot): a metric word and a nearby
# number, in either order. map_metric() is the precision gate — only a span that maps to a real catalog
# metric becomes a claim — so the patterns can be generous. Lower-confidence than structured.
_MW = (r"(balanced[\s_-]*accuracy|accuracy|acc|auroc|roc[\s_-]*auc|auc|f1[\s_-]*score|f1|f-score|"
       r"matthews|mcc|kappa|rmse|mae|mse|r\^?2|r[\s_-]?squared|precision|recall|sharpe)")
_VAL = r"([-+]?\d*\.?\d+\s*%?)"
_SPLIT_W = (r"(?:test|testing|val|valid|validation|holdout|held[\s-]*out|train|training|overall|final|"
            r"mean|average|macro|micro|weighted)")
# value then metric: "96.67% accuracy", "0.88 AUROC", "95% test accuracy"
_PROSE_VM = re.compile(_VAL + r"[\s-]+(?:" + _SPLIT_W + r"[\s-]+){0,2}" + _MW, re.I)
# metric then value via a connector: "F1 score of 0.72", "accuracy of 0.83", "AUC was 0.91", "came out to 95%"
_PROSE_MV = re.compile(_MW + r"[\w\s,'\-]{0,25}?(?:\bof\b|\bwas\b|\bis\b|\bto\b|[:=])\s*" + _VAL, re.I)


def _is_num(s):
    """A results-cell numeric value (accepts a trailing % and surrounding whitespace). Returns the cleaned
    string to use as the claim value, or None."""
    v = (s or "").strip()
    if not v:
        return None
    try:
        float(v[:-1] if v.endswith("%") else v)
    except ValueError:
        return None
    return v


# a GFM table separator row: | --- | :--: | --- |  (cells are only dashes/colons/spaces)
_SEP_RE = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|[\s:|-]*$")


def _split_row(line):
    """Split a markdown table row into trimmed cells, dropping the empty edges from leading/trailing pipes."""
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return cells


def from_markdown_tables(text, location="text") -> list[dict]:
    """Parse WIDE leaderboard tables — the 'paper Table 3' shape where metrics are COLUMN headers and each row
    is a model/dataset:

        | Model  | Dataset | Accuracy | Macro F1 |
        |--------|---------|----------|----------|
        | ResNet | CIFAR10 | 0.912    | 0.889    |

    Metric columns map to the catalog; the remaining labelled columns become each row's context
    (Model=ResNet Dataset=CIFAR10) so the binder can pin each cell to its own computation. The 2-column
    transpose form (| Metric | Value |) is intentionally left to from_text's _ROW_RE — its headers don't map
    to a metric, so those tables are skipped here (no double-count). Pure stdlib."""
    if not text or "|" not in text:
        return []
    lines = text.splitlines()
    claims: list = []
    i = 0
    while i < len(lines) - 1:
        line = lines[i]
        if "|" not in line or not _SEP_RE.match(lines[i + 1]):
            i += 1
            continue
        header = _split_row(line)
        metric_cols = {}          # col-index → (cid, split)
        ctx_idx = []              # col-indexes that label the row (non-metric, non-empty headers)
        for ci, h in enumerate(header):
            cid, split, _conf = map_metric(h)
            if cid:
                metric_cols[ci] = (cid, split)
            elif h:
                ctx_idx.append(ci)
        if not metric_cols:
            i += 2                # header + separator; not a wide metrics table (transpose/other)
            continue
        j = i + 2
        while j < len(lines) and "|" in lines[j] and not _SEP_RE.match(lines[j]):
            cells = _split_row(lines[j])
            if len(cells) >= len(header):
                ctx = " ".join("%s=%s" % (header[c], cells[c]) for c in ctx_idx
                               if c < len(cells) and cells[c])[:90]
                for ci, (cid, split) in metric_cols.items():
                    if ci >= len(cells):
                        continue
                    vs = _is_num(cells[ci])
                    if vs is None:
                        continue
                    claim = {"metric": cid, "value": vs, "location": "%s::%s%s" % (
                        location, header[ci], " [%s]" % ctx if ctx else ""),
                        "source": "md-table", "confidence": 0.85}
                    if ctx:
                        claim["context"] = ctx
                    if split:
                        claim["split"] = split
                    claims.append(claim)
            j += 1
        i = j
    return claims


def from_text(text, location="text") -> list[dict]:
    if not text:
        return []
    claims, seen = [], set()
    for rx, src in ((_ROW_RE, "table"), (_KV_RE, "text")):
        for m in rx.finditer(text):
            name, val = m.group(1), m.group(2)
            cid, split, conf = map_metric(name)
            if not cid:
                continue
            key = (cid, val)
            if key in seen:
                continue
            seen.add(key)
            claim = {"metric": cid, "value": val.strip(), "location": location,
                     "source": src, "confidence": conf * (1.0 if src == "table" else 0.85)}
            if split:
                claim["split"] = split
            claims.append(claim)
    # prose pass (metric↔value in either order); structured matches already in `seen` win
    for rx, mi, vi in ((_PROSE_MV, 1, 2), (_PROSE_VM, 2, 1)):
        for m in rx.finditer(text):
            name, val = m.group(mi), m.group(vi).replace(" ", "")
            cid, split, conf = map_metric(name)
            if not cid:
                continue
            key = (cid, val)
            if key in seen:
                continue
            seen.add(key)
            claim = {"metric": cid, "value": val.strip(), "location": location,
                     "source": "prose", "confidence": conf * 0.7}
            if split:
                claim["split"] = split
            claims.append(claim)
    # wide leaderboard tables (metric COLUMNS, one row per model/dataset). These carry per-row context, so
    # they bypass the (metric, value) seen-gate above — two rows sharing a metric+value for different
    # datasets are distinct claims, not a dup; discover()'s (metric, value, context) dedupe is the backstop.
    claims.extend(from_markdown_tables(text, location=location))
    return claims


_RESULT_FILES = ("results.json", "metrics.json", "result.json", "scores.json", "eval.json")

# columns used to LABEL a row's claims (context), not themselves metrics
_CONTEXT_COLS = ("dataset", "data", "model", "method", "task", "name", "config", "split", "split_source",
                 "group", "fold", "seed", "k", "encoder", "approach", "system", "run")


def from_results_csv(path, max_claims=400) -> list[dict]:
    """Discover claims from a WIDE results table (columns named after metrics, e.g. results.csv with
    accuracy/auroc/mcc columns; each row a dataset/model). Only columns that map to a catalog metric become
    claims; data CSVs (no metric columns) are skipped after a cheap header read. Each claim carries a
    context label built from id columns (dataset=… model=… k=…) so it is meaningful."""
    import csv
    claims: list = []
    try:
        with open(path, newline="", errors="replace") as fh:
            rd = csv.DictReader(fh)
            header = rd.fieldnames or []
            metric_cols = {}
            for col in header:
                cid, _split, _conf = map_metric(col)
                if cid:
                    metric_cols[col] = cid
            if not metric_cols:
                return []                      # not a metrics table (e.g. a data/splits CSV)
            ctx_cols = [c for c in header if c.lower() in _CONTEXT_COLS]
            for row in rd:
                if len(claims) >= max_claims:
                    break
                ctx = " ".join("%s=%s" % (c, row[c]) for c in ctx_cols if row.get(c))[:90]
                for col, cid in metric_cols.items():
                    v = (row.get(col) or "").strip()
                    if not v:
                        continue
                    try:
                        float(v)
                    except ValueError:
                        continue
                    claims.append({"metric": cid, "value": v, "context": ctx,
                                   "location": "%s::%s%s" % (os.path.basename(path), col,
                                                             " [%s]" % ctx if ctx else ""),
                                   "source": "results-csv", "confidence": 0.85})
    except (OSError, csv.Error):
        return []
    return claims


def _candidate_csvs(repo_dir):
    """results-table CSVs to scan: top-level + one level under a results/ dir. Avoids walking data dirs."""
    out = []
    for fn in os.listdir(repo_dir) if os.path.isdir(repo_dir) else []:
        p = os.path.join(repo_dir, fn)
        if fn.lower().endswith(".csv") and os.path.isfile(p):
            out.append(p)
    for d in ("results", "result", "output", "outputs"):
        rd = os.path.join(repo_dir, d)
        if os.path.isdir(rd):
            for fn in os.listdir(rd):
                if fn.lower().endswith(".csv"):
                    out.append(os.path.join(rd, fn))
    return out


def from_notebook(path, max_claims=400) -> list[dict]:
    """Discover claims from a Jupyter notebook's COMMITTED cell outputs — a huge class of repos report their
    headline numbers ONLY in a notebook's rendered output (an `Accuracy: 0.94` print, a metrics-DataFrame
    repr, a classification report), which the json/csv/README scans never see. Reads code-cell outputs
    (stream text + execute_result/display_data `text/plain`) and markdown cells, then applies the same
    map_metric-gated text parse (the precision gate — only a span mapping to a catalog metric becomes a
    claim). Bounded read; FCR-safe (discovery only proposes numbers to CHECK, never a verdict)."""
    try:
        with open(path, errors="replace") as fh:
            nb = json.loads(fh.read(8_000_000))
    except (OSError, ValueError):
        return []
    parts: list[str] = []
    for cell in (nb.get("cells") or []):
        ctype = cell.get("cell_type")
        if ctype == "markdown":
            parts.append("".join(cell.get("source") or []))
        elif ctype == "code":
            for out in (cell.get("outputs") or []):
                if out.get("output_type") == "stream":
                    parts.append("".join(out.get("text") or []))
                elif out.get("output_type") in ("execute_result", "display_data"):
                    tp = (out.get("data") or {}).get("text/plain")
                    if tp:
                        parts.append("".join(tp) if isinstance(tp, list) else str(tp))
    text = "\n".join(parts)
    if not text.strip():
        return []
    claims = from_text(text[:2_000_000], location=os.path.basename(path))
    for c in claims:
        c["source"] = "notebook-output"
    return claims[:max_claims]


def _candidate_notebooks(repo_dir):
    """Committed notebooks in a directory to scan for reported numbers (bounded)."""
    out = []
    try:
        for fn in sorted(os.listdir(repo_dir)):
            if fn.lower().endswith(".ipynb") and os.path.isfile(os.path.join(repo_dir, fn)):
                out.append(os.path.join(repo_dir, fn))
    except OSError:
        pass
    return out[:20]


def _scan_dir(d) -> list[dict]:
    """The result-file + README scan, scoped to a single directory (repo root, or the entry's own
    subdirectory — see `discover`'s `entry` param)."""
    found = []
    for fn in _RESULT_FILES:
        p = os.path.join(d, fn)
        if os.path.isfile(p):
            found.extend(from_results_json(p))
    for p in _candidate_csvs(d):
        found.extend(from_results_csv(p))
    for p in _candidate_notebooks(d):
        found.extend(from_notebook(p))
    for fn in ("README.md", "README.rst", "README.txt", "readme.md"):
        p = os.path.join(d, fn)
        if os.path.isfile(p):
            try:
                with open(p, errors="replace") as fh:
                    found.extend(from_text(fh.read(2_000_000), location=fn))   # bounded README read
            except OSError:
                pass
    return found


def discover(repo_dir, stdout_text="", entry=None) -> list[dict]:
    """Discover claims across a repo's result files + README + (optional) captured stdout. Dedupes on
    (metric, value), preferring the highest-confidence source; assigns stable ids.

    `entry`: the argv the pipeline actually ran (e.g. ["demo-repo/eval.py"] or "examples/mnist/train.py
    --epochs 3"). Real repos commonly nest a runnable example under its OWN subdirectory with its OWN
    README documenting the claimed number (monorepos, `examples/`, a demo folder) — scanning only repo_dir's
    root silently misses that claim entirely. When the entry's dirname differs from repo_dir, that
    subdirectory is scanned TOO (repo-root results still count; this only adds a search location, never
    replaces one — some repos legitimately document per-example results in the top-level README)."""
    found = _scan_dir(repo_dir)
    argv = entry.split() if isinstance(entry, str) else (entry or [])
    entry_path = argv[0] if argv else None
    if entry_path:
        entry_dir = os.path.dirname(entry_path)
        if entry_dir:
            full_entry_dir = os.path.join(repo_dir, entry_dir)
            if os.path.isdir(full_entry_dir) and os.path.normpath(full_entry_dir) != os.path.normpath(repo_dir):
                found.extend(_scan_dir(full_entry_dir))
    if stdout_text:
        found.extend(from_text(stdout_text, location="stdout"))

    # dedupe on (metric, value, context): keep the highest-confidence instance (context keeps distinct
    # CSV rows — same metric+value for different datasets — from collapsing)
    best: dict[tuple, dict] = {}
    for c in found:
        key = (c["metric"], c["value"], c.get("context", ""))
        if key not in best or c["confidence"] > best[key]["confidence"]:
            best[key] = c
    claims = sorted(best.values(), key=lambda c: (-c["confidence"], c["metric"]))
    for i, c in enumerate(claims):
        c["id"] = "d%d_%s" % (i, c["metric"])
        if c.get("split") and c["split"] in ("train", "training"):
            # a train-split claim is rarely the headline; flag low so the binder/verifier can deprioritise
            c["confidence"] = round(c["confidence"] * 0.5, 3)
    return claims
