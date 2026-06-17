import os, csv
os.makedirs("runs", exist_ok=True)
def _lcg(s):
    x=s&0xFFFFFFFF
    while True:
        x=(1103515245*x+12345)&0x7FFFFFFF
        yield x/0x7FFFFFFF
g=_lcg(31)
with open("runs/returns.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["daily_return"])
    for _ in range(252):
        w.writerow((round(0.0006 + (next(g)-0.5)*0.012, 8),))
