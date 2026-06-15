#!/usr/bin/env python3
"""Leakage demo fixture: a held-out AUC that isn't held-out. 30% of the test rows are exact duplicates
of training rows, so the "held-out" set is contaminated. The number reproduces, but the held-out claim
is INVALIDATED (the contaminated rows are separable everywhere, so de-contaminating barely moves the AUC
- it survives correction yet the split was still contaminated). Deterministic; pure stdlib.
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    runs = os.path.join(HERE, "runs")
    os.makedirs(runs, exist_ok=True)
    # train: 100 separable rows (score == label, perfectly ordered)
    train = [[i, float(i % 2), i % 2] for i in range(100)]
    # test: 70 fresh separable rows + 30 EXACT duplicates of train rows (the contamination)
    test = [[1000 + i, float(i % 2), i % 2] for i in range(70)] + [train[i][:] for i in range(30)]
    for name, rows in (("train.csv", train), ("test.csv", test)):
        with open(os.path.join(runs, name), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "score", "y_true"])
            for r in rows:
                w.writerow(r)


if __name__ == "__main__":
    main()
