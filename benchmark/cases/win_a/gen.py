import os, csv
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(53)
rows = []
for _ in range(60):
    r = 0.001 + (next(g) - 0.5) * 0.012
    rows.append((round(r, 8),))
with open("runs/returns.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(['daily_return'])
    for r in rows: w.writerow(r)
