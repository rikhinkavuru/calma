#!/usr/bin/env python3
"""Entrypoint for the nb_run A1-CLI fixture: re-emit the raw machine-readable artifacts the engine
recomputes from. Pure stdlib, fully deterministic (no randomness, no network): same source -> bit
-identical CSVs. This target mirrors targets/btc_like's data exactly, but adds report.ipynb -- a
notebook whose printed metrics are the CLAIM SOURCE -- so it exercises the full A1 CLI seam
(ingest -> route -> to_contract -> engine.verify -> reconcile) end to end:

  runs/oos/preds.csv   y_true,y_pred,score,logit_score   (a classification result)
  runs/oos/returns.csv strat_return                      (an OOS daily-return series)

The returns COMPOUND to roughly -32%, so report.ipynb's "+14,698%" total-return claim is REFUTED on
recompute. preds.csv carries y_pred matching y_true 90/100 (accuracy 0.90) and a score column that
perfectly ranks the labels (AUC 1.0), so the notebook's accuracy/auc claims reproduce.
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _preds_rows():
    rows = []
    for i in range(100):
        y_true = i % 2                                   # alternating 0/1 label
        y_pred = y_true if (i % 10 != 0) else (1 - y_true)   # 10 of 100 flipped -> accuracy 0.90
        score = 0.30 + 0.40 * y_true + (i % 5) * 0.001   # positives ~0.70, negatives ~0.30 -> AUC 1.0
        logit_score = (i - 50) / 10.0                    # -5.0 .. 4.9  (NOT in [0,1]: a decoy column)
        rows.append((y_true, y_pred, "%.4f" % score, "%.4f" % logit_score))
    return rows


def _return_series():
    # Deterministic daily returns that compound to ~ -0.32 over 252 bars. A small symmetric wobble
    # around a negative drift; the period-7 term sums to zero so the mean stays at the drift.
    rets = []
    for i in range(252):
        r = -0.0015 + ((i % 7) - 3) * 0.0020
        rets.append(r)
    return rets


def main():
    outdir = os.path.join(HERE, "runs", "oos")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "preds.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["y_true", "y_pred", "score", "logit_score"])
        for row in _preds_rows():
            w.writerow(row)
    with open(os.path.join(outdir, "returns.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["strat_return"])
        for r in _return_series():
            w.writerow([repr(r)])


if __name__ == "__main__":
    main()
