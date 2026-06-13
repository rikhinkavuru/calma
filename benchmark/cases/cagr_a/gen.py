import os
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(72)
import csv
rows = []
v = 1000.0
rows.append((round(v, 2),))
for _ in range(9 - 1):
    v *= 1.0 + 0.13 + (next(g) - 0.5) * 0.06
    rows.append((round(v, 2),))
with open("runs/revenue.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["revenue"])
    for r in rows: w.writerow(r)
