#!/usr/bin/env python3
"""Realism demo (the CONFIRMED-WITH-CAVEATS side): a strategy whose headline Sharpe reproduces, but the
declared frictions surface soft caveats a buyer must see - it is run at 3x leverage, trades 20% of ADV
(material market-impact risk), and assumes an optimistic VWAP fill. No per-turnover cost is declared, so
nothing materially deflates the number; the verdict stays CONFIRMED-WITH-CAVEATS and the caveats are
surfaced on the headline. Deterministic; pure stdlib.
"""
import csv, os
HERE = os.path.dirname(os.path.abspath(__file__))


def _lcg(seed, n):
    x, out = seed, []
    for _ in range(n):
        z = 0.0
        for _ in range(12):
            x = (1103515245 * x + 12345) & 0x7FFFFFFF
            z += x / 0x7FFFFFFF
        out.append(z - 6.0)
    return out


def main():
    eps = _lcg(13579, 252)
    m = sum(eps) / 252
    sd = (sum((e - m) ** 2 for e in eps) / 251) ** 0.5
    rets = [0.0015 + 0.010 * (e - m) / sd for e in eps]
    out = os.path.join(HERE, "runs", "returns.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["day", "strat_return"])
        for i, r in enumerate(rets):
            w.writerow([i, "%.10f" % r])


if __name__ == "__main__":
    main()
