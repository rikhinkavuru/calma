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
