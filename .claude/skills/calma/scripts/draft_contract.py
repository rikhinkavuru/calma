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
import math
import os
import re
import sys

# Unicode minus/hyphen codepoints that mean "negative" in a numeric claim, normalized to ASCII
# '-' before the value regex runs - so a claim copied from a PDF/editor/LLM ("−14%", U+2212) is
# not silently parsed with the WRONG SIGN (a correct negative claim would otherwise false-REFUTE).
# Deliberately EXCLUDES en/em dash (U+2013/U+2014): those are prose range/clause separators, and
# treating them as minus would create false negatives ("revenue—$4.2M" must not become -4.2M).
_DASHES = {0x2212: "-", 0x2010: "-", 0x2011: "-", 0x2012: "-", 0xFF0D: "-", 0xFE63: "-"}
# a spelled-out "percent"/"percentage"/"pct" after a number is the % suffix written in words
# ("accuracy of 87 percent" must parse 0.87, not 87 -> a true 0.87 would otherwise false-REFUTE).
# \b after the keyword leaves "percentile" / "percentage points" alone (those keep their own meaning).
_PERCENT_WORD = re.compile(r"(\d)\s*(?:percent|percentage|pct)\b", re.IGNORECASE)


def _normalize_claim_text(s):
    """Canonicalize a free-text claim before the value regex: Unicode minus/hyphen -> ASCII '-',
    and a spelled-out 'percent' -> '%'. Sign- and scale-preserving; leaves metric-name hyphens and
    'percentile' untouched."""
    if not isinstance(s, str):
        return s
    return _PERCENT_WORD.sub(r"\1%", s.translate(_DASHES))

# name-regex -> semantic tag (first match wins)
TAG_PATTERNS = [
    (r"benchmark|bench_ret|market_ret|spy_ret|buy_?hold|buy_?and_?hold", "benchmark"),
    (r"(strat|portfolio|daily).*(ret|return)|^ret(urn)?s?$|pnl", "return"),
    (r"log_?prob|loglik", "value"),
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
    (r"error|fail|flag|converted|is_|status|churn", "flag"),
    (r"cash_?flow|^cf$", "cashflow"),
    (r"cost|cogs|expense", "cost"),
    (r"amount|revenue|total|sales|price_usd|value|qty|quantity|count|memory|mem_|measurement|reading", "value"),
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
    ({"value", "cost"}, "margin_pct"),
    ({"cashflow"}, "irr"),
    ({"value"}, "column_sum"),
]
# common entrypoint names first; gen_fixture.py last (calma's own fixture convention)
ENTRYPOINT_CANDIDATES = ["run.sh", "main.py", "run.py", "train.py", "pipeline.py", "backtest.py",
                         "analyze.py", "analysis.py", "evaluate.py", "eval.py", "score.py",
                         "experiment.py", "benchmark.py", "gen_fixture.py"]

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
    ("top-10", "top_k_accuracy"), ("top-k", "top_k_accuracy"),
    ("cache hit", "cache_hit_rate"), ("hit rate", "top_k_accuracy"),
    ("log loss", "log_loss"), ("logloss", "log_loss"), ("cross entropy", "log_loss"),
    ("mcc", "mcc"), ("matthews", "mcc"),
    ("calibration error", "ece"), ("ece", "ece"),
    ("error rate", "error_rate"), ("failure rate", "error_rate"),
    ("p-value", "p_value"), ("p value", "p_value"), ("pvalue", "p_value"),
    ("significant", "p_value"), ("significance", "p_value"), ("t-test", "p_value"),
    ("confidence interval", "confidence_interval"), ("margin of error", "confidence_interval"),
    ("ci", "confidence_interval"),
    ("effect size", "effect_size"), ("cohen's d", "effect_size"), ("cohens d", "effect_size"),
    ("hedges", "effect_size"),
    ("chi-square", "chi_square"), ("chi-squared", "chi_square"), ("chi2", "chi_square"),
    ("chi square", "chi_square"),
    ("correlation", "correlation"), ("pearson", "correlation"), ("spearman", "correlation"),
    ("uplift", "lift"), ("lift", "lift"),
    ("speedup", "speedup_ratio"), ("speed-up", "speedup_ratio"), ("faster", "speedup_ratio"),
    ("p99.9", "percentile"), ("p75", "percentile"),
    ("p90", "latency_p90"),
    ("p50", "latency_p50"), ("p95", "latency_p95"), ("p99", "latency_p99"),
    ("latency", "latency_p50"),
    ("throughput", "throughput"), ("rps", "throughput"), ("qps", "throughput"),
    ("ops/sec", "throughput"), ("ops/s", "throughput"),
    ("peak memory", "peak_memory"), ("memory", "peak_memory"),
    ("coverage", "test_coverage"),
    ("median absolute error", "medae"), ("medae", "medae"),
    ("percentile", "percentile"), ("median", "column_median"),
    ("distinct", "distinct_count"), ("unique", "distinct_count"),
    ("duplicates", "duplicate_count"), ("duplicate", "duplicate_count"),
    ("null", "null_fraction"), ("missing", "null_fraction"),
    ("growth", "growth_rate"), ("mom", "growth_rate"), ("yoy", "growth_rate"),
    ("share", "ratio_share"),
    ("merged", "join_row_loss"), ("merge", "join_row_loss"), ("join", "join_row_loss"),
    ("joined", "join_row_loss"),
    ("sortino", "sortino"), ("calmar", "calmar"), ("volatility", "volatility"),
    ("cvar", "cvar"), ("expected shortfall", "cvar"), ("var", "value_at_risk"),
    ("value at risk", "value_at_risk"),
    ("win rate", "win_rate"), ("profit factor", "profit_factor"), ("omega", "omega_ratio"),
    ("downside deviation", "downside_deviation"),
    ("information ratio", "information_ratio"), ("tracking error", "tracking_error"),
    ("beta", "beta"), ("alpha", "alpha"),
    ("balanced accuracy", "balanced_accuracy"), ("kappa", "cohen_kappa"),
    ("specificity", "specificity"), ("jaccard", "jaccard"), ("iou", "jaccard"),
    ("weighted f1", "weighted_f1"), ("weighted-f1", "weighted_f1"),
    ("f2", "fbeta"), ("f0.5", "fbeta"), ("f-beta", "fbeta"), ("fbeta", "fbeta"),
    ("ks statistic", "ks_statistic"), ("ks test", "ks_test"), ("kolmogorov", "ks_test"),
    ("gini coefficient", "gini_coefficient"), ("gini", "gini_norm"),
    ("rmsle", "msle"), ("msle", "msle"),
    ("max error", "max_error"), ("explained variance", "explained_variance"),
    ("wape", "wape"), ("forecast bias", "forecast_bias"),
    ("adjusted r2", "adjusted_r2"), ("adj r2", "adjusted_r2"), ("adjusted r^2", "adjusted_r2"),
    ("nrmse", "nrmse"), ("durbin", "durbin_watson"),
    ("minimum", "column_min"), ("maximum", "column_max"),
    ("standard deviation", "column_std"), ("std dev", "column_std"), ("stdev", "column_std"),
    ("iqr", "iqr"), ("interquartile", "iqr"),
    ("outliers", "outlier_count"), ("outlier", "outlier_count"),
    ("most common", "mode_share"), ("mode share", "mode_share"),
    ("hhi", "hhi"), ("herfindahl", "hhi"), ("concentration", "hhi"),
    ("entropy", "entropy"),
    ("apdex", "apdex"), ("uptime", "uptime_pct"), ("availability", "uptime_pct"),
    ("mann-whitney", "mann_whitney"), ("mann whitney", "mann_whitney"), ("u test", "mann_whitney"),
    ("anova", "anova"), ("f-test", "anova"),
    ("two-proportion", "proportion_z"), ("proportion test", "proportion_z"),
    ("fisher", "fisher_exact"),
    ("odds ratio", "odds_ratio"), ("relative risk", "relative_risk"), ("risk ratio", "relative_risk"),
    ("cramer", "cramers_v"), ("cramérs v", "cramers_v"),
    ("skewness", "skewness"), ("skew", "skewness"),
    ("kurtosis", "kurtosis"), ("jarque", "jarque_bera"),
    ("autocorrelation", "autocorrelation"), ("acf", "autocorrelation"),
    ("mean average precision", "map_at_k"), ("map@5", "map_at_k"), ("map@10", "map_at_k"),
    ("map@20", "map_at_k"), ("map@100", "map_at_k"),
    ("precision@5", "precision_at_k"), ("precision@10", "precision_at_k"),
    ("precision@20", "precision_at_k"), ("precision@100", "precision_at_k"),
    ("perplexity", "perplexity"), ("ppl", "perplexity"),
    ("word error rate", "wer"), ("wer", "wer"),
    ("character error rate", "wer"), ("cer", "wer"),
    ("cagr", "cagr"), ("npv", "npv"), ("irr", "irr"),
    ("churn", "churn_rate"), ("retention", "churn_rate"),
    ("margin", "margin_pct"),
    ("reconciliation", "reconciliation_total"), ("reconciled", "reconciliation_total"),
    ("ledger", "reconciliation_total"),
    ("smape", "mape"), ("mape", "mape"), ("mase", "mase"),
    ("pinball", "pinball_loss"), ("quantile loss", "pinball_loss"),
    # -- the original single-word hints --
    ("accuracy", "accuracy"), ("auc", "auc"), ("rmse", "rmse"), ("mae", "mae"),
    ("r2", "r2"), ("r^2", "r2"), ("sharpe", "sharpe"), ("drawdown", "max_drawdown"),
    ("return", "total_return"), ("backtest", "total_return"), ("f1", "f1"),
    ("precision", "precision"), ("recall", "recall"), ("brier", "brier"),
    ("rows", "row_count"), ("row", "row_count"), ("count", "row_count"),
    ("sum", "column_sum"), ("total", "column_sum"), ("revenue", "column_sum"),
    ("mean", "column_mean"), ("average", "column_mean"),
]

# anchor of the generic single-word tail above: compiled-recipe hints insert BEFORE it, so a
# multi-word compiled hint ("standard error of the mean") wins over a generic substring ("mean")
_GENERIC_TAIL_ANCHOR = ("accuracy", "accuracy")


def _load_compiled_hints():
    """Claim hints from admitted compiled recipes (assets/compiled_recipes.json). Inserted
    before the generic tail, after every hand-ordered specific hint - so they can never shadow
    a reviewed recipe, and generic words can never shadow them."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "assets", "compiled_recipes.json")
    if not os.path.exists(path):
        return
    try:
        book = json.load(open(path))
    except (OSError, ValueError):
        return
    hints = []
    for r in book.get("recipes", []):
        for h in r.get("claim_hints", []):
            pair = (str(h).lower(), r.get("metric_id"))
            if pair[0] and pair[1] and pair not in CLAIM_METRIC_HINTS:
                hints.append(pair)
    if not hints:
        return
    try:
        idx = CLAIM_METRIC_HINTS.index(_GENERIC_TAIL_ANCHOR)
    except ValueError:
        idx = len(CLAIM_METRIC_HINTS)
    CLAIM_METRIC_HINTS[idx:idx] = sorted(hints, key=lambda p: -len(p[0]))


_load_compiled_hints()

# The leading lookbehind keeps digits glued to identifiers out of the claim value:
# "f1 0.84" must parse 0.84 (not the 1 in f1), "top-5 accuracy 0.91" -> 0.91 (not -5),
# "recall@10 = 0.84" -> 0.84, "p95 latency 120ms" -> 120, "chi2 = 5.99" -> 5.99.
_CLAIM_NUM = re.compile(
    r"([-+]?)\s*\$?\s*(?<![\w@^.])(?<![\w@^.][-+])"
    r"((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?)"
    r"\s*(%|[kKmMbB](?![a-zA-Z]))?")


def claim_precision(text):
    """Half-ULP of the claim's REPORTED precision, including the suffix scale the parser applied:
    '$4.2M' -> 50,000 (one decimal at 1e6 scale), '23.87%' -> 5e-5, '10,000 rows' -> 0.5.
    Without this, a scaled claim's precision is unrecoverable from the bare float (repr of
    23.87/100 carries float artifacts; 4.2e6 looks integer-exact). None when no number."""
    if text is None or isinstance(text, (int, float)):
        return None
    m = _CLAIM_NUM.search(_normalize_claim_text(str(text).strip()))
    if not m:
        return None
    raw = m.group(2).replace(",", "")
    if "e" in raw.lower():
        return None
    d = len(raw.split(".", 1)[1]) if "." in raw else 0
    scale = {"%": 0.01, "k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6, "b": 1e9, "B": 1e9}.get(
        m.group(3) or "", 1.0)
    # An integer claim in the unit range (0 / 1 / -1, no %/k/M suffix) is almost always a bounded
    # metric stated whole - "accuracy 1", "0 errors" - meaning the exact value, NOT "value +/- 0.5".
    # The half-ULP 0.5 there is half the entire [0,1]/[-1,1] range and false-CONFIRMS gross overclaims
    # (claim 1 vs true 0.85). Tighten to a one-significant-figure tolerance: a true perfect/zero score
    # still confirms (recompute ~= claim) but a material overclaim refutes. (Percent claims like "100%"
    # already scale to 0.005; counts/multiples >=2 keep the half-ULP.)
    if d == 0 and scale == 1.0:
        try:
            if abs(float(raw)) <= 1.0:
                return 0.05
        except ValueError:
            pass
    return 0.5 * 10 ** (-d) * scale


def infer_convention(text, metric_id):
    """Pull the recompute convention OUT OF THE CLAIM TEXT, so 'pass@5 0.62' recomputes with
    k=5 (not the k=1 default), 'monthly CAGR' annualizes 12 periods, 'spearman correlation'
    ranks first, '99% CI' uses t99. Tight patterns only - no match means the recipe default,
    and the inferred string is recorded on the contract for audit."""
    if text is None or metric_id is None:
        return None
    s = str(text).lower()
    if metric_id in ("pass_at_k", "recall_at_k", "ndcg_at_k", "mrr", "top_k_accuracy",
                     "map_at_k", "precision_at_k"):
        m = re.search(r"(?:pass|recall|ndcg|mrr|hit|top|map|precision)\s*[@\- ]\s*k?=?(\d+)", s)
        if m:
            k = "k=%s" % m.group(1)
            return k + ",exp" if (metric_id == "ndcg_at_k" and "exp" in s) else k
        return None
    if metric_id in ("sharpe", "sortino", "volatility", "downside_deviation", "calmar",
                     "alpha", "information_ratio", "tracking_error"):
        if "monthly" in s:
            return "periods=12"
        if "weekly" in s:
            return "periods=52"
        if "daily" in s:
            return "periods=252"
        return None
    if metric_id in ("value_at_risk", "cvar"):
        m = re.search(r"(9[0579](?:\.\d+)?)\s*%?\s*(?:var|cvar|level)", s) \
            or re.search(r"(?:var|cvar)\s*\(?(9[0579](?:\.\d+)?)", s)
        return "p%s" % m.group(1) if m else None
    if metric_id == "fbeta":
        m = re.search(r"\bf(\d+(?:\.\d+)?)\b", s)
        if m and m.group(1) != "1":
            return "beta=%s" % m.group(1)
        return None
    if metric_id == "msle":
        return "rmsle" if "rmsle" in s else None
    if metric_id == "entropy":
        return "nats" if "nats" in s or "nat " in s else None
    if metric_id == "autocorrelation":
        m = re.search(r"lag[\s\-]?(\d+)", s)
        return "lag=%s" % m.group(1) if m else None
    if metric_id == "wer":
        return "cer" if ("cer" in s or "character" in s) else None
    if metric_id == "apdex":
        m = re.search(r"t\s*=\s*(\d+(?:\.\d+)?)", s)
        return "t=%s" % m.group(1) if m else None
    if metric_id == "adjusted_r2":
        m = re.search(r"(\d+)\s*(?:predictors|features|regressors)", s)
        return "p=%s" % m.group(1) if m else None
    if metric_id == "cagr":
        if "month" in s:
            return "periods=12"
        if "quarter" in s:
            return "periods=4"
        if "week" in s:
            return "periods=52"
        return None
    if metric_id == "npv":
        m = re.search(r"(?:at|@)\s*(\d+(?:\.\d+)?)\s*%", s)
        return "rate=%g" % (float(m.group(1)) / 100.0) if m else None
    if metric_id == "percentile":
        m = re.search(r"\bp(\d{1,2}(?:\.\d+)?)(?![\d])", s) \
            or re.search(r"(\d{1,2}(?:\.\d+)?)(?:st|nd|rd|th)\s*percentile", s)
        return "p%s" % m.group(1) if m else None
    if metric_id == "correlation" and "spearman" in s:
        return "spearman"
    if metric_id == "mape" and "smape" in s:
        return "smape"
    if metric_id == "effect_size":
        if "hedges" in s:
            return "hedges_g"
        if "glass" in s:
            return "glass_delta"
        return None
    if metric_id == "confidence_interval":
        m = re.search(r"(90|95|99)\s*%", s)
        return "t%s" % m.group(1) if m else None
    if metric_id == "error_rate":
        if "5xx" in s:
            return "http5xx"
        if "4xx" in s:
            return "http4xx"
        return None
    if metric_id == "ece":
        m = re.search(r"(\d+)[\- ]bin", s)
        return "bins=%s" % m.group(1) if m else None
    if metric_id == "pinball_loss":
        m = re.search(r"q\s*=?\s*(0?\.\d+)", s)
        return "q=%s" % m.group(1) if m else None
    if metric_id == "speedup_ratio" and "median" in s:
        return "median"
    if metric_id == "churn_rate" and "retention" in s:
        return "retention"
    if metric_id == "chi_square" and ("statistic" in s or "stat " in s):
        return "statistic"
    if metric_id == "growth_rate" and ("total" in s or "overall" in s or "since" in s):
        return "total"
    return None


def parse_claim(text):
    """Free-text claim -> (value, metric_hint). Accepts 'accuracy 0.87', '+14,698% backtest',
    '$4.2M revenue', 'processed 10,000 rows', or a bare number. '%' divides by 100; k/M/B scale.
    Returns (None, hint) when no number is present."""
    if text is None:
        return None, None
    if isinstance(text, (int, float)):
        f = float(text)
        return (f if math.isfinite(f) else None), None
    s = _normalize_claim_text(str(text).strip())
    low = s.lower()
    hint = None
    for word, mid in CLAIM_METRIC_HINTS:
        if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(word.lower()), low):
            hint = mid
            break
    matches = [mm for mm in _CLAIM_NUM.finditer(s)
               # ordinals ("95th percentile", "3rd quartile") are positions, never claim values
               if not re.match(r"(?:st|nd|rd|th)\b", s[mm.end(2):mm.end(2) + 2], re.IGNORECASE)]
    if not matches:
        return None, hint
    m = matches[0]
    # level-prefixed claims ("95% VaR 2.14%", "99% CI 0.4"): the leading confidence level is a
    # parameter, not the claim value - take the number AFTER it when one exists
    if hint in ("value_at_risk", "cvar", "confidence_interval") and len(matches) > 1:
        if float(m.group(2).replace(",", "")) in (90.0, 95.0, 97.5, 99.0):
            m = matches[1]
    # "npv at 10% 5000": a leading PERCENT is the discount rate (a parameter infer_convention reads),
    # not the claimed NPV - take the value after it (NPV is a currency amount, never a bare percent)
    elif hint == "npv" and len(matches) > 1 and (m.group(3) or "") == "%":
        m = matches[1]
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
    # a value that overflows to +/-inf (e.g. "1e999", a 50k-digit integer) is not a checkable
    # FINITE claim; returning None routes it to a clean input error, never an inf-budget CONFIRM.
    return (val if math.isfinite(val) else None), hint


# ---------- contract loading (tolerant: JSON first, then a small YAML subset) ----------

# a minimal, copy-pasteable verify.yaml - shown verbatim in malformed-contract errors
CONTRACT_EXAMPLE = """\
run: {entrypoint: main.py, network: off}
artifacts:
  - path: out.csv
    columns:
      value: {tag: value}
metrics: []
"""

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
    except (ValueError, RecursionError):
        # RecursionError: pathologically deep nesting (a hand-written contract thousands of maps
        # deep) - fall through to the bounded YAML parse, which converts it to a clean ValueError.
        try:
            obj = parse_simple_yaml(text)
        except (ValueError, RecursionError) as e:
            raise ValueError(
                "%s could not be parsed (%s). The contract accepts JSON or simple YAML "
                "(nested 'key: value' maps and '- ' lists). A minimal verify.yaml:\n%s"
                % (path, type(e).__name__ if isinstance(e, RecursionError) else e, CONTRACT_EXAMPLE))
    if not isinstance(obj, dict):
        raise ValueError("%s parsed to %s, expected a mapping. A minimal verify.yaml:\n%s"
                         % (path, type(obj).__name__, CONTRACT_EXAMPLE))
    return obj


_GRADE_ORDER = ["author-asserted", "plausibly-bound", "independently-bound"]


def regrade_committed(contract, target):
    """Re-derive each committed metric's binding_status from the ACTUAL data and confirm its claim
    target, so a hand-written multi-metric verify.yaml can REFUTE a fabricated SECONDARY metric (it
    used to silently demote it to INCONCLUSIVE). Every committed metric is explicitly pinned by the
    author, so it is a confirmed target; its binding is graded like a forced/unique drafted one
    (generic-numeric upgraded to independently-bound only when clean-finite). Never DOWNGRADES a
    status the author declared (max of declared vs re-derived) - so existing committed fixtures are
    unaffected. Mutates and returns the contract."""
    upgradable = _GENERIC_NUMERIC_TAGS | {"prediction"}
    # grade every declared column once, per artifact, with within-artifact tag-uniqueness
    cell = {}  # (artifact_path, column) -> (grade, finite, tag, tag_count_in_artifact)
    for a in contract.get("artifacts", []):
        path = a.get("path")
        full = os.path.join(target, path) if path else None
        cols = a.get("columns") or {}
        tcount = {}
        for _cn, spec in cols.items():
            t = (spec or {}).get("tag")
            if t:
                tcount[t] = tcount.get(t, 0) + 1
        header_idx = {}
        if full and os.path.exists(full):
            try:
                header_idx = {h: i for i, h in enumerate(next(csv.reader(open(full, newline=""))))}
            except (StopIteration, OSError):
                header_idx = {}
        for cn, spec in cols.items():
            t = (spec or {}).get("tag")
            if not t or cn not in header_idx:
                cell[(path, cn)] = ("author-asserted", False, t, tcount.get(t, 0))
                continue
            if t in STRING_KEY_TAGS:
                g, fin = _grade_string_key(_sample_strings(full, header_idx[cn])), False
            else:
                sample = _sample_numeric(full, header_idx[cn])
                g, fin = _grade(t, sample), _finite_clean(sample)
            cell[(path, cn)] = (g, fin, t, tcount.get(t, 0))
    for m in contract.get("metrics", []):
        art = m.get("artifact")
        binding = m.get("binding") or {}
        grades = []
        for tag, col in binding.items():
            g, fin, t, cnt = cell.get((art, col), ("author-asserted", False, tag, 0))
            if g == "plausibly-bound" and tag in upgradable and fin and cnt == 1:
                g = "independently-bound"
            grades.append(g)
        regraded = min(grades, key=_GRADE_ORDER.index) if grades else "author-asserted"
        declared = m.get("binding_status", "author-asserted")
        # never downgrade what the author declared; otherwise take the data-derived grade
        m["binding_status"] = max(declared, regraded, key=_GRADE_ORDER.index) \
            if declared in _GRADE_ORDER else regraded
        if m.get("claimed_value") is not None and m.get("metric_id"):
            m["claim_confirmed"] = True
    return contract


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


def _finite_clean(vals):
    """True iff vals is non-empty and every value is a finite real number (no NaN/Inf)."""
    if not vals:
        return False
    for v in vals:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return False
        if f != f or f in (float("inf"), float("-inf")):
            return False
    return True


# generic numeric tags with NO inherent name->range expectation: a clean finite column IS the only
# independent check available, so a UNIQUELY-bound one (sole candidate for the tag in its artifact)
# is independently-bound. Range-checked tags (score/prob/return/...) are NOT upgraded by uniqueness -
# a downgrade there means the values violated the tag's expectation, which uniqueness cannot excuse.
_GENERIC_NUMERIC_TAGS = {"value", "x", "y", "cost", "cashflow", "weight", "target", "magnitude",
                         "amount", "quantity"}


def _grade(tag, vals):
    """Independent sanity check of name+value. Any failure caps at plausibly-bound."""
    if not vals:
        return "author-asserted"
    # a column carrying NaN/Inf is bound but not cleanly sanity-checked - degrade (never upgrade),
    # and crucially never reach the int(v) range checks below with a non-finite v (int(inf) raises)
    if not all(math.isfinite(v) for v in vals):
        return "plausibly-bound"
    n = len(vals)
    mean = sum(vals) / n
    rng = (min(vals), max(vals))
    if tag in ("return", "benchmark"):
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
                finite = False
                if tag in STRING_KEY_TAGS:
                    grade = _grade_string_key(_sample_strings(full, idx))
                elif tag:
                    sample = _sample_numeric(full, idx)
                    grade = _grade(tag, sample)
                    finite = _finite_clean(sample)
                else:
                    grade = "author-asserted"
                cols[h] = {"tag": tag, "grade": grade, "dtype": "float", "na_policy": "error",
                           "finite": finite}
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


# When the user NAMES the metric (claim text or --metric), a required tag may bind through an
# alias: probability columns are tagged `score` by name-inference but brier/log_loss/ece require
# `prob` (same data); regression's `target` is often a column tagged `label` (y_true); quantile
# metrics' `value` may be a latency column tagged `duration`. Aliases apply ONLY to forced/named
# metrics - auto-pick keeps the strict tag table so it never reinterprets columns on its own.
TAG_ALIASES = {"prob": ("score",), "target": ("label",), "value": ("duration",)}


def _pick_metric(arts, forced=None, target=None):
    """Return (metric_id, artifact_rel, binding, binding_status) or None."""
    # map tag -> (artifact, column, grade)
    available = {}
    for a in arts:
        for cname, spec in a["columns"].items():
            if spec["tag"]:
                available.setdefault(spec["tag"], (a["path"], cname, spec["grade"]))
    wanted = None
    metric_string_tags = set()
    if forced:
        # bind whatever tags the recipe needs from availability
        import recipes as R
        fn = R.get(forced)
        req = set((fn.manifest.get("required_tags") if fn else []) or [])
        # tags this RECIPE declares as string-typed (e.g. exact_match's prediction/reference):
        # their numeric grade is meaningless for text - they re-grade as string keys below
        metric_string_tags = set((fn.manifest.get("string_tags") if fn else []) or [])
        wanted = (req, forced)
    else:
        for tags, mid in METRIC_BY_TAGS:
            if tags <= set(available):
                wanted = (tags, mid)
                break
    if not wanted:
        return None
    tags, mid = wanted
    by_art = {a["path"]: a["columns"] for a in arts}
    # tags whose only independent check is "clean finite numbers" - upgradable to independently-bound
    # ONLY when the metric is forced (named/pinned) AND the binding is unambiguous (sole column for the
    # tag) AND the column is finite. This lets a PINNED generic metric (column_sum/rmse/mae/r2/
    # percentile/npv/...) REFUTE a clear lie, while a bare-number auto-pick (forced is None) stays
    # plausibly-bound -> INCONCLUSIVE (no false REFUTE from a guessed metric or an ambiguous column).
    upgradable = _GENERIC_NUMERIC_TAGS | {"prediction"}
    binding = {}
    grades = []
    art = None
    for t in tags:
        source = t
        if t not in available and forced:
            source = next((a for a in TAG_ALIASES.get(t, ()) if a in available), t)
        if source not in available:
            return None
        art, col, grade = available[source]
        unique = sum(1 for s in by_art.get(art, {}).values() if s.get("tag") == source) == 1
        if forced and t in metric_string_tags and target and unique:
            # metric-declared STRING column (e.g. exact_match prediction/reference): grade by
            # string-key coverage like query/group - the numeric grade is meaningless for text
            full = os.path.join(target, art)
            try:
                header = next(csv.reader(open(full, newline="")))
                grade = _grade_string_key(_sample_strings(full, header.index(col)))
            except (OSError, StopIteration, ValueError):
                grade = "author-asserted"
        elif (forced and grade == "plausibly-bound" and source in upgradable
                and by_art.get(art, {}).get(col, {}).get("finite") and unique):
            grade = "independently-bound"
        binding[t] = col
        grades.append(grade)
    order = ["author-asserted", "plausibly-bound", "independently-bound"]
    worst = min(grades, key=order.index) if grades else "author-asserted"
    if art is None:  # zero-tag recipe (e.g. row_count): bind to the first scanned artifact
        if not arts:
            return None
        art = arts[0]["path"]
    return mid, art, binding, worst


def draft(target, claim=None, metric=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    claim_value, hint = parse_claim(claim)
    if claim is not None and claim_value is None:
        raise ValueError(
            "no usable claimed value in %r - state a finite number, e.g. \"accuracy 0.87\" or "
            "\"+14,698%%\" (a value that overflows to infinity is not checkable)" % claim)
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
    picked = _pick_metric(arts, metric, target=target)
    if picked:
        mid, art, binding, grade = picked
        # Claim-aware disambiguation: a claim ABOUT the benchmark ("buy and hold returned X",
        # "the market did X") must bind the benchmark-tagged column, never the strategy column -
        # otherwise a true benchmark claim false-REFUTES against the strategy's numbers.
        low = str(claim or "").lower()
        if "return" in binding and any(k in low for k in (
                "buy and hold", "buy-and-hold", "buy & hold", "buyhold", "benchmark", "the market")):
            for a in arts:
                bench = next((c for c, s in a["columns"].items() if s["tag"] == "benchmark"), None)
                if bench:
                    art = a["path"]
                    binding = dict(binding, **{"return": bench})
                    grade = a["columns"][bench]["grade"]
                    break
        # The claim TARGET is confirmed only when the caller stated the number AND the metric is
        # unambiguous (named explicitly / in the claim text) or the binding is independently sane-checked.
        # An auto-picked metric under a bare-number claim stays unconfirmed: REFUTED is then blocked
        # (degrades to INCONCLUSIVE), so a wrong auto-binding can never manufacture a refutation.
        target_confirmed = claim_value is not None and (metric is not None or grade == "independently-bound")
        contract["metrics"].append({
            "metric_id": mid, "artifact": art, "binding": binding,
            "convention": infer_convention(claim, mid),
            "claimed_value": claim_value,
            "claimed_precision": claim_precision(claim) if claim_value is not None else None,
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
