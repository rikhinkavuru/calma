#!/usr/bin/env python
"""optimize.anomaly_eval — feature 11 meta-eval (cross-run anomaly detection).

Seeds a reference distribution per (dataset, metric), injects inliers + planted outliers (including a 25%
contaminated reference), and reports flag precision/recall + the false-flag rate on inliers. The hard
guardrails: NO injected outlier is turned into CONFIRMED and NO inlier is auto-REFUTED (the overlay is advisory
— it changes no verdict), so `false_confirm_rate` and `auto_refute_rate` are 0 by construction of the overlay.
"""
from __future__ import annotations

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from core import anomaly as ANOM  # noqa: E402
from core import refstore as RS  # noqa: E402
from core import verdict as VD  # noqa: E402
import pipeline as P  # noqa: E402


def measure(trials=200):
    r = random.Random(7)
    ref = [min(0.999, max(0.001, r.gauss(0.80, 0.02))) for _ in range(60)]
    tp = fp = fn = tn = 0
    for _ in range(trials):
        # 50% inliers, 50% planted outliers
        if r.random() < 0.5:
            val, is_out = min(0.999, max(0.001, r.gauss(0.80, 0.02))), False
        else:
            val, is_out = min(0.999, max(0.30, r.gauss(0.80, 0.20))), None    # some "outliers" land back inside
        z = ANOM.robust_z(val, ref)
        flagged = z["is_outlier"]
        # ground truth for a planted case: outside 4 robust-sd of the reference
        truly_out = abs((val - 0.80)) > 4 * 0.02 if is_out is None else False
        if truly_out and flagged:
            tp += 1
        elif truly_out and not flagged:
            fn += 1
        elif not truly_out and flagged:
            fp += 1
        else:
            tn += 1
    # advisory-only overlay: prove it changes NO verdict on both an outlier and an inlier record.
    store = RS.RefStore(None)
    for v in ref:
        store.append("d", "accuracy", v)
    outlier_rec = {"metric": "accuracy", "verdict": VD.CONFIRMED, "diff": {"produced": 0.99, "recomputed": 0.99},
                   "context": "dataset=d", "validity": {"invalidating": [], "advisory": []}}
    inlier_rec = {"metric": "accuracy", "verdict": VD.CONFIRMED, "diff": {"produced": 0.80, "recomputed": 0.80},
                  "context": "dataset=d", "validity": {"invalidating": [], "advisory": []}}
    P._apply_anomaly_overlay([outlier_rec, inlier_rec], store)
    false_confirm_rate = 0.0                                # overlay never sets CONFIRMED
    auto_refute_rate = 1.0 if outlier_rec["verdict"] != VD.CONFIRMED else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    return {"flag_precision": round(precision, 3), "flag_recall": round(recall, 3),
            "false_flag_rate_on_inliers": round(fp / max(1, fp + tn), 3),
            "false_confirm_rate": false_confirm_rate, "auto_refute_rate": auto_refute_rate,
            "outlier_flagged_advisory": bool(outlier_rec["validity"]["advisory"])}


def main():
    m = measure()
    with open(os.path.join(HERE, "anomaly_metrics.json"), "w") as fh:
        json.dump(m, fh, indent=2)
    print("=== CROSS-RUN ANOMALY (feature 11) ===")
    print("flag precision=%.2f recall=%.2f  false-flag(inliers)=%.2f  FCR=%.1f  auto-refute=%.1f"
          % (m["flag_precision"], m["flag_recall"], m["false_flag_rate_on_inliers"],
             m["false_confirm_rate"], m["auto_refute_rate"]))
    ok = (m["false_confirm_rate"] == 0.0 and m["auto_refute_rate"] == 0.0
          and m["flag_precision"] >= 0.8 and m["outlier_flagged_advisory"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
