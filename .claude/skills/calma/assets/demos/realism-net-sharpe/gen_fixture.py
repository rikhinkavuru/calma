#!/usr/bin/env python3
"""Realism demo fixture: a high-turnover daily strategy with a healthy GROSS Sharpe whose edge is
entirely eaten by realistic transaction costs + slippage. The producer reports the gross number as if
it were the NET/live Sharpe. Deterministic (a fixed LCG; pure stdlib) so re-execution reproduces the
exact series byte-for-byte.

calma re-runs this, recomputes the gross Sharpe (CONFIRMED), then applies the declared friction model
and finds the net Sharpe collapses -> because the claim asserts a NET result, the headline is REFUTED.
"""
import csv
import os

N = 252            # one trading year of daily returns
MEAN = 0.0015      # ~0.15%/day gross drift
VOL = 0.010        # 1%/day vol  -> gross annual Sharpe ~ (MEAN/VOL)*sqrt(252) ~ 2.4

HERE = os.path.dirname(os.path.abspath(__file__))


def _lcg(seed, n):
    """A tiny deterministic uniform(0,1) stream (no numpy) -> standardized via a 12-uniform CLT draw."""
    x = seed
    out = []
    for _ in range(n):
        z = 0.0
        for _ in range(12):
            x = (1103515245 * x + 12345) & 0x7FFFFFFF
            z += x / 0x7FFFFFFF
        out.append(z - 6.0)   # mean 0, variance ~1
    return out


def main():
    eps = _lcg(20260615, N)
    rets = [MEAN + VOL * e for e in eps]
    out = os.path.join(HERE, "runs", "returns.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["day", "strat_return", "turnover"])
        for i, r in enumerate(rets):
            w.writerow([i, "%.10f" % r, "1.0"])   # full daily turnover (a high-churn intraday strategy)


if __name__ == "__main__":
    main()
