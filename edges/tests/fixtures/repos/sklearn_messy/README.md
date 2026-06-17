# messy classifier

Trains a classifier and writes `out/preds.csv`. Reported **AUC 0.91** on the held-out rows.

Columns in `out/preds.csv`:
- `raw_score` — the model's raw decision-function output (a logit; not a probability)
- `p_hat` — the calibrated probability in [0, 1]
- `y` — the true 0/1 label
