#!/usr/bin/env python3
"""Entrypoint for the decoy_score_2 A2 fixture: the SAME shape as decoy_score (a logit decoy `score`
outside [0,1] next to `p_hat` in [0,1] and the `y` label) but a different file name (out/scores.csv) and
column order. Used by the repo-shape library to test nearest-shape priors + one-shot drafting. Pure
stdlib, deterministic."""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    out = os.path.join(HERE, "out")
    os.makedirs(out, exist_ok=True)
    rows = []
    for i in range(60):
        y = 1 if (i * 5) % 9 >= 4 else 0
        base = 0.82 if y else 0.22
        p = min(0.999, max(0.001, base + ((i % 4) - 2) * 0.035))
        logit = 2.5 + 3.5 * p                            # 2.5 .. 6.0 -- outside [0,1]
        rows.append((i, y, round(p, 4), round(logit, 4)))   # reordered: id, y, p_hat, score
    with open(os.path.join(out, "scores.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "y", "p_hat", "score"])
        for r in rows:
            w.writerow(r)


if __name__ == "__main__":
    main()
