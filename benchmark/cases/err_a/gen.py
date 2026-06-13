import os
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(75)
import csv
rows = []
for _ in range(2000):
    rows.append((1 if next(g) < 0.06 else 0,))
with open("runs/requests.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["error"])
    for r in rows: w.writerow(r)
