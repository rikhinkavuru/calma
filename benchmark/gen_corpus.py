"""Build a reproducible, labeled benchmark corpus for Calma — comprehensive edition.

28 metric bases across 8 families (classification, retrieval/LLM-eval, regression, forecasting,
quant, analytics, engineering, stats). Each base is a deterministic, pure-stdlib project whose
entrypoint (gen.py) re-emits a machine-readable artifact. The TRUE metric value comes from an
INDEPENDENT pure-Python reference (the oracles below — NOT calma's numeric.py), and every oracle
is additionally cross-validated against scikit-learn / SciPy / NumPy reference implementations by
benchmark/validate_oracles.py (the external-credibility step).

Per base, three labeled claims:
  honest  — claim == true value                       (must CONFIRM)
  obvious — a large misreport, eyeball-catchable      (must REFUTE)
  subtle  — small but real (a few points / ~4-10%),   (must REFUTE — beyond calma's calibrated
            inside eyeballing noise on a data sample    budget, invisible to sample inspection)

Flaw direction is sign-aware: "higher is better" metrics get inflated, "lower is better" metrics
(log_loss, rmse, error_rate, latency, volatility, ...) get under-reported — the direction people
actually shade numbers.

Output: benchmark/cases/<id>/gen.py (+ emitted data) and benchmark/manifest.json (ground truth).
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


def o_log_loss(probs, yt):
    return -sum(math.log(p) if y == 1 else math.log(1 - p) for p, y in zip(probs, yt)) / len(yt)


def o_brier(probs, yt):
    return sum((p - y) ** 2 for p, y in zip(probs, yt)) / len(yt)


def o_mcc(yt, yp):
    tp = sum(1 for a, b in zip(yt, yp) if a == 1 and b == 1)
    tn = sum(1 for a, b in zip(yt, yp) if a == 0 and b == 0)
    fp = sum(1 for a, b in zip(yt, yp) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(yt, yp) if a == 1 and b == 0)
    den = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    return (tp * tn - fp * fn) / den if den else 0.0


def o_balanced_accuracy(yt, yp):
    rec = []
    for c in sorted(set(yt)):
        n_c = sum(1 for y in yt if y == c)
        tp = sum(1 for y, p in zip(yt, yp) if y == c and p == c)
        rec.append(tp / n_c)
    return sum(rec) / len(rec)


def o_average_precision(yt, sc):
    """AP with distinct scores (the generator guarantees no ties): sum of P@k at each relevant k."""
    order = sorted(range(len(sc)), key=lambda i: -sc[i])
    n_pos = sum(yt)
    hits, ap = 0, 0.0
    for rank, i in enumerate(order, start=1):
        if yt[i] == 1:
            hits += 1
            ap += hits / rank
    return ap / n_pos if n_pos else float("nan")


def o_recall_at_k(queries, ranks, rels, k):
    per = {}
    for q, r, rel in zip(queries, ranks, rels):
        per.setdefault(q, []).append((r, rel))
    scores = []
    for q, rows in per.items():
        rows.sort()
        total = sum(1 for _, rel in rows if rel > 0)
        if total == 0:
            continue
        scores.append(sum(1 for r, rel in rows[:k] if rel > 0) / total)
    return sum(scores) / len(scores)


def o_mrr(queries, ranks, rels):
    per = {}
    for q, r, rel in zip(queries, ranks, rels):
        per.setdefault(q, []).append((r, rel))
    scores = []
    for q, rows in per.items():
        rows.sort()
        rr = 0.0
        for pos, (_, rel) in enumerate(rows, start=1):
            if rel > 0:
                rr = 1.0 / pos
                break
        scores.append(rr)
    return sum(scores) / len(scores)


def o_exact_match(preds, refs):
    return sum(1 for p, r in zip(preds, refs) if p == r) / len(preds)


def o_rmse(yt, yp):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(yt, yp)) / len(yt))


def o_mae(yt, yp):
    return sum(abs(a - b) for a, b in zip(yt, yp)) / len(yt)


def o_r2(yt, yp):
    m = sum(yt) / len(yt)
    ss_res = sum((a - b) ** 2 for a, b in zip(yt, yp))
    ss_tot = sum((a - m) ** 2 for a in yt)
    return 1 - ss_res / ss_tot if ss_tot else float("nan")


def o_mape(yp, yt):
    return sum(abs(p - a) / abs(a) for p, a in zip(yp, yt)) / len(yt)


def o_total_return(r):
    acc = 1.0
    for x in r:
        acc *= (1 + x)
    return acc - 1


def _std1(xs):
    n = len(xs)
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def o_sharpe(r):
    sd = _std1(r)
    return (sum(r) / len(r) / sd) * math.sqrt(252) if sd else float("nan")


def o_volatility(r):
    return _std1(r) * math.sqrt(252)


def o_sortino(r):
    dd2 = sum(min(x, 0.0) ** 2 for x in r) / len(r)
    return (sum(r) / len(r)) / math.sqrt(dd2) * math.sqrt(252) if dd2 > 0 else float("nan")


def o_cagr(values):
    years = len(values) - 1  # periods_per_year defaults to 1 (annual series)
    return (values[-1] / values[0]) ** (1.0 / years) - 1.0


def o_sum(v):
    return sum(v)


def o_mean(v):
    return sum(v) / len(v)


def o_median(v):
    ys = sorted(v)
    n = len(ys)
    return float(ys[n // 2]) if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2.0


def o_p95(v):
    """numpy default 'linear' interpolation (method 7)."""
    ys = sorted(v)
    h = (len(ys) - 1) * 0.95
    lo = int(math.floor(h))
    frac = h - lo
    return float(ys[lo]) if frac == 0 else ys[lo] + frac * (ys[lo + 1] - ys[lo])


def o_error_rate(flags):
    return sum(1 for f in flags if f != 0) / len(flags)


def o_pearson(xs, ys):
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy)


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


def _emit_classification(seed, n, pos_rate, err_rate):
    """y_true ~ Bernoulli(pos_rate); y_pred flips with err_rate; overlapping score column (AUC<1)."""
    return _GEN_HEADER % seed + '''rows = []
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


def _emit_proba(seed, n, sep):
    """Calibrated-ish probabilities bounded away from 0/1 (log_loss exact mode stays finite),
    DISTINCT scores (no ties - AP/AUC conventions all agree). Columns: y_true, prob."""
    return _GEN_HEADER % seed + '''rows = []
for i in range(%d):
    yt = 1 if next(g) < 0.5 else 0
    u = next(g)
    base = (0.5 + %r * (u - 0.25)) if yt == 1 else (0.5 - %r * (u - 0.25))
    p = max(0.05, min(0.95, base)) + i * 1e-9          # distinct by construction
    rows.append((yt, round(p, 9)))
import csv
with open("runs/preds.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["y_true", "prob"])
    for r in rows: w.writerow(r)
''' % (n, sep, sep)


def _emit_retrieval(seed, n_queries, per_q):
    """IR run: per query, docs at ranks 1..per_q with relevance decaying in rank."""
    return _GEN_HEADER % seed + '''import csv
rows = []
for qi in range(%d):
    for rank in range(1, %d + 1):
        p_rel = max(0.05, 0.7 - 0.08 * (rank - 1))
        rel = 1 if next(g) < p_rel else 0
        rows.append(("q%%03d" %% qi, rank, rel))
with open("runs/results.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["query", "rank", "relevance"])
    for r in rows: w.writerow(r)
''' % (n_queries, per_q)


def _emit_strings(seed, n, match_rate):
    """LLM-eval answers: prediction == reference with match_rate, else a different token."""
    return _GEN_HEADER % seed + '''import csv
VOCAB = ["paris", "berlin", "tokyo", "42", "1969", "oxygen", "mercury", "python", "blue", "seven"]
rows = []
for _ in range(%d):
    ref = VOCAB[int(next(g) * len(VOCAB)) %% len(VOCAB)]
    if next(g) < %r:
        pred = ref
    else:
        pred = VOCAB[(VOCAB.index(ref) + 1 + int(next(g) * (len(VOCAB) - 1))) %% len(VOCAB)]
        if pred == ref: pred = VOCAB[(VOCAB.index(ref) + 1) %% len(VOCAB)]
    rows.append((pred, ref))
with open("runs/answers.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["prediction", "reference"])
    for r in rows: w.writerow(r)
''' % (n, match_rate)


def _emit_regression(seed, n, noise):
    return _GEN_HEADER % seed + '''import csv
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


def _emit_forecast(seed, n, level, noise):
    """Positive actuals away from zero (MAPE-safe) + a forecast with relative error."""
    return _GEN_HEADER % seed + '''import csv
rows = []
for _ in range(%d):
    a = %r + next(g) * %r
    p = a * (1.0 + (next(g) - 0.5) * 0.3)
    rows.append((round(a, 6), round(p, 6)))
with open("runs/forecast.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["target", "prediction"])
    for r in rows: w.writerow(r)
''' % (n, level, noise)


def _emit_returns(seed, n, drift, vol):
    return _GEN_HEADER % seed + '''import csv
rows = []
for _ in range(%d):
    r = %r + (next(g) - 0.5) * %r
    rows.append((round(r, 8),))
with open("runs/returns.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["daily_return"])
    for r in rows: w.writerow(r)
''' % (n, drift, vol)


def _emit_equity(seed, n_years, growth, noise):
    """An annual revenue series compounding at ~growth with noise (CAGR base)."""
    return _GEN_HEADER % seed + '''import csv
rows = []
v = 1000.0
rows.append((round(v, 2),))
for _ in range(%d - 1):
    v *= 1.0 + %r + (next(g) - 0.5) * %r
    rows.append((round(v, 2),))
with open("runs/revenue.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["revenue"])
    for r in rows: w.writerow(r)
''' % (n_years, growth, noise)


def _emit_values(seed, n, lo, hi):
    return _GEN_HEADER % seed + '''import csv
rows = []
for _ in range(%d):
    v = %r + next(g) * (%r - %r)
    rows.append((round(v, 6),))
with open("runs/data.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["value"])
    for r in rows: w.writerow(r)
''' % (n, lo, hi, lo)


def _emit_latency(seed, n):
    """Right-skewed request latencies in ms (sum of uniforms, squared - long tail)."""
    return _GEN_HEADER % seed + '''import csv
rows = []
for _ in range(%d):
    base = 40.0 + 220.0 * (next(g) ** 2) + 120.0 * next(g)
    rows.append((round(base, 3),))
with open("runs/latency_ms.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["latency_ms"])
    for r in rows: w.writerow(r)
''' % n


def _emit_flags(seed, n, rate):
    return _GEN_HEADER % seed + '''import csv
rows = []
for _ in range(%d):
    rows.append((1 if next(g) < %r else 0,))
with open("runs/requests.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["error"])
    for r in rows: w.writerow(r)
''' % (n, rate)


def _emit_xy(seed, n, slope, noise):
    return _GEN_HEADER % seed + '''import csv
rows = []
for _ in range(%d):
    x = next(g) * 20.0
    y = %r * x + (next(g) - 0.5) * %r
    rows.append((round(x, 6), round(y, 6)))
with open("runs/pairs.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["x", "y"])
    for r in rows: w.writerow(r)
''' % (n, slope, noise)


def _read_csv(path):
    import csv
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return {k: [r[k] for r in rows] for k in rows[0]}


def _f(col):
    return [float(x) for x in col]


def _i(col):
    return [int(x) for x in col]


# (id, metric, family, gen-src, artifact, oracle, honest_round, claim_text_fmt, display)
def _bases():
    B = []

    def add(cid, metric, family, src, artifact, oracle, hround=4, fmt=None, display=None):
        B.append((cid, metric, family, src, artifact, oracle, hround,
                  fmt or (metric.replace("_", " ") + " %s"), display or metric))

    # ---- classification (9) ----
    add("acc_a", "accuracy", "classification", _emit_classification(11, 800, 0.5, 0.18), "runs/preds.csv",
        lambda c: o_accuracy(_i(c["y_true"]), _i(c["y_pred"])))
    add("prec_a", "precision", "classification", _emit_classification(12, 800, 0.45, 0.2), "runs/preds.csv",
        lambda c: o_precision(_i(c["y_true"]), _i(c["y_pred"])))
    add("rec_a", "recall", "classification", _emit_classification(13, 800, 0.45, 0.2), "runs/preds.csv",
        lambda c: o_recall(_i(c["y_true"]), _i(c["y_pred"])))
    add("f1_a", "f1", "classification", _emit_classification(14, 800, 0.4, 0.22), "runs/preds.csv",
        lambda c: o_f1(_i(c["y_true"]), _i(c["y_pred"])))
    add("auc_a", "auc", "classification", _emit_classification(15, 600, 0.5, 0.25), "runs/preds.csv",
        lambda c: o_auc(_i(c["y_true"]), _f(c["score"])))
    add("logl_a", "log_loss", "classification", _emit_proba(61, 900, 0.9), "runs/preds.csv",
        lambda c: o_log_loss(_f(c["prob"]), _i(c["y_true"])))
    add("brier_a", "brier", "classification", _emit_proba(62, 900, 0.8), "runs/preds.csv",
        lambda c: o_brier(_f(c["prob"]), _i(c["y_true"])))
    add("mcc_a", "mcc", "classification", _emit_classification(63, 900, 0.5, 0.22), "runs/preds.csv",
        lambda c: o_mcc(_i(c["y_true"]), _i(c["y_pred"])))
    add("bacc_a", "balanced_accuracy", "classification", _emit_classification(64, 900, 0.35, 0.2),
        "runs/preds.csv", lambda c: o_balanced_accuracy(_i(c["y_true"]), _i(c["y_pred"])))

    # ---- retrieval / LLM-eval (4) ----
    add("prauc_a", "pr_auc", "retrieval", _emit_proba(65, 700, 0.85), "runs/preds.csv",
        lambda c: o_average_precision(_i(c["y_true"]), _f(c["prob"])))
    add("rk_a", "recall_at_k", "retrieval", _emit_retrieval(66, 60, 10), "runs/results.csv",
        lambda c: o_recall_at_k(c["query"], _i(c["rank"]), _i(c["relevance"]), 5),
        fmt="recall@5 %s", display="recall@5")
    add("mrr_a", "mrr", "retrieval", _emit_retrieval(67, 60, 10), "runs/results.csv",
        lambda c: o_mrr(c["query"], _i(c["rank"]), _i(c["relevance"])))
    add("em_a", "exact_match", "retrieval", _emit_strings(68, 600, 0.74), "runs/answers.csv",
        lambda c: o_exact_match(c["prediction"], c["reference"]))

    # ---- regression + forecasting (4) ----
    add("rmse_a", "rmse", "regression", _emit_regression(31, 700, 4.0), "runs/reg.csv",
        lambda c: o_rmse(_f(c["target"]), _f(c["prediction"])))
    add("mae_a", "mae", "regression", _emit_regression(32, 700, 4.0), "runs/reg.csv",
        lambda c: o_mae(_f(c["target"]), _f(c["prediction"])))
    add("r2_a", "r2", "regression", _emit_regression(33, 700, 12.0), "runs/reg.csv",
        lambda c: o_r2(_f(c["target"]), _f(c["prediction"])))
    add("mape_a", "mape", "forecasting", _emit_forecast(69, 600, 50.0, 100.0), "runs/forecast.csv",
        lambda c: o_mape(_f(c["prediction"]), _f(c["target"])))

    # ---- quant (5) ----
    add("tr_a", "total_return", "quant", _emit_returns(21, 500, 0.0008, 0.03), "runs/returns.csv",
        lambda c: o_total_return(_f(c["daily_return"])))
    add("shp_a", "sharpe", "quant", _emit_returns(22, 500, 0.0010, 0.02), "runs/returns.csv",
        lambda c: o_sharpe(_f(c["daily_return"])), 3)
    add("vol_a", "volatility", "quant", _emit_returns(70, 504, 0.0004, 0.025), "runs/returns.csv",
        lambda c: o_volatility(_f(c["daily_return"])), 4)
    add("srt_a", "sortino", "quant", _emit_returns(71, 504, 0.0012, 0.022), "runs/returns.csv",
        lambda c: o_sortino(_f(c["daily_return"])), 3)
    add("cagr_a", "cagr", "quant", _emit_equity(72, 9, 0.13, 0.06), "runs/revenue.csv",
        lambda c: o_cagr(_f(c["revenue"])), 4)

    # ---- analytics (3) ----
    add("sum_a", "column_sum", "analytics", _emit_values(41, 1000, 0.0, 100.0), "runs/data.csv",
        lambda c: o_sum(_f(c["value"])), 2)
    add("mean_a", "column_mean", "analytics", _emit_values(42, 1000, 0.0, 100.0), "runs/data.csv",
        lambda c: o_mean(_f(c["value"])))
    add("med_a", "column_median", "analytics", _emit_values(73, 1101, 5.0, 250.0), "runs/data.csv",
        lambda c: o_median(_f(c["value"])), 3)

    # ---- engineering (2) ----
    add("p95_a", "latency_p95", "engineering", _emit_latency(74, 1500), "runs/latency_ms.csv",
        lambda c: o_p95(_f(c["latency_ms"])), 1, fmt="p95 latency %s ms", display="latency p95 (ms)")
    add("err_a", "error_rate", "engineering", _emit_flags(75, 2000, 0.06), "runs/requests.csv",
        lambda c: o_error_rate(_f(c["error"])), 4)

    # ---- stats (1) ----
    add("corr_a", "correlation", "stats", _emit_xy(76, 800, 0.8, 9.0), "runs/pairs.csv",
        lambda c: o_pearson(_f(c["x"]), _f(c["y"])), 4, fmt="pearson correlation %s")
    return B


# lower-is-better metrics get UNDER-reported (the way people actually shade them)
LOWER_IS_BETTER = {"log_loss", "brier", "rmse", "mae", "mape", "error_rate", "latency_p95", "volatility"}
UNIT_RANGE = {"accuracy", "precision", "recall", "f1", "auc", "mcc", "balanced_accuracy", "pr_auc",
              "recall_at_k", "mrr", "exact_match", "r2", "correlation"}


def _flawed_claim(metric, true_v):
    """OBVIOUS misreport - a large margin a reviewer could catch by eyeballing a data sample."""
    if metric in LOWER_IS_BETTER:
        return round(true_v * 0.55, 4)
    if metric in UNIT_RANGE:
        return round(min(0.999, true_v + 0.12), 4)
    if metric in ("sharpe", "sortino"):
        return round(true_v + 1.5, 3)
    if metric == "total_return":
        return round(true_v + 0.5, 4)
    if metric == "cagr":
        return round(true_v + 0.08, 4)
    return round(true_v * 1.4, 4)          # sums/means/medians: 40% high


def _subtle_claim(metric, true_v):
    """SUBTLE misreport: small but real (rounding in your favor / a few points). Beyond calma's
    calibrated budget so it deterministically REFUTES, yet within the noise of eyeballing a sample."""
    if metric in LOWER_IS_BETTER:
        return round(true_v * 0.90, 4)
    if metric in UNIT_RANGE:
        return round(min(0.999, true_v + 0.05), 4)
    if metric in ("sharpe", "sortino"):
        return round(true_v + 0.5, 3)
    if metric == "total_return":
        return round(true_v + 0.06, 4)
    if metric == "cagr":
        return round(true_v + 0.02, 4)
    return round(true_v * 1.04, 4)          # 4% high


def main():
    import shutil
    shutil.rmtree(CASES, ignore_errors=True)
    os.makedirs(CASES)
    manifest = []
    for cid, metric, family, src, artifact, oracle, hround, fmt, display in _bases():
        d = os.path.join(CASES, cid)
        os.makedirs(d)
        with open(os.path.join(d, "gen.py"), "w") as f:
            f.write(src)
        subprocess.run([sys.executable, "gen.py"], cwd=d, check=True, capture_output=True)
        cols = _read_csv(os.path.join(d, artifact))
        true_v = oracle(cols)
        n = len(next(iter(cols.values())))
        for label, tier, claim in (
                ("honest", "honest", round(true_v, hround)),
                ("flawed", "obvious", _flawed_claim(metric, true_v)),
                ("flawed", "subtle", _subtle_claim(metric, true_v))):
            manifest.append({"id": "%s_%s" % (cid, tier), "dir": d, "metric": metric,
                             "family": family, "display": display, "n_rows": n,
                             "artifact": artifact, "track": "synthetic",
                             "true_value": true_v, "claim": claim,
                             "claim_text": fmt % claim, "label": label, "tier": tier})
    with open(os.path.join(HERE, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    fams = {}
    for m in manifest:
        fams.setdefault(m["family"], set()).add(m["metric"])
    print("built %d cases (%d bases, %d families) -> %s"
          % (len(manifest), len(manifest) // 3, len(fams), CASES))
    for fam, mets in sorted(fams.items()):
        print("  %-14s %s" % (fam, ", ".join(sorted(mets))))
    for m in manifest:
        if m["tier"] == "honest":
            print("  %-10s %-18s true=%.6g" % (m["id"][:-7], m["metric"], m["true_value"]))


if __name__ == "__main__":
    main()
