#!/usr/bin/env python3
"""Deflated-Sharpe demo fixture (the DIRECT recipe path): a weak daily strategy (per-period Sharpe ~0.2)
that was selected as the best of a 1000-config backtest search. The producer reports a near-certain
deflated Sharpe (DSR ~0.95, "the edge is real"). Deterministic (fixed LCG; pure stdlib).

calma recomputes the DSR with --metric deflated_sharpe over the declared trials=1000,var_sr=0.01 search:
the realized Sharpe sits BELOW the best-of-1000 no-skill benchmark, so the recomputed DSR is small and
the claimed 0.95 is REFUTED - directly, via the registered recipe (not the findings rail).
"""
import csv
import os

N = 252
MEAN = 0.0020     # ~0.2%/day
VOL = 0.010       # 1%/day -> realized per-period Sharpe ~0.2 (a weak edge)
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
    eps = _lcg(424242, N)
    # center to exactly the target per-period mean/vol so the realized Sharpe is stable
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
