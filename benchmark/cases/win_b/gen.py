import os, csv
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(59)
rows = []
for _ in range(40):
    import datetime
    d = (datetime.date(2024, 1, 1) + datetime.timedelta(days=_)).isoformat()
    r = 0.0008 + (next(g) - 0.5) * 0.01
    rows.append((d, round(r, 8)))
with open("runs/returns.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(['date', 'daily_return'])
    for r in rows: w.writerow(r)
