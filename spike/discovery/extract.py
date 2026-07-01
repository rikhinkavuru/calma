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
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.append((prefix, obj))
    return out


def from_results_json(path) -> list[dict]:
    try:
        with open(path) as fh:
            data = json.loads(fh.read(8_000_000))   # bounded read — a giant results file can't OOM the API
    except (OSError, ValueError):
        return []
    claims = []
    for name, val in _flatten(data):
        leaf = name.split(".")[-1]
        cid, split, conf = map_metric(leaf)
        if not cid:
            continue
        vs = _value_str(val)
        if vs is None:
            continue
        claim = {"metric": cid, "value": vs, "location": "%s::%s" % (os.path.basename(path), name),
                 "source": "results-json", "confidence": conf}
        if split:
            claim["split"] = split
        claims.append(claim)
    return claims


# "Accuracy: 0.83", "test AUC = 0.91", "F1 0.72", "Accuracy: 96.67%"
_KV_RE = re.compile(r"([A-Za-z][A-Za-z0-9 _\-/]{1,40}?)\s*[:=]\s*([-+]?\d*\.?\d+%?)")
# markdown table row: | Accuracy | 0.83 |
_ROW_RE = re.compile(r"\|\s*([A-Za-z][A-Za-z0-9 _\-/]{1,40}?)\s*\|\s*([-+]?\d*\.?\d+%?)\s*\|")

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


def discover(repo_dir, stdout_text="") -> list[dict]:
    """Discover claims across a repo's result files + README + (optional) captured stdout. Dedupes on
    (metric, value), preferring the highest-confidence source; assigns stable ids."""
    found = []
    for fn in _RESULT_FILES:
        p = os.path.join(repo_dir, fn)
        if os.path.isfile(p):
            found.extend(from_results_json(p))
    for p in _candidate_csvs(repo_dir):
        found.extend(from_results_csv(p))
    for fn in ("README.md", "README.rst", "README.txt", "readme.md"):
        p = os.path.join(repo_dir, fn)
        if os.path.isfile(p):
            try:
                with open(p, errors="replace") as fh:
                    found.extend(from_text(fh.read(2_000_000), location=fn))   # bounded README read
            except OSError:
                pass
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
