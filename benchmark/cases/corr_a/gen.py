import os
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(76)
import csv
rows = []
for _ in range(800):
    x = next(g) * 20.0
    y = 0.8 * x + (next(g) - 0.5) * 9.0
    rows.append((round(x, 6), round(y, 6)))
with open("runs/pairs.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["x", "y"])
    for r in rows: w.writerow(r)
