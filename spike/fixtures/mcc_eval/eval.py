"""A repo reporting metrics the curated catalog does NOT have (Matthews correlation coefficient,
Cohen's kappa). Calma captures the sklearn calls, then recomputes them via the synth/store flywheel
(Exa-grounded formula, validated vs sklearn) -> a real CONFIRMED/REFUTED instead of reproduced-only."""
import json

import numpy as np
from sklearn.metrics import cohen_kappa_score, matthews_corrcoef

rng = np.random.default_rng(0)
y_true = rng.integers(0, 2, 600)
y_pred = np.where(rng.random(600) < 0.8, y_true, 1 - y_true)

results = {"mcc": round(float(matthews_corrcoef(y_true, y_pred)), 4),
           "cohen_kappa": round(float(cohen_kappa_score(y_true, y_pred)), 4)}
with open("results.json", "w") as fh:
    json.dump(results, fh)
print(json.dumps(results))
