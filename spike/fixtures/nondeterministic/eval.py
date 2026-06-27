"""A result that does not reproduce: the headline number drifts run-to-run, so it can never earn a hard
CONFIRMED -> NON-DETERMINISTIC (the determinism gate fires on the cross-run spread).

For a deterministic, robust demonstration the drift is driven by CALMA_RUN_INDEX (a harness-provided run
counter) — a controllable stand-in for the real culprits: an unseeded RNG, wall-clock, os.urandom, GPU
nondeterminism. The model is genuinely better than chance (≈0.70 on balanced data, so NOT a trivial
baseline); only the low-order digits move."""
import os

from sklearn.metrics import accuracy_score

run = int(os.environ.get("CALMA_RUN_INDEX", "0"))
n = 1000
y_true = [0, 1] * (n // 2)                 # balanced -> majority baseline 0.5
n_correct = 700 + run                      # 0.700, 0.701, 0.702, ... — drifts each run
y_pred = [y_true[i] if i < n_correct else 1 - y_true[i] for i in range(n)]

acc = accuracy_score(y_true, y_pred)
print(f"accuracy={acc:.4f}")
