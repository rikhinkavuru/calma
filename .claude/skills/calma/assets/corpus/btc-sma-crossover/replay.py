"""Calma corpus replay entrypoint for the BTC SMA-crossover strategy (HilmiSamdya/btc-sma-backtest, MIT).

This demonstrates the OTHER vendoring mechanism (vs. momentum's data snapshot): the calma_vendor HTTP
record/replay shim. The upstream live data source (bundled binance CSVs) is replaced by BTC-USD OHLC
fetched from Coinbase; that fetch was RECORDED once with network on (.calma_httpcache/) and is now
REPLAYED offline - a cache MISS raises, so the run is provably hermetic (network OFF, no live reach).

The strategy itself (strategy.py) is the upstream SMA-crossover + TP/SL logic, unchanged. The headline
emitted for recompute is the per-trade PnL series (runs/trades.csv); Calma re-sums it to total_profit.
Provenance + re-record recipe: VENDORED.md.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import calma_vendor  # vendored copy of the shim (drift-guarded by the test suite)  # noqa: E402
import fetch  # noqa: E402
from strategy import run_backtest  # noqa: E402


def main():
    # offline replay: every fetch is served from the committed cache; a miss would raise
    calma_vendor.install_replay(os.path.join(HERE, ".calma_httpcache"))
    data = fetch.fetch_ohlc()
    trades = run_backtest(data)

    out_dir = os.path.join(HERE, "runs")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "trades.csv"), "w") as fh:
        fh.write("pnl\n")
        for t in trades:
            fh.write("%.10f\n" % t)

    print("n_trades=%d" % len(trades))
    print("total_profit=%.6f" % sum(trades))


if __name__ == "__main__":
    main()
