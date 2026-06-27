"""A clean, honest ML eval: a better-than-chance classifier scored with sklearn, seeded (deterministic).
Used to demonstrate CONFIRMED (claim == produced == recompute) and REFUTED (a perturbed claim)."""
import numpy as np
from sklearn.metrics import accuracy_score, roc_auc_score

rng = np.random.default_rng(0)
n = 800
y_true = rng.integers(0, 2, n)
# a model that is right ~82% of the time, with a calibrated-ish score
flip = rng.random(n) < 0.18
y_pred = np.where(flip, 1 - y_true, y_true)
y_score = np.clip(y_true * 0.7 + rng.normal(0, 0.3, n) + 0.15, 0, 1)

acc = accuracy_score(y_true, y_pred)
auc = roc_auc_score(y_true, y_score)
print(f"accuracy={acc:.4f}")
print(f"roc_auc={auc:.4f}")
