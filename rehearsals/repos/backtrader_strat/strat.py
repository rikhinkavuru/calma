import os, csv, math, datetime
import backtrader as bt

class SmaCross(bt.Strategy):
    params = dict(fast=10, slow=30)
    def __init__(self):
        sma_f = bt.ind.SMA(period=self.p.fast)
        sma_s = bt.ind.SMA(period=self.p.slow)
        self.crossover = bt.ind.CrossOver(sma_f, sma_s)
    def next(self):
        if not self.position and self.crossover > 0:
            self.buy()
        elif self.position and self.crossover < 0:
            self.close()

# deterministic synthetic OHLC feed written to a CSV backtrader can read
rows = [("date","open","high","low","close","volume")]
p = 100.0
d0 = datetime.date(2022, 1, 3)
for i in range(400):
    p *= (1.0 + 0.0006*math.sin(i/11.0) + 0.0003*((i % 5)-2)/2.0)
    o = p*0.999; h = p*1.004; l = p*0.996; c = p
    dt = d0 + datetime.timedelta(days=i)
    rows.append((dt.isoformat(), round(o,4), round(h,4), round(l,4), round(c,4), 1000))
with open("ohlc.csv","w",newline="") as f:
    csv.writer(f).writerows(rows)

cerebro = bt.Cerebro()
cerebro.addstrategy(SmaCross)
data = bt.feeds.GenericCSVData(dataname="ohlc.csv", dtformat="%Y-%m-%d",
    datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1)
cerebro.adddata(data)
cerebro.broker.setcash(10000.0)
cerebro.broker.setcommission(commission=0.001)
cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="tr", timeframe=bt.TimeFrame.Days)
res = cerebro.run()
tr = res[0].analyzers.tr.get_analysis()
os.makedirs("runs", exist_ok=True)
with open("runs/returns.csv","w",newline="") as f:
    w = csv.writer(f); w.writerow(["date","daily_return"])
    for dt, r in tr.items():
        w.writerow([str(dt), r])
total = 1.0
for r in tr.values(): total *= (1.0+r)
print(f"backtrader total_return = {total-1.0:.6f} (backtrader {bt.__version__})")
