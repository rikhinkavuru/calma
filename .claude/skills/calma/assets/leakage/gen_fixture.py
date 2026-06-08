#!/usr/bin/env python3
"""Calma corpus fixture: reproduce the DATA-LEAKAGE pattern that inflates a headline metric.

Grounded in the documented civil-war-onset RF case (Muchlinski et al.; critiqued by Wang 2019 and the
Kapoor-Narayanan leakage corpus): a model TRAINED ON THE WHOLE DATASET and then evaluated on the same
rows reports an inflated AUC (~0.97); evaluated honestly on HELD-OUT data the number collapses. The
original replication is R; this is a faithful, self-contained PYTHON reproduction (pure stdlib logistic
regression, seeded, NO network) that emits the held-out predictions Calma recomputes from.

Emits runs/preds_holdout.csv (score,label) - the honest artifact. Prints the LEAKED (train=test) AUC,
which is the author's headline claim. Run: python3 gen_fixture.py
"""
import csv
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
random.seed(20260607)


def sigmoid(z):
    if z < -700:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def make_data(n, d_signal, d_noise):
    d = d_signal + d_noise
    w_true = [random.gauss(0, 1.4) for _ in range(d_signal)] + [0.0] * d_noise
    X, y = [], []
    for _ in range(n):
        x = [random.gauss(0, 1) for _ in range(d)]
        z = sum(w_true[j] * x[j] for j in range(d_signal))
        p = sigmoid(z)
        y.append(1 if random.random() < p else 0)
        X.append(x)
    return X, y


def train(X, y, epochs=400, lr=0.3, l2=0.0):
    n, d = len(X), len(X[0])
    w = [0.0] * d
    b = 0.0
    for _ in range(epochs):
        gw = [0.0] * d
        gb = 0.0
        for i in range(n):
            p = sigmoid(sum(w[j] * X[i][j] for j in range(d)) + b)
            e = p - y[i]
            for j in range(d):
                gw[j] += e * X[i][j]
            gb += e
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j])
        b -= lr * gb / n
    return w, b


def predict(w, b, X):
    return [sigmoid(sum(w[j] * x[j] for j in range(len(x))) + b) for x in X]


def auc(scores, labels):
    pos = [s for s, l in zip(scores, labels) if l == 1]
    neg = [s for s, l in zip(scores, labels) if l == 0]
    if not pos or not neg:
        return float("nan")
    c = sum((1.0 if p > q else 0.5 if p == q else 0.0) for p in pos for q in neg)
    return c / (len(pos) * len(neg))


def main():
    # many noise features relative to n -> the in-sample fit memorizes noise (the leak)
    X, y = make_data(n=500, d_signal=6, d_noise=80)
    split = int(len(X) * 0.7)
    Xtr, ytr, Xte, yte = X[:split], y[:split], X[split:], y[split:]

    # THE LEAK: train on ALL rows, then "evaluate" on the same rows -> inflated AUC (author's claim)
    w_leak, b_leak = train(X, y)
    leaked = auc(predict(w_leak, b_leak, X), y)

    # HONEST: train on train split, predict the held-out split -> the artifact Calma recomputes
    w_h, b_h = train(Xtr, ytr)
    pte = predict(w_h, b_h, Xte)
    honest = auc(pte, yte)

    outdir = os.path.join(HERE, "runs")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "preds_holdout.csv"), "w", newline="") as fh:
        wri = csv.writer(fh)
        wri.writerow(["score", "label"])
        for s, l in zip(pte, yte):
            wri.writerow([repr(s), l])
    import json
    print(json.dumps({"claimed_leaked_auc": round(leaked, 4), "honest_holdout_auc": round(honest, 4),
                      "n": len(X), "n_holdout": len(Xte)}))


if __name__ == "__main__":
    main()
