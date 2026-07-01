"""The repo's OWN Sharpe implementation — in an importable module so the harness wraps it via a target/bind
hint (an imported custom function; the __main__-defined case is the P1 capture-ladder frontier). This uses
a STANDARD but non-default convention: annualized by √252 (daily) with a POPULATION stdev (ddof=0, numpy's
default). Calma's default recompute (per-period, ddof=1) disagrees — only convention-search reproduces it."""
import math


def sharpe_ratio(returns):
    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / n     # ddof=0 (population; numpy np.std default)
    sd = math.sqrt(var)
    return mean / sd * math.sqrt(252)                    # annualized by √252 (daily)
