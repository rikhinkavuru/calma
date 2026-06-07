"""calma.draft_contract - turn a bare target into a confirmed verify.yaml with zero config.

Read-only: it NEVER installs or runs anything (run_hermetic does, behind a consent token). It scans the
target for machine-readable artifacts, infers a semantic tag per column from name + value plausibility,
grades the binding {independently-bound | plausibly-bound | author-asserted}, picks a headline metric,
and emits a schema-valid contract. The emitted contract is meant to be shown back as a single batched
plain-language confirm screen (not raw YAML).

Library: draft(target, claim=None, metric=None) -> dict.
CLI: draft_contract.py <target_dir> [--claim FLOAT] [--metric ID] [--out verify.yaml]
"""
import argparse
import csv
import json
import os
import re
import sys

# name-regex -> semantic tag (first match wins)
TAG_PATTERNS = [
    (r"(strat|portfolio|daily).*(ret|return)|^ret(urn)?s?$|pnl", "return"),
    (r"price|close|open|high|low|adj", "price"),
    (r"prob|proba|p_hat|phat|score|logit", "score"),
    (r"y_?pred|prediction|pred(icted)?|yhat", "prediction"),
    (r"y_?true|label|target|gt|truth|actual|class", "label"),
    (r"weight|wt", "weight"),
    (r"time|date|ts|timestamp", "timestamp"),
]
# metric selection by available tags
METRIC_BY_TAGS = [
    ({"return"}, "total_return"),
    ({"score", "label"}, "auc"),
    ({"prediction", "label"}, "accuracy"),
]
ENTRYPOINT_CANDIDATES = ["run.sh", "Makefile", "gen_fixture.py", "main.py", "run.py"]


def _infer_tag(name):
    n = name.strip().lower()
    for pat, tag in TAG_PATTERNS:
        if re.search(pat, n):
            return tag
    return None


def _sample_numeric(path, col_idx, limit=500):
    vals = []
    with open(path, newline="") as fh:
        rd = csv.reader(fh)
        next(rd, None)
        for i, row in enumerate(rd):
            if i >= limit:
                break
            if col_idx < len(row):
                try:
                    vals.append(float(row[col_idx]))
                except ValueError:
                    pass
    return vals


def _grade(tag, vals):
    """Independent sanity check of name+value. Any failure caps at plausibly-bound."""
    if not vals:
        return "author-asserted"
    n = len(vals)
    mean = sum(vals) / n
    rng = (min(vals), max(vals))
    if tag == "return":
        # returns: mostly |r|<1, roughly centered
        frac_small = sum(1 for v in vals if abs(v) < 1.0) / n
        if frac_small > 0.95 and abs(mean) < 0.2:
            return "independently-bound"
        return "plausibly-bound"
    if tag in ("score", "prob"):
        if rng[0] >= -0.001 and rng[1] <= 1.001:
            return "independently-bound"
        return "plausibly-bound"
    if tag in ("label", "prediction"):
        uniq = set(round(v, 6) for v in vals)
        if uniq <= {0.0, 1.0} or len(uniq) <= 20:
            return "independently-bound"
        return "plausibly-bound"
    return "plausibly-bound"


def _scan_csvs(target):
    arts = []
    for dp, _, names in os.walk(target):
        for n in sorted(names):
            if not n.lower().endswith(".csv"):
                continue
            full = os.path.join(dp, n)
            rel = os.path.relpath(full, target)
            try:
                with open(full, newline="") as fh:
                    header = next(csv.reader(fh))
            except (StopIteration, OSError):
                continue
            cols = {}
            for idx, h in enumerate(header):
                tag = _infer_tag(h)
                vals = _sample_numeric(full, idx) if tag else []
                cols[h] = {"tag": tag, "grade": _grade(tag, vals) if tag else "author-asserted",
                           "dtype": "float", "na_policy": "error"}
            arts.append({"path": rel, "columns": cols})
    return arts


def _detect_entrypoint(target):
    for c in ENTRYPOINT_CANDIDATES:
        if os.path.exists(os.path.join(target, c)):
            return c
    return "MANUAL"


def _pick_metric(arts, forced=None):
    """Return (metric_id, artifact_rel, binding, binding_status) or None."""
    # map tag -> (artifact, column, grade)
    available = {}
    for a in arts:
        for cname, spec in a["columns"].items():
            if spec["tag"]:
                available.setdefault(spec["tag"], (a["path"], cname, spec["grade"]))
    wanted = None
    if forced:
        # bind whatever tags the recipe needs from availability
        import recipes as R
        fn = R.get(forced)
        req = set((fn.manifest.get("required_tags") if fn else []) or [])
        wanted = (req, forced)
    else:
        for tags, mid in METRIC_BY_TAGS:
            if tags <= set(available):
                wanted = (tags, mid)
                break
    if not wanted:
        return None
    tags, mid = wanted
    binding = {}
    grades = []
    art = None
    for t in tags:
        if t not in available:
            return None
        art, col, grade = available[t]
        binding[t] = col
        grades.append(grade)
    order = ["author-asserted", "plausibly-bound", "independently-bound"]
    worst = min(grades, key=order.index)
    return mid, art, binding, worst


def draft(target, claim=None, metric=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    arts = _scan_csvs(target)
    contract = {
        "run": {"entrypoint": _detect_entrypoint(target), "network": "off", "cwd": "."},
        "env": {"ecosystem": "auto", "trust": "own-code"},
        "artifacts": [
            {"path": a["path"], "re_emit": False,
             "columns": {c: {"tag": s["tag"], "dtype": s["dtype"], "na_policy": s["na_policy"]}
                         for c, s in a["columns"].items() if s["tag"]}}
            for a in arts if any(s["tag"] for s in a["columns"].values())
        ],
        "metrics": [],
        "baselines": [],
    }
    picked = _pick_metric(arts, metric)
    if picked:
        mid, art, binding, grade = picked
        contract["metrics"].append({
            "metric_id": mid, "artifact": art, "binding": binding, "convention": None,
            "claimed_value": float(claim) if claim is not None else None,
            "headline": claim is not None, "binding_status": grade,
            "claim_confirmed": claim is not None,
        })
    contract["_draft_notes"] = {
        "artifacts_found": len(arts),
        "needs_confirmation": [m["metric_id"] for m in contract["metrics"]
                               if m["binding_status"] != "independently-bound" or m["headline"]],
        "warning": None if contract["metrics"] else "no recomputable metric detected; provide --metric/--claim",
    }
    return contract


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--claim")
    ap.add_argument("--metric")
    ap.add_argument("--out")
    a = ap.parse_args()
    contract = draft(a.target, a.claim, a.metric)
    text = json.dumps(contract, indent=2)
    if a.out:
        open(a.out, "w").write(text)
    print(text)
    return 0 if contract["metrics"] else 2


if __name__ == "__main__":
    sys.exit(main())
