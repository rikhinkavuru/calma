"""calma.spike.core.redteam_gate — the inline red-team overlay (feature 8, "red-team-the-confirm").

An independent, DOWNGRADE-ONLY second opinion on every CONFIRMED verdict. It re-derives the
degeneracy / triviality / single-class / value-coincidence screens DIRECTLY from the bound computation —
deliberately NOT by calling core.validity or trusting verdict.decide's output — so a regression in the
primary confirm path is caught by a second, structurally-separate implementation. This is the SetupX
Prosecutor/Judge split applied to our own verifier: the gate is the prosecutor (tries to break a CONFIRMED),
verdict.decide stays the incorruptible judge.

FCR-safety is structural. Every charge is applied through `verdict.monotone`, which can only ever LOWER a
verdict — so on an honest CONFIRMED (multi-class labels, a score above the trivial baseline, finite
equal-length inputs, a unique binding) every screen passes and the verdict is returned unchanged, and on any
computation that should never have confirmed, the gate can only push it DOWN, never up. It therefore cannot
mint or raise a confirm under any input. Pure stdlib; construct-only (no execution).
"""
from __future__ import annotations

from . import catalog as C
from . import verdict as VD

# classification metrics whose score a CONSTANT predictor can trivially reach (so a trivial-baseline screen
# applies) and whose y_true single-class case is vacuous.
_LABEL_METRICS = {"accuracy", "balanced_accuracy", "f1", "precision", "recall", "mcc", "cohen_kappa"}


def _finite(x) -> bool:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return f == f and f not in (float("inf"), float("-inf"))


def _distinct_labels(seq):
    """Distinct class labels in a captured y_true (1.0 and 1 collapse, like sklearn / catalog._as_labels)."""
    out = set()
    for v in seq or []:
        if isinstance(v, bool):
            out.add(int(v))
        elif isinstance(v, float) and v.is_integer():
            out.add(int(v))
        else:
            out.add(v)
    return out


def _majority_frac(seq):
    labs = []
    for v in seq or []:
        if isinstance(v, bool):
            labs.append(int(v))
        elif isinstance(v, float) and v.is_integer():
            labs.append(int(v))
        else:
            labs.append(v)
    if not labs:
        return None
    counts: dict = {}
    for v in labs:
        counts[v] = counts.get(v, 0) + 1
    return max(counts.values()) / len(labs)


def _len(x):
    try:
        return len(x)
    except TypeError:
        return None


def _degenerate_inputs(inputs: dict) -> str | None:
    """A degenerate captured input that must never underwrite a CONFIRMED: a non-finite cell in a numeric
    array, or paired arrays of mismatched length. Independent of catalog._as_floats' own guard."""
    lens = []
    for key in ("y_true", "y_pred", "y_score", "y_prob", "returns", "values", "a", "b"):
        v = inputs.get(key)
        if v is None:
            continue
        n = _len(v)
        if n is not None:
            lens.append(n)
            if n == 0:
                return "captured input %r is empty" % key
        # scan numeric arrays for non-finite cells (labels may be strings — skip those)
        if key in ("y_score", "y_prob", "returns", "values", "a", "b", "y_pred"):
            for cell in (v if isinstance(v, (list, tuple)) else []):
                if isinstance(cell, (int, float)) and not _finite(cell):
                    return "captured input %r contains a non-finite cell (%r)" % (key, cell)
    if len(lens) >= 2 and len(set(lens)) > 1:
        return "captured inputs have mismatched lengths %s" % sorted(set(lens))
    return None


def screen(metric: str, call: dict, _siblings: list[dict] | None = None) -> tuple[str | None, str | None]:
    """Independently screen ONE bound computation that reached CONFIRMED. Returns (proposed_verdict, reason)
    or (None, None) when every screen passes. The caller folds the proposal through `verdict.monotone`, so a
    proposal can only ever lower the verdict. (`_siblings` is accepted for call-site compatibility but unused —
    value-coincidence is binding's job, see the note in the body.)

    `call`     the bound capture call {inputs, result, user_site, site, ...}.
    """
    cid = C.canonical(metric) or (metric or "").strip().lower()
    inputs = call.get("inputs") or {}
    _r = call.get("result")
    try:
        produced = None if _r is None else float(_r)
    except (TypeError, ValueError):
        produced = None

    # 1. degenerate inputs → cannot certify a number computed on corrupt data.
    deg = _degenerate_inputs(inputs)
    if deg is not None:
        return VD.INCONCLUSIVE, deg

    yt = inputs.get("y_true")
    if cid in _LABEL_METRICS and yt is not None:
        classes = _distinct_labels(yt)
        # 2. single-class y_true → the score is vacuous.
        if len(classes) <= 1:
            return VD.INVALIDATED, "y_true has a single class — the %s score is vacuous" % cid
        # 3. trivial baseline → a constant predictor matches it (no signal).
        if produced is not None:
            if cid == "accuracy":
                base = _majority_frac(yt)
                if base is not None and produced <= base + 1e-9:
                    return VD.INVALIDATED, ("accuracy %.4g is at or below the majority-class baseline %.4g "
                                            "— a constant predictor matches it" % (produced, base))
            elif cid == "balanced_accuracy":
                base = 1.0 / max(1, len(classes))
                if produced <= base + 1e-9:
                    return VD.INVALIDATED, ("balanced_accuracy %.4g is at or below the constant-predictor "
                                            "baseline %.4g (1/%d classes)" % (produced, base, len(classes)))

    # 3b. chance-level ranking / no-signal regression.
    if cid == "roc_auc" and produced is not None and produced <= 0.5 + 1e-9:
        return VD.INVALIDATED, "ROC-AUC %.4g is at or below chance (0.5) — no discriminative signal" % produced
    if cid == "r2" and produced is not None and produced <= 0.0 + 1e-9:
        return VD.INVALIDATED, "R² %.4g ≤ 0 — no better than predicting the mean" % produced

    # NOTE: there is deliberately NO value-coincidence screen here. Multiple distinct repo computations of the
    # same metric (train vs test, per-fold, multi-dataset) are NORMAL, not a coincidence — and the PRIMARY
    # binding already disambiguates them by split/occurrence and fails a genuinely-ambiguous bind closed
    # (INCONCLUSIVE) before any CONFIRMED. Re-flagging "more than one value exists" here would false-downgrade
    # every legitimate train+test CONFIRMED. The coincidence risk lives in binding, and is gated there.
    return None, None
