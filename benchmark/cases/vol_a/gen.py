import os
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(70)
import csv
rows = []
for _ in range(504):
    r = 0.0004 + (next(g) - 0.5) * 0.025
    rows.append((round(r, 8),))
with open("runs/returns.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["daily_return"])
    for r in rows: w.writerow(r)
