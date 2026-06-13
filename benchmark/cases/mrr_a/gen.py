import os
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(67)
import csv
rows = []
for qi in range(60):
    for rank in range(1, 10 + 1):
        p_rel = max(0.05, 0.7 - 0.08 * (rank - 1))
        rel = 1 if next(g) < p_rel else 0
        rows.append(("q%03d" % qi, rank, rel))
with open("runs/results.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["query", "rank", "relevance"])
    for r in rows: w.writerow(r)
