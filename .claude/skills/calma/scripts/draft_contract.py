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
    (r"prob(?!lem)|p_hat|phat|score|logit", "score"),
    (r"y_?pred|prediction|pred(icted)?|yhat", "prediction"),
    (r"y_?true|ground.?truth|gt|\bclass\b|\blabel\b", "label"),
    (r"target|actual|y_?act|observed|true_?val", "target"),
    (r"reference|answer|gold", "reference"),
    (r"before|baseline_(ms|time|sec)", "before"),
    (r"after|optimized|new_(ms|time|sec)", "after"),
    (r"duration|latency|elapsed|response_?(time|ms)|_ms$|_sec$", "duration"),
    (r"hits?$|covered|coverage", "hits"),
    (r"query|qid", "query"),
    (r"relevan|judg", "relevance"),
    (r"\brank\b|position", "rank"),
    (r"problem|task_?id", "problem"),
    (r"correct|passed", "correct"),
    (r"control|sample_?a|group_?a", "sample_a"),
    (r"treatment|sample_?b|group_?b|variant", "sample_b"),
    (r"group|region|segment|cohort|category", "group"),
    (r"outcome", "outcome"),
    (r"error|fail|flag|converted|is_|status", "flag"),
    (r"amount|revenue|total|sales|price_usd|value|qty|quantity|count|memory|mem_", "value"),
    (r"weight|wt", "weight"),
    (r"time|date|ts|timestamp", "timestamp"),
    (r"^x$", "x"),
    (r"^y$", "y"),
]
# metric selection by available tags (first satisfiable wins; specific before generic)
METRIC_BY_TAGS = [
    ({"return"}, "total_return"),
    ({"score", "label"}, "auc"),
    ({"prediction", "reference"}, "exact_match"),
    ({"prediction", "target"}, "rmse"),
    ({"prediction", "label"}, "accuracy"),
    ({"query", "rank", "relevance"}, "recall_at_k"),
    ({"problem", "correct"}, "pass_at_k"),
    ({"before", "after"}, "speedup_ratio"),
    ({"hits"}, "test_coverage"),
    ({"duration"}, "latency_p50"),
    ({"x", "y"}, "correlation"),
    ({"value"}, "column_sum"),
]
# common entrypoint names first; gen_fixture.py last (calma's own fixture convention)
ENTRYPOINT_CANDIDATES = ["run.sh", "main.py", "run.py", "train.py", "pipeline.py", "backtest.py",
                         "analyze.py", "gen_fixture.py"]

# free-text claim -> metric hint (first match wins; word-boundary matched). Order matters:
# "total return" must hit total_return before "total" hits column_sum; "average precision"
# before "average"/"precision"; "macro f1" before "f1"; "recall@10" before "recall"; the
# pr-auc spellings before "auc"; "top-5" before "accuracy".
CLAIM_METRIC_HINTS = [
    # -- multi-word / decorated hints first (most specific) --
    ("average precision", "pr_auc"), ("pr auc", "pr_auc"), ("pr-auc", "pr_auc"),
    ("auprc", "pr_auc"),
    ("macro f1", "macro_f1"), ("macro-f1", "macro_f1"),
    ("micro f1", "micro_f1"), ("micro-f1", "micro_f1"),
    ("recall@5", "recall_at_k"), ("recall@10", "recall_at_k"), ("recall@20", "recall_at_k"),
    ("recall@50", "recall_at_k"), ("recall@100", "recall_at_k"),
    ("ndcg", "ndcg_at_k"), ("mrr", "mrr"),
    ("exact match", "exact_match"), ("exact-match", "exact_match"),
    ("pass@1", "pass_at_k"), ("pass@5", "pass_at_k"), ("pass@10", "pass_at_k"),
    ("pass@100", "pass_at_k"), ("pass@k", "pass_at_k"),
    ("top-1", "top_k_accuracy"), ("top-3", "top_k_accuracy"), ("top-5", "top_k_accuracy"),
    ("top-10", "top_k_accuracy"), ("top-k", "top_k_accuracy"), ("hit rate", "top_k_accuracy"),
    ("log loss", "log_loss"), ("logloss", "log_loss"), ("cross entropy", "log_loss"),
    ("mcc", "mcc"), ("matthews", "mcc"),
    ("calibration error", "ece"), ("ece", "ece"),
    ("error rate", "error_rate"), ("failure rate", "error_rate"),
    ("p-value", "p_value"), ("p value", "p_value"), ("pvalue", "p_value"),
    ("significant", "p_value"), ("significance", "p_value"), ("t-test", "p_value"),
    ("confidence interval", "confidence_interval"), ("margin of error", "confidence_interval"),
    ("effect size", "effect_size"), ("cohen's d", "effect_size"), ("cohens d", "effect_size"),
    ("hedges", "effect_size"),
    ("chi-square", "chi_square"), ("chi-squared", "chi_square"), ("chi2", "chi_square"),
    ("chi square", "chi_square"),
    ("correlation", "correlation"), ("pearson", "correlation"), ("spearman", "correlation"),
    ("uplift", "lift"), ("lift", "lift"),
    ("speedup", "speedup_ratio"), ("speed-up", "speedup_ratio"), ("faster", "speedup_ratio"),
    ("p50", "latency_p50"), ("p95", "latency_p95"), ("p99", "latency_p99"),
    ("latency", "latency_p50"),
    ("throughput", "throughput"), ("rps", "throughput"), ("qps", "throughput"),
    ("ops/sec", "throughput"), ("ops/s", "throughput"),
    ("peak memory", "peak_memory"), ("memory", "peak_memory"),
    ("coverage", "test_coverage"),
    ("percentile", "percentile"), ("median", "column_median"),
    ("distinct", "distinct_count"), ("unique", "distinct_count"),
    ("duplicates", "duplicate_count"), ("duplicate", "duplicate_count"),
    ("null", "null_fraction"), ("missing", "null_fraction"),
    ("growth", "growth_rate"), ("mom", "growth_rate"), ("yoy", "growth_rate"),
    ("share", "ratio_share"),
    ("merged", "join_row_loss"), ("merge", "join_row_loss"), ("join", "join_row_loss"),
    ("joined", "join_row_loss"),
    # -- the original single-word hints --
    ("accuracy", "accuracy"), ("auc", "auc"), ("rmse", "rmse"), ("mae", "mae"),
    ("r2", "r2"), ("r^2", "r2"), ("sharpe", "sharpe"), ("drawdown", "max_drawdown"),
    ("return", "total_return"), ("backtest", "total_return"), ("f1", "f1"),
    ("precision", "precision"), ("recall", "recall"), ("brier", "brier"),
    ("rows", "row_count"), ("row", "row_count"), ("count", "row_count"),
    ("sum", "column_sum"), ("total", "column_sum"), ("revenue", "column_sum"),
    ("mean", "column_mean"), ("average", "column_mean"),
]

# The leading lookbehind keeps digits glued to identifiers out of the claim value:
# "f1 0.84" must parse 0.84 (not the 1 in f1), "top-5 accuracy 0.91" -> 0.91 (not -5),
# "recall@10 = 0.84" -> 0.84, "p95 latency 120ms" -> 120, "chi2 = 5.99" -> 5.99.
_CLAIM_NUM = re.compile(
    r"([-+]?)\s*\$?\s*(?<![\w@^.])(?<![\w@^.][-+])"
    r"((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?)"
    r"\s*(%|[kKmMbB](?![a-zA-Z]))?")


def parse_claim(text):
    """Free-text claim -> (value, metric_hint). Accepts 'accuracy 0.87', '+14,698% backtest',
    '$4.2M revenue', 'processed 10,000 rows', or a bare number. '%' divides by 100; k/M/B scale.
    Returns (None, hint) when no number is present."""
    if text is None:
        return None, None
    if isinstance(text, (int, float)):
        return float(text), None
    s = str(text).strip()
    low = s.lower()
    hint = None
    for word, mid in CLAIM_METRIC_HINTS:
        if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(word.lower()), low):
            hint = mid
            break
    m = _CLAIM_NUM.search(s)
    if not m:
        return None, hint
    raw = m.group(2).replace(",", "")
    val = float(raw)
    if m.group(1) == "-":
        val = -val
    suffix = m.group(3) or ""
    if suffix == "%":
        val /= 100.0
    elif suffix in ("k", "K"):
        val *= 1e3
    elif suffix in ("m", "M"):
        val *= 1e6
    elif suffix in ("b", "B"):
        val *= 1e9
    return val, hint


# ---------- contract loading (tolerant: JSON first, then a small YAML subset) ----------

def _strip_comment(line):
    out, in_s, in_d = [], False, False
    for ch in line:
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == "#" and not in_s and not in_d:
            break
        out.append(ch)
    return "".join(out).rstrip()


def _split_flow(inner):
    """Split a flow collection's body on top-level commas."""
    parts, buf, depth, in_s, in_d = [], [], 0, False, False
    for ch in inner:
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif not in_s and not in_d:
            if ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(buf))
                buf = []
                continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _scalar(s):
    s = s.strip()
    if not s:
        return None
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1].strip()
        out = {}
        for part in _split_flow(inner):
            k, _, v = part.partition(":")
            out[_scalar(k)] = _scalar(v)
        return out
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_scalar(p) for p in _split_flow(inner)] if inner else []
    low = s.lower()
    if low in ("null", "~"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    # deliberately NOT YAML-1.1: off/on/yes/no stay strings (the contract uses `network: off`)
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _indent_of(line):
    return len(line) - len(line.lstrip(" "))


def _parse_block(lines, i, indent):
    if i >= len(lines):
        return None, i
    if lines[i].strip().startswith("- "):
        return _parse_list(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_map(lines, i, indent):
    out = {}
    while i < len(lines):
        line = lines[i]
        ind = _indent_of(line)
        if ind < indent or line.strip().startswith("- "):
            break
        if ind > indent:
            raise ValueError("bad indentation at: %r" % line.strip())
        body = line.strip()
        if ":" not in body:
            raise ValueError("expected 'key: value' at: %r" % body)
        key, _, rest = body.partition(":")
        key = _scalar(key)
        rest = rest.strip()
        if rest == "":
            if i + 1 < len(lines) and _indent_of(lines[i + 1]) > indent:
                val, i = _parse_block(lines, i + 1, _indent_of(lines[i + 1]))
            else:
                val = None
                i += 1
            out[key] = val
            continue
        if rest == "[]":
            out[key] = []
        elif rest == "{}":
            out[key] = {}
        else:
            out[key] = _scalar(rest)
        i += 1
    return out, i


def _parse_list(lines, i, indent):
    out = []
    while i < len(lines):
        line = lines[i]
        ind = _indent_of(line)
        if ind != indent or not line.strip().startswith("- "):
            break
        item_body = line.strip()[2:].strip()
        item_indent = ind + 2
        if not item_body:
            if i + 1 < len(lines) and _indent_of(lines[i + 1]) > ind:
                val, i = _parse_block(lines, i + 1, _indent_of(lines[i + 1]))
            else:
                val, i = None, i + 1
            out.append(val)
            continue
        if ":" in item_body and (item_body.endswith(":") or ": " in item_body):
            # mapping that starts inline after the dash
            sub = [" " * item_indent + item_body]
            j = i + 1
            while j < len(lines) and _indent_of(lines[j]) >= item_indent:
                sub.append(lines[j])
                j += 1
            val, _ = _parse_map(sub, 0, item_indent)
            out.append(val)
            i = j
        else:
            out.append(_scalar(item_body))
            i += 1
    return out, i


def parse_simple_yaml(text):
    """Parse the YAML subset a hand-written verify.yaml uses: nested maps by indentation, '- ' lists
    (scalars or block maps), quoted/plain scalars, comments. NOT a full YAML parser."""
    lines = [_strip_comment(raw).replace("\t", "    ") for raw in text.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        return {}
    val, _ = _parse_block(lines, 0, _indent_of(lines[0]))
    return val


def load_contract(path):
    """Load verify.yaml: JSON first (the canonical dependency-free format), then the YAML subset.
    Raises ValueError with an actionable message instead of a raw parser traceback."""
    text = open(path).read()
    try:
        obj = json.loads(text)
    except ValueError:
        try:
            obj = parse_simple_yaml(text)
        except ValueError as e:
            raise ValueError(
                "%s could not be parsed: %s. The contract accepts JSON or simple YAML "
                "(nested 'key: value' maps and '- ' lists)." % (path, e))
    if not isinstance(obj, dict):
        raise ValueError("%s parsed to %s, expected a mapping" % (path, type(obj).__name__))
    return obj


def validate_contract(contract):
    """Light structural check against the verify schema's required fields. Returns a list of errors."""
    errs = []
    run = contract.get("run")
    if not isinstance(run, dict) or not run.get("entrypoint"):
        errs.append("run.entrypoint is required (the command/script that re-produces the result)")
    arts = contract.get("artifacts")
    if not isinstance(arts, list):
        errs.append("artifacts must be a list of {path, columns}")
    else:
        for k, a in enumerate(arts):
            if not isinstance(a, dict) or not a.get("path") or not isinstance(a.get("columns"), dict):
                errs.append("artifacts[%d] needs path + columns" % k)
    if isinstance(arts, list):
        for k, a in enumerate(arts):
            for cname, spec in (a.get("columns") or {}).items() if isinstance(a, dict) else []:
                if not isinstance(spec, dict):
                    errs.append("artifacts[%d].columns[%s] must be a mapping like {tag: label}" % (k, cname))
    mets = contract.get("metrics")
    if not isinstance(mets, list):
        errs.append("metrics must be a list (may be empty)")
    else:
        for k, m in enumerate(mets):
            if not isinstance(m, dict) or not m.get("metric_id") or not m.get("artifact") \
                    or not isinstance(m.get("binding"), dict):
                errs.append("metrics[%d] needs metric_id + artifact + binding" % k)
    return errs


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


# string-keyed tags (grouping/ID columns): the independent sanity check is non-null density,
# not numeric plausibility
STRING_KEY_TAGS = {"query", "problem", "group", "outcome", "left_key", "joined_key"}


def _sample_strings(path, col_idx, limit=500):
    vals = []
    with open(path, newline="") as fh:
        rd = csv.reader(fh)
        next(rd, None)
        for i, row in enumerate(rd):
            if i >= limit:
                break
            if col_idx < len(row):
                vals.append(row[col_idx])
    return vals


def _grade_string_key(raws):
    if not raws:
        return "author-asserted"
    ok = sum(1 for s in raws if s.strip() and s.strip().lower() not in ("nan", "na", "null", "none"))
    return "independently-bound" if ok / len(raws) >= 0.95 else "plausibly-bound"


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
    if tag == "duration":
        # durations/latencies: strictly non-negative and finite
        if rng[0] >= 0.0 and rng[1] < float("inf"):
            return "independently-bound"
        return "plausibly-bound"
    if tag in ("hits", "rank"):
        # whole counts; ranks additionally start at >= 1
        if all(v == int(v) for v in vals) and rng[0] >= (1.0 if tag == "rank" else 0.0):
            return "independently-bound"
        return "plausibly-bound"
    if tag in ("correct", "relevance"):
        uniq = set(round(v, 6) for v in vals)
        if uniq <= {0.0, 1.0} or (rng[0] >= 0.0 and len(uniq) <= 10 and all(v == int(v) for v in vals)):
            return "independently-bound"
        return "plausibly-bound"
    if tag == "flag":
        uniq = set(round(v, 6) for v in vals)
        # binary error/conversion flags, or a sane HTTP-status column
        if uniq <= {0.0, 1.0} or (rng[0] >= 100 and rng[1] <= 599 and all(v == int(v) for v in vals)):
            return "independently-bound"
        return "plausibly-bound"
    if tag in ("before", "after"):
        if rng[0] >= 0.0 and rng[1] < float("inf"):
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
                if tag in STRING_KEY_TAGS:
                    grade = _grade_string_key(_sample_strings(full, idx))
                elif tag:
                    grade = _grade(tag, _sample_numeric(full, idx))
                else:
                    grade = "author-asserted"
                cols[h] = {"tag": tag, "grade": grade, "dtype": "float", "na_policy": "error"}
            arts.append({"path": rel, "columns": cols})
    return arts


def _detect_entrypoint(target):
    for c in ENTRYPOINT_CANDIDATES:
        if os.path.exists(os.path.join(target, c)):
            return c
    # fallback: a single runnable script in the target root is unambiguous
    try:
        names = sorted(os.listdir(target))
    except OSError:
        return "MANUAL"
    pys = [n for n in names if n.endswith(".py") and not n.startswith((".", "_", "test"))]
    if len(pys) == 1:
        return pys[0]
    if not pys:
        others = [n for n in names
                  if os.path.splitext(n)[1].lower() in (".r", ".jl", ".rs", ".c", ".cpp", ".cc", ".js", ".sh")]
        if len(others) == 1:
            return others[0]
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
    claim_value, hint = parse_claim(claim)
    if claim is not None and claim_value is None:
        raise ValueError(
            "no number found in claim %r - state the claimed value, e.g. \"accuracy 0.87\" or \"+14,698%%\"" % claim)
    metric = metric or hint
    arts = _scan_csvs(target)
    contract = {
        "run": {"entrypoint": _detect_entrypoint(target), "network": "off", "cwd": "."},
        "env": {"ecosystem": "auto", "trust": "own-code"},
        "artifacts": [
            {"path": a["path"],
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
        # The claim TARGET is confirmed only when the caller stated the number AND the metric is
        # unambiguous (named explicitly / in the claim text) or the binding is independently sane-checked.
        # An auto-picked metric under a bare-number claim stays unconfirmed: REFUTED is then blocked
        # (degrades to INCONCLUSIVE), so a wrong auto-binding can never manufacture a refutation.
        target_confirmed = claim_value is not None and (metric is not None or grade == "independently-bound")
        contract["metrics"].append({
            "metric_id": mid, "artifact": art, "binding": binding, "convention": None,
            "claimed_value": claim_value,
            "headline": claim_value is not None, "binding_status": grade,
            "claim_confirmed": target_confirmed,
            "binding_source": "named-in-claim" if (metric is not None) else "auto-detected",
        })
    contract["_draft_notes"] = {
        "artifacts_found": len(arts),
        "claim_metric_hint": hint,
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
