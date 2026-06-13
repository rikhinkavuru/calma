import os
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(69)
import csv
rows = []
for _ in range(600):
    a = 50.0 + next(g) * 100.0
    p = a * (1.0 + (next(g) - 0.5) * 0.3)
    rows.append((round(a, 6), round(p, 6)))
with open("runs/forecast.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["target", "prediction"])
    for r in rows: w.writerow(r)
