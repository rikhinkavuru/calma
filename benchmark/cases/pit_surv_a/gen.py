import os, csv
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(101)
with open("runs/returns.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["daily_return"])
    for _ in range(120):
        w.writerow((round(0.0011 + (next(g) - 0.5) * 0.012, 8),))
# point-in-time membership: 60 names, ZERO ever delisted (a current survivors-only snapshot)
with open("runs/universe.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["ticker", "delisted"])
    for i in range(60):
        w.writerow(["T%03d" % i, 0])
