# Vendored corpus member: BTC SMA-crossover (HilmiSamdya/btc-sma-backtest)

The crypto live-data slot, replacing the retired `Erfaniaa/crypto-backtester` (deleted upstream + its
binance source is geo-blocked / HTTP 451 from many hosts — unreproducible). This member demonstrates the
SECOND vendoring mechanism: the `calma_vendor` HTTP **record/replay shim** (momentum-strategy used a
data snapshot), proven here on a real, non-geoblocked network source (Coinbase).

| field | value |
|---|---|
| strategy source | https://github.com/HilmiSamdya/btc-sma-backtest |
| commit | `ca475c4074c14d4de2949f53146a66183459e61e` |
| license | MIT (© 2026 HilmiSamdya — see `LICENSE.upstream`) |
| data source (live) | Coinbase Exchange REST — `BTC-USD` 1h candles |
| headline | `total_profit` = sum of per-trade PnL (price points) |
| recorded value | **19024.77** over 4501 hourly bars (15 paged requests, anchored end 2024-12-31Z), 42 trades |

## What is vendored vs. unchanged

- **Unchanged (the thing under test):** `strategy.py` — the upstream `run_backtest` compute logic
  (50/100 SMA golden/death-cross entries, TP=50000·0.1 / SL=30000·0.1 tick exits, opposite-cross
  reversals), lifted verbatim from the Streamlit app.
- **Replaced data source:** upstream globs bundled binance hourly CSVs; here the same OHLC is fetched
  from Coinbase (`fetch.py`) and **recorded once** into `.calma_httpcache/` via the shim, then replayed
  offline. A cache MISS raises, so `replay.py` is provably hermetic (network OFF, cannot reach live).
- **Removed:** the Streamlit UI (`st.*`) — presentation, not computation.
- **Added (the emit step):** `replay.py` writes `runs/trades.csv` (per-trade PnL) so Calma recomputes
  `column_sum` = `total_profit` from a machine-readable artifact.
- **`calma_vendor.py`** is a vendored copy of the canonical shim (`scripts/calma_vendor.py`), so the
  fixture is self-contained under network-off isolation. The test suite asserts the copy is byte-identical
  to the canonical shim (drift guard).

## Re-record recipe (the one network step)

```bash
cd assets/corpus/btc-sma-crossover
python3 -c "import calma_vendor, fetch; calma_vendor.install_record('.calma_httpcache'); fetch.fetch_ohlc()"
```

## Notes

- Pure-stdlib (urllib + json + arithmetic), no pip deps; the run is `controlled-to-bit` (frozen cache +
  deterministic Python float math). Coinbase requires a `User-Agent`; the shim forwards request headers
  on record (and honors `params`, and patches `requests.Session`/ccxt) — see `scripts/calma_vendor.py`.
