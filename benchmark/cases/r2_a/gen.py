import os
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(33)
import csv
rows = []
for i in range(700):
    x = next(g) * 10.0
    y_true = 3.0 * x + 2.0
    y_pred = y_true + (next(g) - 0.5) * 4.0
    rows.append((round(y_true, 6), round(y_pred, 6)))
with open("runs/reg.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["target", "prediction"])
    for r in rows: w.writerow(r)
