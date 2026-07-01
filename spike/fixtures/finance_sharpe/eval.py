"""A finance repo reporting an ANNUALIZED Sharpe (√252, population stdev) via its own sharpe_ratio(). The
number is a legitimate metric under a standard convention Calma doesn't default to — so it CONFIRMS only
via convention-search (guide §B.2). Seeded → deterministic."""
import random

from metrics import sharpe_ratio

rng = random.Random(20260701)
returns = [rng.gauss(0.0008, 0.02) for _ in range(252)]

sharpe = sharpe_ratio(returns)
print(f"sharpe={sharpe:.4f}")
