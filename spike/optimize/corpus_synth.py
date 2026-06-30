#!/usr/bin/env python
"""optimize.corpus_synth — the HARDER corpus: full confusion across EVERY catalog metric.

The easy corpus only stressed accuracy/AUC/F1 on two clean fixtures, so the metrics read "1.0" partly
because the test was easy. This builds captures for ALL catalog metrics (binary + multiclass classification,
every averaging mode, regression, reductions, finance) with sklearn/scipy/numpy ground truth, and runs the
full confusion per metric:
    honest        claim == true value          → expect CONFIRMED   (false-refute / false-invalidate if not)
    misreport     claim perturbed              → expect REFUTED      (FALSE-CONFIRM if CONFIRMED)
    wrong_formula produced perturbed, inputs honest → expect INVALIDATED (FALSE-CONFIRM if CONFIRMED)
Then the base-rate-mixed precision (#7): of all CONFIRMED, fraction truly honest; of all REFUTED, fraction
truly misreported. Any scenario whose verdict != expected is a REAL gap on a metric the easy corpus hid.
Run in the spike venv.
"""
from __future__ import annotations

import json
import os
import statistics
import sys

import numpy as np
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, brier_score_loss, cohen_kappa_score,
                             f1_score, matthews_corrcoef, mean_absolute_error, mean_squared_error,
                             precision_score, r2_score, recall_score, roc_auc_score)

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from core import diff as D  # noqa: E402
from core import verdict as VD  # noqa: E402

RATE = {"accuracy", "balanced_accuracy", "roc_auc", "f1", "precision", "recall"}


def _call(metric, result, inputs, kwargs=None):
    return {"metric": metric, "result": float(result), "inputs": inputs, "kwargs": kwargs or {},
            "user_site": True, "captured_full": True, "n": len(next(iter(inputs.values()))),
            "seq": 0, "sink": "sklearn.metrics." + metric, "site": "r.py:1"}


def scenarios():
    """[(label, metric, inputs, kwargs, true_value)] across all catalog metrics, clear-signal (valid) inputs."""
    rng = np.random.default_rng(11)
    S = []
    # --- binary classification, ~85% accuracy (clear signal; above every trivial baseline) ----------
    yt = rng.integers(0, 2, 300)
    yp = yt.copy()
    yp[rng.random(300) < 0.15] ^= 1
    db = {"y_true": yt.tolist(), "y_pred": yp.tolist()}
    S += [("accuracy_bin", "accuracy", db, {}, accuracy_score(yt, yp)),
          ("f1_bin", "f1", db, {}, f1_score(yt, yp)),
          ("precision_bin", "precision", db, {}, precision_score(yt, yp)),
          ("recall_bin", "recall", db, {}, recall_score(yt, yp)),
          ("mcc_bin", "mcc", db, {}, matthews_corrcoef(yt, yp)),
          ("kappa_bin", "cohen_kappa", db, {}, cohen_kappa_score(yt, yp))]
    ys = np.clip(yt * 0.6 + rng.normal(0, 0.3, 300) + 0.2, 0, 1)
    S.append(("roc_auc", "roc_auc", {"y_true": yt.tolist(), "y_score": ys.tolist()}, {}, roc_auc_score(yt, ys)))
    S.append(("brier", "brier", {"y_true": yt.tolist(), "y_score": ys.tolist()}, {}, brier_score_loss(yt, ys)))
    # --- multiclass (4 classes), ~80% accuracy ------------------------------------------------------
    ytm = rng.integers(0, 4, 300)
    ypm = ytm.copy()
    fm = rng.random(300) < 0.2
    ypm[fm] = (ypm[fm] + 1) % 4
    dm = {"y_true": ytm.tolist(), "y_pred": ypm.tolist()}
    S.append(("accuracy_mc", "accuracy", dm, {}, accuracy_score(ytm, ypm)))
    S.append(("balanced_acc_mc", "balanced_accuracy", dm, {}, balanced_accuracy_score(ytm, ypm)))
    S.append(("mcc_mc", "mcc", dm, {}, matthews_corrcoef(ytm, ypm)))
    S.append(("kappa_mc", "cohen_kappa", dm, {}, cohen_kappa_score(ytm, ypm)))
    for avg in ("macro", "micro", "weighted"):
        S.append(("f1_%s" % avg, "f1", dm, {"average": avg}, f1_score(ytm, ypm, average=avg)))
        S.append(("precision_%s" % avg, "precision", dm, {"average": avg},
                  precision_score(ytm, ypm, average=avg, zero_division=0)))
        S.append(("recall_%s" % avg, "recall", dm, {"average": avg},
                  recall_score(ytm, ypm, average=avg, zero_division=0)))
    # --- regression ---------------------------------------------------------------------------------
    ytr = rng.normal(0, 10, 200)
    ypr = ytr + rng.normal(0, 3, 200)
    dr = {"y_true": ytr.tolist(), "y_pred": ypr.tolist()}
    S += [("rmse", "rmse", dr, {}, mean_squared_error(ytr, ypr) ** 0.5),
          ("mae", "mae", dr, {}, mean_absolute_error(ytr, ypr)),
          ("mse", "mse", dr, {}, mean_squared_error(ytr, ypr)),
          ("r2", "r2", dr, {}, r2_score(ytr, ypr))]
    # --- reductions + finance -----------------------------------------------------------------------
    vals = rng.normal(5, 2, 100).tolist()
    S += [("mean", "mean", {"values": vals}, {}, float(np.mean(vals))),
          ("sum", "sum", {"values": vals}, {}, float(np.sum(vals)))]
    rets = rng.normal(0.001, 0.02, 250).tolist()
    S.append(("sharpe", "sharpe", {"returns": rets}, {},
              (sum(rets) / len(rets)) / statistics.stdev(rets)))
    return S


def _verdict(metric, value, runs):
    return D.diff_claim({"metric": metric, "value": value}, runs)["verdict"]


def _clamp(metric, v):
    return min(max(v, 0.0), 1.0) if metric in RATE else v


def measure():
    rows = []
    for label, metric, inputs, kwargs, true in scenarios():
        call = _call(metric, true, inputs, kwargs)
        runs = [[call], [dict(call)]]
        # honest (high precision so a rounding boundary never causes a spurious REFUTE)
        v_h = _verdict(metric, "%.10g" % true, runs)
        # misreport: +5% (clamped for rate metrics), formatted at FIXED precision so the perturbation
        # survives — %g would strip 0.9 to "0.9", a faithful 1-decimal rounding of e.g. 0.857 (not a misreport)
        wrong = _clamp(metric, true * 1.05) if abs(true) > 1e-9 else 0.05
        v_m = _verdict(metric, "%.6f" % wrong, runs)
        # wrong-formula: the PRODUCED value is +5% off but inputs are honest → recompute disagrees
        wf_call = _call(metric, _clamp(metric, true * 1.05) if abs(true) > 1e-9 else 0.05, inputs, kwargs)
        v_wf = _verdict(metric, "%.6f" % wf_call["result"], [[wf_call], [dict(wf_call)]])
        rows.append({"label": label, "metric": metric, "true": round(float(true), 6),
                     "honest": v_h, "misreport": v_m, "wrong_formula": v_wf,
                     "honest_ok": v_h == VD.CONFIRMED, "misreport_ok": v_m == VD.REFUTED,
                     "wf_ok": v_wf == VD.INVALIDATED})
    return rows


def score(rows):
    n = len(rows)
    fc = [r for r in rows if r["misreport"] == VD.CONFIRMED or r["wrong_formula"] == VD.CONFIRMED]
    fr = [r for r in rows if r["honest"] == VD.REFUTED]
    fi = [r for r in rows if r["honest"] == VD.INVALIDATED]
    # base-rate-mixed precision (#7): pool one honest + one misreport + one wrong-formula per scenario
    confirmed_honest = sum(r["honest"] == VD.CONFIRMED for r in rows)
    confirmed_total = sum((r["honest"] == VD.CONFIRMED) + (r["misreport"] == VD.CONFIRMED)
                          + (r["wrong_formula"] == VD.CONFIRMED) for r in rows)
    refuted_mis = sum(r["misreport"] == VD.REFUTED for r in rows)
    refuted_total = sum((r["honest"] == VD.REFUTED) + (r["misreport"] == VD.REFUTED)
                        + (r["wrong_formula"] == VD.REFUTED) for r in rows)
    return {
        "n_scenarios": n,
        "honest_confirm_rate": round(sum(r["honest_ok"] for r in rows) / n, 4),
        "misreport_catch_rate": round(sum(r["misreport_ok"] for r in rows) / n, 4),
        "wrong_formula_catch_rate": round(sum(r["wf_ok"] for r in rows) / n, 4),
        "false_confirm_rate": round(len(fc) / (2 * n), 4),       # over the 2n wrong claims
        "false_refute_rate": round(len(fr) / n, 4),
        "false_invalidate_rate": round(len(fi) / n, 4),
        "confirm_precision": round(confirmed_honest / confirmed_total, 4) if confirmed_total else None,
        "refute_precision": round(refuted_mis / refuted_total, 4) if refuted_total else None,
        "gaps": [r for r in rows if not (r["honest_ok"] and r["misreport_ok"] and r["wf_ok"])],
    }


def main():
    rows = measure()
    m = score(rows)
    with open(os.path.join(HERE, "corpus_synth_metrics.json"), "w") as fh:
        json.dump({"summary": {k: v for k, v in m.items() if k != "gaps"}, "rows": rows}, fh, indent=2)
    print("=== HARDER CORPUS — full confusion across %d metric-scenarios ===" % m["n_scenarios"])
    print("honest→CONFIRMED:     %s   [target 1.0]" % m["honest_confirm_rate"])
    print("misreport→REFUTED:    %s   [target 1.0]" % m["misreport_catch_rate"])
    print("wrong-formula→INVALID:%s   [target 1.0]" % m["wrong_formula_catch_rate"])
    print("FALSE-CONFIRM rate:   %s   [target 0]" % m["false_confirm_rate"])
    print("false-refute rate:    %s   [target 0]" % m["false_refute_rate"])
    print("false-invalidate rate:%s   [target 0]" % m["false_invalidate_rate"])
    print("confirm-precision: %s   refute-precision: %s" % (m["confirm_precision"], m["refute_precision"]))
    if m["gaps"]:
        print("\n‼️  GAPS (a metric the easy corpus hid):")
        for g in m["gaps"]:
            print("   %-16s h=%s m=%s wf=%s" % (g["label"], g["honest"], g["misreport"], g["wrong_formula"]))
    else:
        print("\nNo gaps — every catalog metric passes the full confusion.")
    return 1 if m["gaps"] else 0


if __name__ == "__main__":
    sys.exit(main())
