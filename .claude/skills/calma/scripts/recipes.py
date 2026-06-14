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


# ======================================================================================
# Pack ST - statistics & hypothesis tests (8 recipes).
# ======================================================================================

@register("point_biserial", family="stats", required_tags=["binary", "value"], set_maturity="reviewed")
def point_biserial(cols, binding, convention=None):
    return _result(N.point_biserial(cols[binding["binary"]], cols[binding["value"]]),
                   {"n": len(cols[binding["value"]])})


@register("kendall_tau", family="stats", required_tags=["x", "y"], set_maturity="reviewed")
def kendall_tau(cols, binding, convention=None):
    xs, ys = cols[binding["x"]], cols[binding["y"]]
    return _result(N.kendall_tau(xs, ys), {"n": len(xs), "variant": "tau-b"})


@register("theil_sen_slope", family="stats", required_tags=["x", "y"], set_maturity="reviewed")
def theil_sen_slope(cols, binding, convention=None):
    xs, ys = cols[binding["x"]], cols[binding["y"]]
    return _result(N.theil_sen_slope(xs, ys), {"n": len(xs)})


@register("cliffs_delta", family="stats", required_tags=["sample_a", "sample_b"], set_maturity="reviewed")
def cliffs_delta(cols, binding, convention=None):
    a, b = cols[binding["sample_a"]], cols[binding["sample_b"]]
    return _result(N.cliffs_delta(a, b), {"n_a": len(a), "n_b": len(b)})


@register("rank_biserial", family="stats", required_tags=["sample_a", "sample_b"], set_maturity="reviewed")
def rank_biserial(cols, binding, convention=None):
    a, b = cols[binding["sample_a"]], cols[binding["sample_b"]]
    return _result(N.rank_biserial(a, b), {"n_a": len(a), "n_b": len(b)})


@register("eta_squared", family="stats", required_tags=["group", "value"], string_tags=["group"],
          set_maturity="reviewed")
def eta_squared(cols, binding, convention=None):
    groups, values = cols[binding["group"]], cols[binding["value"]]
    return _result(N.eta_squared(groups, values), {"n": len(values)})


@register("g_test", family="stats", required_tags=["group", "outcome"], string_tags=["group", "outcome"],
          set_maturity="reviewed", accepted_conventions=["p", "statistic"])
def g_test(cols, binding, convention=None):
    groups, outcomes = cols[binding["group"]], cols[binding["outcome"]]
    output = "statistic" if _conv_str(convention) == "statistic" else "p"
    return _result(N.g_test(groups, outcomes, output), {"n": len(groups), "output": output})


@register("mcnemar", family="stats", required_tags=["sample_a", "sample_b"], set_maturity="reviewed")
def mcnemar(cols, binding, convention=None):
    a, b = cols[binding["sample_a"]], cols[binding["sample_b"]]
    return _result(N.mcnemar_p(a, b), {"n": len(a)})


# ======================================================================================
# Pack ST2 - variance / distribution / nonparametric k-sample tests + CIs + multiplicity.
# ======================================================================================

@register("levene", family="stats", required_tags=["group", "value"], string_tags=["group"],
          set_maturity="reviewed")
def levene(cols, binding, convention=None):
    g, v = cols[binding["group"]], cols[binding["value"]]
    return _result(N.levene(g, v), {"n": len(v), "center": "median"})


@register("bartlett", family="stats", required_tags=["group", "value"], string_tags=["group"],
          set_maturity="reviewed")
def bartlett(cols, binding, convention=None):
    g, v = cols[binding["group"]], cols[binding["value"]]
    return _result(N.bartlett(g, v), {"n": len(v)})


@register("fligner", family="stats", required_tags=["group", "value"], string_tags=["group"],
          set_maturity="reviewed")
def fligner(cols, binding, convention=None):
    g, v = cols[binding["group"]], cols[binding["value"]]
    return _result(N.fligner(g, v), {"n": len(v), "center": "median"})


@register("kruskal_wallis", family="stats", required_tags=["group", "value"], string_tags=["group"],
          set_maturity="reviewed")
def kruskal_wallis(cols, binding, convention=None):
    g, v = cols[binding["group"]], cols[binding["value"]]
    return _result(N.kruskal_wallis(g, v), {"n": len(v)})


@register("wilcoxon_signed_rank", family="stats", required_tags=["sample_a", "sample_b"],
          set_maturity="reviewed")
def wilcoxon_signed_rank(cols, binding, convention=None):
    a, b = cols[binding["sample_a"]], cols[binding["sample_b"]]
    return _result(N.wilcoxon_signed_rank(a, b), {"n": len(a), "method": "approx"})


@register("anderson_darling", family="stats", required_tags=["value"], set_maturity="reviewed")
def anderson_darling(cols, binding, convention=None):
    v = cols[binding["value"]]
    return _result(N.anderson_darling(v), {"n": len(v), "dist": "norm"})


@register("wilson_lower", family="stats", required_tags=["flag"], set_maturity="reviewed",
          accepted_conventions=["90", "95", "99"])
def wilson_lower(cols, binding, convention=None):
    flags = cols[binding["flag"]]
    lvl = {"90": 0.9, "95": 0.95, "99": 0.99}.get(str(convention).strip(), 0.95) if convention else 0.95
    return _result(N.wilson_lower(flags, lvl), {"n": len(flags), "level": lvl, "bound": "lower"})


@register("wilson_upper", family="stats", required_tags=["flag"], set_maturity="reviewed",
          accepted_conventions=["90", "95", "99"])
def wilson_upper(cols, binding, convention=None):
    flags = cols[binding["flag"]]
    lvl = {"90": 0.9, "95": 0.95, "99": 0.99}.get(str(convention).strip(), 0.95) if convention else 0.95
    return _result(N.wilson_upper(flags, lvl), {"n": len(flags), "level": lvl, "bound": "upper"})


@register("bh_rejections", family="stats", required_tags=["value"], set_maturity="reviewed")
def bh_rejections(cols, binding, convention=None):
    pvals = cols[binding["value"]]
    alpha = float(convention) if convention else 0.05
    return _result(N.bh_rejections(pvals, alpha), {"m": len(pvals), "alpha": alpha, "method": "fdr_bh"})


@register("holm_rejections", family="stats", required_tags=["value"], set_maturity="reviewed")
def holm_rejections(cols, binding, convention=None):
    pvals = cols[binding["value"]]
    alpha = float(convention) if convention else 0.05
    return _result(N.holm_rejections(pvals, alpha), {"m": len(pvals), "alpha": alpha, "method": "holm"})


# ======================================================================================
# Pack RM - risk-model validation: VaR backtesting + distribution shift / discrimination.
# ======================================================================================

@register("kupiec_pof", family="quant", required_tags=["flag"], set_maturity="reviewed",
          accepted_conventions=["0.01", "0.025", "0.05"])
def kupiec_pof(cols, binding, convention=None):
    flags = cols[binding["flag"]]
    rate = float(convention) if convention else 0.01
    return _result(N.kupiec_pof(flags, rate, "p"), {"n": len(flags), "expected_rate": rate})


@register("christoffersen_independence", family="quant", required_tags=["flag"], set_maturity="reviewed")
def christoffersen_independence(cols, binding, convention=None):
    flags = cols[binding["flag"]]
    return _result(N.christoffersen_independence(flags, "p"), {"n": len(flags)})


@register("christoffersen_cc", family="quant", required_tags=["flag"], set_maturity="reviewed",
          accepted_conventions=["0.01", "0.025", "0.05"])
def christoffersen_cc(cols, binding, convention=None):
    flags = cols[binding["flag"]]
    rate = float(convention) if convention else 0.01
    return _result(N.christoffersen_cc(flags, rate, "p"), {"n": len(flags), "expected_rate": rate})


@register("psi", family="analytics", required_tags=["expected", "actual"], set_maturity="reviewed")
def psi(cols, binding, convention=None):
    e, a = cols[binding["expected"]], cols[binding["actual"]]
    return _result(N.psi(e, a), {"bins": len(e)})


@register("information_value", family="stats", required_tags=["group", "label"], string_tags=["group"],
          set_maturity="reviewed")
def information_value(cols, binding, convention=None):
    g, y = cols[binding["group"]], cols[binding["label"]]
    return _result(N.information_value(g, y), {"n": len(y), "bad_label": 1})


@register("kl_divergence", family="stats", required_tags=["p", "q"], set_maturity="reviewed")
def kl_divergence(cols, binding, convention=None):
    return _result(N.kl_divergence(cols[binding["p"]], cols[binding["q"]]), {"bins": len(cols[binding["p"]])})


@register("js_divergence", family="stats", required_tags=["p", "q"], set_maturity="reviewed")
def js_divergence(cols, binding, convention=None):
    return _result(N.js_divergence(cols[binding["p"]], cols[binding["q"]]), {"bins": len(cols[binding["p"]])})


@register("wasserstein_1d", family="stats", required_tags=["sample_a", "sample_b"], set_maturity="reviewed")
def wasserstein_1d(cols, binding, convention=None):
    a, b = cols[binding["sample_a"]], cols[binding["sample_b"]]
    return _result(N.wasserstein_1d(a, b), {"n_a": len(a), "n_b": len(b)})


@register("energy_distance", family="stats", required_tags=["sample_a", "sample_b"], set_maturity="reviewed")
def energy_distance(cols, binding, convention=None):
    a, b = cols[binding["sample_a"]], cols[binding["sample_b"]]
    return _result(N.energy_distance(a, b), {"n_a": len(a), "n_b": len(b)})


@register("ks_2samp", family="stats", required_tags=["sample_a", "sample_b"], set_maturity="reviewed")
def ks_2samp(cols, binding, convention=None):
    a, b = cols[binding["sample_a"]], cols[binding["sample_b"]]
    return _result(N.ks_2samp(a, b), {"n_a": len(a), "n_b": len(b)})


# ======================================================================================
# Pack CR - classification & regression depth (validated vs scikit-learn).
# ======================================================================================

def _cls(fn):
    def recipe(cols, binding, convention=None):
        pred, label = cols[binding["prediction"]], cols[binding["label"]]
        return _result(fn(pred, label), {"n": len(label)})
    return recipe


for _mid, _fn in (
    ("g_mean", "g_mean"), ("youden_j", "youden_j"), ("markedness", "markedness"),
    ("negative_predictive_value", "negative_predictive_value"),
    ("false_positive_rate", "false_positive_rate"), ("false_negative_rate", "false_negative_rate"),
    ("false_discovery_rate", "false_discovery_rate"),
    ("positive_likelihood_ratio", "positive_likelihood_ratio"),
    ("negative_likelihood_ratio", "negative_likelihood_ratio"),
    ("diagnostic_odds_ratio", "diagnostic_odds_ratio"), ("threat_score", "threat_score"),
    ("fowlkes_mallows", "fowlkes_mallows"),
):
    register(_mid, family="classification", required_tags=["prediction", "label"],
             set_maturity="reviewed")(_cls(getattr(N, _fn)))


@register("concordance_correlation", family="regression", required_tags=["prediction", "target"],
          set_maturity="reviewed")
def concordance_correlation(cols, binding, convention=None):
    p, t = cols[binding["prediction"]], cols[binding["target"]]
    return _result(N.concordance_correlation(p, t), {"n": len(t)})


@register("huber_loss", family="regression", required_tags=["prediction", "target"], set_maturity="reviewed",
          accepted_conventions=["delta=<v>"])
def huber_loss(cols, binding, convention=None):
    p, t = cols[binding["prediction"]], cols[binding["target"]]
    delta = _conv_float(convention, "delta", 1.0)
    return _result(N.huber_loss(p, t, delta), {"n": len(t), "delta": delta})


@register("poisson_deviance", family="regression", required_tags=["prediction", "target"], set_maturity="reviewed")
def poisson_deviance(cols, binding, convention=None):
    p, t = cols[binding["prediction"]], cols[binding["target"]]
    return _result(N.poisson_deviance(p, t), {"n": len(t)})


@register("gamma_deviance", family="regression", required_tags=["prediction", "target"], set_maturity="reviewed")
def gamma_deviance(cols, binding, convention=None):
    p, t = cols[binding["prediction"]], cols[binding["target"]]
    return _result(N.gamma_deviance(p, t), {"n": len(t)})


@register("d2_absolute_error", family="regression", required_tags=["prediction", "target"], set_maturity="reviewed")
def d2_absolute_error(cols, binding, convention=None):
    p, t = cols[binding["prediction"]], cols[binding["target"]]
    return _result(N.d2_absolute_error(p, t), {"n": len(t)})


# ======================================================================================
# Pack AN - analytics / data-quality / robust-stats depth (validated vs scipy/statsmodels).
# ======================================================================================

def _val(fn):
    def recipe(cols, binding, convention=None):
        v = cols[binding["value"]]
        return _result(fn(v), {"n": len(v)})
    return recipe


for _mid, _fn in (
    ("variance", "variance"), ("range_value", "range_value"), ("mean_abs_deviation", "mean_abs_deviation"),
    ("median_abs_deviation", "median_abs_deviation"), ("geometric_mean", "geometric_mean"),
    ("harmonic_mean", "harmonic_mean"), ("theil_index", "theil_index"), ("atkinson_index", "atkinson_index"),
    ("quartile_coefficient_dispersion", "quartile_coefficient_dispersion"),
    ("index_of_dispersion", "index_of_dispersion"),
):
    register(_mid, family="analytics", required_tags=["value"], set_maturity="reviewed")(_val(getattr(N, _fn)))


@register("trimmed_mean", family="analytics", required_tags=["value"], set_maturity="reviewed",
          accepted_conventions=["proportion=<v>"])
def trimmed_mean(cols, binding, convention=None):
    v = cols[binding["value"]]
    prop = _conv_float(convention, "proportion", 0.1)
    return _result(N.trimmed_mean(v, prop), {"n": len(v), "proportion": prop})


@register("weighted_mean", family="analytics", required_tags=["value", "weight"], set_maturity="reviewed")
def weighted_mean(cols, binding, convention=None):
    v, w = cols[binding["value"]], cols[binding["weight"]]
    return _result(N.weighted_mean(v, w), {"n": len(v)})


@register("covariance", family="analytics", required_tags=["x", "y"], set_maturity="reviewed")
def covariance(cols, binding, convention=None):
    x, y = cols[binding["x"]], cols[binding["y"]]
    return _result(N.covariance(x, y), {"n": len(x)})


@register("uniqueness_ratio", family="analytics", required_tags=["value"], string_tags=["value"],
          set_maturity="reviewed")
def uniqueness_ratio(cols, binding, convention=None):
    v = cols[binding["value"]]
    return _result(N.uniqueness_ratio(v), {"n": len(v)})


@register("ljung_box", family="stats", required_tags=["value"], set_maturity="reviewed",
          accepted_conventions=["lags=<int>"])
def ljung_box(cols, binding, convention=None):
    v = cols[binding["value"]]
    lags = _conv_int(convention, "lags", 10)
    return _result(N.ljung_box(v, lags), {"n": len(v), "lags": lags})


# ======================================================================================
# Pack TS - forecasting / time-series accuracy (documented forecasting definitions).
# ======================================================================================

def _pt(fn):
    def recipe(cols, binding, convention=None):
        p, t = cols[binding["prediction"]], cols[binding["target"]]
        return _result(fn(p, t), {"n": len(t)})
    return recipe


for _mid in ("theil_u1", "theil_u2", "rmsse", "tracking_signal", "mean_directional_accuracy",
             "relative_absolute_error", "relative_squared_error", "mean_percentage_error",
             "median_absolute_percentage_error"):
    register(_mid, family="forecasting", required_tags=["prediction", "target"],
             set_maturity="reviewed")(_pt(getattr(N, _mid)))


# ======================================================================================
# Pack FAIR - fairness / bias across a sensitive group (validated vs fairlearn).
# ======================================================================================

def _plg(fn):
    def recipe(cols, binding, convention=None):
        p, lab, g = cols[binding["prediction"]], cols[binding["label"]], cols[binding["group"]]
        return _result(fn(p, lab, g), {"n": len(lab)})
    return recipe


for _mid in ("demographic_parity_difference", "demographic_parity_ratio", "equalized_odds_difference",
             "equalized_odds_ratio", "equal_opportunity_difference", "predictive_parity_difference",
             "fpr_parity_difference", "accuracy_parity_difference"):
    register(_mid, family="classification", required_tags=["prediction", "label", "group"],
             string_tags=["group"], set_maturity="reviewed")(_plg(getattr(N, _mid)))


# ======================================================================================
# Pack BC - survival concordance + clustering-agreement (validated vs lifelines / sklearn).
# ======================================================================================

@register("concordance_index", family="stats", required_tags=["time", "score", "event"],
          set_maturity="reviewed")
def concordance_index(cols, binding, convention=None):
    t, s, e = cols[binding["time"]], cols[binding["score"]], cols[binding["event"]]
    return _result(N.concordance_index(t, s, e), {"n": len(t)})


def _ll(fn):
    def recipe(cols, binding, convention=None):
        a, b = cols[binding["labels_true"]], cols[binding["labels_pred"]]
        return _result(fn(a, b), {"n": len(a)})
    return recipe


for _mid in ("mutual_info_score", "normalized_mutual_info", "homogeneity_score", "completeness_score",
             "v_measure_score", "rand_index", "adjusted_rand_index", "fowlkes_mallows_clustering"):
    register(_mid, family="classification", required_tags=["labels_true", "labels_pred"],
             set_maturity="reviewed")(_ll(getattr(N, _mid)))


# ======================================================================================
# Pack ENG - performance / SRE depth (validated vs numpy / definitions).
# ======================================================================================

def _dur(fn):
    def recipe(cols, binding, convention=None):
        d = cols[binding["duration"]]
        return _result(fn(d), {"n": len(d)})
    return recipe


for _mid in ("latency_p75", "latency_p999", "tail_latency_ratio", "latency_stddev", "jitter"):
    register(_mid, family="engineering", required_tags=["duration"],
             set_maturity="reviewed")(_dur(getattr(N, _mid)))


@register("slo_attainment", family="engineering", required_tags=["duration"], set_maturity="reviewed",
          accepted_conventions=["threshold=<v>"])
def slo_attainment(cols, binding, convention=None):
    d = cols[binding["duration"]]
    thr = _conv_float(convention, "threshold", 0.0)
    return _result(N.slo_attainment(d, thr), {"n": len(d), "threshold": thr})


@register("error_budget_burn", family="engineering", required_tags=["flag"], set_maturity="reviewed",
          accepted_conventions=["target=<frac>"])
def error_budget_burn(cols, binding, convention=None):
    flags = cols[binding["flag"]]
    target = _conv_float(convention, "target", 0.01)
    return _result(N.error_budget_burn(flags, target), {"n": len(flags), "target": target})


@register("compression_ratio", family="engineering", required_tags=["original", "compressed"],
          set_maturity="reviewed")
def compression_ratio(cols, binding, convention=None):
    o, c = cols[binding["original"]], cols[binding["compressed"]]
    return _result(N.compression_ratio(o, c), {"n": len(o)})


@register("availability", family="engineering", required_tags=["uptime", "downtime"], set_maturity="reviewed")
def availability(cols, binding, convention=None):
    u, d = cols[binding["uptime"]], cols[binding["downtime"]]
    return _result(N.availability(u, d), {"n": len(u)})


@register("mtbf", family="engineering", required_tags=["flag"], set_maturity="reviewed")
def mtbf(cols, binding, convention=None):
    flags = cols[binding["flag"]]
    return _result(N.mtbf(flags), {"n": len(flags)})


# ======================================================================================
# Pack QR2 - quant performance depth (documented conventions).
# ======================================================================================

def _ret_p(fn, path):
    def recipe(cols, binding, convention=None):
        rets = cols[binding["return"]]
        p = _periods(convention, binding)
        return _result(fn(rets, p), {"n": len(rets), "periods": p}, path_dependent=path)
    return recipe


for _mid, _path in (("pain_ratio", True), ("sterling_ratio", True), ("burke_ratio", True)):
    register(_mid, family="quant", required_tags=["return"], periodicity_param="periods",
             set_maturity="reviewed", accepted_conventions=["252", "365", "52"])(_ret_p(getattr(N, _mid), _path))


def _ret_only(fn):
    def recipe(cols, binding, convention=None):
        rets = cols[binding["return"]]
        return _result(fn(rets), {"n": len(rets)})
    return recipe


for _mid in ("common_sense_ratio", "downside_potential", "upside_potential"):
    register(_mid, family="quant", required_tags=["return"], set_maturity="reviewed")(_ret_only(getattr(N, _mid)))


@register("m2_measure", family="quant", required_tags=["return", "benchmark"], set_maturity="reviewed")
def m2_measure(cols, binding, convention=None):
    return _result(N.m2_measure(cols[binding["return"]], cols[binding["benchmark"]]),
                   {"n": len(cols[binding["return"]])})


@register("appraisal_ratio", family="quant", required_tags=["return", "benchmark"], set_maturity="reviewed")
def appraisal_ratio(cols, binding, convention=None):
    return _result(N.appraisal_ratio(cols[binding["return"]], cols[binding["benchmark"]]),
                   {"n": len(cols[binding["return"]])})


@register("rachev_ratio", family="quant", required_tags=["return"], set_maturity="reviewed",
          accepted_conventions=["p95", "p99"])
def rachev_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    level = _conv_q(convention) if convention else 0.95
    return _result(N.rachev_ratio(rets, level), {"n": len(rets), "level": level})


@register("omega_sharpe_ratio", family="quant", required_tags=["return"], set_maturity="reviewed",
          accepted_conventions=["threshold=<frac>"])
def omega_sharpe_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    thr = _conv_float(convention, "threshold", 0.0)
    return _result(N.omega_sharpe_ratio(rets, thr), {"n": len(rets), "threshold": thr})


# ======================================================================================
# Pack EXP - causal / experimentation (A/B testing).
# ======================================================================================

def _tc(fn):
    def recipe(cols, binding, convention=None):
        t, c = cols[binding["treatment"]], cols[binding["control"]]
        return _result(fn(t, c), {"n_t": len(t), "n_c": len(c)})
    return recipe


for _mid in ("average_treatment_effect", "risk_difference", "relative_risk_reduction",
             "number_needed_to_treat", "standardized_mean_difference"):
    register(_mid, family="stats", required_tags=["treatment", "control"],
             set_maturity="reviewed")(_tc(getattr(N, _mid)))


@register("cuped_ate", family="stats", required_tags=["value", "covariate", "group"], set_maturity="reviewed")
def cuped_ate(cols, binding, convention=None):
    return _result(N.cuped_ate(cols[binding["value"]], cols[binding["covariate"]], cols[binding["group"]]),
                   {"n": len(cols[binding["value"]])})


@register("variance_reduction_cuped", family="stats", required_tags=["value", "covariate"],
          set_maturity="reviewed")
def variance_reduction_cuped(cols, binding, convention=None):
    return _result(N.variance_reduction_cuped(cols[binding["value"]], cols[binding["covariate"]]),
                   {"n": len(cols[binding["value"]])})


@register("srm_pvalue", family="stats", required_tags=["group"], string_tags=["group"],
          set_maturity="reviewed")
def srm_pvalue(cols, binding, convention=None):
    g = cols[binding["group"]]
    return _result(N.srm_pvalue(g), {"n": len(g)})


# ======================================================================================
# Pack IR - retrieval / ranking depth + token-overlap text metrics.
# ======================================================================================

def _qrr(fn, kconv):
    def recipe(cols, binding, convention=None):
        q, rk, rel = cols[binding["query"]], cols[binding["rank"]], cols[binding["relevance"]]
        if kconv == "k":
            k = _conv_int(convention, "k", 10)
            return _result(fn(q, rk, rel, k), {"k": k, "n_rows": len(rk)})
        if kconv == "p":
            p = _conv_float(convention, "p", 0.8)
            return _result(fn(q, rk, rel, p), {"p": p, "n_rows": len(rk)})
        return _result(fn(q, rk, rel), {"n_rows": len(rk)})
    return recipe


register("r_precision", family="retrieval", required_tags=["query", "rank", "relevance"],
         string_tags=["query"], set_maturity="reviewed")(_qrr(N.r_precision, None))
register("mean_average_precision", family="retrieval", required_tags=["query", "rank", "relevance"],
         string_tags=["query"], set_maturity="reviewed")(_qrr(N.mean_average_precision, None))
register("f1_at_k", family="retrieval", required_tags=["query", "rank", "relevance"], string_tags=["query"],
         set_maturity="reviewed", accepted_conventions=["k=<int>"])(_qrr(N.f1_at_k, "k"))
register("fallout_at_k", family="retrieval", required_tags=["query", "rank", "relevance"], string_tags=["query"],
         set_maturity="reviewed", accepted_conventions=["k=<int>"])(_qrr(N.fallout_at_k, "k"))
register("rbp", family="retrieval", required_tags=["query", "rank", "relevance"], string_tags=["query"],
         set_maturity="reviewed", accepted_conventions=["p=<frac>"])(_qrr(N.rbp, "p"))


def _pr(fn):
    def recipe(cols, binding, convention=None):
        p, r = cols[binding["prediction"]], cols[binding["reference"]]
        return _result(fn(p, r), {"n": len(p)})
    return recipe


for _mid in ("token_f1", "token_jaccard", "token_dice"):
    register(_mid, family="llm-eval", required_tags=["prediction", "reference"],
             string_tags=["prediction", "reference"], set_maturity="reviewed")(_pr(getattr(N, _mid)))


# ======================================================================================
# Pack FI - fixed-income analytics (cashflow + time columns, yield convention).
# ======================================================================================

def _fi_y(fn):
    def recipe(cols, binding, convention=None):
        cf, t = cols[binding["cashflow"]], cols[binding["time"]]
        y = _conv_float(convention, "ytm", 0.05)
        return _result(fn(cf, t, y), {"n": len(cf), "ytm": y})
    return recipe


for _mid in ("bond_price", "macaulay_duration", "modified_duration", "convexity", "dv01"):
    register(_mid, family="finance", required_tags=["cashflow", "time"],
             set_maturity="reviewed", accepted_conventions=["ytm=<frac>"])(_fi_y(getattr(N, _mid)))


@register("weighted_average_life", family="finance", required_tags=["cashflow", "time"],
          set_maturity="reviewed")
def weighted_average_life(cols, binding, convention=None):
    cf, t = cols[binding["cashflow"]], cols[binding["time"]]
    return _result(N.weighted_average_life(cf, t), {"n": len(cf)})


@register("yield_to_maturity", family="finance", required_tags=["cashflow", "time"],
          set_maturity="reviewed", accepted_conventions=["price=<float>"])
def yield_to_maturity(cols, binding, convention=None):
    cf, t = cols[binding["cashflow"]], cols[binding["time"]]
    price = _conv_float(convention, "price", 100.0)
    return _result(N.yield_to_maturity(cf, t, price), {"n": len(cf), "price": price})


# ======================================================================================
# Pack OPT - Black-Scholes option pricing & Greeks. Bind per-position spot/strike/time/
# vol/rate + signed quantity columns; recipes return the portfolio book aggregate. The
# call-vs-put convention picks the wing (default call).
# ======================================================================================

def _opt_is_call(convention):
    s = _conv_str(convention)
    if "=" in s:
        s = s.partition("=")[2].strip()
    return s != "put"


def _opt_book(fn):
    def recipe(cols, binding, convention=None):
        S, K, T = cols[binding["spot"]], cols[binding["strike"]], cols[binding["time"]]
        sig, r, qty = cols[binding["vol"]], cols[binding["rate"]], cols[binding["quantity"]]
        ic = _opt_is_call(convention)
        return _result(fn(S, K, T, sig, r, qty, ic),
                       {"n": len(S), "type": "call" if ic else "put"})
    return recipe


for _mid in ("bs_value", "bs_delta", "bs_gamma", "bs_vega", "bs_theta",
             "bs_rho", "bs_vanna", "bs_volga", "bs_speed", "bs_zomma", "bs_charm", "bs_color",
             "bs_veta", "bs_ultima", "bs_lambda"):
    register(_mid, family="derivatives",
             required_tags=["spot", "strike", "time", "vol", "rate", "quantity"],
             set_maturity="reviewed",
             accepted_conventions=["type=call", "type=put"])(_opt_book(getattr(N, _mid)))


@register("bs_implied_vol", family="derivatives",
          required_tags=["spot", "strike", "time", "rate", "price"],
          set_maturity="reviewed", accepted_conventions=["type=call", "type=put"])
def bs_implied_vol(cols, binding, convention=None):
    S, K, T = cols[binding["spot"]], cols[binding["strike"]], cols[binding["time"]]
    r, px = cols[binding["rate"]], cols[binding["price"]]
    ic = _opt_is_call(convention)
    return _result(N.bs_implied_vol(S, K, T, r, px, ic),
                   {"n": len(S), "type": "call" if ic else "put"})


# ======================================================================================
# Pack ES - expected-shortfall / VaR backtesting. Bind a realized return column with the
# day's predicted VaR (positive loss) and, for the magnitude tests, the predicted ES; the
# tail level comes from the convention. Complements the Kupiec / Christoffersen suite.
# ======================================================================================

def _es_rv(fn):
    def recipe(cols, binding, convention=None):
        r, v = cols[binding["return"]], cols[binding["var"]]
        return _result(fn(r, v), {"n": len(r)}, path_dependent=True)
    return recipe


for _mid in ("var_breach_rate", "realized_shortfall", "expected_exceedance", "basel_traffic_light"):
    register(_mid, family="quant", required_tags=["return", "var"],
             set_maturity="reviewed")(_es_rv(getattr(N, _mid)))


@register("es_backtest_ratio", family="quant", required_tags=["return", "var", "es"],
          set_maturity="reviewed")
def es_backtest_ratio(cols, binding, convention=None):
    r, v, e = cols[binding["return"]], cols[binding["var"]], cols[binding["es"]]
    return _result(N.es_backtest_ratio(r, v, e), {"n": len(r)}, path_dependent=True)


def _es_z(fn):
    def recipe(cols, binding, convention=None):
        r, v, e = cols[binding["return"]], cols[binding["var"]], cols[binding["es"]]
        level = _conv_float(convention, "level", 0.975)
        return _result(fn(r, v, e, level), {"n": len(r), "level": level}, path_dependent=True)
    return recipe


for _mid in ("acerbi_szekely_z1", "acerbi_szekely_z2"):
    register(_mid, family="quant", required_tags=["return", "var", "es"],
             set_maturity="reviewed", accepted_conventions=["level=<frac>"])(_es_z(getattr(N, _mid)))


# ======================================================================================
# Pack CR - credit / default risk. Per-name PD/LGD/EAD columns for portfolio loss; the
# five Altman ratios for the bankruptcy Z-scores; structural asset value/debt/drift/vol/
# horizon columns for the Merton distance-to-default and its implied PD.
# ======================================================================================

def _cr_ple(fn):
    def recipe(cols, binding, convention=None):
        pd_, lgd, ead = cols[binding["pd"]], cols[binding["lgd"]], cols[binding["ead"]]
        return _result(fn(pd_, lgd, ead), {"n": len(ead)})
    return recipe


for _mid in ("expected_loss", "expected_loss_rate", "unexpected_loss"):
    register(_mid, family="credit", required_tags=["pd", "lgd", "ead"],
             set_maturity="reviewed")(_cr_ple(getattr(N, _mid)))


@register("weighted_lgd", family="credit", required_tags=["lgd", "ead"], set_maturity="reviewed")
def weighted_lgd(cols, binding, convention=None):
    lgd, ead = cols[binding["lgd"]], cols[binding["ead"]]
    return _result(N.weighted_lgd(lgd, ead), {"n": len(ead)})


@register("altman_z", family="credit", required_tags=["x1", "x2", "x3", "x4", "x5"],
          set_maturity="reviewed")
def altman_z(cols, binding, convention=None):
    a = [cols[binding[k]] for k in ("x1", "x2", "x3", "x4", "x5")]
    return _result(N.altman_z(*a), {"n": len(a[0])})


@register("altman_z_prime", family="credit", required_tags=["x1", "x2", "x3", "x4"],
          set_maturity="reviewed")
def altman_z_prime(cols, binding, convention=None):
    a = [cols[binding[k]] for k in ("x1", "x2", "x3", "x4")]
    return _result(N.altman_z_prime(*a), {"n": len(a[0])})


def _cr_merton(fn):
    def recipe(cols, binding, convention=None):
        a = [cols[binding[k]] for k in ("asset_value", "debt", "drift", "vol", "time")]
        return _result(fn(*a), {"n": len(a[0])})
    return recipe


for _mid in ("merton_distance_to_default", "merton_pd"):
    register(_mid, family="credit",
             required_tags=["asset_value", "debt", "drift", "vol", "time"],
             set_maturity="reviewed")(_cr_merton(getattr(N, _mid)))


# ======================================================================================
# Pack CR2 - Basel ASRF / Vasicek credit-portfolio capital. PD/LGD/EAD columns; the asset
# correlation rho via convention (Basel default ~0.15). The 99.9% quantile is fixed.
# ======================================================================================

def _cr2_capital(fn):
    def recipe(cols, binding, convention=None):
        p, l, e = cols[binding["pd"]], cols[binding["lgd"]], cols[binding["ead"]]
        rho = _conv_float(convention, "rho", 0.15)
        return _result(fn(p, l, e, rho), {"n": len(p), "rho": rho})
    return recipe


for _mid in ("asrf_capital_requirement", "asrf_rwa"):
    register(_mid, family="credit", required_tags=["pd", "lgd", "ead"],
             set_maturity="reviewed", accepted_conventions=["rho=<frac>"])(_cr2_capital(getattr(N, _mid)))


@register("vasicek_conditional_pd", family="credit", required_tags=["pd"],
          set_maturity="reviewed", accepted_conventions=["rho=<frac>"])
def vasicek_conditional_pd(cols, binding, convention=None):
    p = cols[binding["pd"]]
    rho = _conv_float(convention, "rho", 0.15)
    return _result(N.vasicek_conditional_pd(p, rho), {"n": len(p), "rho": rho})


# ======================================================================================
# Pack CX - credit recovery & exposure-weighting. Realized recovery rate plus the
# exposure-weighted PD / maturity (reusing the weighted-mean kernel).
# ======================================================================================

@register("recovery_rate", family="credit", required_tags=["recovery", "exposure"],
          set_maturity="reviewed")
def recovery_rate(cols, binding, convention=None):
    rec, exp = cols[binding["recovery"]], cols[binding["exposure"]]
    return _result(N.recovery_rate(rec, exp), {"n": len(rec)})


@register("exposure_weighted_pd", family="credit", required_tags=["pd", "ead"],
          set_maturity="reviewed")
def exposure_weighted_pd(cols, binding, convention=None):
    p, e = cols[binding["pd"]], cols[binding["ead"]]
    return _result(N.weighted_mean(p, e), {"n": len(p)})


@register("exposure_weighted_maturity", family="credit", required_tags=["maturity", "ead"],
          set_maturity="reviewed")
def exposure_weighted_maturity(cols, binding, convention=None):
    m, e = cols[binding["maturity"]], cols[binding["ead"]]
    return _result(N.weighted_mean(m, e), {"n": len(m)})


# ======================================================================================
# Pack CLU - clustering agreement depth. Predicted cluster + true class label columns.
# ======================================================================================

def _clu_recipe(fn):
    def recipe(cols, binding, convention=None):
        p, l = cols[binding["prediction"]], cols[binding["label"]]
        return _result(fn(p, l), {"n": len(p)})
    return recipe


for _mid in ("purity", "bcubed_precision", "bcubed_recall", "bcubed_f1"):
    register(_mid, family="classification", required_tags=["prediction", "label"],
             string_tags=["prediction", "label"], set_maturity="reviewed")(_clu_recipe(getattr(N, _mid)))


# ======================================================================================
# Pack PERF2 - consistency & ODD-flag metrics. A return column (+ benchmark for batting avg).
# ======================================================================================

@register("batting_average", family="quant", required_tags=["return", "benchmark"],
          set_maturity="reviewed")
def batting_average(cols, binding, convention=None):
    r, b = cols[binding["return"]], cols[binding["benchmark"]]
    return _result(N.batting_average(r, b), {"n": len(r)})


@register("bias_ratio", family="quant", required_tags=["return"], set_maturity="reviewed")
def bias_ratio(cols, binding, convention=None):
    r = cols[binding["return"]]
    return _result(N.bias_ratio(r), {"n": len(r)})


@register("max_consecutive_losses", family="quant", required_tags=["return"], set_maturity="reviewed")
def max_consecutive_losses(cols, binding, convention=None):
    r = cols[binding["return"]]
    return _result(N.max_consecutive_losses(r), {"n": len(r)}, path_dependent=True)


# ======================================================================================
# Pack QR - tail-risk-adjusted reward ratios. A return column; the tail level via convention.
# ======================================================================================

def _qr_ratio(fn):
    def recipe(cols, binding, convention=None):
        r = cols[binding["return"]]
        q = _conv_q(convention)
        level = q if (q == q and 0.5 < q < 1.0) else 0.95
        return _result(fn(r, level), {"n": len(r), "level": level})
    return recipe


for _mid in ("reward_to_var_ratio", "starr_ratio", "modified_sharpe_ratio"):
    register(_mid, family="quant", required_tags=["return"], set_maturity="reviewed",
             accepted_conventions=["p95", "p99"])(_qr_ratio(getattr(N, _mid)))


# ======================================================================================
# Pack RV - realized volatility / jump measures. A return column.
# ======================================================================================

def _rv_recipe(fn):
    def recipe(cols, binding, convention=None):
        r = cols[binding["return"]]
        return _result(fn(r), {"n": len(r)})
    return recipe


for _mid in ("realized_variance", "realized_volatility", "bipower_variation", "jump_variation"):
    register(_mid, family="quant", required_tags=["return"],
             set_maturity="reviewed")(_rv_recipe(getattr(N, _mid)))


# ======================================================================================
# Pack HU - Hurst / long-memory. A series column.
# ======================================================================================

@register("rescaled_range", family="quant", required_tags=["value"], set_maturity="reviewed")
def rescaled_range(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.rescaled_range(xs), {"n": len(xs)})


@register("hurst_rs", family="quant", required_tags=["value"], set_maturity="reviewed")
def hurst_rs(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.hurst_rs(xs), {"n": len(xs)})


# ======================================================================================
# Pack ML2 - margin classification losses. Decision-score + binary-label columns.
# ======================================================================================

def _ml2_recipe(fn):
    def recipe(cols, binding, convention=None):
        s, y = cols[binding["score"]], cols[binding["label"]]
        return _result(fn(s, y), {"n": len(s)})
    return recipe


for _mid in ("hinge_loss", "squared_hinge_loss", "exponential_loss"):
    register(_mid, family="classification", required_tags=["score", "label"],
             set_maturity="reviewed")(_ml2_recipe(getattr(N, _mid)))


# ======================================================================================
# Pack PA - portfolio construction & attribution. Per-segment portfolio/benchmark weight
# and return columns drive Brinson attribution; weight vectors drive active share,
# turnover and the effective number of bets.
# ======================================================================================

@register("brinson_allocation", family="portfolio",
          required_tags=["port_weight", "bench_weight", "bench_return"], set_maturity="reviewed")
def brinson_allocation(cols, binding, convention=None):
    wp, wb, rb = cols[binding["port_weight"]], cols[binding["bench_weight"]], cols[binding["bench_return"]]
    return _result(N.brinson_allocation(wp, wb, rb), {"n": len(wp)})


@register("brinson_selection", family="portfolio",
          required_tags=["bench_weight", "port_return", "bench_return"], set_maturity="reviewed")
def brinson_selection(cols, binding, convention=None):
    wb, rp, rb = cols[binding["bench_weight"]], cols[binding["port_return"]], cols[binding["bench_return"]]
    return _result(N.brinson_selection(wb, rp, rb), {"n": len(wb)})


def _pa_brinson4(fn):
    def recipe(cols, binding, convention=None):
        a = [cols[binding[k]] for k in ("port_weight", "bench_weight", "port_return", "bench_return")]
        return _result(fn(*a), {"n": len(a[0])})
    return recipe


for _mid in ("brinson_interaction", "brinson_total_active"):
    register(_mid, family="portfolio",
             required_tags=["port_weight", "bench_weight", "port_return", "bench_return"],
             set_maturity="reviewed")(_pa_brinson4(getattr(N, _mid)))


@register("active_share", family="portfolio",
          required_tags=["port_weight", "bench_weight"], set_maturity="reviewed")
def active_share(cols, binding, convention=None):
    wp, wb = cols[binding["port_weight"]], cols[binding["bench_weight"]]
    return _result(N.active_share(wp, wb), {"n": len(wp)})


@register("portfolio_turnover", family="portfolio",
          required_tags=["prev_weight", "curr_weight"], set_maturity="reviewed")
def portfolio_turnover(cols, binding, convention=None):
    wp, wc = cols[binding["prev_weight"]], cols[binding["curr_weight"]]
    return _result(N.portfolio_turnover(wp, wc), {"n": len(wp)})


@register("effective_number_of_bets", family="portfolio",
          required_tags=["weight"], set_maturity="reviewed")
def effective_number_of_bets(cols, binding, convention=None):
    w = cols[binding["weight"]]
    return _result(N.effective_number_of_bets(w), {"n": len(w)})


@register("brinson_fachler_allocation", family="portfolio",
          required_tags=["port_weight", "bench_weight", "bench_return"], set_maturity="reviewed")
def brinson_fachler_allocation(cols, binding, convention=None):
    wp, wb, rb = cols[binding["port_weight"]], cols[binding["bench_weight"]], cols[binding["bench_return"]]
    return _result(N.brinson_fachler_allocation(wp, wb, rb), {"n": len(wp)})


@register("geometric_excess_return", family="portfolio",
          required_tags=["port_weight", "bench_weight", "port_return", "bench_return"],
          set_maturity="reviewed")
def geometric_excess_return(cols, binding, convention=None):
    a = [cols[binding[k]] for k in ("port_weight", "bench_weight", "port_return", "bench_return")]
    return _result(N.geometric_excess_return(*a), {"n": len(a[0])})


# ======================================================================================
# Pack RC - rates / curve analytics. Zero-curve columns (rate + tenor) drive par yields,
# annuity factors and forward rates; a curve plus cashflows drives a multi-curve PV;
# effective duration / convexity bump a single yield by +/-1bp and reprice.
# ======================================================================================

def _rc_curve(fn):
    def recipe(cols, binding, convention=None):
        z, t = cols[binding["zero_rate"]], cols[binding["time"]]
        return _result(fn(z, t), {"n": len(z)})
    return recipe


for _mid in ("par_yield", "annuity_factor", "forward_rate"):
    register(_mid, family="finance", required_tags=["zero_rate", "time"],
             set_maturity="reviewed")(_rc_curve(getattr(N, _mid)))


@register("curve_pv", family="finance", required_tags=["cashflow", "zero_rate", "time"],
          set_maturity="reviewed")
def curve_pv(cols, binding, convention=None):
    cf, z, t = cols[binding["cashflow"]], cols[binding["zero_rate"]], cols[binding["time"]]
    return _result(N.curve_pv(cf, z, t), {"n": len(cf)})


def _rc_bump(fn):
    def recipe(cols, binding, convention=None):
        cf, t = cols[binding["cashflow"]], cols[binding["time"]]
        y = _conv_float(convention, "ytm", 0.05)
        return _result(fn(cf, t, y), {"n": len(cf), "ytm": y})
    return recipe


for _mid in ("effective_duration", "effective_convexity"):
    register(_mid, family="finance", required_tags=["cashflow", "time"],
             set_maturity="reviewed", accepted_conventions=["ytm=<frac>"])(_rc_bump(getattr(N, _mid)))


# ======================================================================================
# Pack FM - fund / LP economics. Capital-call (contribution) and distribution columns
# drive the LP performance multiples; residual NAV, commitment and carry are conventions.
# ======================================================================================

@register("dpi", family="finance", required_tags=["contribution", "distribution"],
          set_maturity="reviewed")
def dpi(cols, binding, convention=None):
    c, d = cols[binding["contribution"]], cols[binding["distribution"]]
    return _result(N.dpi(c, d), {"n": len(c)})


@register("rvpi", family="finance", required_tags=["contribution"],
          set_maturity="reviewed", accepted_conventions=["nav=<float>"])
def rvpi(cols, binding, convention=None):
    c = cols[binding["contribution"]]
    nav = _conv_float(convention, "nav", 0.0)
    return _result(N.rvpi(c, nav), {"n": len(c), "nav": nav})


@register("tvpi", family="finance", required_tags=["contribution", "distribution"],
          set_maturity="reviewed", accepted_conventions=["nav=<float>"])
def tvpi(cols, binding, convention=None):
    c, d = cols[binding["contribution"]], cols[binding["distribution"]]
    nav = _conv_float(convention, "nav", 0.0)
    return _result(N.tvpi(c, d, nav), {"n": len(c), "nav": nav})


@register("called_pct", family="finance", required_tags=["contribution"],
          set_maturity="reviewed", accepted_conventions=["committed=<float>"])
def called_pct(cols, binding, convention=None):
    c = cols[binding["contribution"]]
    committed = _conv_float(convention, "committed", 0.0)
    return _result(N.called_pct(c, committed), {"n": len(c), "committed": committed})


@register("carried_interest", family="finance", required_tags=["contribution", "distribution"],
          set_maturity="reviewed", accepted_conventions=["carry=<frac>"])
def carried_interest(cols, binding, convention=None):
    c, d = cols[binding["contribution"]], cols[binding["distribution"]]
    carry = _conv_float(convention, "carry", 0.20)
    return _result(N.carried_interest(c, d, carry), {"n": len(c), "carry": carry})


@register("realization_ratio", family="finance", required_tags=["distribution"],
          set_maturity="reviewed", accepted_conventions=["nav=<float>"])
def realization_ratio(cols, binding, convention=None):
    d = cols[binding["distribution"]]
    nav = _conv_float(convention, "nav", 0.0)
    return _result(N.realization_ratio(d, nav), {"n": len(d), "nav": nav})


# ======================================================================================
# Pack LQ - liquidity / microstructure. Per-day return / dollar-volume / price / quote
# columns drive the price-impact and spread estimators.
# ======================================================================================

def _lq_rv(fn):
    def recipe(cols, binding, convention=None):
        r, v = cols[binding["return"]], cols[binding["dollar_volume"]]
        return _result(fn(r, v), {"n": len(r)})
    return recipe


for _mid in ("amihud_illiquidity", "amivest_liquidity"):
    register(_mid, family="liquidity", required_tags=["return", "dollar_volume"],
             set_maturity="reviewed")(_lq_rv(getattr(N, _mid)))


@register("roll_spread", family="liquidity", required_tags=["price"],
          set_maturity="reviewed")
def roll_spread(cols, binding, convention=None):
    p = cols[binding["price"]]
    return _result(N.roll_spread(p), {"n": len(p)}, path_dependent=True)


@register("kyle_lambda", family="liquidity", required_tags=["price_change", "signed_volume"],
          set_maturity="reviewed")
def kyle_lambda(cols, binding, convention=None):
    dp, q = cols[binding["price_change"]], cols[binding["signed_volume"]]
    return _result(N.kyle_lambda(dp, q), {"n": len(dp)})


@register("vwap", family="liquidity", required_tags=["price", "volume"],
          set_maturity="reviewed")
def vwap(cols, binding, convention=None):
    p, v = cols[binding["price"]], cols[binding["volume"]]
    return _result(N.vwap(p, v), {"n": len(p)})


@register("relative_spread", family="liquidity", required_tags=["bid", "ask"],
          set_maturity="reviewed")
def relative_spread(cols, binding, convention=None):
    b, a = cols[binding["bid"]], cols[binding["ask"]]
    return _result(N.relative_spread(b, a), {"n": len(b)})


# ======================================================================================
# Pack AB - multiple-testing corrections. A p-value column + family alpha convention give
# the rejection count under each procedure; complements bh_rejections / holm_rejections.
# ======================================================================================

_AB_METHOD = {
    "bonferroni_rejections": "bonferroni", "sidak_rejections": "sidak",
    "holm_sidak_rejections": "holm-sidak", "hochberg_rejections": "simes-hochberg",
    "benjamini_yekutieli": "fdr_by",
}


def _ab_reject(fn, method):
    def recipe(cols, binding, convention=None):
        pvals = cols[binding["value"]]
        alpha = _conv_float(convention, "alpha", 0.05)
        return _result(fn(pvals, alpha), {"m": len(pvals), "alpha": alpha, "method": method})
    return recipe


for _mid, _method in _AB_METHOD.items():
    register(_mid, family="stats", required_tags=["value"], set_maturity="reviewed",
             accepted_conventions=["alpha=<frac>"])(_ab_reject(getattr(N, _mid), _method))


# ======================================================================================
# Pack TS - time-series / return diagnostics. A return (or residual) column drives the
# variance ratio, runs test and ARCH-LM(1) statistic.
# ======================================================================================

@register("variance_ratio", family="quant", required_tags=["return"],
          set_maturity="reviewed", accepted_conventions=["q=<int>"])
def variance_ratio(cols, binding, convention=None):
    rets = cols[binding["return"]]
    q = _conv_int(convention, "q", 2)
    return _result(N.variance_ratio(rets, q), {"n": len(rets), "q": q})


@register("runs_test", family="stats", required_tags=["value"], set_maturity="reviewed")
def runs_test(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.runs_test(xs), {"n": len(xs)})


@register("arch_lm", family="stats", required_tags=["value"], set_maturity="reviewed")
def arch_lm(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.arch_lm(xs), {"n": len(xs)})


# ======================================================================================
# Pack OPS - exposure, leverage & operational-due-diligence metrics. A signed exposure
# column (position as a fraction of NAV) drives the exposure / leverage / concentration
# metrics; a weight + days-to-liquidate column drives liquidity coverage.
# ======================================================================================

def _ops_exp(fn):
    def recipe(cols, binding, convention=None):
        e = cols[binding["exposure"]]
        return _result(fn(e), {"n": len(e)})
    return recipe


for _mid in ("gross_exposure", "net_exposure", "long_exposure", "short_exposure",
             "long_short_ratio", "largest_position"):
    register(_mid, family="exposure", required_tags=["exposure"],
             set_maturity="reviewed")(_ops_exp(getattr(N, _mid)))


@register("liquidity_coverage", family="exposure",
          required_tags=["weight", "days_to_liquidate"], set_maturity="reviewed",
          accepted_conventions=["threshold=<days>"])
def liquidity_coverage(cols, binding, convention=None):
    w, d = cols[binding["weight"]], cols[binding["days_to_liquidate"]]
    threshold = _conv_float(convention, "threshold", 5.0)
    return _result(N.liquidity_coverage(w, d, threshold), {"n": len(w), "threshold": threshold})


# ======================================================================================
# Pack FX - single-factor market-model risk. Bind asset return + benchmark return columns;
# the market model is fit by OLS for idiosyncratic vol, alpha/beta t-stats and bull/bear beta.
# ======================================================================================

def _fx_rb(fn):
    def recipe(cols, binding, convention=None):
        r, b = cols[binding["return"]], cols[binding["benchmark"]]
        return _result(fn(r, b), {"n": len(r)})
    return recipe


for _mid in ("idiosyncratic_volatility", "alpha_tstat", "beta_tstat",
             "bull_beta", "bear_beta", "up_down_beta_ratio"):
    register(_mid, family="quant", required_tags=["return", "benchmark"],
             set_maturity="reviewed")(_fx_rb(getattr(N, _mid)))


# ======================================================================================
# Pack AR - credit-quality / covenant ratios. Balance-sheet and income columns drive the
# leverage and coverage ratios; each recipe binds the line-item columns it needs.
# ======================================================================================

_AR_BIND = {
    "current_ratio": ["current_assets", "current_liabilities"],
    "quick_ratio": ["current_assets", "inventory", "current_liabilities"],
    "interest_coverage": ["ebit", "interest_expense"],
    "debt_to_equity": ["debt", "equity"],
    "debt_to_ebitda": ["debt", "ebitda"],
    "net_debt_to_ebitda": ["debt", "cash", "ebitda"],
    "ebitda_margin": ["ebitda", "revenue"],
}


def _ar_recipe(fn, tags):
    def recipe(cols, binding, convention=None):
        a = [cols[binding[t]] for t in tags]
        return _result(fn(*a), {"n": len(a[0])})
    return recipe


for _mid, _tags in _AR_BIND.items():
    register(_mid, family="credit", required_tags=list(_tags),
             set_maturity="reviewed")(_ar_recipe(getattr(N, _mid), _tags))


# ======================================================================================
# Pack CAL - probability-calibration depth. Predicted-probability + binary-outcome columns;
# the binned metrics take a bins convention (default 15, matching ECE).
# ======================================================================================

def _cal_binned(fn):
    def recipe(cols, binding, convention=None):
        p, y = cols[binding["probability"]], cols[binding["label"]]
        bins = _conv_int(convention, "bins", 15)
        return _result(fn(p, y, bins), {"n": len(p), "bins": bins})
    return recipe


for _mid in ("maximum_calibration_error", "brier_reliability", "brier_resolution"):
    register(_mid, family="classification", required_tags=["probability", "label"],
             set_maturity="reviewed", accepted_conventions=["bins=<int>"])(_cal_binned(getattr(N, _mid)))


def _cal_pl(fn):
    def recipe(cols, binding, convention=None):
        p, y = cols[binding["probability"]], cols[binding["label"]]
        return _result(fn(p, y), {"n": len(p)})
    return recipe


for _mid in ("brier_skill_score", "calibration_in_the_large", "spiegelhalter_z"):
    register(_mid, family="classification", required_tags=["probability", "label"],
             set_maturity="reviewed")(_cal_pl(getattr(N, _mid)))


@register("sharpness", family="classification", required_tags=["probability"],
          set_maturity="reviewed")
def sharpness(cols, binding, convention=None):
    p = cols[binding["probability"]]
    return _result(N.sharpness(p), {"n": len(p)})


# ======================================================================================
# Pack DIST - distribution-distance depth. Two histogram / share columns (p, q),
# sum-normalized to distributions, matching the existing KL / JS bindings.
# ======================================================================================

def _dist_pq(fn):
    def recipe(cols, binding, convention=None):
        p, q = cols[binding["p"]], cols[binding["q"]]
        return _result(fn(p, q), {"bins": len(p)})
    return recipe


for _mid in ("hellinger_distance", "total_variation_distance", "bhattacharyya_distance",
             "jeffreys_divergence", "chi_square_distance"):
    register(_mid, family="stats", required_tags=["p", "q"],
             set_maturity="reviewed")(_dist_pq(getattr(N, _mid)))


# ======================================================================================
# Pack SV - survival / time-to-event. Duration + event (1=observed, 0=censored) columns;
# the point-in-time metrics take a t / horizon convention.
# ======================================================================================

@register("km_median_survival", family="stats", required_tags=["duration", "event"],
          set_maturity="reviewed")
def km_median_survival(cols, binding, convention=None):
    d, e = cols[binding["duration"]], cols[binding["event"]]
    return _result(N.km_median_survival(d, e), {"n": len(d)}, path_dependent=True)


@register("km_survival_at", family="stats", required_tags=["duration", "event"],
          set_maturity="reviewed", accepted_conventions=["t=<float>"])
def km_survival_at(cols, binding, convention=None):
    d, e = cols[binding["duration"]], cols[binding["event"]]
    t = _conv_float(convention, "t", 1.0)
    return _result(N.km_survival_at(d, e, t), {"n": len(d), "t": t}, path_dependent=True)


@register("nelson_aalen_cumhaz", family="stats", required_tags=["duration", "event"],
          set_maturity="reviewed", accepted_conventions=["t=<float>"])
def nelson_aalen_cumhaz(cols, binding, convention=None):
    d, e = cols[binding["duration"]], cols[binding["event"]]
    t = _conv_float(convention, "t", 1.0)
    return _result(N.nelson_aalen_cumhaz(d, e, t), {"n": len(d), "t": t}, path_dependent=True)


@register("restricted_mean_survival_time", family="stats", required_tags=["duration", "event"],
          set_maturity="reviewed", accepted_conventions=["horizon=<float>"])
def restricted_mean_survival_time(cols, binding, convention=None):
    d, e = cols[binding["duration"]], cols[binding["event"]]
    horizon = _conv_float(convention, "horizon", 1.0)
    return _result(N.restricted_mean_survival_time(d, e, horizon),
                   {"n": len(d), "horizon": horizon}, path_dependent=True)


# ======================================================================================
# Pack TX - transaction-cost analysis. Fill price, benchmark price and quantity columns;
# the side convention (buy / sell) signs the cost. Participation needs only volumes.
# ======================================================================================

def _tca_side(convention):
    s = _conv_str(convention)
    if "=" in s:
        s = s.partition("=")[2].strip()
    return -1.0 if s == "sell" else 1.0


_TX_BENCH = {
    "implementation_shortfall": ("decision_price", N.implementation_shortfall),
    "arrival_slippage": ("arrival_price", N.arrival_slippage),
    "vwap_slippage": ("vwap_price", N.vwap_slippage),
    "effective_spread_bps": ("mid_price", N.effective_spread_bps),
}


def _tx_cost(bench_tag, fn):
    def recipe(cols, binding, convention=None):
        e, b, q = cols[binding["exec_price"]], cols[binding[bench_tag]], cols[binding["quantity"]]
        side = _tca_side(convention)
        return _result(fn(e, b, q, side), {"n": len(e), "side": "sell" if side < 0 else "buy"})
    return recipe


for _mid, (_bench, _fn) in _TX_BENCH.items():
    register(_mid, family="execution",
             required_tags=["exec_price", _bench, "quantity"],
             set_maturity="reviewed", accepted_conventions=["side=buy", "side=sell"])(_tx_cost(_bench, _fn))


@register("participation_rate", family="execution",
          required_tags=["order_volume", "market_volume"], set_maturity="reviewed")
def participation_rate(cols, binding, convention=None):
    o, m = cols[binding["order_volume"]], cols[binding["market_volume"]]
    return _result(N.participation_rate(o, m), {"n": len(o)})


# ======================================================================================
# Pack PME - private-market benchmarking. Contribution / distribution / public-index-level
# columns; residual NAV via convention.
# ======================================================================================

def _pme_recipe(fn):
    def recipe(cols, binding, convention=None):
        c, d, ix = cols[binding["contribution"]], cols[binding["distribution"]], cols[binding["index"]]
        nav = _conv_float(convention, "nav", 0.0)
        return _result(fn(c, d, ix, nav), {"n": len(c), "nav": nav})
    return recipe


for _mid in ("ks_pme", "direct_alpha", "pme_plus_lambda"):
    register(_mid, family="finance", required_tags=["contribution", "distribution", "index"],
             set_maturity="reviewed", accepted_conventions=["nav=<float>"])(_pme_recipe(getattr(N, _mid)))


# ======================================================================================
# Pack IC - information criteria / model selection. A residual column; the penalized
# criteria take the fitted-parameter count k via convention (default 2).
# ======================================================================================

@register("log_likelihood_gaussian", family="regression", required_tags=["residual"],
          set_maturity="reviewed")
def log_likelihood_gaussian(cols, binding, convention=None):
    r = cols[binding["residual"]]
    return _result(N.log_likelihood_gaussian(r), {"n": len(r)})


def _ic_k(fn):
    def recipe(cols, binding, convention=None):
        r = cols[binding["residual"]]
        k = _conv_int(convention, "k", 2)
        return _result(fn(r, k), {"n": len(r), "k": k})
    return recipe


for _mid in ("aic", "bic", "aicc", "hqic"):
    register(_mid, family="regression", required_tags=["residual"],
             set_maturity="reviewed", accepted_conventions=["k=<int>"])(_ic_k(getattr(N, _mid)))


# ======================================================================================
# Pack INE - inequality / concentration depth. A positive value column; GE takes an alpha.
# ======================================================================================

@register("hoover_index", family="analytics", required_tags=["value"], set_maturity="reviewed")
def hoover_index(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.hoover_index(xs), {"n": len(xs)})


@register("mean_log_deviation", family="analytics", required_tags=["value"], set_maturity="reviewed")
def mean_log_deviation(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.mean_log_deviation(xs), {"n": len(xs)})


@register("generalized_entropy_index", family="analytics", required_tags=["value"],
          set_maturity="reviewed", accepted_conventions=["alpha=<float>"])
def generalized_entropy_index(cols, binding, convention=None):
    xs = cols[binding["value"]]
    alpha = _conv_float(convention, "alpha", 2.0)
    return _result(N.generalized_entropy_index(xs, alpha), {"n": len(xs), "alpha": alpha})


@register("percentile_ratio", family="analytics", required_tags=["value"], set_maturity="reviewed")
def percentile_ratio(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.percentile_ratio(xs), {"n": len(xs)})


# ======================================================================================
# Pack EF - effect-size depth. Two samples (sample_a / sample_b); Cohen's h reads them as
# binary outcome columns.
# ======================================================================================

def _ef_ab(fn):
    def recipe(cols, binding, convention=None):
        a, b = cols[binding["sample_a"]], cols[binding["sample_b"]]
        return _result(fn(a, b), {"n_a": len(a), "n_b": len(b)})
    return recipe


for _mid in ("glass_delta", "hedges_g", "common_language_effect_size", "cohens_h"):
    register(_mid, family="stats", required_tags=["sample_a", "sample_b"],
             set_maturity="reviewed")(_ef_ab(getattr(N, _mid)))


# ======================================================================================
# Pack VOL - range-based (OHLC) volatility estimators. Parkinson needs high/low; the others
# need the full open/high/low/close bars.
# ======================================================================================

@register("parkinson_volatility", family="quant", required_tags=["high", "low"],
          set_maturity="reviewed")
def parkinson_volatility(cols, binding, convention=None):
    h, l = cols[binding["high"]], cols[binding["low"]]
    return _result(N.parkinson_volatility(h, l), {"n": len(h)})


def _vol_ohlc(fn):
    def recipe(cols, binding, convention=None):
        o, h, l, c = (cols[binding["open"]], cols[binding["high"]],
                      cols[binding["low"]], cols[binding["close"]])
        return _result(fn(o, h, l, c), {"n": len(o)})
    return recipe


for _mid in ("garman_klass_volatility", "rogers_satchell_volatility", "yang_zhang_volatility"):
    register(_mid, family="quant", required_tags=["open", "high", "low", "close"],
             set_maturity="reviewed")(_vol_ohlc(getattr(N, _mid)))


# ======================================================================================
# Pack RGD - regression / GLM deviance depth. Prediction + target columns; Tweedie takes a
# power convention. RMSLE reuses the existing msle kernel with root=True.
# ======================================================================================

@register("mean_squared_error", family="regression", required_tags=["prediction", "target"],
          set_maturity="reviewed")
def mean_squared_error(cols, binding, convention=None):
    p, a = cols[binding["prediction"]], cols[binding["target"]]
    return _result(N.mean_squared_error(p, a), {"n": len(p)})


@register("rmsle", family="regression", required_tags=["prediction", "target"],
          set_maturity="reviewed")
def rmsle(cols, binding, convention=None):
    p, a = cols[binding["prediction"]], cols[binding["target"]]
    return _result(N.msle(p, a, root=True), {"n": len(p)})


def _rgd_tweedie(fn):
    def recipe(cols, binding, convention=None):
        p, a = cols[binding["prediction"]], cols[binding["target"]]
        power = _conv_float(convention, "power", 1.5)
        return _result(fn(p, a, power), {"n": len(p), "power": power})
    return recipe


for _mid in ("mean_tweedie_deviance", "d2_tweedie_score"):
    register(_mid, family="regression", required_tags=["prediction", "target"],
             set_maturity="reviewed", accepted_conventions=["power=<float>"])(_rgd_tweedie(getattr(N, _mid)))


# ======================================================================================
# Pack FCI - prediction-interval / probabilistic-forecast evaluation. Lower / upper / actual
# columns; the Winkler score and coverage deviation take the interval level alpha.
# ======================================================================================

@register("interval_coverage", family="forecasting",
          required_tags=["lower", "upper", "actual"], set_maturity="reviewed")
def interval_coverage(cols, binding, convention=None):
    lo, hi, a = cols[binding["lower"]], cols[binding["upper"]], cols[binding["actual"]]
    return _result(N.interval_coverage(lo, hi, a), {"n": len(a)})


@register("mean_interval_width", family="forecasting",
          required_tags=["lower", "upper"], set_maturity="reviewed")
def mean_interval_width(cols, binding, convention=None):
    lo, hi = cols[binding["lower"]], cols[binding["upper"]]
    return _result(N.mean_interval_width(lo, hi), {"n": len(lo)})


def _fci_alpha(fn):
    def recipe(cols, binding, convention=None):
        lo, hi, a = cols[binding["lower"]], cols[binding["upper"]], cols[binding["actual"]]
        alpha = _conv_float(convention, "alpha", 0.10)
        return _result(fn(lo, hi, a, alpha), {"n": len(a), "alpha": alpha})
    return recipe


for _mid in ("winkler_score", "coverage_deviation"):
    register(_mid, family="forecasting", required_tags=["lower", "upper", "actual"],
             set_maturity="reviewed", accepted_conventions=["alpha=<frac>"])(_fci_alpha(getattr(N, _mid)))


# ======================================================================================
# Pack AG - inter-rater agreement coefficients. Two categorical rater columns.
# ======================================================================================

def _ag_recipe(fn):
    def recipe(cols, binding, convention=None):
        a, b = cols[binding["rater_a"]], cols[binding["rater_b"]]
        return _result(fn(a, b), {"n": len(a)})
    return recipe


for _mid in ("percentage_agreement", "scott_pi", "brennan_prediger", "gwet_ac1"):
    register(_mid, family="classification", required_tags=["rater_a", "rater_b"],
             string_tags=["rater_a", "rater_b"], set_maturity="reviewed")(_ag_recipe(getattr(N, _mid)))


# ======================================================================================
# Pack CO - correlation / dependence depth. Two value columns (x / y).
# ======================================================================================

def _co_xy(fn):
    def recipe(cols, binding, convention=None):
        x, y = cols[binding["x"]], cols[binding["y"]]
        return _result(fn(x, y), {"n": len(x)})
    return recipe


for _mid in ("distance_correlation", "somers_d", "goodman_kruskal_gamma"):
    register(_mid, family="stats", required_tags=["x", "y"],
             set_maturity="reviewed")(_co_xy(getattr(N, _mid)))


# ======================================================================================
# Pack RNK - ranking / IR depth. Per-query (query, rank, relevance) rows; k via convention.
# ======================================================================================

def _rnk_recipe(fn):
    def recipe(cols, binding, convention=None):
        q, r, rel = cols[binding["query"]], cols[binding["rank"]], cols[binding["relevance"]]
        k = _conv_int(convention, "k", 10)
        return _result(fn(q, r, rel, k), {"k": k, "n_rows": len(r)})
    return recipe


for _mid in ("err_at_k", "success_at_k", "arhr_at_k"):
    register(_mid, family="retrieval", required_tags=["query", "rank", "relevance"],
             set_maturity="reviewed", string_tags=["query"],
             accepted_conventions=["k=<int>"])(_rnk_recipe(getattr(N, _mid)))


# ======================================================================================
# Pack SH - robust distribution shape. A single value column.
# ======================================================================================

def _sh_recipe(fn):
    def recipe(cols, binding, convention=None):
        xs = cols[binding["value"]]
        return _result(fn(xs), {"n": len(xs)})
    return recipe


for _mid in ("bowley_skewness", "moors_kurtosis", "l_skewness", "l_kurtosis"):
    register(_mid, family="stats", required_tags=["value"],
             set_maturity="reviewed")(_sh_recipe(getattr(N, _mid)))


# ======================================================================================
# Pack TL - tail-risk / extreme-value estimators. A positive loss / magnitude column; Hill
# and Pickands take a k convention (number of order statistics), max-to-sum takes a moment p.
# ======================================================================================

def _tl_k(fn):
    def recipe(cols, binding, convention=None):
        xs = cols[binding["value"]]
        k = _conv_int(convention, "k", 25)
        return _result(fn(xs, k), {"n": len(xs), "k": k}, path_dependent=True)
    return recipe


for _mid in ("hill_estimator", "pickands_estimator"):
    register(_mid, family="quant", required_tags=["value"], set_maturity="reviewed",
             accepted_conventions=["k=<int>"])(_tl_k(getattr(N, _mid)))


@register("max_to_sum_ratio", family="quant", required_tags=["value"],
          set_maturity="reviewed", accepted_conventions=["p=<float>"])
def max_to_sum_ratio(cols, binding, convention=None):
    xs = cols[binding["value"]]
    p = _conv_float(convention, "p", 2.0)
    return _result(N.max_to_sum_ratio(xs, p), {"n": len(xs), "p": p})


# ======================================================================================
# Pack BIZ - return-on-capital & efficiency ratios. Each recipe binds the two line-item
# columns it needs (income / capital / revenue), summed across entities.
# ======================================================================================

_BIZ_BIND = {
    "return_on_equity": ["net_income", "equity"],
    "return_on_assets": ["net_income", "assets"],
    "return_on_invested_capital": ["nopat", "invested_capital"],
    "asset_turnover": ["revenue", "assets"],
    "days_sales_outstanding": ["receivables", "revenue"],
}


def _biz_recipe(fn, tags):
    def recipe(cols, binding, convention=None):
        a = [cols[binding[t]] for t in tags]
        return _result(fn(*a), {"n": len(a[0])})
    return recipe


for _mid, _tags in _BIZ_BIND.items():
    register(_mid, family="finance", required_tags=list(_tags),
             set_maturity="reviewed")(_biz_recipe(getattr(N, _mid), _tags))


# ======================================================================================
# Pack AC - profitability margin ratios. Each binds the two line-item columns it needs.
# ======================================================================================

_AC_BIND = {
    "operating_margin": ["operating_income", "revenue"],
    "net_margin": ["net_income", "revenue"],
    "free_cash_flow_margin": ["fcf", "revenue"],
    "dividend_payout_ratio": ["dividends", "net_income"],
}

for _mid, _tags in _AC_BIND.items():
    register(_mid, family="finance", required_tags=list(_tags),
             set_maturity="reviewed")(_biz_recipe(getattr(N, _mid), _tags))


# ======================================================================================
# Pack DD - drawdown / path-risk depth. A return column; drawdown-at-risk takes a level.
# ======================================================================================

@register("time_underwater", family="quant", required_tags=["return"], set_maturity="reviewed")
def time_underwater(cols, binding, convention=None):
    r = cols[binding["return"]]
    return _result(N.time_underwater(r), {"n": len(r)}, path_dependent=True)


@register("drawdown_deviation", family="quant", required_tags=["return"], set_maturity="reviewed")
def drawdown_deviation(cols, binding, convention=None):
    r = cols[binding["return"]]
    return _result(N.drawdown_deviation(r), {"n": len(r)}, path_dependent=True)


@register("drawdown_at_risk", family="quant", required_tags=["return"],
          set_maturity="reviewed", accepted_conventions=["p95", "p99"])
def drawdown_at_risk(cols, binding, convention=None):
    r = cols[binding["return"]]
    q = _conv_q(convention)
    level = q if (q == q and 0.5 < q < 1.0) else 0.95
    return _result(N.drawdown_at_risk(r, level), {"n": len(r), "level": level}, path_dependent=True)


# ======================================================================================
# Pack FC2 - forecasting accuracy depth. Prediction + actual columns.
# ======================================================================================

def _fc2_recipe(fn):
    def recipe(cols, binding, convention=None):
        p, a = cols[binding["prediction"]], cols[binding["target"]]
        return _result(fn(p, a), {"n": len(p)})
    return recipe


for _mid in ("mean_arctangent_ape", "geometric_mean_absolute_error", "cumulative_forecast_error",
             "nash_sutcliffe_efficiency", "willmott_index", "kling_gupta_efficiency"):
    register(_mid, family="forecasting", required_tags=["prediction", "target"],
             set_maturity="reviewed")(_fc2_recipe(getattr(N, _mid)))


# ======================================================================================
# Pack DV - diversity / breadth indices. A non-negative amounts column; Hill takes order q.
# ======================================================================================

@register("shannon_diversity", family="analytics", required_tags=["value"], set_maturity="reviewed")
def shannon_diversity(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.shannon_diversity(xs), {"n": len(xs)})


@register("pielou_evenness", family="analytics", required_tags=["value"], set_maturity="reviewed")
def pielou_evenness(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.pielou_evenness(xs), {"n": len(xs)})


@register("berger_parker", family="analytics", required_tags=["value"], set_maturity="reviewed")
def berger_parker(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.berger_parker(xs), {"n": len(xs)})


# ======================================================================================
# Pack CN - concentration-ratio depth. A non-negative amounts column; CRk takes a k.
# ======================================================================================

@register("concentration_ratio", family="analytics", required_tags=["value"],
          set_maturity="reviewed", accepted_conventions=["k=<int>"])
def concentration_ratio(cols, binding, convention=None):
    xs = cols[binding["value"]]
    k = _conv_int(convention, "k", 4)
    return _result(N.concentration_ratio(xs, k), {"n": len(xs), "k": k})


for _mid in ("normalized_hhi", "rosenbluth_index", "comprehensive_concentration_index"):
    @register(_mid, family="analytics", required_tags=["value"], set_maturity="reviewed")
    def _cn(cols, binding, convention=None, _fn=getattr(N, _mid)):
        xs = cols[binding["value"]]
        return _result(_fn(xs), {"n": len(xs)})


# ======================================================================================
# Pack NP - nonparametric scale / location tests. Two samples (sample_a / sample_b).
# ======================================================================================

def _np_ab(fn):
    def recipe(cols, binding, convention=None):
        a, b = cols[binding["sample_a"]], cols[binding["sample_b"]]
        return _result(fn(a, b), {"n_a": len(a), "n_b": len(b)})
    return recipe


for _mid in ("mood_test", "ansari_bradley", "brunner_munzel"):
    register(_mid, family="stats", required_tags=["sample_a", "sample_b"],
             set_maturity="reviewed")(_np_ab(getattr(N, _mid)))


# ======================================================================================
# Pack MOM - robust moment & dispersion depth. A single value column.
# ======================================================================================

def _mom_recipe(fn):
    def recipe(cols, binding, convention=None):
        xs = cols[binding["value"]]
        return _result(fn(xs), {"n": len(xs)})
    return recipe


for _mid in ("pearson_median_skewness", "studentized_range", "relative_mean_deviation", "midhinge",
             "trimean", "hodges_lehmann_estimator", "gastwirth_location",
             "gini_mean_difference", "relative_mean_difference", "l_scale", "l_cv"):
    register(_mid, family="analytics", required_tags=["value"],
             set_maturity="reviewed")(_mom_recipe(getattr(N, _mid)))


@register("hill_number", family="analytics", required_tags=["value"],
          set_maturity="reviewed", accepted_conventions=["q=<float>"])
def hill_number(cols, binding, convention=None):
    xs = cols[binding["value"]]
    q = _conv_float(convention, "q", 1.0)
    return _result(N.hill_number(xs, q), {"n": len(xs), "q": q})


# ======================================================================================
# Pack WIN - winsorized / trimmed robust statistics. A value column; symmetric trim fraction.
# ======================================================================================

def _win_recipe(fn):
    def recipe(cols, binding, convention=None):
        xs = cols[binding["value"]]
        trim = _conv_float(convention, "trim", 0.1)
        return _result(fn(xs, trim), {"n": len(xs), "trim": trim})
    return recipe


for _mid in ("winsorized_mean", "winsorized_std", "trimmed_std"):
    register(_mid, family="analytics", required_tags=["value"],
             set_maturity="reviewed", accepted_conventions=["trim=<frac>"])(_win_recipe(getattr(N, _mid)))


# ======================================================================================
# Pack BD2 - fixed-income spread analytics. Cashflow + zero-curve columns; Z-spread needs a price.
# ======================================================================================

def _bd2_dur(fn):
    def recipe(cols, binding, convention=None):
        cf, z, t = cols[binding["cashflow"]], cols[binding["zero_rate"]], cols[binding["time"]]
        return _result(fn(cf, z, t), {"n": len(cf)})
    return recipe


for _mid in ("spread_duration", "spread_dv01"):
    register(_mid, family="finance", required_tags=["cashflow", "zero_rate", "time"],
             set_maturity="reviewed")(_bd2_dur(getattr(N, _mid)))


@register("z_spread", family="finance", required_tags=["cashflow", "zero_rate", "time"],
          set_maturity="reviewed", accepted_conventions=["price=<float>"])
def z_spread(cols, binding, convention=None):
    cf, z, t = cols[binding["cashflow"]], cols[binding["zero_rate"]], cols[binding["time"]]
    price = _conv_float(convention, "price", 100.0)
    return _result(N.z_spread(cf, z, t, price), {"n": len(cf), "price": price})


# ======================================================================================
# Pack TS2 - time-series diagnostics depth. A value/series column; the lag/order convention.
# ======================================================================================

@register("box_pierce", family="stats", required_tags=["value"],
          set_maturity="reviewed", accepted_conventions=["lags=<int>"])
def box_pierce(cols, binding, convention=None):
    xs = cols[binding["value"]]
    lags = _conv_int(convention, "lags", 10)
    return _result(N.box_pierce(xs, lags), {"n": len(xs), "lags": lags})


@register("permutation_entropy", family="stats", required_tags=["value"],
          set_maturity="reviewed", accepted_conventions=["order=<int>"])
def permutation_entropy(cols, binding, convention=None):
    xs = cols[binding["value"]]
    order = _conv_int(convention, "order", 3)
    return _result(N.permutation_entropy(xs, order), {"n": len(xs), "order": order})


@register("partial_autocorrelation", family="stats", required_tags=["value"],
          set_maturity="reviewed", accepted_conventions=["lag=<int>"])
def partial_autocorrelation(cols, binding, convention=None):
    xs = cols[binding["value"]]
    lag = _conv_int(convention, "lag", 1)
    return _result(N.partial_autocorrelation(xs, lag), {"n": len(xs), "lag": lag})


# ======================================================================================
# Pack GM - generalized means & power-sum descriptive statistics. A single value column.
# power_mean / lehmer_mean take a power p; the others are parameter-free.
# ======================================================================================

@register("power_mean", family="analytics", required_tags=["value"],
          set_maturity="reviewed", accepted_conventions=["p=<float>"])
def power_mean(cols, binding, convention=None):
    xs = cols[binding["value"]]
    p = _conv_float(convention, "p", 2.0)
    return _result(N.power_mean(xs, p), {"n": len(xs), "p": p})


@register("lehmer_mean", family="analytics", required_tags=["value"],
          set_maturity="reviewed", accepted_conventions=["p=<float>"])
def lehmer_mean(cols, binding, convention=None):
    xs = cols[binding["value"]]
    p = _conv_float(convention, "p", 2.0)
    return _result(N.lehmer_mean(xs, p), {"n": len(xs), "p": p})


@register("geometric_std", family="analytics", required_tags=["value"], set_maturity="reviewed")
def geometric_std(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.geometric_std(xs), {"n": len(xs)})


@register("root_mean_square", family="analytics", required_tags=["value"], set_maturity="reviewed")
def root_mean_square(cols, binding, convention=None):
    xs = cols[binding["value"]]
    return _result(N.root_mean_square(xs), {"n": len(xs)})


for _mid in ("kstat_third", "kstat_fourth"):
    register(_mid, family="stats", required_tags=["value"],
             set_maturity="reviewed")(_mom_recipe(getattr(N, _mid)))


# ======================================================================================
# Pack NT - normality & nonparametric test statistics. skewtest/kurtosistest/normaltest/
# differential_entropy take a single value column; the two-sample location tests take
# sample_a / sample_b.
# ======================================================================================

for _mid in ("skewtest", "kurtosistest", "normaltest", "differential_entropy"):
    register(_mid, family="stats", required_tags=["value"],
             set_maturity="reviewed")(_mom_recipe(getattr(N, _mid)))


for _mid in ("wilcoxon_rank_sum", "mood_median_test"):
    register(_mid, family="stats", required_tags=["sample_a", "sample_b"],
             set_maturity="reviewed")(_np_ab(getattr(N, _mid)))


# ======================================================================================
# Pack FE4 - forecasting & hydrology skill metrics. prediction + target columns.
# ======================================================================================

for _mid in ("root_mean_square_percentage_error", "legates_mccabe_efficiency",
             "refined_willmott_index", "fractional_bias", "mean_bias_error",
             "log_nash_sutcliffe"):
    register(_mid, family="forecasting", required_tags=["prediction", "target"],
             set_maturity="reviewed")(_fc2_recipe(getattr(N, _mid)))


# ======================================================================================
# Pack DEC - diversity, entropy & welfare depth. A non-negative amounts/counts column;
# renyi_entropy / tsallis_entropy take an order q.
# ======================================================================================

for _mid in ("renyi_entropy", "tsallis_entropy"):
    @register(_mid, family="analytics", required_tags=["value"], set_maturity="reviewed",
              accepted_conventions=["q=<float>"])
    def _dec_q(cols, binding, convention=None, _fn=getattr(N, _mid)):
        xs = cols[binding["value"]]
        q = _conv_float(convention, "q", 2.0)
        return _result(_fn(xs, q), {"n": len(xs), "q": q})


for _mid in ("margalef_richness", "menhinick_richness", "mcintosh_diversity",
             "sen_welfare", "simpson_evenness"):
    register(_mid, family="analytics", required_tags=["value"],
             set_maturity="reviewed")(_mom_recipe(getattr(N, _mid)))


# ======================================================================================
# Pack CR3 - distress-scoring models & bank-capital ratios. Each binds its named ratio /
# line-item columns; the kernel applies the published coefficients (scores averaged over
# firms; capital ratios summed across the balance sheet).
# ======================================================================================

_CR3_BIND = {
    "altman_z_double_prime": ["x1", "x2", "x3", "x4"],
    "springate_score": ["wc_ta", "ebit_ta", "ebt_cl", "sales_ta"],
    "zmijewski_score": ["roa", "tl_ta", "ca_cl"],
    "capital_adequacy_ratio": ["capital", "rwa"],
    "tier1_leverage_ratio": ["tier1_capital", "total_exposure"],
    "provision_coverage_ratio": ["provisions", "npl"],
    "cds_implied_hazard": ["spread", "recovery"],
}

for _mid, _tags in _CR3_BIND.items():
    register(_mid, family="credit", required_tags=list(_tags),
             set_maturity="reviewed")(_biz_recipe(getattr(N, _mid), _tags))


# ======================================================================================
# Pack EFF - effect sizes & association measures. Categorical association binds (group,
# outcome) as strings; ANOVA effect sizes bind (group string, value).
# ======================================================================================

def _assoc_recipe(fn):
    def recipe(cols, binding, convention=None):
        g, o = cols[binding["group"]], cols[binding["outcome"]]
        return _result(fn(g, o), {"n": len(g)})
    return recipe


for _mid in ("tschuprow_t", "pearson_contingency_coefficient", "cohens_w"):
    register(_mid, family="stats", required_tags=["group", "outcome"],
             string_tags=["group", "outcome"], set_maturity="reviewed")(_assoc_recipe(getattr(N, _mid)))


def _anova_eff_recipe(fn):
    def recipe(cols, binding, convention=None):
        groups, values = cols[binding["group"]], cols[binding["value"]]
        return _result(fn(groups, values), {"n": len(values)})
    return recipe


for _mid in ("omega_squared", "epsilon_squared", "cohens_f"):
    register(_mid, family="stats", required_tags=["group", "value"], string_tags=["group"],
             set_maturity="reviewed")(_anova_eff_recipe(getattr(N, _mid)))


# ======================================================================================
# Pack MS - market-microstructure / execution depth. Spread estimators bind OHLC columns;
# the signed realized-spread / price-impact metrics take a side=buy|sell convention.
# ======================================================================================

@register("corwin_schultz_spread", family="liquidity", required_tags=["high", "low"],
          set_maturity="reviewed")
def corwin_schultz_spread(cols, binding, convention=None):
    h, l = cols[binding["high"]], cols[binding["low"]]
    return _result(N.corwin_schultz_spread(h, l), {"n": len(h)})


@register("abdi_ranaldo_spread", family="liquidity", required_tags=["close", "high", "low"],
          set_maturity="reviewed")
def abdi_ranaldo_spread(cols, binding, convention=None):
    c, h, l = cols[binding["close"]], cols[binding["high"]], cols[binding["low"]]
    return _result(N.abdi_ranaldo_spread(c, h, l), {"n": len(c)})


@register("order_flow_imbalance", family="liquidity", required_tags=["buy_volume", "sell_volume"],
          set_maturity="reviewed")
def order_flow_imbalance(cols, binding, convention=None):
    b, s = cols[binding["buy_volume"]], cols[binding["sell_volume"]]
    return _result(N.order_flow_imbalance(b, s), {"n": len(b)})


@register("share_turnover", family="liquidity", required_tags=["volume", "shares_outstanding"],
          set_maturity="reviewed")
def share_turnover(cols, binding, convention=None):
    v, s = cols[binding["volume"]], cols[binding["shares_outstanding"]]
    return _result(N.share_turnover(v, s), {"n": len(v)})


@register("realized_spread_bps", family="execution",
          required_tags=["exec_price", "mid_future_price", "quantity"],
          set_maturity="reviewed", accepted_conventions=["side=buy", "side=sell"])
def realized_spread_bps(cols, binding, convention=None):
    e, m, q = cols[binding["exec_price"]], cols[binding["mid_future_price"]], cols[binding["quantity"]]
    side = _tca_side(convention)
    return _result(N.realized_spread_bps(e, m, q, side), {"n": len(e), "side": "sell" if side < 0 else "buy"})


@register("price_impact_bps", family="execution",
          required_tags=["mid_price", "mid_future_price", "quantity"],
          set_maturity="reviewed", accepted_conventions=["side=buy", "side=sell"])
def price_impact_bps(cols, binding, convention=None):
    m0, m1, q = cols[binding["mid_price"]], cols[binding["mid_future_price"]], cols[binding["quantity"]]
    side = _tca_side(convention)
    return _result(N.price_impact_bps(m0, m1, q, side), {"n": len(m0), "side": "sell" if side < 0 else "buy"})


# ======================================================================================
# Pack SK - sklearn-validated classification / regression depth. Agreement / accuracy /
# overlap metrics bind (prediction, label); d2_pinball binds (prediction, target) + an alpha;
# d2_log_loss binds (prob, label).
# ======================================================================================

def _pl_recipe(fn):
    def recipe(cols, binding, convention=None):
        p, l = cols[binding["prediction"]], cols[binding["label"]]
        return _result(fn(p, l), {"n": len(l)})
    return recipe


for _mid in ("cohen_kappa_linear", "cohen_kappa_quadratic", "balanced_accuracy_adjusted",
             "jaccard_macro"):
    register(_mid, family="classification", required_tags=["prediction", "label"],
             set_maturity="reviewed")(_pl_recipe(getattr(N, _mid)))


@register("d2_pinball_score", family="regression", required_tags=["prediction", "target"],
          set_maturity="reviewed", accepted_conventions=["alpha=<float>"])
def d2_pinball_score(cols, binding, convention=None):
    p, t = cols[binding["prediction"]], cols[binding["target"]]
    alpha = _conv_float(convention, "alpha", 0.5)
    return _result(N.d2_pinball_score(p, t, alpha), {"n": len(t), "alpha": alpha})


@register("d2_log_loss_score", family="classification", required_tags=["prob", "label"],
          set_maturity="reviewed")
def d2_log_loss_score(cols, binding, convention=None):
    p, l = cols[binding["prob"]], cols[binding["label"]]
    return _result(N.d2_log_loss_score(p, l), {"n": len(l)})


# ======================================================================================
# Pack CF - corporate finance & capital-budgeting depth. The capital-budgeting metrics bind
# a cashflow column (rate conventions); the working-capital / coverage ratios bind line items.
# ======================================================================================

def _conv_kv(convention):
    """Parse 'finance=0.1,reinvest=0.12' (or ';'-separated) -> {key: float}."""
    out = {}
    for part in _conv_str(convention).replace(";", ",").split(","):
        if "=" in part:
            k, _, v = part.partition("=")
            try:
                out[k.strip()] = float(v.strip())
            except ValueError:
                pass
    return out


@register("modified_irr", family="finance", required_tags=["cashflow"], set_maturity="reviewed",
          accepted_conventions=["finance=<frac>,reinvest=<frac>"])
def modified_irr(cols, binding, convention=None):
    cf = cols[binding["cashflow"]]
    kv = _conv_kv(convention)
    fr = kv.get("finance", 0.1)
    rr = kv.get("reinvest", 0.1)
    return _result(N.modified_irr(cf, fr, rr), {"n": len(cf), "finance_rate": fr, "reinvest_rate": rr})


@register("profitability_index", family="finance", required_tags=["cashflow"], set_maturity="reviewed",
          accepted_conventions=["rate=<frac>"])
def profitability_index(cols, binding, convention=None):
    cf = cols[binding["cashflow"]]
    rate = _conv_float(convention, "rate", float("nan"))
    return _result(N.profitability_index(cf, rate), {"n": len(cf), "rate": rate})


@register("equivalent_annual_annuity", family="finance", required_tags=["cashflow"],
          set_maturity="reviewed", accepted_conventions=["rate=<frac>"])
def equivalent_annual_annuity(cols, binding, convention=None):
    cf = cols[binding["cashflow"]]
    rate = _conv_float(convention, "rate", float("nan"))
    return _result(N.equivalent_annual_annuity(cf, rate), {"n": len(cf), "rate": rate})


_CF_BIND = {
    "days_inventory_outstanding": ["inventory", "cogs"],
    "days_payable_outstanding": ["payables", "cogs"],
    "cash_conversion_cycle": ["receivables", "inventory", "payables", "revenue", "cogs"],
    "fixed_charge_coverage": ["ebit", "lease", "interest"],
}

for _mid, _tags in _CF_BIND.items():
    register(_mid, family="finance", required_tags=list(_tags),
             set_maturity="reviewed")(_biz_recipe(getattr(N, _mid), _tags))


# ======================================================================================
# Pack TSF - time-series / signal-shape features over a single ordered value column.
# ======================================================================================

for _mid in ("zero_crossing_rate", "hjorth_mobility", "hjorth_complexity",
             "turning_point_rate", "rms_successive_differences", "mean_absolute_change"):
    register(_mid, family="stats", required_tags=["value"],
             set_maturity="reviewed")(_mom_recipe(getattr(N, _mid)))


# ======================================================================================
# Pack REL - reliability & operations engineering. Two-column reliability / quality ratios;
# rolled throughput yield is a product over a single per-step yield column.
# ======================================================================================

_REL_BIND = {
    "failure_rate": ["failures", "operating_time"],
    "mean_time_to_repair": ["downtime", "repairs"],
    "mean_time_to_failure": ["uptime", "failures"],
    "defect_density": ["defects", "size"],
    "dpmo": ["defects", "opportunities"],
    "first_pass_yield": ["passed", "total"],
}

for _mid, _tags in _REL_BIND.items():
    register(_mid, family="engineering", required_tags=list(_tags),
             set_maturity="reviewed")(_biz_recipe(getattr(N, _mid), _tags))


@register("rolled_throughput_yield", family="engineering", required_tags=["yield_step"],
          set_maturity="reviewed")
def rolled_throughput_yield(cols, binding, convention=None):
    ys = cols[binding["yield_step"]]
    return _result(N.rolled_throughput_yield(ys), {"n": len(ys)})


# ======================================================================================
# Pack RC2 - robust correlation & regression-slope estimators over paired (x, y) columns.
# ======================================================================================

def _xy_recipe(fn):
    def recipe(cols, binding, convention=None):
        x, y = cols[binding["x"]], cols[binding["y"]]
        return _result(fn(x, y), {"n": len(x)})
    return recipe


for _mid in ("siegel_slope", "linregress_slope_stderr", "linregress_intercept_stderr",
             "chatterjee_xi", "blomqvist_beta", "gaussian_rank_correlation"):
    register(_mid, family="stats", required_tags=["x", "y"],
             set_maturity="reviewed")(_xy_recipe(getattr(N, _mid)))


# ======================================================================================
# Pack VD - vector distance & similarity between two equal-length columns. Most are
# parameter-free; minkowski takes an order p.
# ======================================================================================

for _mid in ("euclidean_distance", "squared_euclidean_distance", "manhattan_distance",
             "chebyshev_distance", "cosine_distance", "braycurtis_distance",
             "canberra_distance", "correlation_distance"):
    register(_mid, family="analytics", required_tags=["x", "y"],
             set_maturity="reviewed")(_xy_recipe(getattr(N, _mid)))


@register("minkowski_distance", family="analytics", required_tags=["x", "y"],
          set_maturity="reviewed", accepted_conventions=["p=<float>"])
def minkowski_distance(cols, binding, convention=None):
    x, y = cols[binding["x"]], cols[binding["y"]]
    p = _conv_float(convention, "p", 2.0)
    return _result(N.minkowski_distance(x, y, p), {"n": len(x), "p": p})
