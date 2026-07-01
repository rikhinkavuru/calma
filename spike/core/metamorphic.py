"""calma.spike.core.metamorphic — feature 7 metamorphic verification.

When a metric has no independent recompute path, we can still test whether the repo's own callable HONOURS a
relation whose effect on the output is known analytically: permute the samples → accuracy unchanged; negate the
scores → AUC → 1−AUC; translate both regression vectors → RMSE unchanged; scale the returns → Sharpe unchanged.
These are EXACT invariances (not heuristics), so a violation is a hard fault: the reported formula is not the
metric it claims. It runs on the repo's OWN outputs (from capture.reinvoke's `.fuzz` emit), never the catalog,
so it is a genuine pseudo-oracle.

FCR-safety: DOWNGRADE-OR-HOLD only. A VIOLATED relation appends to `validity.invalidating` → INVALIDATED. A
SATISFIED relation NEVER yields CONFIRMED — metamorphic satisfaction is necessary, not sufficient (a wrong
formula can still be permutation-invariant), so the strongest a satisfied MR does is annotate the reason. This
preserves FCR=0 by construction: MRs can only fail a number closed, never open it.
"""
from __future__ import annotations

from . import catalog as C
from . import tolerance as T


def _eq(b, v):
    return T.close(b, v)


# metric -> [(transform tag, relation(base_out, variant_out) -> bool, human description)]. Only EXACT,
# well-established invariances are encoded; a relation absent here is simply not checked (fail-open on
# checking, never on the verdict). See the MDPI 2025 confusion-matrix invariance result + classic AUC/Pearson
# properties cited in the build plan.
_MR = {
    "accuracy": [("perm_samples", _eq, "sample-order invariance"),
                 ("perm_labels", _eq, "class-relabel invariance")],
    "balanced_accuracy": [("perm_samples", _eq, "sample-order invariance"),
                          ("perm_labels", _eq, "class-relabel invariance")],
    "f1": [("perm_samples", _eq, "sample-order invariance")],
    "precision": [("perm_samples", _eq, "sample-order invariance")],
    "recall": [("perm_samples", _eq, "sample-order invariance")],
    "mcc": [("perm_samples", _eq, "sample-order invariance")],
    "cohen_kappa": [("perm_samples", _eq, "sample-order invariance")],
    "roc_auc": [("perm_samples", _eq, "sample-order invariance"),
                ("neg_score", lambda b, v: T.close(1.0 - b, v), "score-negation → 1−AUC")],
    "correlation": [("perm_samples", _eq, "paired-order invariance"),
                    ("neg_second", lambda b, v: T.close(-b, v), "sign flip of one variable → −r"),
                    ("scale_pos", _eq, "positive-affine invariance")],
    "sharpe": [("perm_samples", _eq, "order invariance"),
               ("scale_pos", _eq, "positive-scale invariance")],
    "sortino": [("perm_samples", _eq, "order invariance"),
                ("scale_pos", _eq, "positive-scale invariance")],
    "mean": [("perm_samples", _eq, "order invariance"),
             ("scale_pos", lambda b, v: T.close(1.5 * b, v), "scale-equivariance ×1.5")],
    "sum": [("perm_samples", _eq, "order invariance"),
            ("scale_pos", lambda b, v: T.close(1.5 * b, v), "scale-equivariance ×1.5")],
    "total_sum": [("perm_samples", _eq, "order invariance"),
                  ("scale_pos", lambda b, v: T.close(1.5 * b, v), "scale-equivariance ×1.5")],
    "stdev": [("perm_samples", _eq, "order invariance"),
              ("scale_pos", lambda b, v: T.close(1.5 * b, v), "scale-equivariance ×1.5")],
    "variance": [("perm_samples", _eq, "order invariance"),
                 ("scale_pos", lambda b, v: T.close(2.25 * b, v), "scale-equivariance ×2.25")],
    "rmse": [("perm_samples", _eq, "order invariance"),
             ("translate", _eq, "translation invariance"),
             ("scale_pos", lambda b, v: T.close(1.5 * b, v), "scale-equivariance ×1.5")],
    "mae": [("perm_samples", _eq, "order invariance"),
            ("translate", _eq, "translation invariance"),
            ("scale_pos", lambda b, v: T.close(1.5 * b, v), "scale-equivariance ×1.5")],
    "r2": [("perm_samples", _eq, "order invariance"),
           ("translate", _eq, "translation invariance"),
           ("scale_pos", _eq, "positive-scale invariance")],
}


def _finite(x):
    return isinstance(x, (int, float)) and x == x and x not in (float("inf"), float("-inf"))


def check_record(metric: str, cases: list[dict]) -> dict:
    """Check every known EXACT metamorphic relation for `metric` across the fuzz `cases`. Returns
    {invalidating, checked, violations:[...], satisfied:[...]}. A relation is declared VIOLATED only when it
    fails on a MAJORITY of the (base, variant) pairs where both outputs are finite — robust against a lone
    degenerate synthetic input; a genuine metric honours an exact invariance on every non-degenerate case."""
    cid = C.canonical(metric) or (metric or "").strip().lower()
    rels = _MR.get(cid, [])
    if not rels:
        return {"invalidating": False, "checked": 0, "violations": [], "satisfied": []}
    per_tag: dict[str, list[int]] = {}    # tag -> [checked, violated]
    counterexample: dict[str, dict] = {}
    for case in cases or []:
        outs = case.get("outputs", {})
        base = outs.get("base")
        if not _finite(base):
            continue
        for tag, relate, _desc in rels:
            v = outs.get(tag)
            if not _finite(v):
                continue
            slot = per_tag.setdefault(tag, [0, 0])
            slot[0] += 1
            try:
                ok = relate(base, v)
            except Exception:  # noqa: BLE001
                ok = True
            if not ok:
                slot[1] += 1
                counterexample.setdefault(tag, {"tag": tag, "base": base, "variant": v})
    violations, satisfied, checked = [], [], 0
    desc_by_tag = {tag: desc for tag, _r, desc in rels}
    for tag, (n, bad) in per_tag.items():
        checked += n
        if n >= 3 and bad >= (n + 1) // 2:
            violations.append({"relation": desc_by_tag.get(tag, tag), "tag": tag,
                               "counterexample": counterexample.get(tag), "n": n, "violated": bad})
        elif n > 0 and bad == 0:
            satisfied.append(desc_by_tag.get(tag, tag))
    return {"invalidating": bool(violations), "checked": checked,
            "violations": violations, "satisfied": satisfied}
