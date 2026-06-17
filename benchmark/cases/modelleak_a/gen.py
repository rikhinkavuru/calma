import os, csv
os.makedirs("runs", exist_ok=True)
def _lcg(s):
    x=s&0xFFFFFFFF
    while True:
        x=(1103515245*x+12345)&0x7FFFFFFF
        yield x/0x7FFFFFFF
g=_lcg(71)
with open("runs/preds.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["y_pred","y_true"])
    for i in range(200):
        y=1 if next(g)>0.5 else 0
        p=y if next(g)<0.88 else (1-y)   # ~88% correct
        w.writerow([p,y])
