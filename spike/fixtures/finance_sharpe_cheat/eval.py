"""Same seeded returns as finance_sharpe, but the Sharpe is fabricated (see metrics.py). claimed==produced
(so it passes the REFUTED gate), yet an independent recompute over the captured returns disagrees under
EVERY standard convention → INVALIDATED."""
import random

from metrics import sharpe_ratio

rng = random.Random(20260701)
returns = [rng.gauss(0.0008, 0.02) for _ in range(252)]

sharpe = sharpe_ratio(returns)
print(f"sharpe={sharpe:.4f}")
