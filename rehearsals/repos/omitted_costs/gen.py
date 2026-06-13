# a high-turnover strategy: big GROSS return, but costs eat most of it. The deck claims gross.
import os, csv, math
os.makedirs("runs", exist_ok=True)
rows=[("date","gross_return","turnover")]
g=0.0
for i in range(252):
    r = 0.004*math.sin(i/5.0) + 0.0015   # ~ +0.15%/day drift, oscillating
    rows.append((f"2023-{1+i//21:02d}-{1+i%21+1:02d}", round(r,6), 1.0))  # full turnover daily
with open("runs/returns.csv","w",newline="") as f:
    csv.writer(f).writerows(rows)
# gross total
tot=1.0
for _,r,_ in rows[1:]: tot*= (1.0+float(r))
print(f"gross total_return = {tot-1.0:.4f}")
