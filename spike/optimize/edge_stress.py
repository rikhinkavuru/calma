#!/usr/bin/env python
"""optimize.edge_stress — numerical edge cases: degenerate inputs must FAIL CLOSED, valid extremes must work.

The places a recompute oracle most easily (a) false-CONFIRMS a meaningless number or (b) chokes on a valid
but extreme input. Two assertions: a degenerate/invalid case must NEVER be CONFIRMED; a valid extreme must be
CONFIRMED (the oracle stays correct at scale / tiny magnitude). Run in the spike venv.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from core import diff as D  # noqa: E402
from core import verdict as VD  # noqa: E402


def _call(metric, result, inputs, kwargs=None):
    return {"metric": metric, "result": result, "inputs": inputs, "kwargs": kwargs or {},
            "user_site": True, "captured_full": True, "n": len(next(iter(inputs.values()))),
            "seq": 0, "sink": "sklearn.metrics." + metric, "site": "r.py:1"}


def _verdict(metric, value, inputs, result, kwargs=None):
    call = _call(metric, result, inputs, kwargs)
    return D.diff_claim({"metric": metric, "value": value}, [[call], [dict(call)]])["verdict"]


def cases():
    """[(label, expect_confirmed: bool, verdict)]."""
    out = []

    # --- degenerate / invalid → must NOT confirm ----------------------------------------------------
    # Sharpe on (near-)constant returns: variance ~0 → ratio explodes → degenerate, must not confirm.
    rets = [0.001] * 250
    out.append(("sharpe_zero_var", False, _verdict("sharpe", "9999", {"returns": rets}, 9999.0)))
    # R² with a constant y_true → undefined → degenerate.
    out.append(("r2_constant_ytrue", False,
                _verdict("r2", "1.0", {"y_true": [5.0] * 50, "y_pred": [5.0 + 0.01 * i for i in range(50)]}, 1.0)))
    # ROC-AUC with all-equal scores → AUC is 0.5 by ties; a claimed 0.95 must be REFUTED, never confirmed.
    yt = [0, 1] * 50
    out.append(("auc_all_equal_scores", False,
                _verdict("roc_auc", "0.95", {"y_true": yt, "y_score": [0.5] * 100}, 0.95)))
    # single-class y_true → accuracy vacuous.
    out.append(("accuracy_single_class", False,
                _verdict("accuracy", "1.0", {"y_true": [1] * 80, "y_pred": [1] * 80}, 1.0)))
    # NaN in a regression input → degenerate recompute.
    out.append(("rmse_nan_input", False,
                _verdict("rmse", "2.0", {"y_true": [1.0, 2.0, float("nan"), 4.0], "y_pred": [1.0, 2.0, 3.0, 4.0]}, 2.0)))

    # --- valid but EXTREME → must still CONFIRM (oracle correct at scale / tiny magnitude) -----------
    rng = np.random.default_rng(3)
    # huge magnitude regression (~1e9)
    yt = (rng.normal(0, 1, 200) * 1e9)
    yp = yt + rng.normal(0, 1, 200) * 1e6
    rmse = float(np.sqrt(np.mean((yt - yp) ** 2)))
    out.append(("rmse_1e9_scale", True,
                _verdict("rmse", "%.10g" % rmse, {"y_true": yt.tolist(), "y_pred": yp.tolist()}, rmse)))
    # tiny magnitude mean (~1e-8)
    vals = (rng.normal(0, 1, 100) * 1e-8).tolist()
    out.append(("mean_1e-8_scale", True,
                _verdict("mean", "%.10g" % (sum(vals) / len(vals)), {"values": vals}, sum(vals) / len(vals))))
    # extreme class imbalance (1% positives), accuracy well above the 99% majority is impossible, so use a
    # genuinely-good balanced case just above baseline: 99% majority, predict-all-majority = 0.99 = baseline
    # → trivial → must NOT confirm.
    ytb = [0] * 99 + [1]
    out.append(("accuracy_at_99pct_baseline", False, _verdict("accuracy", "0.99", {"y_true": ytb, "y_pred": [0] * 100}, 0.99)))
    # perfect, 2-class, genuine signal → reproduces → CONFIRMED (perfect is suspicious but not invalid here)
    yt2 = [0, 1] * 40
    out.append(("accuracy_perfect_2class", True, _verdict("accuracy", "1.0", {"y_true": yt2, "y_pred": list(yt2)}, 1.0)))
    # mae with a huge outlier (valid) → recompute correct
    yt = [1.0, 2.0, 3.0, 1e7]
    yp = [1.0, 2.0, 3.0, 0.0]
    mae = sum(abs(a - b) for a, b in zip(yt, yp)) / 4
    out.append(("mae_huge_outlier", True, _verdict("mae", "%.10g" % mae, {"y_true": yt, "y_pred": yp}, mae)))
    return out


def main():
    rows = cases()
    fc = [(lbl, v) for lbl, exp, v in rows if not exp and v == VD.CONFIRMED]   # degenerate confirmed = breach
    miss = [(lbl, v) for lbl, exp, v in rows if exp and v != VD.CONFIRMED]     # valid extreme not confirmed
    with open(os.path.join(HERE, "edge_metrics.json"), "w") as fh:
        json.dump({"rows": [{"label": lbl, "expect_confirmed": e, "verdict": v} for lbl, e, v in rows],
                   "false_confirms": fc, "valid_misses": miss}, fh, indent=2)
    print("=== EDGE-NUMERIC stress (degenerate must fail closed; valid extremes must confirm) ===")
    for lbl, exp, v in rows:
        ok = (v == VD.CONFIRMED) == exp
        print("  %-26s expect=%-9s → %-15s %s" % (lbl, "CONFIRM" if exp else "fail-closed", v, "" if ok else "‼️"))
    print("\nFALSE-CONFIRMS on degenerate inputs:", fc or "none")
    print("valid extremes not confirmed:", miss or "none")
    return 1 if (fc or miss) else 0


if __name__ == "__main__":
    sys.exit(main())
