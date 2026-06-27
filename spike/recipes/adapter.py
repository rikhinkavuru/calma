"""calma.spike.recipes.adapter — expose the lifted 626-recipe catalog through the new (inputs, kwargs)
interface so recompute_any can use it.

The old recipes consume `(cols, binding, convention)` where `binding` maps each `required_tag` to a column
and `cols` holds the column arrays — that came from a hand-authored verify.yaml. The new pipeline captures
*canonical* inputs at the metric call site (y_true, y_pred, y_score, values, returns, …). This adapter
bridges the two: for a recipe's required_tags it finds the matching captured input, builds (cols, binding),
calls the recipe, and maps the result back. If any required tag can't be filled from the captured inputs,
it returns None so recompute_any falls through (to the synth/store flywheel) — never a wrong recompute.
"""
from __future__ import annotations

import os
import sys

_R = None  # lazily-imported recipes_legacy module


def _recipes():
    global _R
    if _R is None:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)   # so recipes_legacy's `import numeric` resolves to our copy
        import recipes_legacy  # noqa: PLC0415
        _R = recipes_legacy
    return _R


# which captured canonical input(s) can fill each recipe `required_tag` (first present wins)
_TAG_SOURCES = {
    "label": ["y_true", "target", "label", "actual", "y", "truth"],
    "target": ["y_true", "target", "actual", "y", "truth"],
    "prediction": ["y_pred", "prediction", "pred", "yhat", "y"],
    "score": ["y_score", "score", "y_prob", "prob", "proba", "scores"],
    "prob": ["y_score", "y_prob", "prob", "proba", "score"],
    "value": ["values", "value", "x", "data", "column"],
    "return": ["returns", "return", "values", "x"],
    "benchmark": ["benchmark", "bench", "market", "y2"],
    "before": ["before", "baseline", "control", "x"],
    "after": ["after", "candidate", "treatment", "y"],
    "weight": ["sample_weight", "weight", "weights"],
    "group": ["group", "era", "fold", "groups"],
    "x": ["x", "values", "y_true"],
    "y": ["y", "y_pred"],
}

# common library/claim names → recipe id, when they differ
_ALIASES = {
    "log_loss": "log_loss", "cross_entropy": "log_loss", "logloss": "log_loss",
    "brier_score_loss": "brier", "brier_score": "brier", "brier": "brier",
    "sortino_ratio": "sortino", "calmar_ratio": "calmar", "value_at_risk": "var",
    "ndcg_score": "ndcg", "average_precision_score": "average_precision",
    "explained_variance_score": "explained_variance", "median_absolute_error": "median_ae",
    "matthews_corrcoef": "mcc",
}


def _resolve_id(metric: str):
    R = _recipes()
    m = (metric or "").strip().lower()
    if R.get(m) is not None:
        return m
    aid = _ALIASES.get(m)
    if aid and R.get(aid) is not None:
        return aid
    return None


def _bind(required_tags, inputs):
    """Build (cols, binding) by filling each required tag from the captured inputs. None if any is missing."""
    cols, binding = {}, {}
    for tag in required_tags:
        src = next((k for k in _TAG_SOURCES.get(tag, [tag]) if inputs.get(k) is not None), None)
        if src is None:
            return None
        cols[tag] = inputs[src]
        binding[tag] = tag
    return cols, binding


def recompute_recipe(metric: str, inputs: dict, kwargs: dict | None = None):
    """Recompute via a lifted recipe. Returns a Result dict (with provenance 'recipe') or None if the metric
    is not a recipe or its inputs can't be bound from what we captured."""
    rid = _resolve_id(metric)
    if rid is None:
        return None
    R = _recipes()
    fn = R.get(rid)
    required = fn.manifest.get("required_tags", []) or []
    bound = _bind(required, inputs or {})
    if bound is None:
        return None
    cols, binding = bound
    convention = (kwargs or {}).get("convention")
    if convention is None and (kwargs or {}).get("periods_per_year"):
        convention = str(int(kwargs["periods_per_year"]))
    try:
        r = fn(cols, binding, convention)
    except Exception as e:  # noqa: BLE001 — a binding/kernel failure → fall through, never a wrong number
        return {"value": float("nan"), "degenerate": True, "note": "recipe %r raised: %s" % (rid, e),
                "terms": {}, "provenance": "recipe"}
    return {"value": float(r.get("value", float("nan"))), "degenerate": bool(r.get("degenerate")),
            "note": "recipe:%s" % rid, "terms": r.get("terms", {}), "provenance": "recipe", "formula": rid}


def count() -> int:
    R = _recipes()
    return len(R.list_ids() if hasattr(R, "list_ids") else R._REGISTRY)
