"""A result that re-runs AND recomputes correctly, yet is invalid: 92% accuracy on data that is 92% one
class, from a model that just predicts the majority class. sklearn agrees it is 0.92; our recompute agrees;
but the validity overlay flags it as no better than the majority-class baseline -> INVALIDATED
(reproducible-but-invalid). The 'no baseline' smell, caught from the captured y_true."""
import numpy as np
from sklearn.metrics import accuracy_score

rng = np.random.default_rng(3)
n = 1000
# 92% class 0, 8% class 1
y_true = (rng.random(n) < 0.08).astype(int)
y_pred = np.zeros(n, dtype=int)  # constant majority-class predictor

acc = accuracy_score(y_true, y_pred)
print(f"accuracy={acc:.4f}")
