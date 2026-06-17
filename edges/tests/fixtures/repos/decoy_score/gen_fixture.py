#!/usr/bin/env python3
"""Entrypoint for the decoy_score A2 fixture: (re-)emit out/preds.csv. Pure stdlib, deterministic so the
engine can re-run it and recompute. The lie a naive binder falls for: `score` is a LOGIT (values ~2..6,
outside [0,1]) while `p_hat` is the calibrated probability in [0,1] -- AUC needs the [0,1] column."""
import csv
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    out = os.path.join(HERE, "out")
    os.makedirs(out, exist_ok=True)
    rows = []
    for i in range(60):
        y = 1 if (i * 3) % 7 >= 3 else 0                 # deterministic ~57% ones
        # p_hat ranks the label well (AUC ~0.9); score is a shifted logit, always > 1 (a decoy)
        base = 0.80 if y else 0.25
        p = min(0.999, max(0.001, base + ((i % 5) - 2) * 0.03))
        logit = 2.0 + 4.0 * p                            # 2.0 .. 6.0 -- clearly outside [0,1]
        rows.append((i, round(logit, 4), round(p, 4), y))
    with open(os.path.join(out, "preds.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "score", "p_hat", "y"])
        for r in rows:
            w.writerow(r)


if __name__ == "__main__":
    main()
