#!/usr/bin/env python3
"""Overfitting demo fixture: a strategy with a healthy-looking annualised Sharpe that was selected as the
best of a 1000-config backtest search. Its per-period Sharpe (~0.20) sits below the best-of-1000 no-skill
benchmark (~0.33), so it does NOT survive the multiple-testing (Deflated Sharpe) correction. The number
reproduces, but - because the claim asserts the SELECTED / best-of-N edge - it is INVALIDATED.
Deterministic; pure stdlib.
"""
import csv
import os

N = 252
MEAN = 0.0020
VOL = 0.010
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
    eps = _lcg(7777, N)
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
