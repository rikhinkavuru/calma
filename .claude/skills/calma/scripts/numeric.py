"""calma.numeric - the reference-deterministic numeric kernels.

Every M1 recipe is built from operations that are IEEE-754 correctly-rounded on a given build:
`math.fsum` (correctly-rounded sum), exact multiplication via a pairwise product, and `math.sqrt`
(correctly-rounded). NO platform-libm transcendental (log/exp/pow) appears in any M1 recipe, so the
result is bit-identical on the same Python/build and within a tight envelope across builds - WITHOUT
numpy and WITHOUT a vendored libm. (Transcendental-bearing metrics - e.g. a log-return path - will
route through mpmath at fixed precision when added; the M1 set is transcendental-free by construction.)

HARD RULE enforced by tests: no `import numpy` and no bare np reductions in any recipe path.
"""
import math


def _has_nan(xs):
    return any(not (v == v) for v in xs)


def fmean(xs):
    xs = list(xs)
    return math.fsum(xs) / len(xs)


def fvar(xs, ddof=1):
    xs = list(xs)
    n = len(xs)
    if n - ddof <= 0:
        return float("nan")
    m = fmean(xs)
    return math.fsum((x - m) * (x - m) for x in xs) / (n - ddof)


def fstd(xs, ddof=1):
    v = fvar(xs, ddof)
    return math.sqrt(v) if v == v and v >= 0 else float("nan")


def pairwise_prod(xs):
    """Divide-and-conquer product: deterministic and more accurate than a left fold."""
    xs = list(xs)
    if not xs:
        return 1.0
    while len(xs) > 1:
        xs = [xs[i] * xs[i + 1] for i in range(0, len(xs) - 1, 2)] + (
            [xs[-1]] if len(xs) % 2 else [])
    return xs[0]


def total_return(rets):
    """product(1+r) - 1 over a return series."""
    return pairwise_prod([1.0 + r for r in rets]) - 1.0


def sharpe(rets, periods):
    """Annualised Sharpe. Returns (value, near_zero_vol_flag). Caller degrades to INCONCLUSIVE on flag."""
    rets = list(rets)
    if len(rets) < 2:
        return float("nan"), True
    s = fstd(rets, ddof=1)
    if not (s == s) or s <= 0:
        return float("nan"), True
    return (fmean(rets) / s) * math.sqrt(periods), False


def sharpe_se(sr, T):
    """Sampling SE of an annualised Sharpe (Lo, IID-Gaussian core). skew/kurtosis correction = M3."""
    if T <= 1:
        return float("nan")
    return math.sqrt((1.0 + 0.5 * sr * sr) / T)


def max_drawdown(rets):
    """Worst peak-to-trough on the cumulative-equity curve. Path-dependent (argmin) - the caller
    routes this through the path-dependence condition, never the forward-error budget."""
    if _has_nan(rets):
        return float("nan")
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    for r in rets:
        eq *= (1.0 + r)
        if eq > peak:
            peak = eq
        dd = eq / peak - 1.0
        if dd < mdd:
            mdd = dd
    return mdd


def accuracy(preds, labels):
    n = len(labels)
    if n == 0 or _has_nan(preds) or _has_nan(labels):
        return float("nan")
    correct = sum(1 for p, y in zip(preds, labels) if p == y)
    return correct / n


def _psi(a, b):
    if a > b:
        return 1.0
    if a == b:
        return 0.5
    return 0.0


def auc(scores, labels):
    """AUC = P(score_pos > score_neg) with tie=0.5 (Mann-Whitney). labels in {0,1}."""
    if _has_nan(scores) or _has_nan(labels):
        return float("nan")
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return float("nan")
    total = math.fsum(_psi(p, q) for p in pos for q in neg)
    return total / (len(pos) * len(neg))


def auc_delong_se(scores, labels):
    """DeLong sampling SE of a single AUC via the structural components V10 (over positives) and
    V01 (over negatives). O(m*n) - exact, fine for verification-scale fixtures."""
    if _has_nan(scores) or _has_nan(labels):
        return float("nan")
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    m, n = len(pos), len(neg)
    if m < 2 or n < 2:
        return float("nan")
    v10 = [math.fsum(_psi(p, q) for q in neg) / n for p in pos]
    v01 = [math.fsum(_psi(p, q) for p in pos) / m for q in neg]
    var = fvar(v10, ddof=1) / m + fvar(v01, ddof=1) / n
    return math.sqrt(var) if var == var and var >= 0 else float("nan")


# ---- regression metrics ----
def rmse(pred, actual):
    if len(pred) != len(actual) or not pred or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    return math.sqrt(math.fsum((p - a) * (p - a) for p, a in zip(pred, actual)) / len(pred))


def mae(pred, actual):
    if len(pred) != len(actual) or not pred or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    return math.fsum(abs(p - a) for p, a in zip(pred, actual)) / len(pred)


def r2(pred, actual):
    if len(pred) != len(actual) or len(actual) < 2 or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    m = fmean(actual)
    ss_res = math.fsum((a - p) * (a - p) for p, a in zip(pred, actual))
    ss_tot = math.fsum((a - m) * (a - m) for a in actual)
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


# ---- classification depth (binary 0/1 hard predictions) ----
def _confusion(pred, label):
    tp = fp = fn = tn = 0
    for p, y in zip(pred, label):
        if p == 1 and y == 1:
            tp += 1
        elif p == 1 and y == 0:
            fp += 1
        elif p == 0 and y == 1:
            fn += 1
        else:
            tn += 1
    return tp, fp, fn, tn


def precision(pred, label):
    if _has_nan(pred) or _has_nan(label):
        return float("nan")
    tp, fp, _, _ = _confusion(pred, label)
    return tp / (tp + fp) if (tp + fp) else float("nan")


def recall(pred, label):
    if _has_nan(pred) or _has_nan(label):
        return float("nan")
    tp, _, fn, _ = _confusion(pred, label)
    return tp / (tp + fn) if (tp + fn) else float("nan")


def f1(pred, label):
    pr, rc = precision(pred, label), recall(pred, label)
    if pr != pr or rc != rc or (pr + rc) == 0:
        return float("nan")
    return 2 * pr * rc / (pr + rc)


# ---- column aggregates (analytics / data-pipeline claims) ----
def col_sum(xs):
    return float("nan") if _has_nan(xs) else math.fsum(xs)


def col_mean(xs):
    return float("nan") if (not xs or _has_nan(xs)) else fmean(xs)


def brier(probs, labels):
    """Brier score = mean((p - y)^2) for probabilistic predictions p in [0,1], y in {0,1}. Lower=better."""
    if len(probs) != len(labels) or not probs or _has_nan(probs) or _has_nan(labels):
        return float("nan")
    return math.fsum((p - y) * (p - y) for p, y in zip(probs, labels)) / len(probs)
