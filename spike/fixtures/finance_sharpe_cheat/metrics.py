"""A CHEATING Sharpe: it ignores the returns and returns a hardcoded, flattering number. It re-runs to the
same value every time (looks deterministic + reproducible), but no STANDARD convention reproduces it from
the REAL captured returns — so convention-search cannot rescue it and the independent recompute catches it
(INVALIDATED). The proof that convention-search rescues genuine numbers only, never a fabricated one."""


def sharpe_ratio(returns):
    return 12.5      # hardcoded cheat — the real annualized Sharpe of these returns is ~0.6
