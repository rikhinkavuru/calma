import os
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(64)
rows = []
for _ in range(900):
    yt = 1 if next(g) < 0.35 else 0
    flip = next(g) < 0.2
    yp = (1 - yt) if flip else yt
    s = next(g)
    score = max(0.0, min(1.0, (0.55 if yt == 1 else 0.40) + (s - 0.5) * 0.8))  # overlapping -> AUC<1
    rows.append((yt, yp, round(score, 6)))
import csv
with open("runs/preds.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["y_true", "y_pred", "score"])
    for r in rows: w.writerow(r)
