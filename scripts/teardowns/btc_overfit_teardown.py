#!/usr/bin/env python3
"""Calma execution teardown: reproduce the 'huge backtest %' lie pattern on REAL BTC-USD
daily data (Coinbase), then run the recompute pillar (same params, out-of-sample, WITH costs).
Pure stdlib. No lookahead is used; the collapse comes purely from in-sample overfit + costs.

Run: python3 scripts/teardowns/btc_overfit_teardown.py
"""
import json, time, urllib.request, datetime as dt, math, os

SNAPSHOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "btc_snapshot.json")

def fetch_btc_daily(years=4):
    """Coinbase daily candles, paginated backwards (<=300 per call). Returns [(epoch, close)] asc.
    Cached to btc_snapshot.json on first fetch so re-runs are REPRODUCIBLE and need no network —
    mirroring the skill's hard rule that the recompute runs network-OFF from a vendored snapshot.
    Delete btc_snapshot.json to refresh."""
    if os.path.exists(SNAPSHOT):
        return [(int(t), float(c)) for t, c in json.load(open(SNAPSHOT))]
    out = {}
    end = dt.datetime.now(dt.UTC)
    for _ in range(years * 2 + 2):  # 300d per call
        start = end - dt.timedelta(days=300)
        url = ("https://api.exchange.coinbase.com/products/BTC-USD/candles"
               f"?granularity=86400&start={start.isoformat()}&end={end.isoformat()}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "calma-teardown"})
            rows = json.load(urllib.request.urlopen(req, timeout=20))
        except Exception as e:
            print("  fetch warn:", e); time.sleep(1); end = start; continue
        for r in rows:  # [time, low, high, open, close, vol]
            out[int(r[0])] = float(r[4])
        end = start
        time.sleep(0.4)
    series = [(t, out[t]) for t in sorted(out)]
    try:
        json.dump(series, open(SNAPSHOT, "w"))
    except Exception:
        pass
    return series

def sharpe(daily_rets, periods=365):
    if len(daily_rets) < 2: return 0.0
    m = sum(daily_rets) / len(daily_rets)
    var = sum((x - m) ** 2 for x in daily_rets) / (len(daily_rets) - 1)
    sd = math.sqrt(var)
    return (m / sd) * math.sqrt(periods) if sd > 0 else 0.0

def sma(xs, n, i):
    if i + 1 < n: return None
    return sum(xs[i - n + 1:i + 1]) / n

def backtest(closes, fast, slow, lev, fee_per_side=0.0):
    """Long/flat MA-crossover. Signal from close[t] trades return[t+1] (NO lookahead).
    fee_per_side applied on position change (fee+slippage). Returns (total_return, daily_rets)."""
    rets = []; prev_pos = 0.0; equity = 1.0
    for i in range(len(closes) - 1):
        f = sma(closes, fast, i); s = sma(closes, slow, i)
        pos = lev if (f is not None and s is not None and f > s) else 0.0
        day_ret = (closes[i + 1] / closes[i]) - 1.0
        cost = abs(pos - prev_pos) * fee_per_side
        strat = pos * day_ret - cost
        equity *= (1.0 + strat); rets.append(strat); prev_pos = pos
    return equity - 1.0, rets

def main():
    print("Fetching real BTC-USD daily data from Coinbase...")
    series = fetch_btc_daily(years=4)
    closes = [c for _, c in series]
    dates = [dt.datetime.fromtimestamp(t, dt.UTC).date().isoformat() for t, _ in series]
    n = len(closes)
    print(f"  got {n} daily bars, {dates[0]} -> {dates[-1]}")
    if n < 400:
        print("  insufficient data; abort"); return

    split = int(n * 0.70)
    IS, OOS = closes[:split], closes[split:]
    print(f"  in-sample: {dates[0]}..{dates[split-1]} ({len(IS)} bars)")
    print(f"  out-of-sample: {dates[split]}..{dates[-1]} ({len(OOS)} bars)")

    # ---- THE LIE: grid-search params IN-SAMPLE, NO costs, maximize return (Hyperopt-style) ----
    fasts = [5, 10, 15, 20, 30]; slows = [40, 60, 100, 150, 200]; levs = [1, 3, 5, 10]
    best = None; tested = 0
    for fa in fasts:
        for sl in slows:
            if fa >= sl: continue
            for lv in levs:
                tested += 1
                tot, rets = backtest(IS, fa, sl, lv, fee_per_side=0.0)
                if best is None or tot > best[0]:
                    best = (tot, fa, sl, lv, sharpe(rets))
    is_ret, bf, bs, bl, is_sharpe = best
    print(f"\n  [grid search] tested N={tested} param combos in-sample, kept the winner")

    bh_is = IS[-1] / IS[0] - 1.0
    print("\n================ CLAIMED (in-sample, no costs, best-of-N) ================")
    print(f"  params: fast={bf} slow={bs} leverage={bl}x")
    print(f"  CLAIMED return: {is_ret*100:,.0f}%   in-sample Sharpe: {is_sharpe:.2f}")
    print(f"  (buy & hold same period: {bh_is*100:,.0f}%)")

    fee = 0.0015  # 0.10% fee + 0.05% slippage per side
    oos_ret_nocost, _ = backtest(OOS, bf, bs, bl, fee_per_side=0.0)
    oos_ret, oos_rets = backtest(OOS, bf, bs, bl, fee_per_side=fee)
    bh_oos = OOS[-1] / OOS[0] - 1.0
    bh_oos_rets = [(OOS[i+1]/OOS[i]) - 1 for i in range(len(OOS)-1)]
    print("\n================ CALMA RECOMPUTE (out-of-sample, real costs) ================")
    print(f"  same params applied forward, fee+slippage {fee*100:.2f}%/side")
    print(f"  REAL OOS return: {oos_ret*100:,.1f}%   OOS Sharpe (net): {sharpe(oos_rets):.2f}")
    print(f"  OOS return if costs ignored: {oos_ret_nocost*100:,.1f}%")
    print(f"  (buy & hold OOS: {bh_oos*100:,.1f}%, Sharpe {sharpe(bh_oos_rets):.2f})")

    beat_bh = oos_ret > bh_oos
    # NOTE: this 0.25/beat-BH test is a DEMONSTRATION heuristic — it shows the verdict SHAPE only.
    # The Calma skill does NOT use it. The skill derives REFUTED from a band-aware recompute diff
    # plus a baseline-edge CI guard (docs/calma-skill-blueprint.md §10 / §15-M1.3). Do not port this rule.
    verdict = "REFUTED" if (oos_ret < is_ret * 0.25 or not beat_bh) else "CONFIRMED-WITH-CAVEATS"
    print("\n================ CALMA VERDICT ================")
    print(f"  {verdict}: claimed {is_ret*100:,.0f}% -> real out-of-sample {oos_ret*100:,.1f}% net of costs")
    print(f"  - OVERFITTING: winner of N={tested} param combos picked on the SAME data it reports;")
    print(f"    no out-of-sample, no deflated Sharpe. In-sample Sharpe {is_sharpe:.2f} -> OOS Sharpe {sharpe(oos_rets):.2f}.")
    print(f"  - REALISM: costs move OOS from {oos_ret_nocost*100:,.1f}% to {oos_ret*100:,.1f}% at {bl}x leverage.")
    print(f"  - BENCHMARK: strategy {'beats' if beat_bh else 'does NOT beat'} buy&hold OOS ({oos_ret*100:,.1f}% vs {bh_oos*100:,.1f}%).")
    print("  scope: real BTC-USD daily (Coinbase), no-lookahead backtest, recompute completed.")

if __name__ == "__main__":
    main()
