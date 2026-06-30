#!/usr/bin/env python
"""optimize.recompute_stress — does the trusted catalog match sklearn on the SUBTLE inputs? (#1/#8 dual.)

The catalog is the independent oracle: when the repo computes a metric honestly, our recompute must AGREE
(else we false-INVALIDATE an honest result — a false alarm; the dual of a false confirm). The 324 catalog
tests pin this on chosen vectors; this stresses the EDGE distributions where a from-scratch reimplementation
most easily diverges from sklearn:
  - multiclass macro / micro / weighted averaging (precision/recall/F1)
  - ROC-AUC with TIED scores (the average-rank path) and non-{0,1} labels
  - label-type coercion: string labels, float-vs-int labels, pos_label != 1
  - class imbalance, balanced_accuracy
  - regression with negatives (r2/rmse/mae), mse-vs-rmse

Method: build a capture whose `result` IS sklearn's value on the input, claim that value, and assert Calma
returns CONFIRMED. A RECOMPUTE divergence shows up as INVALIDATED with a "recompute … gives" reason — that's
a real oracle bug. (Validity-driven INVALIDATED, e.g. chance-level AUC, is distinguished by its reason and
is NOT counted as a bug.) Runs under the spike venv (needs sklearn for ground truth).
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, f1_score, mean_absolute_error,
                             mean_squared_error, precision_score, r2_score, recall_score, roc_auc_score)

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from core import diff as D  # noqa: E402
from core import verdict as VD  # noqa: E402


def _call(metric, result, inputs, kwargs=None):
    return {"metric": metric, "result": float(result), "inputs": inputs, "kwargs": kwargs or {},
            "user_site": True, "captured_full": True, "n": len(next(iter(inputs.values()))),
            "seq": 0, "sink": "sklearn.metrics." + metric, "site": "r.py:1"}


def _check(name, metric, result, inputs, kwargs=None):
    """Run one honest case through Calma; CONFIRMED = recompute agrees with sklearn."""
    call = _call(metric, result, inputs, kwargs)
    rec = D.diff_claim({"metric": metric, "value": "%.6f" % result}, [[call], [dict(call)]])
    v, reason = rec["verdict"], rec.get("reason", "")
    is_recompute_bug = (v == VD.INVALIDATED and "recompute" in reason)
    return {"name": name, "metric": metric, "sklearn": round(float(result), 6),
            "verdict": v, "reason": reason[:140], "recompute_bug": is_recompute_bug}


def cases():
    out = []
    rng = np.random.default_rng(7)

    # multiclass averaging (3 classes, imbalanced) — precision/recall/F1 macro/micro/weighted
    yt = np.array([0, 0, 0, 0, 1, 1, 1, 2, 2, 2])
    yp = np.array([0, 0, 1, 2, 1, 1, 0, 2, 2, 1])
    for avg in ("macro", "micro", "weighted"):
        out.append(("f1_%s" % avg, "f1", f1_score(yt, yp, average=avg),
                    {"y_true": yt.tolist(), "y_pred": yp.tolist()}, {"average": avg}))
        out.append(("precision_%s" % avg, "precision", precision_score(yt, yp, average=avg, zero_division=0),
                    {"y_true": yt.tolist(), "y_pred": yp.tolist()}, {"average": avg}))
        out.append(("recall_%s" % avg, "recall", recall_score(yt, yp, average=avg, zero_division=0),
                    {"y_true": yt.tolist(), "y_pred": yp.tolist()}, {"average": avg}))

    # binary precision/recall/F1 with pos_label = 0
    ytb = np.array([0, 0, 1, 1, 0, 1, 0, 1])
    ypb = np.array([0, 1, 1, 1, 0, 0, 0, 1])
    out.append(("f1_pos0", "f1", f1_score(ytb, ypb, pos_label=0),
                {"y_true": ytb.tolist(), "y_pred": ypb.tolist()}, {"pos_label": 0}))

    # accuracy with STRING labels
    yts = ["cat", "dog", "cat", "bird", "dog", "cat"]
    yps = ["cat", "dog", "bird", "bird", "cat", "cat"]
    out.append(("accuracy_strlabels", "accuracy", accuracy_score(yts, yps),
                {"y_true": yts, "y_pred": yps}, {}))

    # balanced accuracy, imbalanced
    yti = np.array([0, 0, 0, 0, 0, 0, 1, 1])
    ypi = np.array([0, 0, 0, 1, 0, 0, 1, 0])
    out.append(("balanced_accuracy", "balanced_accuracy", balanced_accuracy_score(yti, ypi),
                {"y_true": yti.tolist(), "y_pred": ypi.tolist()}, {}))

    # ROC-AUC with TIED scores + non-{0,1} positive label
    yta = np.array([0, 0, 1, 1, 1, 0, 1, 0])
    sca = np.array([0.2, 0.2, 0.8, 0.8, 0.5, 0.5, 0.5, 0.1])   # deliberate ties
    out.append(("roc_auc_ties", "roc_auc", roc_auc_score(yta, sca),
                {"y_true": yta.tolist(), "y_score": sca.tolist()}, {}))
    ytL = np.array([1, 1, 2, 2, 1, 2])                          # labels {1,2}, not {0,1}
    scL = np.array([0.1, 0.4, 0.35, 0.8, 0.3, 0.9])
    out.append(("roc_auc_labels12", "roc_auc", roc_auc_score(ytL, scL),
                {"y_true": ytL.tolist(), "y_score": scL.tolist()}, {}))

    # regression with negatives
    ytr = rng.normal(0, 5, 50)
    ypr = ytr + rng.normal(0, 1, 50)
    out.append(("r2_neg", "r2", r2_score(ytr, ypr), {"y_true": ytr.tolist(), "y_pred": ypr.tolist()}, {}))
    out.append(("mae_neg", "mae", mean_absolute_error(ytr, ypr),
                {"y_true": ytr.tolist(), "y_pred": ypr.tolist()}, {}))
    out.append(("rmse_neg", "rmse", mean_squared_error(ytr, ypr) ** 0.5,
                {"y_true": ytr.tolist(), "y_pred": ypr.tolist()}, {}))
    return out


def main():
    rows = [_check(*c) for c in cases()]
    bugs = [r for r in rows if r["recompute_bug"]]
    confirmed = [r for r in rows if r["verdict"] == VD.CONFIRMED]
    other = [r for r in rows if r["verdict"] != VD.CONFIRMED and not r["recompute_bug"]]
    with open(os.path.join(HERE, "recompute_stress.json"), "w") as fh:
        json.dump({"n": len(rows), "confirmed": len(confirmed), "recompute_bugs": bugs, "other": other,
                   "rows": rows}, fh, indent=2)
    print("=== RECOMPUTE-CORRECTNESS stress (catalog vs sklearn on subtle inputs) ===")
    print("cases=%d  CONFIRMED (recompute==sklearn)=%d  recompute-bugs=%d  other=%d"
          % (len(rows), len(confirmed), len(bugs), len(other)))
    if bugs:
        print("!! RECOMPUTE BUGS (oracle disagrees with sklearn — a false-invalidate / FCR-dual risk):")
        for r in bugs:
            print("   ", r["name"], "sklearn=%s" % r["sklearn"], "→", r["verdict"], "|", r["reason"])
    for r in other:
        print(".. non-CONFIRMED (check):", r["name"], "→", r["verdict"], "|", r["reason"])
    if not bugs and not other:
        print("all subtle cases CONFIRMED — the oracle matches sklearn across averaging/ties/coercion.")
    return 1 if bugs else 0


if __name__ == "__main__":
    sys.exit(main())
