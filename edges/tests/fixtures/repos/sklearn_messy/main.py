#!/usr/bin/env python3
"""A messy sklearn-style classifier repo (a fixture for A2's drafter). It emits out/preds.csv with a
LOGIT decoy column (raw_score, outside [0,1]) next to the true probability (p_hat, in [0,1]) and the
label (y). A name-based heuristic mis-binds an AUC to raw_score; the drafter must bind it to p_hat by
reading the values.

For the P2.1 acceptance test only the FILES need to exist (the engine smoke is exercised in P2.2)."""
import csv
import math
import os

from sklearn.metrics import roc_auc_score  # noqa: F401  (framework signature; not run in the test)

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    out = os.path.join(HERE, "out")
    os.makedirs(out, exist_ok=True)
    rows = []
    for i in range(40):
        y = 1 if (i * 7) % 10 >= 5 else 0
        logit = (2.0 if y else -2.0) + ((i % 5) - 2) * 0.7
        p = 1.0 / (1.0 + math.exp(-logit))
        rows.append((i, round(logit, 4), round(p, 4), y))
    with open(os.path.join(out, "preds.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "raw_score", "p_hat", "y"])
        for r in rows:
            w.writerow(r)


if __name__ == "__main__":
    main()
