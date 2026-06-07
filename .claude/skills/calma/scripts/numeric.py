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
    if n == 0:
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
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return float("nan")
    total = math.fsum(_psi(p, q) for p in pos for q in neg)
    return total / (len(pos) * len(neg))


def auc_delong_se(scores, labels):
    """DeLong sampling SE of a single AUC via the structural components V10 (over positives) and
    V01 (over negatives). O(m*n) - exact, fine for verification-scale fixtures."""
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    m, n = len(pos), len(neg)
    if m < 2 or n < 2:
        return float("nan")
    v10 = [math.fsum(_psi(p, q) for q in neg) / n for p in pos]
    v01 = [math.fsum(_psi(p, q) for p in pos) / m for q in neg]
    var = fvar(v10, ddof=1) / m + fvar(v01, ddof=1) / n
    return math.sqrt(var) if var == var and var >= 0 else float("nan")
