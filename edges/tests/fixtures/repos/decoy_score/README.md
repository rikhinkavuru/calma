# decoy classifier

Trains a classifier; writes `out/preds.csv`. Reported **AUC 0.93**.

- `score` — raw decision-function output (a logit; NOT a probability)
- `p_hat` — calibrated probability in [0,1]
- `y` — the 0/1 label
