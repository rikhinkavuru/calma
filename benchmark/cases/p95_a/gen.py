import os
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(74)
import csv
rows = []
for _ in range(1500):
    base = 40.0 + 220.0 * (next(g) ** 2) + 120.0 * next(g)
    rows.append((round(base, 3),))
with open("runs/latency_ms.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["latency_ms"])
    for r in rows: w.writerow(r)
