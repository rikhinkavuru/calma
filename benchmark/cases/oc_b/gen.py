import os, csv
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(47)
rows = []
for _ in range(120):
    gr = 0.0009 + (next(g) - 0.5) * 0.01
    rows.append((round(gr, 8), 0.0015))
with open("runs/returns.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(['daily_return', 'cost'])
    for r in rows: w.writerow(r)
