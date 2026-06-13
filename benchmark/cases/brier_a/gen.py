import os
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(62)
rows = []
for i in range(900):
    yt = 1 if next(g) < 0.5 else 0
    u = next(g)
    base = (0.5 + 0.8 * (u - 0.25)) if yt == 1 else (0.5 - 0.8 * (u - 0.25))
    p = max(0.05, min(0.95, base)) + i * 1e-9          # distinct by construction
    rows.append((yt, round(p, 9)))
import csv
with open("runs/preds.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["y_true", "prob"])
    for r in rows: w.writerow(r)
