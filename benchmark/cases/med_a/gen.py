import os
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(73)
import csv
rows = []
for _ in range(1101):
    v = 5.0 + next(g) * (250.0 - 5.0)
    rows.append((round(v, 6),))
with open("runs/data.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["value"])
    for r in rows: w.writerow(r)
