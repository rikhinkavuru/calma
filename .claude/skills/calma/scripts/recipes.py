"""calma.recipes - the canonical metric-recipe library (registered callables).

A recipe takes a `cols` dict (column-name -> list of values, parsed from a raw machine-readable
artifact) plus a `binding` (which columns feed it) and an optional `convention`, and returns a
RecipeResult {value, terms, near_zero_vol, path_dependent, degenerate}. Two families ship at M1:
quant (sharpe, total_return, max_drawdown) and general/classification (accuracy, auc) - so the recipe
architecture is demonstrably domain-agnostic, not quant-only.

The value is computed ONLY via numeric.py kernels (fsum / pairwise-product / sqrt) - no transcendental,
no numpy. A `manifest` per recipe declares required tags, periodicity, accepted conventions, set maturity.
"""
import math

import numeric as N

_REGISTRY = {}


def register(metric_id, **manifest):
    def deco(fn):
        fn.metric_id = metric_id
        fn.manifest = dict(manifest)
        _REGISTRY[metric_id] = fn
        return fn
    return deco


def get(metric_id):
    return _REGISTRY.get(metric_id)


def ids():
    return sorted(_REGISTRY)


def _result(value, terms=None, near_zero_vol=False, path_dependent=False):
    degenerate = not (isinstance(value, float) and value == value and value not in (float("inf"), float("-inf")))
    return {
        "value": value, "terms": terms or {}, "near_zero_vol": near_zero_vol,
        "path_dependent": path_dependent, "degenerate": bool(degenerate),
    }


# ---- quant family ----
@register("total_return", family="quant", required_tags=["return"], set_maturity="reviewed",
          accepted_conventions=["compounded"])
def total_return(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.total_return(rets), {"n": len(rets)})


@register("sharpe", family="quant", required_tags=["return"], periodicity_param="periods",
          set_maturity="reviewed", accepted_conventions=["252", "365", "52"])
def sharpe(cols, binding, convention=None):
    rets = cols[binding["return"]]
    periods = int(convention or binding.get("periods") or 252)
    val, nzv = N.sharpe(rets, periods)
    se = N.sharpe_se(val, len(rets)) if not nzv else float("nan")
    return _result(val, {"periods": periods, "n": len(rets), "sampling_se": se}, near_zero_vol=nzv)


@register("max_drawdown", family="quant", required_tags=["return"], set_maturity="reviewed",
          accepted_conventions=["compounded"])
def max_drawdown(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.max_drawdown(rets), {"n": len(rets)}, path_dependent=True)


# ---- general / classification family ----
@register("accuracy", family="classification", required_tags=["label", "prediction"],
          set_maturity="reviewed", accepted_conventions=["argmax"])
def accuracy(cols, binding, convention=None):
    preds = cols[binding["prediction"]]
    labels = cols[binding["label"]]
    return _result(N.accuracy(preds, labels), {"n": len(labels)})


@register("auc", family="classification", required_tags=["label", "score"], set_maturity="reviewed",
          accepted_conventions=["roc-auc"])
def auc(cols, binding, convention=None):
    scores = cols[binding["score"]]
    labels = cols[binding["label"]]
    val = N.auc(scores, labels)
    se = N.auc_delong_se(scores, labels)
    return _result(val, {"n": len(labels), "sampling_se": se, "se_method": "delong"})


# ---- regression family ----
@register("rmse", family="regression", required_tags=["prediction", "target"], set_maturity="reviewed")
def rmse(cols, binding, convention=None):
    return _result(N.rmse(cols[binding["prediction"]], cols[binding["target"]]), {"n": len(cols[binding["target"]])})


@register("mae", family="regression", required_tags=["prediction", "target"], set_maturity="reviewed")
def mae(cols, binding, convention=None):
    return _result(N.mae(cols[binding["prediction"]], cols[binding["target"]]), {"n": len(cols[binding["target"]])})


@register("r2", family="regression", required_tags=["prediction", "target"], set_maturity="reviewed")
def r2(cols, binding, convention=None):
    return _result(N.r2(cols[binding["prediction"]], cols[binding["target"]]), {"n": len(cols[binding["target"]])})


# ---- classification depth ----
@register("precision", family="classification", required_tags=["prediction", "label"], set_maturity="reviewed")
def precision(cols, binding, convention=None):
    return _result(N.precision(cols[binding["prediction"]], cols[binding["label"]]), {"n": len(cols[binding["label"]])})


@register("recall", family="classification", required_tags=["prediction", "label"], set_maturity="reviewed")
def recall(cols, binding, convention=None):
    return _result(N.recall(cols[binding["prediction"]], cols[binding["label"]]), {"n": len(cols[binding["label"]])})


@register("f1", family="classification", required_tags=["prediction", "label"], set_maturity="reviewed")
def f1(cols, binding, convention=None):
    return _result(N.f1(cols[binding["prediction"]], cols[binding["label"]]), {"n": len(cols[binding["label"]])})


# ---- analytics / data-pipeline aggregates ----
@register("column_sum", family="analytics", required_tags=["value"], set_maturity="reviewed")
def column_sum(cols, binding, convention=None):
    return _result(N.col_sum(cols[binding["value"]]), {"n": len(cols[binding["value"]])})


@register("column_mean", family="analytics", required_tags=["value"], set_maturity="reviewed")
def column_mean(cols, binding, convention=None):
    return _result(N.col_mean(cols[binding["value"]]), {"n": len(cols[binding["value"]])})


@register("row_count", family="analytics", required_tags=[], set_maturity="reviewed")
def row_count(cols, binding, convention=None):
    col = binding.get("column") or (next(iter(cols)) if cols else None)
    return _result(float(len(cols[col])) if col in cols else float("nan"), {"column": col})


@register("brier", family="classification", required_tags=["prob", "label"], set_maturity="reviewed")
def brier(cols, binding, convention=None):
    return _result(N.brier(cols[binding["prob"]], cols[binding["label"]]), {"n": len(cols[binding["label"]])})


# ======================================================================================
# Convention parsing helpers (conventions are plain strings on the contract metric:
# "k=10", "p95", "bins=15", "welch", "spearman", "t99", "sum:West", "median", ...)
# ======================================================================================

def _conv_str(convention):
    return str(convention).strip().lower() if convention is not None else ""


def _conv_int(convention, key, default):
    """Parse 'k=10' / 'bins=15' / bare '10' -> int."""
    s = _conv_str(convention)
    if not s:
        return default
    if "=" in s:
        k, _, v = s.partition("=")
        if k.strip() != key:
            return default
        s = v.strip()
    try:
        return int(float(s))
    except ValueError:
        return default


def _conv_q(convention):
    """Parse a quantile spec: 'p95'/'p99.9' -> 0.95/0.999, 'q=0.9' -> 0.9, '90' -> 0.9, '0.9' -> 0.9."""
    s = _conv_str(convention)
    if not s:
        return float("nan")
    if s.startswith("p") or s.startswith("q="):
        s = s[1:] if s.startswith("p") else s[2:]
        try:
            v = float(s)
        except ValueError:
            return float("nan")
        return v / 100.0 if s.find(".") == -1 or v > 1.0 else v
    try:
        v = float(s)
    except ValueError:
        return float("nan")
    return v / 100.0 if v > 1.0 else v


def _conv_level(convention, default_dist="t", default_level=0.95):
    """Parse 't95'/'z99'/'t90' -> (dist, level)."""
    s = _conv_str(convention)
    if not s:
        return default_dist, default_level
    dist = default_dist
    if s[0] in ("t", "z"):
        dist, s = s[0], s[1:]
    try:
        v = float(s)
        level = v / 100.0 if v > 1.0 else v
    except ValueError:
        level = default_level
    return dist, level


# ======================================================================================
# Pack 1 - performance & engineering claims
# ======================================================================================

@register("speedup_ratio", family="engineering", required_tags=["before", "after"],
          set_maturity="reviewed", accepted_conventions=["mean", "median"])
def speedup_ratio(cols, binding, convention=None):
    before, after = cols[binding["before"]], cols[binding["after"]]
    mode = _conv_str(convention) or "mean"
    return _result(N.speedup_ratio(before, after, mode),
                   {"n_before": len(before), "n_after": len(after), "mode": mode})


def _latency(cols, binding, q):
    durs = cols[binding["duration"]]
    return _result(N.quantile(durs, q), {"n": len(durs), "q": q, "method": "linear"})


@register("latency_p50", family="engineering", required_tags=["duration"], set_maturity="reviewed")
def latency_p50(cols, binding, convention=None):
    return _latency(cols, binding, 0.50)


@register("latency_p95", family="engineering", required_tags=["duration"], set_maturity="reviewed")
def latency_p95(cols, binding, convention=None):
    return _latency(cols, binding, 0.95)


@register("latency_p99", family="engineering", required_tags=["duration"], set_maturity="reviewed")
def latency_p99(cols, binding, convention=None):
    return _latency(cols, binding, 0.99)


@register("throughput", family="engineering", required_tags=["duration"], set_maturity="reviewed")
def throughput(cols, binding, convention=None):
    durs = cols[binding["duration"]]
    return _result(N.throughput(durs), {"n": len(durs)})


@register("peak_memory", family="engineering", required_tags=["value"], set_maturity="reviewed")
def peak_memory(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.peak(xs), {"n": len(xs)})


@register("test_coverage", family="engineering", required_tags=["hits"], set_maturity="reviewed")
def test_coverage(cols, binding, convention=None):
    hits = cols[binding["hits"]]
    return _result(N.coverage_fraction(hits), {"n_lines": len(hits)})


@register("error_rate", family="engineering", required_tags=["flag"], set_maturity="reviewed",
          accepted_conventions=["flag", "http4xx", "http5xx"])
def error_rate(cols, binding, convention=None):
    flags = cols[binding["flag"]]
    mode = _conv_str(convention) or "flag"
    return _result(N.error_rate(flags, mode), {"n": len(flags), "mode": mode})


# ======================================================================================
# Pack 2 - analytics depth
# ======================================================================================

@register("column_median", family="analytics", required_tags=["value"], set_maturity="reviewed")
def column_median(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.quantile(xs, 0.5), {"n": len(xs), "method": "linear"})


@register("percentile", family="analytics", required_tags=["value"], set_maturity="reviewed",
          accepted_conventions=["p<NN>", "q=<frac>"])
def percentile(cols, binding, convention=None):
    xs = cols[binding["value"]]
    q = _conv_q(convention)
    return _result(N.quantile(xs, q), {"n": len(xs), "q": q, "method": "linear"})


@register("groupby_aggregate", family="analytics", required_tags=["group", "value"],
          set_maturity="reviewed", string_tags=["group"],
          accepted_conventions=["sum", "mean", "sum:<group>", "mean:<group>"])
def groupby_aggregate(cols, binding, convention=None):
    groups, values = cols[binding["group"]], cols[binding["value"]]
    s = str(convention).strip() if convention is not None else "sum"
    agg, _, label = s.partition(":")
    agg = agg.strip().lower() or "sum"
    label = label.strip() or None
    val, per_group = N.groupby_aggregate(groups, values, agg, label)
    return _result(val, {"n": len(values), "agg": agg, "group": label, "groups": per_group})


@register("distinct_count", family="analytics", required_tags=["value"], set_maturity="reviewed",
          string_tags=["value"], accepted_conventions=["drop_null", "include_null"])
def distinct_count(cols, binding, convention=None):
    raw = cols[binding["value"]]
    include_null = _conv_str(convention) == "include_null"
    return _result(N.distinct_count(raw, include_null), {"n": len(raw)})


@register("growth_rate", family="analytics", required_tags=["value"], set_maturity="reviewed",
          accepted_conventions=["period", "total"])
def growth_rate(cols, binding, convention=None):
    xs = cols[binding["value"]]
    mode = _conv_str(convention) or "period"
    return _result(N.growth_rate(xs, mode), {"n": len(xs), "mode": mode})


@register("ratio_share", family="analytics", required_tags=["flag"], set_maturity="reviewed")
def ratio_share(cols, binding, convention=None):
    flags = cols[binding["flag"]]
    return _result(N.ratio_share(flags), {"n": len(flags)})


@register("null_fraction", family="analytics", required_tags=["value"], set_maturity="reviewed",
          string_tags=["value"])
def null_fraction(cols, binding, convention=None):
    raw = cols[binding["value"]]
    return _result(N.null_fraction(raw), {"n": len(raw)})


@register("duplicate_count", family="analytics", required_tags=["value"], set_maturity="reviewed",
          string_tags=["value"])
def duplicate_count(cols, binding, convention=None):
    raw = cols[binding["value"]]
    return _result(N.duplicate_count(raw), {"n": len(raw)})


@register("join_row_loss", family="analytics", required_tags=["left_key", "joined_key"],
          set_maturity="reviewed", string_tags=["left_key", "joined_key"])
def join_row_loss(cols, binding, convention=None):
    left, joined = cols[binding["left_key"]], cols[binding["joined_key"]]
    return _result(N.join_row_loss(left, joined), {"n_left": len(left), "n_joined": len(joined)})


# ======================================================================================
# Pack 3 - modern ML & RAG evals
# (retrieval layout: one row per (query, rank, relevance); rank 1 = best)
# ======================================================================================

@register("recall_at_k", family="retrieval", required_tags=["query", "rank", "relevance"],
          set_maturity="reviewed", string_tags=["query"], accepted_conventions=["k=<int>"])
def recall_at_k(cols, binding, convention=None):
    k = _conv_int(convention, "k", 10)
    val = N.recall_at_k(cols[binding["query"]], cols[binding["rank"]], cols[binding["relevance"]], k)
    return _result(val, {"k": k, "n_rows": len(cols[binding["rank"]])})


@register("ndcg_at_k", family="retrieval", required_tags=["query", "rank", "relevance"],
          set_maturity="reviewed", string_tags=["query"],
          accepted_conventions=["k=<int>", "k=<int>,exp"])
def ndcg_at_k(cols, binding, convention=None):
    s = _conv_str(convention)
    gain = "exp" if "exp" in s else "linear"
    k = _conv_int(s.replace(",exp", "").replace("exp", "") or None, "k", 10)
    val = N.ndcg_at_k(cols[binding["query"]], cols[binding["rank"]], cols[binding["relevance"]], k, gain)
    return _result(val, {"k": k, "gain": gain, "n_rows": len(cols[binding["rank"]])})


@register("mrr", family="retrieval", required_tags=["query", "rank", "relevance"],
          set_maturity="reviewed", string_tags=["query"], accepted_conventions=["k=<int>"])
def mrr(cols, binding, convention=None):
    k = _conv_int(convention, "k", 0) or None
    val = N.mrr(cols[binding["query"]], cols[binding["rank"]], cols[binding["relevance"]], k)
    return _result(val, {"k": k, "n_rows": len(cols[binding["rank"]])})


@register("top_k_accuracy", family="retrieval", required_tags=["query", "rank", "relevance"],
          set_maturity="reviewed", string_tags=["query"], accepted_conventions=["k=<int>"])
def top_k_accuracy(cols, binding, convention=None):
    k = _conv_int(convention, "k", 5)
    val = N.hit_at_k(cols[binding["query"]], cols[binding["rank"]], cols[binding["relevance"]], k)
    return _result(val, {"k": k, "n_rows": len(cols[binding["rank"]])})


@register("exact_match", family="llm-eval", required_tags=["prediction", "reference"],
          set_maturity="reviewed", string_tags=["prediction", "reference"],
          accepted_conventions=["strict", "normalized"])
def exact_match(cols, binding, convention=None):
    normalized = _conv_str(convention) == "normalized"
    preds, refs = cols[binding["prediction"]], cols[binding["reference"]]
    return _result(N.exact_match(preds, refs, normalized),
                   {"n": len(preds), "normalized": normalized})


@register("pass_at_k", family="llm-eval", required_tags=["problem", "correct"],
          set_maturity="reviewed", string_tags=["problem"], accepted_conventions=["k=<int>"])
def pass_at_k(cols, binding, convention=None):
    k = _conv_int(convention, "k", 1)
    probs, corrects = cols[binding["problem"]], cols[binding["correct"]]
    return _result(N.pass_at_k(probs, corrects, k),
                   {"k": k, "n_samples": len(corrects), "n_problems": len(set(p.strip() for p in probs))})


@register("macro_f1", family="classification", required_tags=["prediction", "label"], set_maturity="reviewed")
def macro_f1(cols, binding, convention=None):
    return _result(N.macro_f1(cols[binding["prediction"]], cols[binding["label"]]),
                   {"n": len(cols[binding["label"]])})


@register("micro_f1", family="classification", required_tags=["prediction", "label"], set_maturity="reviewed")
def micro_f1(cols, binding, convention=None):
    return _result(N.micro_f1(cols[binding["prediction"]], cols[binding["label"]]),
                   {"n": len(cols[binding["label"]])})


@register("pr_auc", family="classification", required_tags=["score", "label"], set_maturity="reviewed",
          accepted_conventions=["average_precision", "trapezoid"])
def pr_auc(cols, binding, convention=None):
    scores, labels = cols[binding["score"]], cols[binding["label"]]
    mode = _conv_str(convention) or "average_precision"
    val = N.pr_auc_trapezoid(scores, labels) if mode == "trapezoid" else N.average_precision(scores, labels)
    return _result(val, {"n": len(labels), "mode": mode})


@register("log_loss", family="classification", required_tags=["prob", "label"], set_maturity="reviewed",
          accepted_conventions=["exact", "clip"])
def log_loss(cols, binding, convention=None):
    clip = _conv_str(convention) == "clip"
    return _result(N.log_loss(cols[binding["prob"]], cols[binding["label"]], clip),
                   {"n": len(cols[binding["label"]]), "clip": clip})


@register("mcc", family="classification", required_tags=["prediction", "label"], set_maturity="reviewed")
def mcc(cols, binding, convention=None):
    return _result(N.mcc(cols[binding["prediction"]], cols[binding["label"]]),
                   {"n": len(cols[binding["label"]])})


@register("ece", family="classification", required_tags=["prob", "label"], set_maturity="reviewed",
          accepted_conventions=["bins=<int>"])
def ece(cols, binding, convention=None):
    bins = _conv_int(convention, "bins", 15)
    return _result(N.ece(cols[binding["prob"]], cols[binding["label"]], bins),
                   {"n": len(cols[binding["label"]]), "bins": bins})


# ======================================================================================
# Pack 4 - statistical claims (two-sample layout: tags sample_a / sample_b)
# ======================================================================================

@register("p_value", family="stats", required_tags=["sample_a", "sample_b"], set_maturity="reviewed",
          accepted_conventions=["welch", "pooled", "z"])
def p_value(cols, binding, convention=None):
    a, b = cols[binding["sample_a"]], cols[binding["sample_b"]]
    mode = _conv_str(convention) or "welch"
    return _result(N.t_test_p(a, b, mode), {"n_a": len(a), "n_b": len(b), "mode": mode})


@register("confidence_interval", family="stats", required_tags=["value"], set_maturity="reviewed",
          accepted_conventions=["t95", "t90", "t99", "z95", "z99"])
def confidence_interval(cols, binding, convention=None):
    xs = cols[binding["value"]]
    dist, level = _conv_level(convention)
    return _result(N.ci_half_width(xs, level, dist), {"n": len(xs), "dist": dist, "level": level})


@register("lift", family="stats", required_tags=["sample_a", "sample_b"], set_maturity="reviewed",
          accepted_conventions=["relative", "absolute"])
def lift(cols, binding, convention=None):
    a, b = cols[binding["sample_a"]], cols[binding["sample_b"]]
    mode = _conv_str(convention) or "relative"
    return _result(N.lift(a, b, mode), {"n_control": len(a), "n_treatment": len(b), "mode": mode})


@register("chi_square", family="stats", required_tags=["group", "outcome"], set_maturity="reviewed",
          string_tags=["group", "outcome"],
          accepted_conventions=["p", "statistic", "p-no-yates", "statistic-no-yates"])
def chi_square(cols, binding, convention=None):
    groups, outcomes = cols[binding["group"]], cols[binding["outcome"]]
    s = _conv_str(convention) or "p"
    yates = "no-yates" not in s
    output = "statistic" if s.startswith("statistic") else "p"
    return _result(N.chi_square(groups, outcomes, yates, output),
                   {"n": len(groups), "yates": yates, "output": output})


@register("correlation", family="stats", required_tags=["x", "y"], set_maturity="reviewed",
          accepted_conventions=["pearson", "spearman"])
def correlation(cols, binding, convention=None):
    xs, ys = cols[binding["x"]], cols[binding["y"]]
    mode = _conv_str(convention) or "pearson"
    val = N.spearman_r(xs, ys) if mode == "spearman" else N.pearson_r(xs, ys)
    return _result(val, {"n": len(xs), "mode": mode})


@register("effect_size", family="stats", required_tags=["sample_a", "sample_b"], set_maturity="reviewed",
          accepted_conventions=["cohen_d", "hedges_g", "glass_delta"])
def effect_size(cols, binding, convention=None):
    a, b = cols[binding["sample_a"]], cols[binding["sample_b"]]
    mode = _conv_str(convention) or "cohen_d"
    return _result(N.cohen_d(a, b, mode), {"n_a": len(a), "n_b": len(b), "mode": mode})


def _conv_float(convention, key, default):
    """Parse 'rate=0.08' / 'q=0.9' / bare '0.08' -> float."""
    s = _conv_str(convention)
    if not s:
        return default
    if "=" in s:
        k, _, v = s.partition("=")
        if k.strip() != key:
            return default
        s = v.strip()
    try:
        return float(s)
    except ValueError:
        return default


# ======================================================================================
# Pack 5 - business & finance beyond trading
# ======================================================================================

@register("cagr", family="finance", required_tags=["value"], set_maturity="reviewed",
          accepted_conventions=["periods=<per-year>"])
def cagr(cols, binding, convention=None):
    xs = cols[binding["value"]]
    ppy = _conv_int(convention, "periods", 1)
    return _result(N.cagr(xs, float(ppy)), {"n": len(xs), "periods_per_year": ppy})


@register("npv", family="finance", required_tags=["cashflow"], set_maturity="reviewed",
          accepted_conventions=["rate=<frac>"])
def npv(cols, binding, convention=None):
    cf = cols[binding["cashflow"]]
    rate = _conv_float(convention, "rate", None)
    val = N.npv(cf, rate) if rate is not None else float("nan")
    return _result(val, {"n": len(cf), "rate": rate})


@register("irr", family="finance", required_tags=["cashflow"], set_maturity="reviewed")
def irr(cols, binding, convention=None):
    cf = cols[binding["cashflow"]]
    return _result(N.irr(cf), {"n": len(cf)})


@register("churn_rate", family="finance", required_tags=["flag"], set_maturity="reviewed",
          accepted_conventions=["churn", "retention"])
def churn_rate(cols, binding, convention=None):
    flags = cols[binding["flag"]]
    mode = _conv_str(convention) or "churn"
    return _result(N.churn_rate(flags, mode), {"n": len(flags), "mode": mode})


@register("margin_pct", family="finance", required_tags=["value", "cost"], set_maturity="reviewed")
def margin_pct(cols, binding, convention=None):
    rev, cost = cols[binding["value"]], cols[binding["cost"]]
    return _result(N.margin_pct(rev, cost), {"n_revenue": len(rev), "n_cost": len(cost)})


@register("reconciliation_total", family="finance", required_tags=["value_a", "value_b"],
          set_maturity="reviewed")
def reconciliation_total(cols, binding, convention=None):
    a, b = cols[binding["value_a"]], cols[binding["value_b"]]
    return _result(N.reconciliation_diff(a, b), {"n_a": len(a), "n_b": len(b)})


# ======================================================================================
# Pack 6 - forecasting
# ======================================================================================

@register("mape", family="forecasting", required_tags=["prediction", "target"], set_maturity="reviewed",
          accepted_conventions=["mape", "smape"])
def mape(cols, binding, convention=None):
    mode = _conv_str(convention) or "mape"
    val = N.mape(cols[binding["prediction"]], cols[binding["target"]], symmetric=(mode == "smape"))
    return _result(val, {"n": len(cols[binding["target"]]), "mode": mode})


@register("mase", family="forecasting", required_tags=["prediction", "target"], set_maturity="reviewed",
          accepted_conventions=["m=<season>"])
def mase(cols, binding, convention=None):
    m = _conv_int(convention, "m", 1)
    val = N.mase(cols[binding["prediction"]], cols[binding["target"]], m)
    return _result(val, {"n": len(cols[binding["target"]]), "m": m})


@register("pinball_loss", family="forecasting", required_tags=["prediction", "target"],
          set_maturity="reviewed", accepted_conventions=["q=<quantile>"])
def pinball_loss(cols, binding, convention=None):
    q = _conv_float(convention, "q", 0.5)
    val = N.pinball(cols[binding["prediction"]], cols[binding["target"]], q)
    return _result(val, {"n": len(cols[binding["target"]]), "q": q})


# ======================================================================================
# Pack 7 - quant risk & relative performance
# ======================================================================================

def _periods(convention, binding, default=252):
    return _conv_int(convention, "periods", int(binding.get("periods") or default))


@register("volatility", family="quant", required_tags=["return"], periodicity_param="periods",
          set_maturity="reviewed", accepted_conventions=["252", "365", "52"])
def volatility(cols, binding, convention=None):
    rets = cols[binding["return"]]
    p = _periods(convention, binding)
    return _result(N.volatility(rets, p), {"n": len(rets), "periods": p})


@register("downside_deviation", family="quant", required_tags=["return"], set_maturity="reviewed",
          accepted_conventions=["252", "365", "52"])
def downside_deviation(cols, binding, convention=None):
    rets = cols[binding["return"]]
    p = _periods(convention, binding)
    return _result(N.downside_deviation(rets, p), {"n": len(rets), "periods": p})


@register("sortino", family="quant", required_tags=["return"], set_maturity="reviewed",
          accepted_conventions=["252", "365", "52"])
def sortino(cols, binding, convention=None):
    rets = cols[binding["return"]]
    p = _periods(convention, binding)
    return _result(N.sortino(rets, p), {"n": len(rets), "periods": p, "target": 0.0})


@register("calmar", family="quant", required_tags=["return"], set_maturity="reviewed",
          accepted_conventions=["252", "365", "52"])
def calmar(cols, binding, convention=None):
    rets = cols[binding["return"]]
    p = _periods(convention, binding)
    return _result(N.calmar(rets, p), {"n": len(rets), "periods": p}, path_dependent=True)


@register("value_at_risk", family="quant", required_tags=["return"], set_maturity="reviewed",
          accepted_conventions=["p95", "p99"])
def value_at_risk(cols, binding, convention=None):
    rets = cols[binding["return"]]
    level = _conv_q(convention) if convention else 0.95
    return _result(N.value_at_risk(rets, level), {"n": len(rets), "level": level, "sign": "loss-positive"})


@register("cvar", family="quant", required_tags=["return"], set_maturity="reviewed",
          accepted_conventions=["p95", "p99"])
def cvar(cols, binding, convention=None):
    rets = cols[binding["return"]]
    level = _conv_q(convention) if convention else 0.95
    return _result(N.cvar(rets, level), {"n": len(rets), "level": level, "sign": "loss-positive"})


@register("win_rate", family="quant", required_tags=["return"], set_maturity="reviewed")
def win_rate(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.win_rate(rets), {"n": len(rets)})


@register("profit_factor", family="quant", required_tags=["return"], set_maturity="reviewed")
def profit_factor(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.profit_factor(rets), {"n": len(rets)})


@register("omega_ratio", family="quant", required_tags=["return"], set_maturity="reviewed",
          accepted_conventions=["threshold=<frac>"])
def omega_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    th = _conv_float(convention, "threshold", 0.0)
    return _result(N.omega_ratio(rets, th), {"n": len(rets), "threshold": th})


@register("beta", family="quant", required_tags=["return", "benchmark"], set_maturity="reviewed")
def beta(cols, binding, convention=None):
    rets, bench = cols[binding["return"]], cols[binding["benchmark"]]
    return _result(N.beta(rets, bench), {"n": len(rets)})


@register("alpha", family="quant", required_tags=["return", "benchmark"], set_maturity="reviewed",
          accepted_conventions=["252", "365", "52"])
def alpha(cols, binding, convention=None):
    rets, bench = cols[binding["return"]], cols[binding["benchmark"]]
    p = _periods(convention, binding)
    return _result(N.alpha(rets, bench, p), {"n": len(rets), "periods": p, "rf": 0.0})


@register("information_ratio", family="quant", required_tags=["return", "benchmark"],
          set_maturity="reviewed", accepted_conventions=["252", "365", "52"])
def information_ratio(cols, binding, convention=None):
    rets, bench = cols[binding["return"]], cols[binding["benchmark"]]
    p = _periods(convention, binding)
    return _result(N.information_ratio(rets, bench, p), {"n": len(rets), "periods": p})


@register("tracking_error", family="quant", required_tags=["return", "benchmark"],
          set_maturity="reviewed", accepted_conventions=["252", "365", "52"])
def tracking_error(cols, binding, convention=None):
    rets, bench = cols[binding["return"]], cols[binding["benchmark"]]
    p = _periods(convention, binding)
    return _result(N.tracking_error(rets, bench, p), {"n": len(rets), "periods": p})


# ======================================================================================
# Pack 8 - classification & regression depth II
# ======================================================================================

@register("balanced_accuracy", family="classification", required_tags=["prediction", "label"],
          set_maturity="reviewed")
def balanced_accuracy(cols, binding, convention=None):
    return _result(N.balanced_accuracy(cols[binding["prediction"]], cols[binding["label"]]),
                   {"n": len(cols[binding["label"]])})


@register("cohen_kappa", family="classification", required_tags=["prediction", "label"],
          set_maturity="reviewed")
def cohen_kappa(cols, binding, convention=None):
    return _result(N.cohen_kappa(cols[binding["prediction"]], cols[binding["label"]]),
                   {"n": len(cols[binding["label"]])})


@register("specificity", family="classification", required_tags=["prediction", "label"],
          set_maturity="reviewed")
def specificity(cols, binding, convention=None):
    return _result(N.specificity(cols[binding["prediction"]], cols[binding["label"]]),
                   {"n": len(cols[binding["label"]])})


@register("fbeta", family="classification", required_tags=["prediction", "label"],
          set_maturity="reviewed", accepted_conventions=["beta=<v>"])
def fbeta(cols, binding, convention=None):
    b = _conv_float(convention, "beta", 1.0)
    return _result(N.fbeta(cols[binding["prediction"]], cols[binding["label"]], b),
                   {"n": len(cols[binding["label"]]), "beta": b})


@register("jaccard", family="classification", required_tags=["prediction", "label"],
          set_maturity="reviewed")
def jaccard(cols, binding, convention=None):
    return _result(N.jaccard(cols[binding["prediction"]], cols[binding["label"]]),
                   {"n": len(cols[binding["label"]])})


@register("weighted_f1", family="classification", required_tags=["prediction", "label"],
          set_maturity="reviewed")
def weighted_f1(cols, binding, convention=None):
    return _result(N.weighted_f1(cols[binding["prediction"]], cols[binding["label"]]),
                   {"n": len(cols[binding["label"]])})


@register("ks_statistic", family="classification", required_tags=["score", "label"],
          set_maturity="reviewed")
def ks_statistic(cols, binding, convention=None):
    return _result(N.ks_statistic(cols[binding["score"]], cols[binding["label"]]),
                   {"n": len(cols[binding["label"]])})


@register("gini_norm", family="classification", required_tags=["score", "label"],
          set_maturity="reviewed")
def gini_norm(cols, binding, convention=None):
    return _result(N.gini_norm(cols[binding["score"]], cols[binding["label"]]),
                   {"n": len(cols[binding["label"]]), "definition": "2*AUC-1"})


@register("msle", family="regression", required_tags=["prediction", "target"],
          set_maturity="reviewed", accepted_conventions=["msle", "rmsle"])
def msle(cols, binding, convention=None):
    root = _conv_str(convention) == "rmsle"
    return _result(N.msle(cols[binding["prediction"]], cols[binding["target"]], root),
                   {"n": len(cols[binding["target"]]), "root": root})


@register("medae", family="regression", required_tags=["prediction", "target"], set_maturity="reviewed")
def medae(cols, binding, convention=None):
    return _result(N.medae(cols[binding["prediction"]], cols[binding["target"]]),
                   {"n": len(cols[binding["target"]])})


@register("max_error", family="regression", required_tags=["prediction", "target"], set_maturity="reviewed")
def max_error(cols, binding, convention=None):
    return _result(N.max_error(cols[binding["prediction"]], cols[binding["target"]]),
                   {"n": len(cols[binding["target"]])})


@register("explained_variance", family="regression", required_tags=["prediction", "target"],
          set_maturity="reviewed")
def explained_variance(cols, binding, convention=None):
    return _result(N.explained_variance(cols[binding["prediction"]], cols[binding["target"]]),
                   {"n": len(cols[binding["target"]])})


@register("wape", family="forecasting", required_tags=["prediction", "target"], set_maturity="reviewed")
def wape(cols, binding, convention=None):
    return _result(N.wape(cols[binding["prediction"]], cols[binding["target"]]),
                   {"n": len(cols[binding["target"]])})


@register("forecast_bias", family="forecasting", required_tags=["prediction", "target"],
          set_maturity="reviewed")
def forecast_bias(cols, binding, convention=None):
    return _result(N.forecast_bias(cols[binding["prediction"]], cols[binding["target"]]),
                   {"n": len(cols[binding["target"]]), "sign": "positive=over-forecast"})


@register("adjusted_r2", family="regression", required_tags=["prediction", "target"],
          set_maturity="reviewed", accepted_conventions=["p=<predictors> (required)"])
def adjusted_r2(cols, binding, convention=None):
    p = _conv_int(convention, "p", 0) or None
    return _result(N.adjusted_r2(cols[binding["prediction"]], cols[binding["target"]], p),
                   {"n": len(cols[binding["target"]]), "predictors": p})


@register("nrmse", family="regression", required_tags=["prediction", "target"],
          set_maturity="reviewed", accepted_conventions=["mean", "range"])
def nrmse(cols, binding, convention=None):
    mode = _conv_str(convention) or "mean"
    return _result(N.nrmse(cols[binding["prediction"]], cols[binding["target"]], mode),
                   {"n": len(cols[binding["target"]]), "mode": mode})


@register("durbin_watson", family="regression", required_tags=["prediction", "target"],
          set_maturity="reviewed")
def durbin_watson(cols, binding, convention=None):
    return _result(N.durbin_watson(cols[binding["prediction"]], cols[binding["target"]]),
                   {"n": len(cols[binding["target"]]), "residual": "target - prediction"})


# ======================================================================================
# Pack 9 - analytics & engineering depth II
# ======================================================================================

@register("column_min", family="analytics", required_tags=["value"], set_maturity="reviewed")
def column_min(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.col_min(xs), {"n": len(xs)})


@register("column_max", family="analytics", required_tags=["value"], set_maturity="reviewed")
def column_max(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.col_max(xs), {"n": len(xs)})


@register("column_std", family="analytics", required_tags=["value"], set_maturity="reviewed",
          accepted_conventions=["ddof=1", "ddof=0"])
def column_std(cols, binding, convention=None):
    xs = cols[binding["value"]]
    ddof = _conv_int(convention, "ddof", 1)
    return _result(N.col_std(xs, ddof), {"n": len(xs), "ddof": ddof})


@register("iqr", family="analytics", required_tags=["value"], set_maturity="reviewed")
def iqr(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.iqr(xs), {"n": len(xs), "method": "linear"})


@register("outlier_count", family="analytics", required_tags=["value"], set_maturity="reviewed",
          accepted_conventions=["k=<fence> (1.5)"])
def outlier_count(cols, binding, convention=None):
    xs = cols[binding["value"]]
    k = _conv_float(convention, "k", 1.5)
    return _result(N.outlier_count(xs, k), {"n": len(xs), "k": k, "rule": "tukey"})


@register("mode_share", family="analytics", required_tags=["value"], set_maturity="reviewed",
          string_tags=["value"])
def mode_share(cols, binding, convention=None):
    raw = cols[binding["value"]]
    return _result(N.mode_share(raw), {"n": len(raw)})


@register("gini_coefficient", family="analytics", required_tags=["value"], set_maturity="reviewed")
def gini_coefficient(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.gini_coefficient(xs), {"n": len(xs)})


@register("hhi", family="analytics", required_tags=["value"], set_maturity="reviewed")
def hhi(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.hhi(xs), {"n": len(xs), "scale": "0-1"})


@register("entropy", family="analytics", required_tags=["value"], set_maturity="reviewed",
          string_tags=["value"], accepted_conventions=["bits", "nats"])
def entropy(cols, binding, convention=None):
    raw = cols[binding["value"]]
    base = _conv_str(convention) or "bits"
    return _result(N.cat_entropy(raw, base), {"n": len(raw), "base": base})


@register("latency_p90", family="engineering", required_tags=["duration"], set_maturity="reviewed")
def latency_p90(cols, binding, convention=None):
    return _latency(cols, binding, 0.90)


@register("apdex", family="engineering", required_tags=["duration"], set_maturity="reviewed",
          accepted_conventions=["t=<seconds> (required)"])
def apdex(cols, binding, convention=None):
    durs = cols[binding["duration"]]
    t = _conv_float(convention, "t", None)
    val = N.apdex(durs, t) if t is not None else float("nan")
    return _result(val, {"n": len(durs), "t": t})


@register("uptime_pct", family="engineering", required_tags=["flag"], set_maturity="reviewed")
def uptime_pct(cols, binding, convention=None):
    flags = cols[binding["flag"]]
    return _result(N.ratio_share(flags), {"n": len(flags), "flag": "nonzero=up"})


@register("cache_hit_rate", family="engineering", required_tags=["flag"], set_maturity="reviewed")
def cache_hit_rate(cols, binding, convention=None):
    flags = cols[binding["flag"]]
    return _result(N.ratio_share(flags), {"n": len(flags), "flag": "nonzero=hit"})


# ======================================================================================
# Pack 10 - statistical tests II
# ======================================================================================

@register("mann_whitney", family="stats", required_tags=["sample_a", "sample_b"],
          set_maturity="reviewed")
def mann_whitney(cols, binding, convention=None):
    a, b = cols[binding["sample_a"]], cols[binding["sample_b"]]
    return _result(N.mann_whitney_p(a, b),
                   {"n_a": len(a), "n_b": len(b), "method": "asymptotic+ties+continuity"})


@register("ks_test", family="stats", required_tags=["sample_a", "sample_b"], set_maturity="reviewed")
def ks_test(cols, binding, convention=None):
    a, b = cols[binding["sample_a"]], cols[binding["sample_b"]]
    return _result(N.ks_p(a, b), {"n_a": len(a), "n_b": len(b), "method": "asymptotic"})


@register("anova", family="stats", required_tags=["group", "value"], set_maturity="reviewed",
          string_tags=["group"], accepted_conventions=["p", "statistic"])
def anova(cols, binding, convention=None):
    groups, values = cols[binding["group"]], cols[binding["value"]]
    output = "statistic" if _conv_str(convention) == "statistic" else "p"
    return _result(N.anova_p(groups, values, output), {"n": len(values), "output": output})


@register("proportion_z", family="stats", required_tags=["sample_a", "sample_b"],
          set_maturity="reviewed")
def proportion_z(cols, binding, convention=None):
    a, b = cols[binding["sample_a"]], cols[binding["sample_b"]]
    return _result(N.proportion_z_p(a, b), {"n_a": len(a), "n_b": len(b), "pooled": True})


@register("fisher_exact", family="stats", required_tags=["group", "outcome"], set_maturity="reviewed",
          string_tags=["group", "outcome"])
def fisher_exact(cols, binding, convention=None):
    g, o = cols[binding["group"]], cols[binding["outcome"]]
    return _result(N.fisher_exact_p(g, o), {"n": len(g), "method": "exact-two-sided"})


@register("odds_ratio", family="stats", required_tags=["group", "outcome"], set_maturity="reviewed",
          string_tags=["group", "outcome"], accepted_conventions=["sample", "haldane"])
def odds_ratio(cols, binding, convention=None):
    g, o = cols[binding["group"]], cols[binding["outcome"]]
    haldane = _conv_str(convention) == "haldane"
    return _result(N.odds_ratio_2x2(g, o, haldane), {"n": len(g), "haldane": haldane})


@register("relative_risk", family="stats", required_tags=["group", "outcome"], set_maturity="reviewed",
          string_tags=["group", "outcome"])
def relative_risk(cols, binding, convention=None):
    g, o = cols[binding["group"]], cols[binding["outcome"]]
    return _result(N.relative_risk_2x2(g, o), {"n": len(g), "rows": "sorted group keys"})


@register("cramers_v", family="stats", required_tags=["group", "outcome"], set_maturity="reviewed",
          string_tags=["group", "outcome"])
def cramers_v(cols, binding, convention=None):
    g, o = cols[binding["group"]], cols[binding["outcome"]]
    return _result(N.cramers_v(g, o), {"n": len(g), "correction": False})


@register("skewness", family="stats", required_tags=["value"], set_maturity="reviewed")
def skewness(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.skewness(xs), {"n": len(xs), "bias": "biased-g1"})


@register("kurtosis", family="stats", required_tags=["value"], set_maturity="reviewed")
def kurtosis(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.kurtosis_excess(xs), {"n": len(xs), "definition": "excess (Fisher)"})


@register("jarque_bera", family="stats", required_tags=["value"], set_maturity="reviewed",
          accepted_conventions=["p", "statistic"])
def jarque_bera(cols, binding, convention=None):
    xs = cols[binding["value"]]
    output = "statistic" if _conv_str(convention) == "statistic" else "p"
    return _result(N.jarque_bera_p(xs, output), {"n": len(xs), "output": output})


@register("autocorrelation", family="stats", required_tags=["value"], set_maturity="reviewed",
          accepted_conventions=["lag=<k> (1)"])
def autocorrelation(cols, binding, convention=None):
    xs = cols[binding["value"]]
    lag = _conv_int(convention, "lag", 1)
    return _result(N.autocorrelation(xs, lag), {"n": len(xs), "lag": lag})


# ======================================================================================
# Pack 11 - retrieval / LLM evals II
# ======================================================================================

@register("precision_at_k", family="retrieval", required_tags=["query", "rank", "relevance"],
          set_maturity="reviewed", string_tags=["query"], accepted_conventions=["k=<int>"])
def precision_at_k(cols, binding, convention=None):
    k = _conv_int(convention, "k", 10)
    val = N.precision_at_k(cols[binding["query"]], cols[binding["rank"]], cols[binding["relevance"]], k)
    return _result(val, {"k": k, "n_rows": len(cols[binding["rank"]])})


@register("map_at_k", family="retrieval", required_tags=["query", "rank", "relevance"],
          set_maturity="reviewed", string_tags=["query"], accepted_conventions=["k=<int>"])
def map_at_k(cols, binding, convention=None):
    k = _conv_int(convention, "k", 10)
    val = N.map_at_k(cols[binding["query"]], cols[binding["rank"]], cols[binding["relevance"]], k)
    return _result(val, {"k": k, "denominator": "min(R,k)", "n_rows": len(cols[binding["rank"]])})


@register("perplexity", family="llm-eval", required_tags=["value"], set_maturity="reviewed")
def perplexity(cols, binding, convention=None):
    lps = cols[binding["value"]]
    return _result(N.perplexity(lps), {"n_tokens": len(lps), "log_base": "natural"})


@register("wer", family="llm-eval", required_tags=["prediction", "reference"],
          set_maturity="reviewed", string_tags=["prediction", "reference"],
          accepted_conventions=["wer", "cer"])
def wer(cols, binding, convention=None):
    char_level = _conv_str(convention) == "cer"
    preds, refs = cols[binding["prediction"]], cols[binding["reference"]]
    return _result(N.wer(preds, refs, char_level),
                   {"n": len(preds), "level": "char" if char_level else "word"})


# ---------------------------------------------------------------------------
# Compiled recipes (the recipe compiler's output) - loaded from
# assets/compiled_recipes.json. Each entry was admitted by the deterministic
# gate in compiler.py (differential vs a named oracle + metamorphic suite +
# degeneracy + bit-stability) and frozen under a content hash. The hash is
# RE-VALIDATED here, so a tampered asset entry fails closed (skipped, with a
# stderr warning) instead of executing a program nobody admitted.
# Execution is the dsl.py interpreter - deterministic kernels only, no model.
# ---------------------------------------------------------------------------

def _load_compiled():
    import json as _json
    import os as _os
    import sys as _sys
    path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                         "..", "assets", "compiled_recipes.json")
    if not _os.path.exists(path):
        return
    import dsl as _dsl
    try:
        book = _json.load(open(path))
    except (OSError, ValueError) as e:
        print("calma: compiled_recipes.json unreadable, skipping: %s" % e, file=_sys.stderr)
        return
    for entry in book.get("recipes", []):
        mid = entry.get("metric_id")
        prog = entry.get("program")
        if not mid or mid in _REGISTRY:
            print("calma: compiled recipe %r skipped (missing/duplicate id)" % mid,
                  file=_sys.stderr)
            continue
        if _dsl.program_hash(prog) != entry.get("program_sha256") or _dsl.validate(prog):
            print("calma: compiled recipe %r skipped (program hash/validation mismatch - "
                  "the asset was modified after admission)" % mid, file=_sys.stderr)
            continue

        def _make(p, m):
            def _fn(cols, binding, convention=None):
                tag_values = {t: cols[binding[t]] for t in p["inputs"] if t in binding}
                if set(tag_values) != set(p["inputs"]):
                    return _result(float("nan"))
                return _result(_dsl.execute(p, tag_values))
            return _fn

        fn = _make(prog, mid)
        fn.metric_id = mid
        fn.manifest = {
            "family": entry.get("family", "compiled"),
            "required_tags": entry.get("required_tags", []),
            "string_tags": entry.get("string_tags", []),
            "set_maturity": entry.get("set_maturity", "compiled-validated"),
            "program_sha256": entry.get("program_sha256"),
        }
        _REGISTRY[mid] = fn


_load_compiled()


# ======================================================================================
# Pack QR - quant-risk depth (25 recipes). Return series via tag `return`; relative-
# performance metrics also bind `benchmark`. Annualized metrics take periods 252/365/52.
# ======================================================================================

@register("ulcer_index", family="quant", required_tags=["return"], set_maturity="reviewed")
def ulcer_index(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.ulcer_index(rets), {"n": len(rets)}, path_dependent=True)


@register("pain_index", family="quant", required_tags=["return"], set_maturity="reviewed")
def pain_index(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.pain_index(rets), {"n": len(rets)}, path_dependent=True)


@register("martin_ratio", family="quant", required_tags=["return"], periodicity_param="periods",
          set_maturity="reviewed", accepted_conventions=["252", "365", "52"])
def martin_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    p = _periods(convention, binding)
    return _result(N.martin_ratio(rets, p), {"n": len(rets), "periods": p}, path_dependent=True)


@register("recovery_factor", family="quant", required_tags=["return"], set_maturity="reviewed")
def recovery_factor(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.recovery_factor(rets), {"n": len(rets)}, path_dependent=True)


@register("gain_to_pain_ratio", family="quant", required_tags=["return"], set_maturity="reviewed")
def gain_to_pain_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.gain_to_pain_ratio(rets), {"n": len(rets)})


@register("tail_ratio", family="quant", required_tags=["return"], set_maturity="reviewed")
def tail_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.tail_ratio(rets), {"n": len(rets)})


@register("gain_loss_ratio", family="quant", required_tags=["return"], set_maturity="reviewed")
def gain_loss_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.gain_loss_ratio(rets), {"n": len(rets)})


@register("win_loss_ratio", family="quant", required_tags=["return"], set_maturity="reviewed")
def win_loss_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.win_loss_ratio(rets), {"n": len(rets)})


@register("kelly_criterion", family="quant", required_tags=["return"], set_maturity="reviewed")
def kelly_criterion(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.kelly_criterion(rets), {"n": len(rets)})


@register("upside_deviation", family="quant", required_tags=["return"], periodicity_param="periods",
          set_maturity="reviewed", accepted_conventions=["252", "365", "52"])
def upside_deviation(cols, binding, convention=None):
    rets = cols[binding["return"]]
    p = _periods(convention, binding)
    return _result(N.upside_deviation(rets, p), {"n": len(rets), "periods": p, "target": 0.0})


@register("upside_potential_ratio", family="quant", required_tags=["return"], set_maturity="reviewed")
def upside_potential_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.upside_potential_ratio(rets), {"n": len(rets), "target": 0.0})


@register("kappa_three", family="quant", required_tags=["return"], set_maturity="reviewed")
def kappa_three(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.kappa_three(rets), {"n": len(rets), "target": 0.0, "order": 3})


@register("cdar", family="quant", required_tags=["return"], set_maturity="reviewed",
          accepted_conventions=["p95", "p99"])
def cdar(cols, binding, convention=None):
    rets = cols[binding["return"]]
    level = _conv_q(convention) if convention else 0.95
    return _result(N.cdar(rets, level), {"n": len(rets), "level": level, "sign": "loss-positive"},
                   path_dependent=True)


@register("max_drawdown_duration", family="quant", required_tags=["return"], set_maturity="reviewed")
def max_drawdown_duration(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.max_drawdown_duration(rets), {"n": len(rets), "unit": "periods"},
                   path_dependent=True)


@register("parametric_var", family="quant", required_tags=["return"], set_maturity="reviewed",
          accepted_conventions=["p95", "p99"])
def parametric_var(cols, binding, convention=None):
    rets = cols[binding["return"]]
    level = _conv_q(convention) if convention else 0.95
    return _result(N.parametric_var(rets, level), {"n": len(rets), "level": level, "sign": "loss-positive"})


@register("parametric_es", family="quant", required_tags=["return"], set_maturity="reviewed",
          accepted_conventions=["p95", "p99"])
def parametric_es(cols, binding, convention=None):
    rets = cols[binding["return"]]
    level = _conv_q(convention) if convention else 0.95
    return _result(N.parametric_es(rets, level), {"n": len(rets), "level": level, "sign": "loss-positive"})


@register("cornish_fisher_var", family="quant", required_tags=["return"], set_maturity="reviewed",
          accepted_conventions=["p95", "p99"])
def cornish_fisher_var(cols, binding, convention=None):
    rets = cols[binding["return"]]
    level = _conv_q(convention) if convention else 0.95
    return _result(N.cornish_fisher_var(rets, level), {"n": len(rets), "level": level, "sign": "loss-positive"})


@register("adjusted_sharpe_ratio", family="quant", required_tags=["return"], set_maturity="reviewed")
def adjusted_sharpe_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    return _result(N.adjusted_sharpe_ratio(rets), {"n": len(rets), "basis": "per-period"})


@register("probabilistic_sharpe_ratio", family="quant", required_tags=["return"], set_maturity="reviewed")
def probabilistic_sharpe_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    bsr = float(convention or binding.get("benchmark_sr") or 0.0)
    return _result(N.probabilistic_sharpe_ratio(rets, bsr), {"n": len(rets), "benchmark_sr": bsr})


@register("up_capture_ratio", family="quant", required_tags=["return", "benchmark"], set_maturity="reviewed")
def up_capture_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    bench = cols[binding["benchmark"]]
    return _result(N.up_capture_ratio(rets, bench), {"n": len(rets)})


@register("down_capture_ratio", family="quant", required_tags=["return", "benchmark"], set_maturity="reviewed")
def down_capture_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    bench = cols[binding["benchmark"]]
    return _result(N.down_capture_ratio(rets, bench), {"n": len(rets)})


@register("capture_ratio", family="quant", required_tags=["return", "benchmark"], set_maturity="reviewed")
def capture_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    bench = cols[binding["benchmark"]]
    return _result(N.capture_ratio(rets, bench), {"n": len(rets)})


@register("treynor_ratio", family="quant", required_tags=["return", "benchmark"], periodicity_param="periods",
          set_maturity="reviewed", accepted_conventions=["252", "365", "52"])
def treynor_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    bench = cols[binding["benchmark"]]
    p = _periods(convention, binding)
    return _result(N.treynor_ratio(rets, bench, p), {"n": len(rets), "periods": p})


@register("r_squared", family="quant", required_tags=["return", "benchmark"], set_maturity="reviewed")
def r_squared(cols, binding, convention=None):
    rets = cols[binding["return"]]
    bench = cols[binding["benchmark"]]
    return _result(N.r_squared(rets, bench), {"n": len(rets)})


@register("active_return", family="quant", required_tags=["return", "benchmark"], periodicity_param="periods",
          set_maturity="reviewed", accepted_conventions=["252", "365", "52"])
def active_return(cols, binding, convention=None):
    rets = cols[binding["return"]]
    bench = cols[binding["benchmark"]]
    p = _periods(convention, binding)
    return _result(N.active_return(rets, bench, p), {"n": len(rets), "periods": p})
