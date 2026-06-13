import os
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(68)
import csv
VOCAB = ["paris", "berlin", "tokyo", "42", "1969", "oxygen", "mercury", "python", "blue", "seven"]
rows = []
for _ in range(600):
    ref = VOCAB[int(next(g) * len(VOCAB)) % len(VOCAB)]
    if next(g) < 0.74:
        pred = ref
    else:
        pred = VOCAB[(VOCAB.index(ref) + 1 + int(next(g) * (len(VOCAB) - 1))) % len(VOCAB)]
        if pred == ref: pred = VOCAB[(VOCAB.index(ref) + 1) % len(VOCAB)]
    rows.append((pred, ref))
with open("runs/answers.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["prediction", "reference"])
    for r in rows: w.writerow(r)
