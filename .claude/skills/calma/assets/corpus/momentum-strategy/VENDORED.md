# Vendored corpus member: sh-mukherjee/momentum-strategy

A real, public, third-party quant backtest, vendored into the served-fraction corpus as a *live-data*
member (the dominant coverage killer). It is the BTC vendoring pattern (freeze the data, run offline,
emit the raw series) applied to a yfinance repo.

| field | value |
|---|---|
| source | https://github.com/sh-mukherjee/momentum-strategy |
| commit | `ffda83af3fd697151332efb761df430745ff89da` |
| license | MIT (© 2025 Shantala Mukherjee — see `LICENSE.upstream`) |
| data source (live) | Yahoo Finance via `yfinance` |
| headline | Total Return = `prod(1 + daily_return) - 1` over net daily strategy returns |
| recorded value | **-2.76%** (Total Return; Sharpe -0.46) over 2015-01-01 … 2024-12-31, 13 assets, 2607 days |

## What is vendored vs. unchanged

- **Unchanged (the thing under test):** the compute path — `signals/` (multi-lookback momentum),
  `risk/` (volatility-scaled position sizing), `backtest/` (transaction-cost backtest), `config.py`.
- **Frozen:** `vendored_prices.csv` — the adjusted-close panel the upstream `DataFetcher` returns,
  recorded ONCE with network on (the universe + date range in `config.py`). The run reads this instead
  of fetching, so it is hermetic (network OFF) and reproducible.
- **Added (the emit step):** `replay.py` reads the snapshot, runs the unchanged compute path, and writes
  `runs/returns.csv` (the raw daily strategy returns) so Calma can independently recompute the headline
  from a machine-readable artifact. The plotly/streamlit visualization is not exercised (irrelevant to
  the number); the live `DataFetcher` is replaced by the snapshot read.

## Re-record recipe (the one network step)

```bash
python3 -m venv .rec && ./.rec/bin/pip install yfinance pandas
# from a clone of the upstream repo at the pinned commit:
./.rec/bin/python -c "import config; from data import DataFetcher; \
  t=config.EQUITIES+config.FX_PAIRS+config.FUTURES; \
  DataFetcher(config.START_DATE, config.END_DATE).fetch_data(t).to_csv('vendored_prices.csv')"
```

## Notes

- Upstream calls `DataFrame.fillna(method='ffill')`, removed in pandas 3.0. `requirements.txt` pins
  `pandas==2.2.3` (cp313 wheels, `method=` still honored) so the repo runs as authored — a faithful
  vendor, not a code change. The headline is bit-stable across numpy 1.26/2.1 (verified).
- Determinism stamps `measured-band` (imports numpy/pandas); the run is `restored-venv` (deps come from
  `.calma_venv`, built from `requirements.txt`, not the host interpreter).
