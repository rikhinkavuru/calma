import os, csv
os.makedirs("runs", exist_ok=True)
def _lcg(s):
    x=s&0xFFFFFFFF
    while True:
        x=(1103515245*x+12345)&0x7FFFFFFF
        yield x/0x7FFFFFFF
g=_lcg(91)
with open("runs/train.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["feat","y_pred","y_true"])
    for i in range(60):
        y=i%2; w.writerow([round(next(g),4), y, y])
with open("runs/test.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["feat","y_pred","y_true"])
    for i in range(60):
        y=i%2; p=y if next(g)<0.88 else 1-y
        w.writerow([round(3+next(g),4), p, y])
