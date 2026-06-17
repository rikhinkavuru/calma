import os, csv
os.makedirs("runs", exist_ok=True)
def _lcg(s):
    x=s&0xFFFFFFFF
    while True:
        x=(1103515245*x+12345)&0x7FFFFFFF
        yield x/0x7FFFFFFF
g=_lcg(13)
rows=[]
for _ in range(40):
    rows.append(round(0.008 + (next(g)-0.5)*0.01, 8))   # regime 1: strong edge
for _ in range(40):
    rows.append(round(-0.001 + (next(g)-0.5)*0.01, 8))  # regime 2: edge gone
with open("runs/returns.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["daily_return"])
    [w.writerow((r,)) for r in rows]
