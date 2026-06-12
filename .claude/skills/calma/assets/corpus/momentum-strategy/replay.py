"""Calma corpus replay entrypoint for sh-mukherjee/momentum-strategy (MIT).

This runs the upstream strategy's REAL compute path (momentum signals -> volatility-scaled
risk weights -> backtest with transaction costs) on a FROZEN price snapshot, so the whole run is
hermetic (network OFF). It is the BTC vendoring pattern applied to a yfinance repo:

  * data is vendored once (vendored_prices.csv, recorded via the upstream DataFetcher) instead of
    fetched live -> the run needs no network and is reproducible;
  * the only code NOT exercised is the live fetch (replaced by the snapshot read) and the plotly/
    streamlit visualization (irrelevant to the headline number);
  * a one-line EMIT of the raw daily strategy returns (runs/returns.csv) is added so Calma can
    independently recompute the headline metric from a machine-readable artifact.

Headline metric: Total Return = prod(1 + daily_return) - 1 over the strategy's net daily returns.
Provenance + re-record recipe: VENDORED.md.
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pandas as pd  # noqa: E402

import config  # noqa: E402
from backtest import Backtester  # noqa: E402
from risk import RiskManager  # noqa: E402
from signals import MomentumSignals  # noqa: E402


def main():
    # frozen input snapshot (no network) - the vendored equivalent of the live yfinance fetch
    prices = pd.read_csv(os.path.join(HERE, "vendored_prices.csv"), index_col=0, parse_dates=True)

    # upstream compute path, unchanged
    signals = MomentumSignals(lookback_periods=config.MOMENTUM_LOOKBACKS) \
        .combined_signal(prices, config.CROSS_SECTIONAL_LOOKBACK)
    positions = RiskManager(target_vol=config.TARGET_VOLATILITY,
                            vol_lookback=config.VOLATILITY_LOOKBACK) \
        .volatility_scaled_weights(signals, prices)
    returns = Backtester(transaction_cost=config.TRANSACTION_COST) \
        .calculate_portfolio_returns(positions, prices)

    # EMIT the raw daily strategy returns so Calma can recompute the headline from raw outputs
    out_dir = os.path.join(HERE, "runs")
    os.makedirs(out_dir, exist_ok=True)
    series = returns.fillna(0.0)
    series.index.name = "date"
    series.name = "daily_return"
    series.to_csv(os.path.join(out_dir, "returns.csv"))

    total_return = float((1.0 + series).prod() - 1.0)
    print("total_return=%.6f" % total_return)


if __name__ == "__main__":
    main()
