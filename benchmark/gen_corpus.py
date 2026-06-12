"""Build a reproducible, labeled benchmark corpus for Calma.

Each base is a deterministic, pure-stdlib project whose entrypoint (gen.py) re-emits a machine-readable
artifact. We compute the TRUE metric value with an INDEPENDENT pure-Python reference (oracle below -
NOT calma's numeric.py), then register two claims per base: an HONEST one (== true value, label "honest")
and a FLAWED one (a plausible-but-wrong overclaim, label "flawed"). Data sizes are 200-1500 rows so a
human/LLM reviewer cannot mentally recompute - which is exactly where re-execution beats eyeballing.

Output: benchmark/cases/<id>/gen.py (+ a run to emit data) and benchmark/manifest.json (ground truth).
Run: python3 benchmark/gen_corpus.py
"""
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(HERE, "cases")


# ----- deterministic data generator (pure-stdlib LCG; identical in gen.py and here) -----
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF


# ----- independent pure-Python ORACLE metrics (the reference; not calma's kernels) -----
def o_accuracy(yt, yp):
    return sum(1 for a, b in zip(yt, yp) if a == b) / len(yt)


def o_precision(yt, yp):
    tp = sum(1 for a, b in zip(yt, yp) if b == 1 and a == 1)
    fp = sum(1 for a, b in zip(yt, yp) if b == 1 and a == 0)
    return tp / (tp + fp) if (tp + fp) else 0.0


def o_recall(yt, yp):
    tp = sum(1 for a, b in zip(yt, yp) if b == 1 and a == 1)
    fn = sum(1 for a, b in zip(yt, yp) if b == 0 and a == 1)
    return tp / (tp + fn) if (tp + fn) else 0.0


def o_f1(yt, yp):
    p, r = o_precision(yt, yp), o_recall(yt, yp)
    return 2 * p * r / (p + r) if (p + r) else 0.0


def o_auc(yt, sc):
    pos = [s for y, s in zip(yt, sc) if y == 1]
    neg = [s for y, s in zip(yt, sc) if y == 0]
    if not pos or not neg:
        return float("nan")
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else (0.5 if p == n else 0.0)
    return wins / (len(pos) * len(neg))


def o_rmse(yt, yp):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(yt, yp)) / len(yt))


def o_mae(yt, yp):
    return sum(abs(a - b) for a, b in zip(yt, yp)) / len(yt)


def o_r2(yt, yp):
    m = sum(yt) / len(yt)
    ss_res = sum((a - b) ** 2 for a, b in zip(yt, yp))
    ss_tot = sum((a - m) ** 2 for a in yt)
    return 1 - ss_res / ss_tot if ss_tot else float("nan")


def o_total_return(r):
    acc = 1.0
    for x in r:
        acc *= (1 + x)
    return acc - 1


def o_sharpe(r):
    n = len(r)
    m = sum(r) / n
    var = sum((x - m) ** 2 for x in r) / (n - 1)
    sd = math.sqrt(var)
    return (m / sd) * math.sqrt(252) if sd else float("nan")


def o_sum(v):
    return sum(v)


def o_mean(v):
    return sum(v) / len(v)


# ----- gen.py templates: self-contained, deterministic, stdlib-only, write runs/<file> -----
_GEN_HEADER = '''import os
os.makedirs("runs", exist_ok=True)
def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF
g = _lcg(%d)
'''


def _emit_classification(seed, n, pos_rate, err_rate, scored=False):
    """y_true ~ Bernoulli(pos_rate); y_pred flips with err_rate; optional score column for AUC."""
    body = _GEN_HEADER % seed + '''rows = []
for _ in range(%d):
    yt = 1 if next(g) < %r else 0
    flip = next(g) < %r
    yp = (1 - yt) if flip else yt
    s = next(g)
    score = max(0.0, min(1.0, (0.55 if yt == 1 else 0.40) + (s - 0.5) * 0.8))  # overlapping -> AUC<1
    rows.append((yt, yp, round(score, 6)))
import csv
with open("runs/preds.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["y_true", "y_pred", "score"])
    for r in rows: w.writerow(r)
''' % (n, pos_rate, err_rate)
    return body


def _emit_regression(seed, n, noise):
    body = _GEN_HEADER % seed + '''import csv
rows = []
for i in range(%d):
    x = next(g) * 10.0
    y_true = 3.0 * x + 2.0
    y_pred = y_true + (next(g) - 0.5) * %r
    rows.append((round(y_true, 6), round(y_pred, 6)))
with open("runs/reg.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["target", "prediction"])
    for r in rows: w.writerow(r)
''' % (n, noise)
    return body


def _emit_returns(seed, n, drift, vol):
    body = _GEN_HEADER % seed + '''import csv
rows = []
for _ in range(%d):
    r = %r + (next(g) - 0.5) * %r
    rows.append((round(r, 8),))
with open("runs/returns.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["daily_return"])
    for r in rows: w.writerow(r)
''' % (n, drift, vol)
    return body


def _emit_values(seed, n, lo, hi):
    body = _GEN_HEADER % seed + '''import csv
rows = []
for _ in range(%d):
    v = %r + next(g) * (%r - %r)
    rows.append((round(v, 6),))
with open("runs/data.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["value"])
    for r in rows: w.writerow(r)
''' % (n, lo, hi, lo)
    return body


def _read_csv(path):
    import csv
    with open(path) as f:
        rd = csv.DictReader(f)
        rows = list(rd)
        cols = {k: [r[k] for r in rows] for k in rows[0]}
    return cols


# (id, metric, gen.py source, artifact, oracle fn over the emitted columns, honest_round, flawed_value)
def _bases():
    specs = []

    def add(cid, metric, src, artifact, oracle, hround, flawed):
        specs.append((cid, metric, src, artifact, oracle, hround, flawed))

    # classification (binds well -> calma can REFUTE)
    add("acc_a", "accuracy", _emit_classification(11, 800, 0.5, 0.18, True), "runs/preds.csv",
        lambda c: o_accuracy([int(x) for x in c["y_true"]], [int(x) for x in c["y_pred"]]), 4, None)
    add("prec_a", "precision", _emit_classification(12, 800, 0.45, 0.2, True), "runs/preds.csv",
        lambda c: o_precision([int(x) for x in c["y_true"]], [int(x) for x in c["y_pred"]]), 4, None)
    add("rec_a", "recall", _emit_classification(13, 800, 0.45, 0.2, True), "runs/preds.csv",
        lambda c: o_recall([int(x) for x in c["y_true"]], [int(x) for x in c["y_pred"]]), 4, None)
    add("f1_a", "f1", _emit_classification(14, 800, 0.4, 0.22, True), "runs/preds.csv",
        lambda c: o_f1([int(x) for x in c["y_true"]], [int(x) for x in c["y_pred"]]), 4, None)
    add("auc_a", "auc", _emit_classification(15, 600, 0.5, 0.25, True), "runs/preds.csv",
        lambda c: o_auc([int(x) for x in c["y_true"]], [float(x) for x in c["score"]]), 4, None)

    # quant (return tag -> independently-bound)
    add("tr_a", "total_return", _emit_returns(21, 500, 0.0008, 0.03), "runs/returns.csv",
        lambda c: o_total_return([float(x) for x in c["daily_return"]]), 4, None)
    add("shp_a", "sharpe", _emit_returns(22, 500, 0.0010, 0.02), "runs/returns.csv",
        lambda c: o_sharpe([float(x) for x in c["daily_return"]]), 3, None)

    # regression (value-family: prediction/target -> calma currently abstains on REFUTE)
    add("rmse_a", "rmse", _emit_regression(31, 700, 4.0), "runs/reg.csv",
        lambda c: o_rmse([float(x) for x in c["target"]], [float(x) for x in c["prediction"]]), 4, None)
    add("mae_a", "mae", _emit_regression(32, 700, 4.0), "runs/reg.csv",
        lambda c: o_mae([float(x) for x in c["target"]], [float(x) for x in c["prediction"]]), 4, None)
    add("r2_a", "r2", _emit_regression(33, 700, 4.0), "runs/reg.csv",
        lambda c: o_r2([float(x) for x in c["target"]], [float(x) for x in c["prediction"]]), 4, None)

    # analytics (value tag -> calma currently abstains on REFUTE)
    add("sum_a", "column_sum", _emit_values(41, 1000, 0.0, 100.0), "runs/data.csv",
        lambda c: o_sum([float(x) for x in c["value"]]), 2, None)
    add("mean_a", "column_mean", _emit_values(42, 1000, 0.0, 100.0), "runs/data.csv",
        lambda c: o_mean([float(x) for x in c["value"]]), 4, None)
    return specs


def _flawed_claim(metric, true_v):
    """An OBVIOUS overclaim - a large margin a reviewer could catch by eyeballing a data sample."""
    if metric in ("rmse", "mae"):
        return round(true_v * 0.55, 4)              # under-report error (looks better)
    if metric in ("accuracy", "precision", "recall", "f1", "auc", "r2"):
        return round(min(0.999, true_v + 0.12), 4)  # inflate a [0,1] score
    if metric == "sharpe":
        return round(true_v + 1.5, 3)               # inflate risk-adjusted return
    if metric == "total_return":
        return round(true_v + 0.5, 4)               # +50pp
    if metric in ("column_sum", "column_mean"):
        return round(true_v * 1.4, 4)               # 40% high
    return round(true_v * 1.5, 4)


def _subtle_claim(metric, true_v):
    """A SUBTLE misreport: small but real (rounding in your favor / a few points). Beyond calma's
    statistical band so it deterministically REFUTES, yet within the noise of eyeballing a sample -
    where an LLM-as-judge cannot reliably tell it from the truth. This is the differentiator."""
    if metric in ("rmse", "mae"):
        return round(true_v * 0.90, 4)              # 10% under-report
    if metric in ("accuracy", "precision", "recall", "f1", "auc", "r2"):
        return round(min(0.999, true_v + 0.05), 4)  # +5 points
    if metric == "sharpe":
        return round(true_v + 0.5, 3)
    if metric == "total_return":
        return round(true_v + 0.06, 4)              # +6pp
    if metric in ("column_sum", "column_mean"):
        return round(true_v * 1.04, 4)              # 4% high
    return round(true_v * 1.08, 4)


def main():
    import shutil
    shutil.rmtree(CASES, ignore_errors=True)
    os.makedirs(CASES)
    manifest = []
    for cid, metric, src, artifact, oracle, hround, _ in _bases():
        d = os.path.join(CASES, cid)
        os.makedirs(d)
        with open(os.path.join(d, "gen.py"), "w") as f:
            f.write(src)
        subprocess.run([sys.executable, "gen.py"], cwd=d, check=True, capture_output=True)
        cols = _read_csv(os.path.join(d, artifact))
        true_v = oracle(cols)
        honest = round(true_v, hround)
        n = len(next(iter(cols.values())))
        manifest.append({"id": cid + "_honest", "dir": d, "metric": metric, "n_rows": n,
                         "true_value": true_v, "claim": honest, "label": "honest", "tier": "honest"})
        manifest.append({"id": cid + "_obvious", "dir": d, "metric": metric, "n_rows": n,
                         "true_value": true_v, "claim": _flawed_claim(metric, true_v),
                         "label": "flawed", "tier": "obvious"})
        manifest.append({"id": cid + "_subtle", "dir": d, "metric": metric, "n_rows": n,
                         "true_value": true_v, "claim": _subtle_claim(metric, true_v),
                         "label": "flawed", "tier": "subtle"})
    with open(os.path.join(HERE, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print("built %d cases (%d bases) -> %s" % (len(manifest), len(manifest) // 2, CASES))
    for m in manifest:
        print("  %-16s %-14s true=%.4f claim=%.4f [%s]"
              % (m["id"], m["metric"], m["true_value"], m["claim"], m["label"]))


if __name__ == "__main__":
    main()
