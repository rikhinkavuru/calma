"""SMA-crossover backtest with TP/SL, vendored from HilmiSamdya/btc-sma-backtest (MIT).

This is the upstream `run_backtest` compute logic, UNCHANGED in substance — golden/death SMA
crossover entries, take-profit / stop-loss exits in ticks, opposite-cross reversals — lifted out of
the Streamlit app verbatim. The ONLY edits are vendoring-mechanical:
  * the price data is passed in as a DataFrame (the upstream globs bundled binance CSVs; here the
    same OHLC is fetched from a recordable source — see fetch.py / replay.py);
  * the Streamlit UI (`st.*`) is removed (it is presentation, not computation);
  * the per-trade PnL list (`trades`) is returned directly so it can be emitted for recompute.

Upstream: https://github.com/HilmiSamdya/btc-sma-backtest @ ca475c4 (© 2026 HilmiSamdya, MIT).
"""


def run_backtest(df, SMA_FAST=50, SMA_SLOW=100, TICKS_TP=50000.0, TICKS_SL=30000.0, TICK_SIZE=0.1):
    """df: rows sorted oldest->newest with float columns close/high/low. Returns the list of
    per-trade PnL (price points), exactly as upstream accumulates it."""
    close = list(df["close"])
    high = list(df["high"])
    low = list(df["low"])
    n = len(close)

    def _sma(series, w, i):
        if i + 1 < w:
            return None
        return sum(series[i + 1 - w:i + 1]) / w

    trades = []
    position = None
    for i in range(SMA_SLOW + 1, n):
        pf, ps = _sma(close, SMA_FAST, i), _sma(close, SMA_SLOW, i)
        ppf, pps = _sma(close, SMA_FAST, i - 1), _sma(close, SMA_SLOW, i - 1)
        if None in (pf, ps, ppf, pps):
            continue
        golden = (ppf <= pps) and (pf > ps)
        death = (ppf >= pps) and (pf < ps)
        c, h, lo = close[i], high[i], low[i]
        if position is None:
            if golden:
                position = {"side": "BUY", "entry": c}
            elif death:
                position = {"side": "SELL", "entry": c}
        else:
            entry = position["entry"]
            if position["side"] == "BUY":
                tp_level = entry + TICKS_TP * TICK_SIZE
                sl_level = entry - TICKS_SL * TICK_SIZE
                if h >= tp_level:
                    trades.append(tp_level - entry); position = None
                elif lo <= sl_level:
                    trades.append(sl_level - entry); position = None
                elif death:
                    trades.append(c - entry); position = {"side": "SELL", "entry": c}
            else:
                tp_level = entry - TICKS_TP * TICK_SIZE
                sl_level = entry + TICKS_SL * TICK_SIZE
                if lo <= tp_level:
                    trades.append(entry - tp_level); position = None
                elif h >= sl_level:
                    trades.append(entry - sl_level); position = None
                elif golden:
                    trades.append(entry - c); position = {"side": "BUY", "entry": c}
    return trades
