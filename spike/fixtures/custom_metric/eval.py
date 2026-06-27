"""A repo that computes its OWN 'accuracy' with a buggy/cheating formula that REPRODUCES perfectly but is
wrong. `my_accuracy` (in metrics.py) ignores y_true and compares predictions to themselves -> always 1.0.
The number re-runs to 1.0 every time and looks great; only an INDEPENDENT recompute of accuracy(y_true,
y_pred) on the SAME captured inputs catches it. This is exactly the case pure re-running cannot catch
-> INVALIDATED."""
import numpy as np

from metrics import my_accuracy

rng = np.random.default_rng(7)
n = 600
y_true = rng.integers(0, 2, n)
y_pred = rng.integers(0, 2, n)   # ~chance predictions; true accuracy ≈ 0.5

acc = my_accuracy(y_true, y_pred)
print(f"accuracy={acc:.4f}")     # reports a perfect 1.0000
