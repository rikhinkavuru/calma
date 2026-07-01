"""A realistic (if small) self-contained ML eval: a real train/test split, a real LogisticRegression, and
headline numbers computed with sklearn and written to results.json — the shape Calma must verify on actual
repos. Seeded end-to-end, so it is genuinely deterministic. Run via the harness's build-runnable path
(a per-repo venv from requirements.txt)."""
import json

from sklearn.datasets import make_classification
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split

X, y = make_classification(n_samples=4000, n_features=20, n_informative=8, weights=[0.6, 0.4],
                           random_state=42)
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3, random_state=42)

clf = LogisticRegression(max_iter=2000, random_state=42).fit(Xtr, ytr)
proba = clf.predict_proba(Xte)[:, 1]
pred = clf.predict(Xte)

results = {
    "test_accuracy": round(float(accuracy_score(yte, pred)), 4),
    "test_roc_auc": round(float(roc_auc_score(yte, proba)), 4),
    "test_f1": round(float(f1_score(yte, pred)), 4),
}
with open("results.json", "w") as fh:
    json.dump(results, fh, indent=2)
print(json.dumps(results))
