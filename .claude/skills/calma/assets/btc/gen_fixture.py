#!/usr/bin/env python3
"""Entrypoint for the BTC fixture: re-emit the raw machine-readable artifacts the skill recomputes
from. Reproduces the overfit-backtest lie pattern (grid-search params in-sample, no costs -> apply
forward OOS with real costs) on the VENDORED Coinbase snapshot (btc_snapshot.json, NO network).

Emits (next to this file): runs/oos/returns.csv (strat daily OOS returns), runs/oos/baseline.csv
(buy&hold OOS daily returns). Pure stdlib, deterministic: same snapshot -> bit-identical CSVs.

Run: python3 gen_fixture.py
"""
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "btc_snapshot.json")


def sma(xs, n, i):
    if i + 1 < n:
        return None
    return sum(xs[i - n + 1:i + 1]) / n


def backtest(closes, fast, slow, lev, fee=0.0):
    rets = []
    prev = 0.0
    eq = 1.0
    for i in range(len(closes) - 1):
        f = sma(closes, fast, i)
        s = sma(closes, slow, i)
        pos = lev if (f is not None and s is not None and f > s) else 0.0
        day = (closes[i + 1] / closes[i]) - 1.0
        cost = abs(pos - prev) * fee
        strat = pos * day - cost
        eq *= (1.0 + strat)
        rets.append(strat)
        prev = pos
    return eq - 1.0, rets


def main():
    series = [(int(t), float(c)) for t, c in json.load(open(SNAP))]
    closes = [c for _, c in series]
    n = len(closes)
    split = int(n * 0.70)
    IS, OOS = closes[:split], closes[split:]

    # THE LIE: grid-search in-sample, no costs, keep the winner (best-of-N)
    fasts = [5, 10, 15, 20, 30]
    slows = [40, 60, 100, 150, 200]
    levs = [1, 3, 5, 10]
    best = None
    tested = 0
    for fa in fasts:
        for sl in slows:
            if fa >= sl:
                continue
            for lv in levs:
                tested += 1
                tot, _ = backtest(IS, fa, sl, lv, fee=0.0)
                if best is None or tot > best[0]:
                    best = (tot, fa, sl, lv)
    is_ret, bf, bs, bl = best

    # apply forward OOS WITH real costs; baseline = buy & hold OOS
    fee = 0.0015
    _, oos_rets = backtest(OOS, bf, bs, bl, fee=fee)
    bh_rets = [(OOS[i + 1] / OOS[i]) - 1.0 for i in range(len(OOS) - 1)]

    outdir = os.path.join(HERE, "runs", "oos")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "returns.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["strat_return"])
        for r in oos_rets:
            w.writerow([repr(r)])
    with open(os.path.join(outdir, "baseline.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["bh_return"])
        for r in bh_rets:
            w.writerow([repr(r)])
    print(json.dumps({
        "claimed_in_sample_return": is_ret, "params": {"fast": bf, "slow": bs, "lev": bl},
        "tested": tested, "oos_bars": len(oos_rets),
    }))


if __name__ == "__main__":
    main()
