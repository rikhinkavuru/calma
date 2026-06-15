#!/usr/bin/env python3
"""Deflated-Sharpe demo fixture (the CONFIRMED side of the direct recipe path): a genuinely strong daily
strategy (per-period Sharpe ~0.50) that was the best of a 1000-config search. Its per-period Sharpe is
WELL ABOVE the best-of-1000 no-skill benchmark (~0.33), so it SURVIVES the multiple-testing correction:
the recomputed Deflated Sharpe is ~0.99 and the producer's claimed 0.99 is CONFIRMED. Deterministic.
"""
import csv
import os

N = 252
MEAN = 0.0050     # ~0.50%/day
VOL = 0.010       # 1%/day -> realized per-period Sharpe ~0.50 (a strong, real edge)
HERE = os.path.dirname(os.path.abspath(__file__))


def _lcg(seed, n):
    x = seed
    out = []
    for _ in range(n):
        z = 0.0
        for _ in range(12):
            x = (1103515245 * x + 12345) & 0x7FFFFFFF
            z += x / 0x7FFFFFFF
        out.append(z - 6.0)
    return out


def main():
    eps = _lcg(20260616, N)
    m = sum(eps) / N
    sd = (sum((e - m) ** 2 for e in eps) / (N - 1)) ** 0.5
    rets = [MEAN + VOL * (e - m) / sd for e in eps]
    out = os.path.join(HERE, "runs", "returns.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["day", "strat_return"])
        for i, r in enumerate(rets):
            w.writerow([i, "%.10f" % r])


if __name__ == "__main__":
    main()
