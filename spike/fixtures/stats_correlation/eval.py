"""A statistics repo reporting a 'correlation' that is actually SPEARMAN. Confirms only via the correlation
type-search (guide §B.2). Seeded → deterministic."""
import random

from metrics import compute_correlation

rng = random.Random(424242)
x = [rng.gauss(0, 1) for _ in range(120)]
y = [xi * 0.6 + rng.gauss(0, 1) for xi in x]     # monotone-ish; Spearman != Pearson here

corr = compute_correlation(x, y)
print(f"correlation={corr:.4f}")
