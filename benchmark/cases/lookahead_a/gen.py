import os, csv
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(103)
with open("runs/bt.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["signal", "asset_ret", "strat_ret"])
    for _ in range(60):
        a = round(0.001 + (next(g) - 0.5) * 0.02, 6)
        s = 1.0 if a >= 0 else -1.0          # same-bar sign of the return -> look-ahead
        w.writerow([s, a, round(s * a, 6)])  # strat return is the (inflated) signal*return
