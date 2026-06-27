"""A repo that computes the SAME metric twice — train accuracy then test accuracy. A bare 'accuracy'
claim is ambiguous (which one?) -> INCONCLUSIVE until the claim is scoped. With a bind hint naming the
occurrence (the test computation), it resolves. Demonstrates the fail-closed 'scope the claim' path."""
import numpy as np
from sklearn.metrics import accuracy_score

rng = np.random.default_rng(11)
n = 500
y_tr = rng.integers(0, 2, n)
y_te = rng.integers(0, 2, n)
# overfit-ish: near-perfect on train, ~chance on test
pred_tr = np.where(rng.random(n) < 0.97, y_tr, 1 - y_tr)
pred_te = np.where(rng.random(n) < 0.55, y_te, 1 - y_te)

acc_train = accuracy_score(y_tr, pred_tr)   # occurrence 0
acc_test = accuracy_score(y_te, pred_te)    # occurrence 1
print(f"train_accuracy={acc_train:.4f}")
print(f"test_accuracy={acc_test:.4f}")
