"""calma.spike.core.validity — the always-on validity overlay (guide §2 static smells, §4.6).

These run on the *captured inputs* of a reproduced claim and catch results that re-run and recompute
perfectly yet are meaningless or invalid. The spike ships the high-signal, low-false-positive subset that
needs only the captured arrays (no extra data connection):

  - trivial-baseline: a classification score no better than a constant majority-class predictor; an AUC at
    or below chance (0.5); an R² at or below 0 (worse than predicting the mean). Each is *invalidating* —
    the headline carries no signal.
  - degenerate-distribution: y_true has a single class (accuracy/AUC are vacuous).

`invalidating` findings flip a would-be CONFIRMED to INVALIDATED. `advisory` findings attach as caveats.
Leakage / overfitting / era-leakage (which need train+test arrays or the trials matrix) are a deeper layer
carried from the existing infer_validity.py — noted here, ported when the spike graduates.
"""
from __future__ import annotations

from . import catalog as C
from . import tolerance as T


def check(metric: str, inputs: dict, produced: float) -> dict:
    """Return {"invalidating": [...], "advisory": [...]} for a reproduced (metric, inputs, value)."""
    cid = C.canonical(metric)
    inv: list[str] = []
    adv: list[str] = []
    if cid in ("accuracy", "balanced_accuracy", "f1", "precision", "recall"):
        yt = inputs.get("y_true")
        if yt:
            labs = C._as_labels(yt)
            classes = set(labs)
            if len(classes) <= 1:
                inv.append("y_true has a single class — the score is vacuous")
            else:
                counts = {c: labs.count(c) for c in classes}
                majority = max(counts.values()) / len(labs)
                if cid in ("accuracy", "balanced_accuracy") and produced is not None \
                        and produced <= majority + 1e-9:
                    inv.append("accuracy %.4g is at or below the majority-class baseline %.4g — a constant "
                               "predictor matches it (no signal)" % (produced, majority))
                elif cid in ("accuracy", "balanced_accuracy") and produced is not None \
                        and produced <= majority + 0.02:
                    adv.append("only %.2g above the %.4g majority-class baseline — thin margin"
                               % (produced - majority, majority))
    elif cid == "roc_auc":
        if produced is not None and produced <= 0.5 + 1e-9:
            inv.append("ROC-AUC %.4g is at or below chance (0.5) — no discriminative signal" % produced)
        elif produced is not None and produced <= 0.55:
            adv.append("ROC-AUC %.4g is barely above chance" % produced)
    elif cid == "r2":
        if produced is not None and produced <= 0.0 + 1e-9:
            inv.append("R² %.4g ≤ 0 — the model is no better than predicting the mean" % produced)
    return {"invalidating": inv, "advisory": adv}
