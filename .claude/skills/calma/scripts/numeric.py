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


# ======================================================================================
# Deterministic transcendental kernels.
#
# The hard rule stands: no platform-libm transcendental (math.log/exp/pow/lgamma/erf)
# in any recipe path. Metrics that need ln/exp/log2/lgamma/incomplete-beta/incomplete-
# gamma (log_loss, ndcg, p_value, chi_square, ece, confidence_interval) use THESE
# kernels, built only from IEEE-754 correctly-rounded primitives: + - * / sqrt, fsum,
# frexp/ldexp (exact). Every loop terminates on a pure-float condition, so results are
# bit-identical on any IEEE-754 double platform - same guarantee as the M1 set.
# Accuracy is ~1-2 ulp for dlog/dexp and <=1e-13 relative for the composed special
# functions - validated against SciPy reference vectors in test_recipes_sota.py.
# ======================================================================================

_LN2_HI = 6.93147180369123816490e-01   # fdlibm hi/lo split of ln 2 (hi has trailing zeros,
_LN2_LO = 1.90821492927058770002e-10   # so k*_LN2_HI is exact for modest integer k)
_LN2 = 0.6931471805599453
_LOG2E = 1.4426950408889634
_SQRT_HALF = 0.7071067811865476
_LN_SQRT_2PI = 0.9189385332046727
_SQRT2 = 1.4142135623730951


def dlog(x):
    """Deterministic natural log: frexp range-reduction + atanh series under fsum."""
    if x != x:
        return x
    if x < 0.0:
        return float("nan")
    if x == 0.0:
        return float("-inf")
    if x == float("inf"):
        return x
    m, e = math.frexp(x)            # x = m * 2^e, m in [0.5, 1)
    if m < _SQRT_HALF:              # recenter m into [sqrt(.5), sqrt(2)) so |t| <= 0.1716
        m *= 2.0
        e -= 1
    t = (m - 1.0) / (m + 1.0)
    t2 = t * t
    term = t
    parts = [t]
    for k in range(3, 61, 2):       # ln(m) = 2*(t + t^3/3 + t^5/5 + ...)
        term *= t2
        parts.append(term / k)
        if abs(term) < 1e-20:
            break
    lnm = 2.0 * math.fsum(parts)
    return math.fsum([e * _LN2_HI, e * _LN2_LO, lnm])


def dlog2(x):
    return dlog(x) * _LOG2E


def dexp(x):
    """Deterministic exp: k*ln2 range-reduction (hi/lo) + Taylor under fsum + exact ldexp."""
    if x != x:
        return x
    if x > 709.782712893384:
        return float("inf")
    if x < -745.2:
        return 0.0
    k = math.floor(x * _LOG2E + 0.5)
    r = (x - k * _LN2_HI) - k * _LN2_LO     # |r| <= ln2/2
    term = 1.0
    parts = [1.0]
    for i in range(1, 30):
        term = term * r / i
        parts.append(term)
        if abs(term) < 1e-20:
            break
    return math.ldexp(math.fsum(parts), int(k))


_LANCZOS_G = 7.0
_LANCZOS = (0.99999999999980993, 676.5203681218851, -1259.1392167224028,
            771.32342877765313, -176.61502916214059, 12.507343278686905,
            -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7)


def dlgamma(z):
    """Deterministic log-gamma for z > 0 (Lanczos g=7,n=9; z<0.5 via the recurrence -
    the negative axis is never needed by any recipe)."""
    if z != z or z <= 0.0:
        return float("nan")
    if z < 0.5:
        return dlgamma(z + 1.0) - dlog(z)
    zz = z - 1.0
    a = math.fsum([_LANCZOS[0]] + [_LANCZOS[i] / (zz + i) for i in range(1, 9)])
    t = zz + _LANCZOS_G + 0.5
    return _LN_SQRT_2PI + (zz + 0.5) * dlog(t) - t + dlog(a)


def _betacf(a, b, x):
    """Continued fraction for the regularized incomplete beta (modified Lentz)."""
    MAXIT, EPS, FPMIN = 300, 3e-16, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return h


def betainc_reg(a, b, x):
    """Regularized incomplete beta I_x(a,b), a,b > 0, x in [0,1]."""
    if a != a or b != b or x != x or a <= 0.0 or b <= 0.0:
        return float("nan")
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_bt = dlgamma(a + b) - dlgamma(a) - dlgamma(b) + a * dlog(x) + b * dlog(1.0 - x)
    bt = dexp(ln_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def gammainc_upper_reg(s, x):
    """Regularized upper incomplete gamma Q(s,x), s > 0, x >= 0 (series / Lentz CF)."""
    if s != s or x != x or s <= 0.0 or x < 0.0:
        return float("nan")
    if x == 0.0:
        return 1.0
    if x < s + 1.0:
        ap = s
        term = 1.0 / s
        total = term
        for _ in range(500):
            ap += 1.0
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-17:
                break
        return 1.0 - total * dexp(-x + s * dlog(x) - dlgamma(s))
    FPMIN = 1e-300
    b = x + 1.0 - s
    c = 1.0 / FPMIN
    d = 1.0 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - s)
        b += 2.0
        d = an * d + b
        if abs(d) < FPMIN:
            d = FPMIN
        c = b + an / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < 1e-16:
            break
    return dexp(-x + s * dlog(x) - dlgamma(s)) * h


def derfc(x):
    """Deterministic erfc via the incomplete gamma: erfc(x) = Q(1/2, x^2) for x >= 0."""
    if x != x:
        return x
    if x >= 0.0:
        return gammainc_upper_reg(0.5, x * x)
    return 2.0 - gammainc_upper_reg(0.5, x * x)


def normal_sf(z):
    """P(Z > z) for standard normal."""
    return 0.5 * derfc(z / _SQRT2)


def t_sf_two_sided(t, df):
    """Two-sided p of a t statistic: I_{df/(df+t^2)}(df/2, 1/2)."""
    if t != t or df != df or df <= 0:
        return float("nan")
    return betainc_reg(df / 2.0, 0.5, df / (df + t * t))


def chi2_sf(x, df):
    """Chi-square survival function Q(df/2, x/2)."""
    if x != x or df <= 0:
        return float("nan")
    if x < 0:
        return 1.0
    return gammainc_upper_reg(df / 2.0, x / 2.0)


def _bisect_inv(f, target, lo, hi, iters=200):
    """Deterministic bisection for a DECREASING f: find x with f(x) = target. Pure-float
    midpoints converge to adjacent doubles well inside `iters`; no tolerance knob."""
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if mid <= lo or mid >= hi:
            break
        if f(mid) > target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def t_ppf_two_sided(alpha, df):
    """Critical t with two-sided tail mass alpha (e.g. alpha=0.05 -> the 95% CI multiplier)."""
    if not (0.0 < alpha < 1.0) or df <= 0:
        return float("nan")
    hi = 2.0
    while t_sf_two_sided(hi, df) > alpha and hi < 1e10:
        hi *= 2.0
    return _bisect_inv(lambda t: t_sf_two_sided(t, df), alpha, 0.0, hi)


def z_ppf_two_sided(alpha):
    """Critical z with two-sided tail mass alpha."""
    if not (0.0 < alpha < 1.0):
        return float("nan")
    hi = 2.0
    while 2.0 * normal_sf(hi) > alpha and hi < 1e3:
        hi *= 2.0
    return _bisect_inv(lambda z: 2.0 * normal_sf(z), alpha, 0.0, hi)


# ======================================================================================
# Pack 1 - performance & engineering kernels
# ======================================================================================

def quantile(xs, q, method="linear"):
    """Quantile with numpy's default 'linear' interpolation (method 7). q in [0,1]."""
    xs = list(xs)
    if not xs or _has_nan(xs) or q != q or not (0.0 <= q <= 1.0):
        return float("nan")
    ys = sorted(xs)
    n = len(ys)
    if n == 1:
        return float(ys[0])
    h = (n - 1) * q
    lo = int(math.floor(h))
    frac = h - lo
    if frac == 0.0:
        return float(ys[lo])
    return ys[lo] + frac * (ys[lo + 1] - ys[lo])


def speedup_ratio(before, after, mode="mean"):
    """before/after recomputed from raw timing columns: mean(before)/mean(after) (or medians)."""
    if not before or not after or _has_nan(before) or _has_nan(after):
        return float("nan")
    if mode == "median":
        num, den = quantile(before, 0.5), quantile(after, 0.5)
    else:
        num, den = fmean(before), fmean(after)
    return num / den if den > 0 else float("nan")


def throughput(durations):
    """Ops per unit time from a column of per-op durations: n / sum(durations)."""
    if not durations or _has_nan(durations):
        return float("nan")
    total = math.fsum(durations)
    return len(durations) / total if total > 0 else float("nan")


def peak(xs):
    """Max of a sampled series (peak memory etc.)."""
    if not xs or _has_nan(xs):
        return float("nan")
    return float(max(xs))


def coverage_fraction(hits):
    """Line coverage recomputed from raw per-line hit counts: lines with hits>0 / lines."""
    if not hits or _has_nan(hits):
        return float("nan")
    return sum(1 for h in hits if h > 0) / len(hits)


def error_rate(flags, mode="flag"):
    """Failures over totals. 'flag': nonzero = error. 'http4xx': status >= 400. 'http5xx': >= 500."""
    if not flags or _has_nan(flags):
        return float("nan")
    if mode == "http4xx":
        bad = sum(1 for v in flags if v >= 400)
    elif mode == "http5xx":
        bad = sum(1 for v in flags if v >= 500)
    else:
        bad = sum(1 for v in flags if v != 0)
    return bad / len(flags)


# ======================================================================================
# Pack 2 - analytics kernels (string-column kernels take raw cell strings)
# ======================================================================================

_NULL_TOKENS = ("", "nan", "na", "null", "none")


def _is_null_str(s):
    return s.strip().lower() in _NULL_TOKENS


def null_fraction(raw):
    """Fraction of cells that are empty/NaN/NA/null/None (raw string cells)."""
    if not raw:
        return float("nan")
    return sum(1 for s in raw if _is_null_str(s)) / len(raw)


def distinct_count(raw, include_null=False):
    """Count of distinct (stripped) cell values; nulls dropped by default (pandas nunique)."""
    if not raw:
        return float("nan")
    vals = [s.strip() for s in raw]
    if not include_null:
        vals = [v for v in vals if not _is_null_str(v)]
    return float(len(set(vals)))


def duplicate_count(raw):
    """Rows that duplicate an earlier row (pandas duplicated(keep='first').sum()); nulls compare equal."""
    if not raw:
        return float("nan")
    vals = [s.strip() for s in raw]
    return float(len(vals) - len(set(vals)))


def growth_rate(xs, mode="period"):
    """'period': last/prev - 1 (MoM-style). 'total': last/first - 1."""
    if len(xs) < 2 or _has_nan(xs):
        return float("nan")
    base = xs[0] if mode == "total" else xs[-2]
    return xs[-1] / base - 1.0 if base != 0 else float("nan")


def ratio_share(flags):
    """'42% of users' - fraction of rows with a truthy flag."""
    if not flags or _has_nan(flags):
        return float("nan")
    return sum(1 for v in flags if v != 0) / len(flags)


def groupby_aggregate(groups, values, agg="sum", label=None):
    """Aggregate `values` by `groups` (raw string keys). Returns (value_for_label, per_group dict).
    Without a label there is no single scalar to compare - value is NaN, per-group stays in terms."""
    if not groups or len(groups) != len(values) or _has_nan(values):
        return float("nan"), {}
    buckets = {}
    for g, v in zip(groups, values):
        buckets.setdefault(g.strip(), []).append(v)
    out = {}
    for g in sorted(buckets):
        out[g] = math.fsum(buckets[g]) if agg == "sum" else fmean(buckets[g])
    if label is None:
        return float("nan"), out
    return out.get(label.strip(), float("nan")), out


def join_row_loss(left_keys, joined_keys):
    """Rows lost by a merge: len(left) - len(joined). 0 = lossless; negative = join fan-out."""
    return float(len(left_keys) - len(joined_keys))


# ======================================================================================
# Pack 3 - retrieval / RAG / LLM-eval / multiclass kernels
# ======================================================================================

def _by_query(queries, ranks, rels):
    """Group (rank, rel) rows per query, each sorted by rank ascending."""
    per = {}
    for q, r, rel in zip(queries, ranks, rels):
        per.setdefault(q.strip(), []).append((r, rel))
    for q in per:
        per[q].sort(key=lambda t: t[0])
    return per


def recall_at_k(queries, ranks, rels, k):
    """Mean over queries of (relevant in top-k) / (all relevant for the query). Queries with
    no relevant docs are skipped (standard IR convention)."""
    if not queries or _has_nan(ranks) or _has_nan(rels) or k < 1:
        return float("nan")
    per = _by_query(queries, ranks, rels)
    scores = []
    for q, rows in per.items():
        total_rel = sum(1 for _, rel in rows if rel > 0)
        if total_rel == 0:
            continue
        in_top = sum(1 for r, rel in rows[:k] if rel > 0)
        scores.append(in_top / total_rel)
    return fmean(scores) if scores else float("nan")


def ndcg_at_k(queries, ranks, rels, k, gain="linear"):
    """Mean NDCG@k. Discount 1/log2(i+1); gains 'linear' (sklearn default) or 'exp' (2^rel - 1).
    Queries with zero ideal DCG are skipped."""
    if not queries or _has_nan(ranks) or _has_nan(rels) or k < 1:
        return float("nan")

    def g(rel):
        if gain == "exp":
            return dexp(rel * _LN2) - 1.0 if rel > 0 else 0.0
        return rel

    per = _by_query(queries, ranks, rels)
    scores = []
    for q, rows in per.items():
        gains = [g(rel) for _, rel in rows]
        dcg = math.fsum(gv / dlog2(i + 2.0) for i, gv in enumerate(gains[:k]))
        ideal = sorted(gains, reverse=True)
        idcg = math.fsum(gv / dlog2(i + 2.0) for i, gv in enumerate(ideal[:k]))
        if idcg > 0:
            scores.append(dcg / idcg)
    return fmean(scores) if scores else float("nan")


def mrr(queries, ranks, rels, k=None):
    """Mean reciprocal rank of the first relevant result per query (0 when none in scope)."""
    if not queries or _has_nan(ranks) or _has_nan(rels):
        return float("nan")
    per = _by_query(queries, ranks, rels)
    scores = []
    for q, rows in per.items():
        rows = rows if k is None else rows[:k]
        rr = 0.0
        for pos, (_, rel) in enumerate(rows, start=1):
            if rel > 0:
                rr = 1.0 / pos
                break
        scores.append(rr)
    return fmean(scores) if scores else float("nan")


def hit_at_k(queries, ranks, rels, k):
    """Top-k accuracy / hit-rate: fraction of queries with >= 1 relevant in the top k."""
    if not queries or _has_nan(ranks) or _has_nan(rels) or k < 1:
        return float("nan")
    per = _by_query(queries, ranks, rels)
    hits = sum(1 for rows in per.values() if any(rel > 0 for _, rel in rows[:k]))
    return hits / len(per)


_EM_ARTICLES = ("a", "an", "the")


def _em_normalize(s):
    """SQuAD answer normalization: lowercase, strip punctuation, drop articles, collapse spaces."""
    s = s.lower()
    s = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in s)
    toks = [t for t in s.split() if t not in _EM_ARTICLES]
    return " ".join(toks)


def exact_match(preds, refs, normalized=False):
    """Mean exact-string match; 'normalized' applies SQuAD normalization to both sides."""
    if not preds or len(preds) != len(refs):
        return float("nan")
    if normalized:
        return sum(1 for p, r in zip(preds, refs) if _em_normalize(p) == _em_normalize(r)) / len(preds)
    return sum(1 for p, r in zip(preds, refs) if p.strip() == r.strip()) / len(preds)


def pass_at_k(problems, corrects, k):
    """HumanEval unbiased pass@k (Chen et al. 2021): per problem 1 - C(n-c,k)/C(n,k), exact via
    integer combinatorics, averaged over problems. Any problem with n < k samples -> NaN."""
    if not problems or _has_nan(corrects) or k < 1:
        return float("nan")
    per_n, per_c = {}, {}
    for p, c in zip(problems, corrects):
        key = p.strip()
        per_n[key] = per_n.get(key, 0) + 1
        per_c[key] = per_c.get(key, 0) + (1 if c != 0 else 0)
    ests = []
    for key in per_n:
        n, c = per_n[key], per_c[key]
        if n < k:
            return float("nan")
        if n - c < k:
            ests.append(1.0)
        else:
            ests.append(1.0 - math.comb(n - c, k) / math.comb(n, k))
    return fmean(ests)


def _multiclass_counts(preds, labels):
    classes = sorted(set(labels) | set(preds))
    tp = {c: 0 for c in classes}
    fp = {c: 0 for c in classes}
    fn = {c: 0 for c in classes}
    for p, y in zip(preds, labels):
        if p == y:
            tp[p] += 1
        else:
            fp[p] += 1
            fn[y] += 1
    return classes, tp, fp, fn


def macro_f1(preds, labels):
    """Unweighted mean of per-class F1 over classes seen in labels or preds (sklearn macro,
    zero_division=0)."""
    if not labels or len(preds) != len(labels) or _has_nan(preds) or _has_nan(labels):
        return float("nan")
    classes, tp, fp, fn = _multiclass_counts(preds, labels)
    f1s = []
    for c in classes:
        denom = 2 * tp[c] + fp[c] + fn[c]
        f1s.append(2 * tp[c] / denom if denom else 0.0)
    return fmean(f1s)


def micro_f1(preds, labels):
    """Global-count F1 (sklearn micro; equals accuracy for single-label multiclass)."""
    if not labels or len(preds) != len(labels) or _has_nan(preds) or _has_nan(labels):
        return float("nan")
    _, tp, fp, fn = _multiclass_counts(preds, labels)
    stp, sfp, sfn = sum(tp.values()), sum(fp.values()), sum(fn.values())
    denom = 2 * stp + sfp + sfn
    return 2 * stp / denom if denom else 0.0


def average_precision(scores, labels):
    """AP = sum_n (R_n - R_{n-1}) * P_n over descending score thresholds with ties grouped
    (sklearn average_precision_score)."""
    if not scores or len(scores) != len(labels) or _has_nan(scores) or _has_nan(labels):
        return float("nan")
    total_pos = sum(1 for y in labels if y == 1)
    if total_pos == 0 or total_pos == len(labels):
        return float("nan") if total_pos == 0 else 1.0
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    ap_terms = []
    tp = fp = 0
    prev_recall = 0.0
    i = 0
    n = len(order)
    while i < n:
        j = i
        while j < n and scores[order[j]] == scores[order[i]]:
            tp += 1 if labels[order[j]] == 1 else 0
            fp += 0 if labels[order[j]] == 1 else 1
            j += 1
        recall_ = tp / total_pos
        precision_ = tp / (tp + fp)
        ap_terms.append((recall_ - prev_recall) * precision_)
        prev_recall = recall_
        i = j
    return math.fsum(ap_terms)


def pr_auc_trapezoid(scores, labels):
    """Trapezoidal area under the PR curve (ties grouped) - the 'auc(recall, precision)' convention."""
    if not scores or len(scores) != len(labels) or _has_nan(scores) or _has_nan(labels):
        return float("nan")
    total_pos = sum(1 for y in labels if y == 1)
    if total_pos == 0:
        return float("nan")
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    pts = [(0.0, 1.0)]
    tp = fp = 0
    i = 0
    n = len(order)
    while i < n:
        j = i
        while j < n and scores[order[j]] == scores[order[i]]:
            tp += 1 if labels[order[j]] == 1 else 0
            fp += 0 if labels[order[j]] == 1 else 1
            j += 1
        pts.append((tp / total_pos, tp / (tp + fp)))
        i = j
    return math.fsum((r2_ - r1_) * 0.5 * (p1_ + p2_)
                     for (r1_, p1_), (r2_, p2_) in zip(pts, pts[1:]))


def log_loss(probs, labels, clip=False):
    """-mean(y ln p + (1-y) ln(1-p)) on the deterministic dlog. p exactly 0/1 on the wrong side
    -> inf (degenerate) unless clip=True (clip to [1e-15, 1-1e-15], legacy sklearn)."""
    if not probs or len(probs) != len(labels) or _has_nan(probs) or _has_nan(labels):
        return float("nan")
    terms = []
    for p, y in zip(probs, labels):
        if clip:
            p = min(max(p, 1e-15), 1.0 - 1e-15)
        terms.append(dlog(p) if y == 1 else dlog(1.0 - p))
    return -math.fsum(terms) / len(probs)


def mcc(preds, labels):
    """Matthews correlation, multiclass-general (Gorodkin) with exact integer sums; reduces to
    the binary formula. Zero denominator -> 0.0 (sklearn)."""
    if not labels or len(preds) != len(labels) or _has_nan(preds) or _has_nan(labels):
        return float("nan")
    n = len(labels)
    correct = sum(1 for p, y in zip(preds, labels) if p == y)
    classes = sorted(set(labels) | set(preds))
    pred_ct = {c: 0 for c in classes}
    true_ct = {c: 0 for c in classes}
    for p, y in zip(preds, labels):
        pred_ct[p] += 1
        true_ct[y] += 1
    cov = n * correct - sum(pred_ct[c] * true_ct[c] for c in classes)
    var_p = n * n - sum(v * v for v in pred_ct.values())
    var_t = n * n - sum(v * v for v in true_ct.values())
    if var_p == 0 or var_t == 0:
        return 0.0
    return cov / math.sqrt(float(var_p)) / math.sqrt(float(var_t))


def ece(probs, labels, bins=15):
    """Expected calibration error (Guo et al. 2017): equal-width bins (lo, hi] on confidence,
    ece = sum_b (n_b/n) * |acc_b - conf_b|."""
    if not probs or len(probs) != len(labels) or _has_nan(probs) or _has_nan(labels) or bins < 1:
        return float("nan")
    n = len(probs)
    bsum_p = [0.0] * bins
    bsum_y = [0.0] * bins
    bn = [0] * bins
    for p, y in zip(probs, labels):
        idx = min(max(int(math.ceil(p * bins)) - 1, 0), bins - 1)
        bsum_p[idx] += p
        bsum_y[idx] += 1.0 if y == 1 else 0.0
        bn[idx] += 1
    return math.fsum(abs(bsum_y[i] / bn[i] - bsum_p[i] / bn[i]) * bn[i] / n
                     for i in range(bins) if bn[i])


# ======================================================================================
# Pack 4 - statistical-claim kernels
# ======================================================================================

def t_test_p(a, b, mode="welch"):
    """Two-sided two-sample p. 'welch' (scipy default equal_var=False), 'pooled' (Student),
    'z' (normal with sample variances)."""
    if len(a) < 2 or len(b) < 2 or _has_nan(a) or _has_nan(b):
        return float("nan")
    na, nb = len(a), len(b)
    ma, mb = fmean(a), fmean(b)
    va, vb = fvar(a, 1), fvar(b, 1)
    if mode == "pooled":
        sp2 = ((na - 1) * va + (nb - 1) * vb) / (na + nb - 2)
        if sp2 <= 0:
            return float("nan")
        t = (ma - mb) / math.sqrt(sp2 * (1.0 / na + 1.0 / nb))
        return t_sf_two_sided(abs(t), float(na + nb - 2))
    sea, seb = va / na, vb / nb
    se2 = sea + seb
    if se2 <= 0:
        return float("nan")
    z = (ma - mb) / math.sqrt(se2)
    if mode == "z":
        return 2.0 * normal_sf(abs(z))
    df = se2 * se2 / (sea * sea / (na - 1) + seb * seb / (nb - 1))  # Welch-Satterthwaite
    return t_sf_two_sided(abs(z), df)


def ci_half_width(xs, level=0.95, dist="t"):
    """Half-width (margin of error) of the CI for the mean: crit * s / sqrt(n)."""
    if len(xs) < 2 or _has_nan(xs) or not (0.0 < level < 1.0):
        return float("nan")
    n = len(xs)
    s = fstd(xs, 1)
    if not (s == s):
        return float("nan")
    alpha = 1.0 - level
    crit = z_ppf_two_sided(alpha) if dist == "z" else t_ppf_two_sided(alpha, float(n - 1))
    return crit * s / math.sqrt(n)


def lift(control, treatment, mode="relative"):
    """A/B uplift of treatment over control: relative (mb-ma)/ma or absolute mb-ma."""
    if not control or not treatment or _has_nan(control) or _has_nan(treatment):
        return float("nan")
    ma, mb = fmean(control), fmean(treatment)
    if mode == "absolute":
        return mb - ma
    return (mb - ma) / ma if ma != 0 else float("nan")


def chi_square(groups, outcomes, yates=True, output="p"):
    """Chi-square test of independence recomputed from RAW observation pairs (group, outcome).
    Builds the contingency table, applies Yates only when df==1 (scipy chi2_contingency default),
    returns the p-value ('p') or the statistic ('statistic'). Any zero expected cell -> NaN."""
    if not groups or len(groups) != len(outcomes):
        return float("nan")
    rows = sorted(set(g.strip() for g in groups))
    cols = sorted(set(o.strip() for o in outcomes))
    if len(rows) < 2 or len(cols) < 2:
        return float("nan")
    obs = {(r, c): 0 for r in rows for c in cols}
    for g, o in zip(groups, outcomes):
        obs[(g.strip(), o.strip())] += 1
    n = len(groups)
    row_tot = {r: sum(obs[(r, c)] for c in cols) for r in rows}
    col_tot = {c: sum(obs[(r, c)] for r in rows) for c in cols}
    df = (len(rows) - 1) * (len(cols) - 1)
    correct = yates and df == 1
    terms = []
    for r in rows:
        for c in cols:
            e = row_tot[r] * col_tot[c] / n
            if e == 0:
                return float("nan")
            o = float(obs[(r, c)])
            if correct:
                o = o + 0.5 * _sign_f(e - o)   # scipy: shrink observed toward expected by 0.5
            terms.append((o - e) * (o - e) / e)
    stat = math.fsum(terms)
    return stat if output == "statistic" else chi2_sf(stat, float(df))


def _sign_f(x):
    return 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)


def pearson_r(xs, ys):
    """Pearson correlation via fsum-centered cross-products."""
    if len(xs) != len(ys) or len(xs) < 2 or _has_nan(xs) or _has_nan(ys):
        return float("nan")
    mx, my = fmean(xs), fmean(ys)
    sxy = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = math.fsum((x - mx) * (x - mx) for x in xs)
    syy = math.fsum((y - my) * (y - my) for y in ys)
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return sxy / math.sqrt(sxx) / math.sqrt(syy)


def _avg_ranks(xs):
    """Average (midrank) ranks, 1-based, ties share the mean rank."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j < len(order) and xs[order[j]] == xs[order[i]]:
            j += 1
        avg = (i + 1 + j) / 2.0
        for t in range(i, j):
            ranks[order[t]] = avg
        i = j
    return ranks


def spearman_r(xs, ys):
    """Spearman rho = Pearson on midranks (scipy convention)."""
    if len(xs) != len(ys) or len(xs) < 2 or _has_nan(xs) or _has_nan(ys):
        return float("nan")
    return pearson_r(_avg_ranks(xs), _avg_ranks(ys))


def cohen_d(a, b, mode="cohen_d"):
    """Standardized mean difference (a - b). 'cohen_d': pooled SD. 'hedges_g': exact small-sample
    correction J = Gamma(df/2) / (sqrt(df/2) * Gamma((df-1)/2)). 'glass_delta': control(=b) SD."""
    if len(a) < 2 or len(b) < 2 or _has_nan(a) or _has_nan(b):
        return float("nan")
    na, nb = len(a), len(b)
    diff = fmean(a) - fmean(b)
    if mode == "glass_delta":
        sb = fstd(b, 1)
        return diff / sb if sb > 0 else float("nan")
    df = na + nb - 2
    sp2 = ((na - 1) * fvar(a, 1) + (nb - 1) * fvar(b, 1)) / df
    if not (sp2 > 0):
        return float("nan")
    d = diff / math.sqrt(sp2)
    if mode == "hedges_g":
        j = dexp(dlgamma(df / 2.0) - dlgamma((df - 1) / 2.0)) / math.sqrt(df / 2.0)
        return d * j
    return d


# ======================================================================================
# Pack 5 - business & finance kernels
# ======================================================================================

def dpow(base, expo):
    """Deterministic real power for base > 0: exp(expo * ln(base))."""
    if base != base or expo != expo or base < 0.0:
        return float("nan")
    if base == 0.0:
        return 0.0 if expo > 0 else float("nan")
    return dexp(expo * dlog(base))


def cagr(xs, periods_per_year=1.0):
    """Compound annual growth rate from a time-ordered value series:
    (last/first)^(1/years) - 1 with years = (n-1)/periods_per_year."""
    if len(xs) < 2 or _has_nan(xs) or xs[0] <= 0 or xs[-1] <= 0 or periods_per_year <= 0:
        return float("nan")
    years = (len(xs) - 1) / periods_per_year
    return dpow(xs[-1] / xs[0], 1.0 / years) - 1.0


def npv(cashflows, rate):
    """Net present value, cashflows[0] at t=0 (numpy-financial convention):
    sum cf_t / (1+rate)^t. Integer powers by exact repeated multiplication."""
    if not cashflows or _has_nan(cashflows) or rate != rate or rate <= -1.0:
        return float("nan")
    terms = []
    denom = 1.0
    for cf in cashflows:
        terms.append(cf / denom)
        denom *= (1.0 + rate)
    return math.fsum(terms)


def irr(cashflows):
    """Internal rate of return: the rate in (-1, inf) where npv = 0, found by deterministic
    expansion + bisection. Requires at least one sign change in the cashflows; ambiguous or
    rootless series -> NaN."""
    if not cashflows or _has_nan(cashflows):
        return float("nan")
    has_pos = any(cf > 0 for cf in cashflows)
    has_neg = any(cf < 0 for cf in cashflows)
    if not (has_pos and has_neg):
        return float("nan")
    lo, hi = -0.9999, 1.0
    f_lo = npv(cashflows, lo)
    while npv(cashflows, hi) * f_lo > 0:
        hi *= 2.0
        if hi > 1e6:
            return float("nan")
    # bisection on a sign change; npv is continuous in rate
    f_l = f_lo
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if mid <= lo or mid >= hi:
            break
        f_m = npv(cashflows, mid)
        if (f_m > 0) == (f_l > 0):
            lo, f_l = mid, f_m
        else:
            hi = mid
    return 0.5 * (lo + hi)


def churn_rate(flags, mode="churn"):
    """Churned over total from raw 0/1 churn flags; 'retention' = 1 - churn."""
    if not flags or _has_nan(flags):
        return float("nan")
    c = sum(1 for v in flags if v != 0) / len(flags)
    return 1.0 - c if mode == "retention" else c


def margin_pct(revenue, cost):
    """Gross margin fraction: (sum(revenue) - sum(cost)) / sum(revenue)."""
    if not revenue or not cost or _has_nan(revenue) or _has_nan(cost):
        return float("nan")
    rev = math.fsum(revenue)
    if rev == 0:
        return float("nan")
    return (rev - math.fsum(cost)) / rev


def reconciliation_diff(a, b):
    """'The totals match the ledger': sum(a) - sum(b). 0 = reconciled."""
    if not a or not b or _has_nan(a) or _has_nan(b):
        return float("nan")
    return math.fsum(a) - math.fsum(b)


# ======================================================================================
# Pack 6 - forecasting kernels
# ======================================================================================

def mape(pred, actual, symmetric=False):
    """MAPE = mean(|p-a|/|a|); any zero actual -> NaN (degenerate), never an epsilon fudge.
    symmetric (sMAPE) = mean(2|p-a| / (|p|+|a|)); zero denominator -> NaN."""
    if len(pred) != len(actual) or not pred or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    terms = []
    for p, a in zip(pred, actual):
        if symmetric:
            denom = abs(p) + abs(a)
        else:
            denom = abs(a)
        if denom == 0:
            return float("nan")
        factor = 2.0 if symmetric else 1.0
        terms.append(factor * abs(p - a) / denom)
    return math.fsum(terms) / len(pred)


def mase(pred, actual, m=1):
    """Mean absolute scaled error (Hyndman & Koehler 2006): mean|p-a| scaled by the in-sample
    naive seasonal forecast MAE, mean(|a_t - a_{t-m}|) for t = m..n-1."""
    n = len(actual)
    if len(pred) != n or n <= m or m < 1 or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    scale = math.fsum(abs(actual[t] - actual[t - m]) for t in range(m, n)) / (n - m)
    if scale == 0:
        return float("nan")
    err = math.fsum(abs(p - a) for p, a in zip(pred, actual)) / n
    return err / scale


def pinball(pred, actual, q):
    """Pinball (quantile) loss at quantile q: mean(max(q*(a-p), (q-1)*(a-p))) (sklearn)."""
    if len(pred) != len(actual) or not pred or _has_nan(pred) or _has_nan(actual) \
            or q != q or not (0.0 < q < 1.0):
        return float("nan")
    terms = []
    for p, a in zip(pred, actual):
        d = a - p
        terms.append(max(q * d, (q - 1.0) * d))
    return math.fsum(terms) / len(pred)


# ======================================================================================
# Pack 7 - quant risk & relative-performance kernels
# (annualized via sqrt(periods) like sharpe; the deep overfitting stats stay in R1)
# ======================================================================================

def volatility(rets, periods):
    """Annualized volatility: std(ddof=1) * sqrt(periods)."""
    if len(rets) < 2 or _has_nan(rets):
        return float("nan")
    return fstd(rets, 1) * math.sqrt(periods)


def downside_deviation(rets, periods):
    """Annualized downside deviation, target 0, full-sample denominator (the common
    convention): sqrt(mean(min(r,0)^2)) * sqrt(periods)."""
    if not rets or _has_nan(rets):
        return float("nan")
    dd2 = math.fsum(min(r, 0.0) ** 2 for r in rets) / len(rets)
    return math.sqrt(dd2) * math.sqrt(periods)


def sortino(rets, periods):
    """Sortino ratio: mean / downside-deviation * sqrt(periods); zero downside degrades."""
    if len(rets) < 2 or _has_nan(rets):
        return float("nan")
    dd2 = math.fsum(min(r, 0.0) ** 2 for r in rets) / len(rets)
    if dd2 <= 0:
        return float("nan")
    return fmean(rets) / math.sqrt(dd2) * math.sqrt(periods)


def calmar(rets, periods):
    """Calmar ratio: annualized (CAGR-style) return / |max drawdown|. Path-dependent."""
    if len(rets) < 2 or _has_nan(rets):
        return float("nan")
    growth = pairwise_prod([1.0 + r for r in rets])
    if growth <= 0:
        return float("nan")
    ann = dpow(growth, periods / len(rets)) - 1.0
    mdd = max_drawdown(rets)
    if not (mdd < 0):
        return float("nan")
    return ann / abs(mdd)


def value_at_risk(rets, level):
    """Historical VaR at `level` (e.g. 0.95): the loss at the (1-level) return quantile,
    reported as a POSITIVE loss fraction."""
    if not rets or _has_nan(rets) or not (0.5 < level < 1.0):
        return float("nan")
    return -quantile(rets, 1.0 - level)


def cvar(rets, level):
    """Historical CVaR / expected shortfall at `level`: mean loss beyond the VaR cut,
    reported positive."""
    if not rets or _has_nan(rets) or not (0.5 < level < 1.0):
        return float("nan")
    cut = quantile(rets, 1.0 - level)
    tail = [r for r in rets if r <= cut]
    return -fmean(tail) if tail else float("nan")


def win_rate(rets):
    """Fraction of strictly positive periods."""
    if not rets or _has_nan(rets):
        return float("nan")
    return sum(1 for r in rets if r > 0) / len(rets)


def profit_factor(rets):
    """Gross gains / gross losses; no losing periods -> degenerate (nothing to divide by)."""
    if not rets or _has_nan(rets):
        return float("nan")
    gains = math.fsum(r for r in rets if r > 0)
    losses = -math.fsum(r for r in rets if r < 0)
    return gains / losses if losses > 0 else float("nan")


def omega_ratio(rets, threshold=0.0):
    """Omega(theta): sum of gains above theta / sum of shortfalls below theta."""
    if not rets or _has_nan(rets) or threshold != threshold:
        return float("nan")
    up = math.fsum(max(r - threshold, 0.0) for r in rets)
    down = math.fsum(max(threshold - r, 0.0) for r in rets)
    return up / down if down > 0 else float("nan")


def beta(rets, bench):
    """CAPM beta: cov(r, b) / var(b), sample (ddof=1)."""
    n = len(rets)
    if n != len(bench) or n < 2 or _has_nan(rets) or _has_nan(bench):
        return float("nan")
    mr, mb = fmean(rets), fmean(bench)
    cov = math.fsum((r - mr) * (b - mb) for r, b in zip(rets, bench)) / (n - 1)
    vb = fvar(bench, 1)
    return cov / vb if vb > 0 else float("nan")


def alpha(rets, bench, periods):
    """Simple annualized CAPM alpha (rf = 0): (mean(r) - beta * mean(b)) * periods."""
    b = beta(rets, bench)
    if b != b:
        return float("nan")
    return (fmean(rets) - b * fmean(bench)) * periods


def tracking_error(rets, bench, periods):
    """Annualized std of the active return (r - b), ddof=1."""
    if len(rets) != len(bench) or len(rets) < 2 or _has_nan(rets) or _has_nan(bench):
        return float("nan")
    diff = [r - b for r, b in zip(rets, bench)]
    return fstd(diff, 1) * math.sqrt(periods)


def information_ratio(rets, bench, periods):
    """Annualized mean active return / tracking error."""
    if len(rets) != len(bench) or len(rets) < 2 or _has_nan(rets) or _has_nan(bench):
        return float("nan")
    diff = [r - b for r, b in zip(rets, bench)]
    s = fstd(diff, 1)
    if not (s > 0):
        return float("nan")
    return fmean(diff) / s * math.sqrt(periods)


# ======================================================================================
# Pack 8 - classification depth II
# ======================================================================================

def balanced_accuracy(preds, labels):
    """Mean per-class recall over the classes present in labels (sklearn)."""
    if not labels or len(preds) != len(labels) or _has_nan(preds) or _has_nan(labels):
        return float("nan")
    classes = sorted(set(labels))
    recalls = []
    for c in classes:
        tp = sum(1 for p, y in zip(preds, labels) if y == c and p == c)
        n_c = sum(1 for y in labels if y == c)
        recalls.append(tp / n_c)
    return fmean(recalls)


def cohen_kappa(preds, labels):
    """Cohen's kappa, multiclass: (po - pe) / (1 - pe) with exact integer marginals."""
    if not labels or len(preds) != len(labels) or _has_nan(preds) or _has_nan(labels):
        return float("nan")
    n = len(labels)
    classes = sorted(set(labels) | set(preds))
    po = sum(1 for p, y in zip(preds, labels) if p == y) / n
    pred_ct = {c: 0 for c in classes}
    true_ct = {c: 0 for c in classes}
    for p, y in zip(preds, labels):
        pred_ct[p] += 1
        true_ct[y] += 1
    pe = math.fsum(pred_ct[c] * true_ct[c] for c in classes) / (n * n)
    return (po - pe) / (1.0 - pe) if pe != 1.0 else float("nan")


def specificity(preds, labels):
    """True-negative rate: tn / (tn + fp), binary 0/1."""
    if _has_nan(preds) or _has_nan(labels):
        return float("nan")
    _, fp, _, tn = _confusion(preds, labels)
    return tn / (tn + fp) if (tn + fp) else float("nan")


def fbeta(preds, labels, beta_v=1.0):
    """F-beta, binary: (1+b^2) P R / (b^2 P + R); zero denominator -> nan."""
    if beta_v != beta_v or beta_v <= 0:
        return float("nan")
    pr, rc = precision(preds, labels), recall(preds, labels)
    if pr != pr or rc != rc:
        return float("nan")
    b2 = beta_v * beta_v
    denom = b2 * pr + rc
    return (1 + b2) * pr * rc / denom if denom > 0 else float("nan")


def jaccard(preds, labels):
    """Jaccard / IoU on the positive class: tp / (tp + fp + fn) (sklearn binary)."""
    if _has_nan(preds) or _has_nan(labels):
        return float("nan")
    tp, fp, fn, _ = _confusion(preds, labels)
    denom = tp + fp + fn
    return tp / denom if denom else float("nan")


def weighted_f1(preds, labels):
    """Support-weighted mean of per-class F1 over classes in labels (sklearn 'weighted',
    zero_division=0)."""
    if not labels or len(preds) != len(labels) or _has_nan(preds) or _has_nan(labels):
        return float("nan")
    classes, tp, fp, fn = _multiclass_counts(preds, labels)
    total = len(labels)
    out = []
    for c in classes:
        support = sum(1 for y in labels if y == c)
        if support == 0:
            continue
        denom = 2 * tp[c] + fp[c] + fn[c]
        f1c = 2 * tp[c] / denom if denom else 0.0
        out.append(f1c * support / total)
    return math.fsum(out)


def ks_statistic(scores, labels):
    """Two-sample KS statistic between the score distributions of the two classes -
    the credit-scoring 'KS'. max |ECDF_pos - ECDF_neg|."""
    if _has_nan(scores) or _has_nan(labels):
        return float("nan")
    pos = sorted(s for s, y in zip(scores, labels) if y == 1)
    neg = sorted(s for s, y in zip(scores, labels) if y == 0)
    if not pos or not neg:
        return float("nan")
    return _ks_d(pos, neg)


def _ks_d(a_sorted, b_sorted):
    """max |ECDF_a - ECDF_b| over the pooled sample (both inputs sorted)."""
    import bisect
    best = 0.0
    for v in a_sorted + b_sorted:
        ca = bisect.bisect_right(a_sorted, v) / len(a_sorted)
        cb = bisect.bisect_right(b_sorted, v) / len(b_sorted)
        best = max(best, abs(ca - cb))
    return best


def gini_norm(scores, labels):
    """Normalized Gini (credit-model accuracy ratio): 2*AUC - 1."""
    a = auc(scores, labels)
    return 2.0 * a - 1.0 if a == a else float("nan")


# ======================================================================================
# Pack 8 - regression & forecast depth II
# ======================================================================================

def msle(pred, actual, root=False):
    """Mean squared log error (sklearn): mean((ln(1+p) - ln(1+a))^2); any value <= -1
    degrades. root=True -> RMSLE."""
    if len(pred) != len(actual) or not pred or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    if any(v <= -1.0 for v in pred) or any(v <= -1.0 for v in actual):
        return float("nan")
    s = math.fsum((dlog(1.0 + p) - dlog(1.0 + a)) ** 2 for p, a in zip(pred, actual)) / len(pred)
    return math.sqrt(s) if root else s


def medae(pred, actual):
    """Median absolute error (sklearn)."""
    if len(pred) != len(actual) or not pred or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    return quantile([abs(p - a) for p, a in zip(pred, actual)], 0.5)


def max_error(pred, actual):
    """Largest absolute error (sklearn max_error)."""
    if len(pred) != len(actual) or not pred or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    return max(abs(p - a) for p, a in zip(pred, actual))


def explained_variance(pred, actual):
    """sklearn explained_variance_score: 1 - var(a - p) / var(a) (population variance)."""
    n = len(actual)
    if len(pred) != n or n < 2 or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    err = [a - p for p, a in zip(pred, actual)]
    va = fvar(actual, 0)
    if not (va > 0):
        return float("nan")
    return 1.0 - fvar(err, 0) / va


def wape(pred, actual):
    """Weighted absolute percentage error: sum|p - a| / sum|a| (retail-forecasting standard)."""
    if len(pred) != len(actual) or not pred or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    denom = math.fsum(abs(a) for a in actual)
    if denom == 0:
        return float("nan")
    return math.fsum(abs(p - a) for p, a in zip(pred, actual)) / denom


def forecast_bias(pred, actual):
    """Aggregate bias: (sum(p) - sum(a)) / sum(a). Positive = over-forecast."""
    if len(pred) != len(actual) or not pred or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    sa = math.fsum(actual)
    if sa == 0:
        return float("nan")
    return (math.fsum(pred) - sa) / sa


def adjusted_r2(pred, actual, p):
    """Adjusted R^2 for p predictors: 1 - (1 - R2)(n - 1)/(n - p - 1)."""
    n = len(actual)
    if p is None or p < 1 or n - p - 1 <= 0:
        return float("nan")
    r = r2(pred, actual)
    if r != r:
        return float("nan")
    return 1.0 - (1.0 - r) * (n - 1) / (n - p - 1)


def nrmse(pred, actual, mode="mean"):
    """RMSE normalized by mean(actual) (default) or by the actual range."""
    r = rmse(pred, actual)
    if r != r:
        return float("nan")
    if mode == "range":
        denom = max(actual) - min(actual)
    else:
        denom = fmean(actual)
    return r / denom if denom != 0 else float("nan")


def durbin_watson(pred, actual):
    """Durbin-Watson on the residuals e = a - p: sum((e_t - e_{t-1})^2) / sum(e^2)."""
    n = len(actual)
    if len(pred) != n or n < 2 or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    e = [a - p for p, a in zip(pred, actual)]
    den = math.fsum(v * v for v in e)
    if den == 0:
        return float("nan")
    num = math.fsum((e[t] - e[t - 1]) ** 2 for t in range(1, n))
    return num / den


# ======================================================================================
# Pack 9 - analytics depth II
# ======================================================================================

def col_min(xs):
    return float("nan") if (not xs or _has_nan(xs)) else float(min(xs))


def col_max(xs):
    return float("nan") if (not xs or _has_nan(xs)) else float(max(xs))


def col_std(xs, ddof=1):
    """Sample standard deviation (ddof=1 default; ddof=0 via convention)."""
    if len(xs) < 2 or _has_nan(xs):
        return float("nan")
    return fstd(xs, ddof)


def iqr(xs):
    """Interquartile range with linear-interpolation quartiles (scipy default)."""
    if not xs or _has_nan(xs):
        return float("nan")
    return quantile(xs, 0.75) - quantile(xs, 0.25)


def outlier_count(xs, k=1.5):
    """Tukey-fence outliers: values outside [q1 - k*iqr, q3 + k*iqr]."""
    if not xs or _has_nan(xs) or k != k or k <= 0:
        return float("nan")
    q1, q3 = quantile(xs, 0.25), quantile(xs, 0.75)
    spread = q3 - q1
    lo, hi = q1 - k * spread, q3 + k * spread
    return float(sum(1 for v in xs if v < lo or v > hi))


def mode_share(raw):
    """Share of the most frequent (stripped) cell value, nulls counted as values."""
    if not raw:
        return float("nan")
    counts = {}
    for s in raw:
        key = s.strip()
        counts[key] = counts.get(key, 0) + 1
    return max(counts.values()) / len(raw)


def gini_coefficient(xs):
    """Gini inequality of a non-negative column: sum((2i - n - 1) x_(i)) / (n * sum(x))."""
    if not xs or _has_nan(xs) or any(v < 0 for v in xs):
        return float("nan")
    ys = sorted(xs)
    n = len(ys)
    total = math.fsum(ys)
    if total <= 0:
        return float("nan")
    return math.fsum((2 * (i + 1) - n - 1) * v for i, v in enumerate(ys)) / (n * total)


def hhi(xs):
    """Herfindahl-Hirschman concentration of non-negative amounts: sum((x/sum)^2) in [0,1]."""
    if not xs or _has_nan(xs) or any(v < 0 for v in xs):
        return float("nan")
    total = math.fsum(xs)
    if total <= 0:
        return float("nan")
    return math.fsum((v / total) ** 2 for v in xs)


def cat_entropy(raw, base="bits"):
    """Shannon entropy of a categorical column from its value counts; 'bits' (default) or 'nats'."""
    if not raw:
        return float("nan")
    counts = {}
    for s in raw:
        key = s.strip()
        counts[key] = counts.get(key, 0) + 1
    n = len(raw)
    h = -math.fsum((c / n) * dlog(c / n) for c in counts.values() if c > 0)
    return h * _LOG2E if base == "bits" else h


# ======================================================================================
# Pack 9 - engineering depth II
# ======================================================================================

def apdex(durations, t):
    """Apdex: (satisfied + tolerating/2) / n with satisfied <= T, tolerating <= 4T."""
    if not durations or _has_nan(durations) or t != t or t <= 0:
        return float("nan")
    sat = sum(1 for d in durations if d <= t)
    tol = sum(1 for d in durations if t < d <= 4 * t)
    return (sat + tol / 2.0) / len(durations)


# ======================================================================================
# Pack 10 - statistical tests II (all on the deterministic special-function kernels)
# ======================================================================================

def mann_whitney_p(a, b):
    """Two-sided Mann-Whitney U, normal approximation with tie correction and continuity
    correction (scipy's asymptotic method)."""
    n1, n2 = len(a), len(b)
    if n1 < 1 or n2 < 1 or _has_nan(a) or _has_nan(b):
        return float("nan")
    ranks = _avg_ranks(list(a) + list(b))
    r1 = math.fsum(ranks[:n1])
    u1 = r1 - n1 * (n1 + 1) / 2.0
    n = n1 + n2
    # tie correction over pooled tie groups
    pooled = sorted(list(a) + list(b))
    tie_term = 0.0
    i = 0
    while i < n:
        j = i
        while j < n and pooled[j] == pooled[i]:
            j += 1
        t = j - i
        tie_term += t ** 3 - t
        i = j
    var = n1 * n2 / 12.0 * ((n + 1) - tie_term / (n * (n - 1)))
    if var <= 0:
        return float("nan")
    mu = n1 * n2 / 2.0
    z = (abs(u1 - mu) - 0.5) / math.sqrt(var)   # continuity-corrected
    return min(1.0, 2.0 * normal_sf(z))


def _kolmogorov_sf(x):
    """Kolmogorov distribution survival function Q(x) = 2 sum (-1)^(j-1) exp(-2 j^2 x^2)."""
    if x <= 0:
        return 1.0
    terms = []
    for j in range(1, 101):
        t = 2.0 * ((-1.0) ** (j - 1)) * dexp(-2.0 * j * j * x * x)
        terms.append(t)
        if abs(t) < 1e-18:
            break
    return min(1.0, max(0.0, math.fsum(terms)))


def ks_p(a, b):
    """Two-sided two-sample KS p, asymptotic (scipy ks_2samp method='asymp')."""
    n1, n2 = len(a), len(b)
    if n1 < 1 or n2 < 1 or _has_nan(a) or _has_nan(b):
        return float("nan")
    d = _ks_d(sorted(a), sorted(b))
    en = math.sqrt(n1 * n2 / (n1 + n2))
    return _kolmogorov_sf(en * d)


def f_sf(f, d1, d2):
    """F-distribution survival function via the regularized incomplete beta."""
    if f != f or f < 0 or d1 <= 0 or d2 <= 0:
        return float("nan")
    return betainc_reg(d2 / 2.0, d1 / 2.0, d2 / (d2 + d1 * f))


def anova_p(groups, values, output="p"):
    """One-way ANOVA from raw (group, value) rows (scipy f_oneway). Returns p or the F stat."""
    if not groups or len(groups) != len(values) or _has_nan(values):
        return float("nan")
    buckets = {}
    for g, v in zip(groups, values):
        buckets.setdefault(g.strip(), []).append(v)
    k = len(buckets)
    n = len(values)
    if k < 2 or n - k <= 0:
        return float("nan")
    grand = fmean(values)
    ssb = math.fsum(len(vs) * (fmean(vs) - grand) ** 2 for vs in buckets.values())
    ssw = math.fsum(math.fsum((v - fmean(vs)) ** 2 for v in vs) for vs in buckets.values())
    if ssw <= 0:
        return float("nan")
    f = (ssb / (k - 1)) / (ssw / (n - k))
    return f if output == "statistic" else f_sf(f, k - 1, n - k)


def proportion_z_p(a, b):
    """Two-sided two-proportion pooled z-test from raw 0/1 outcome columns
    (statsmodels proportions_ztest)."""
    n1, n2 = len(a), len(b)
    if n1 < 1 or n2 < 1 or _has_nan(a) or _has_nan(b):
        return float("nan")
    x1 = sum(1 for v in a if v != 0)
    x2 = sum(1 for v in b if v != 0)
    pool = (x1 + x2) / (n1 + n2)
    var = pool * (1 - pool) * (1.0 / n1 + 1.0 / n2)
    if var <= 0:
        return float("nan")
    z = (x1 / n1 - x2 / n2) / math.sqrt(var)
    return 2.0 * normal_sf(abs(z))


def _table_2x2(groups, outcomes):
    """Exact 2x2 integer table from raw (group, outcome) string pairs, keys sorted."""
    rows = sorted(set(g.strip() for g in groups))
    cols = sorted(set(o.strip() for o in outcomes))
    if len(rows) != 2 or len(cols) != 2:
        return None
    t = {(r, c): 0 for r in rows for c in cols}
    for g, o in zip(groups, outcomes):
        t[(g.strip(), o.strip())] += 1
    return (t[(rows[0], cols[0])], t[(rows[0], cols[1])],
            t[(rows[1], cols[0])], t[(rows[1], cols[1])])


def fisher_exact_p(groups, outcomes):
    """Fisher's exact test, two-sided, on the 2x2 table from raw pairs - exact hypergeometric
    arithmetic via integer combinatorics (scipy's two-sided definition incl. its relative
    tolerance on 'as extreme')."""
    tab = _table_2x2(groups, outcomes)
    if tab is None:
        return float("nan")
    a_, b_, c_, d_ = tab
    r1, r2 = a_ + b_, c_ + d_
    c1 = a_ + c_
    n = r1 + r2
    if min(r1, r2, c1, n - c1) < 0 or n == 0:
        return float("nan")
    denom = math.comb(n, c1)

    def pmf_num(x):
        if x < max(0, c1 - r2) or x > min(c1, r1):
            return 0
        return math.comb(r1, x) * math.comb(r2, c1 - x)

    obs = pmf_num(a_)
    # scipy: sum P(x) for all x with pmf <= pmf(observed) * (1 + 1e-7)
    gate = obs + obs // 10 ** 7 + 1   # integer-safe ceiling of obs*(1+1e-7)
    total = sum(pn for x in range(max(0, c1 - r2), min(c1, r1) + 1)
                if (pn := pmf_num(x)) <= gate)
    return min(1.0, total / denom)


def odds_ratio_2x2(groups, outcomes, haldane=False):
    """Sample odds ratio (a*d)/(b*c) from raw pairs; zero cell -> degenerate unless the
    Haldane-Anscombe +0.5 convention is requested."""
    tab = _table_2x2(groups, outcomes)
    if tab is None:
        return float("nan")
    a_, b_, c_, d_ = tab
    if haldane:
        a_, b_, c_, d_ = a_ + 0.5, b_ + 0.5, c_ + 0.5, d_ + 0.5
    if b_ * c_ == 0:
        return float("nan")
    return (a_ * d_) / (b_ * c_)


def relative_risk_2x2(groups, outcomes):
    """Relative risk from raw pairs: (a/(a+b)) / (c/(c+d)), rows sorted by group key."""
    tab = _table_2x2(groups, outcomes)
    if tab is None:
        return float("nan")
    a_, b_, c_, d_ = tab
    if (a_ + b_) == 0 or (c_ + d_) == 0 or c_ == 0:
        return float("nan")
    return (a_ / (a_ + b_)) / (c_ / (c_ + d_))


def cramers_v(groups, outcomes):
    """Cramer's V: sqrt(chi2_nocorrection / (n * min(r-1, c-1))) from raw pairs."""
    if not groups or len(groups) != len(outcomes):
        return float("nan")
    stat = chi_square(groups, outcomes, yates=False, output="statistic")
    if stat != stat:
        return float("nan")
    rows = len(set(g.strip() for g in groups))
    cols = len(set(o.strip() for o in outcomes))
    k = min(rows - 1, cols - 1)
    if k < 1:
        return float("nan")
    return math.sqrt(stat / (len(groups) * k))


def skewness(xs):
    """Biased sample skewness g1 = m3 / m2^1.5 (scipy.stats.skew default)."""
    n = len(xs)
    if n < 2 or _has_nan(xs):
        return float("nan")
    m = fmean(xs)
    m2 = math.fsum((x - m) ** 2 for x in xs) / n
    if m2 <= 0:
        return float("nan")
    m3 = math.fsum((x - m) ** 3 for x in xs) / n
    return m3 / m2 ** 1.5


def kurtosis_excess(xs):
    """Biased excess kurtosis g2 = m4/m2^2 - 3 (scipy.stats.kurtosis default, Fisher)."""
    n = len(xs)
    if n < 2 or _has_nan(xs):
        return float("nan")
    m = fmean(xs)
    m2 = math.fsum((x - m) ** 2 for x in xs) / n
    if m2 <= 0:
        return float("nan")
    m4 = math.fsum((x - m) ** 4 for x in xs) / n
    return m4 / (m2 * m2) - 3.0


def jarque_bera_p(xs, output="p"):
    """Jarque-Bera normality test: JB = n/6 (S^2 + K^2/4), p from chi2(2) (scipy)."""
    n = len(xs)
    if n < 4 or _has_nan(xs):
        return float("nan")
    s = skewness(xs)
    k = kurtosis_excess(xs)
    if s != s or k != k:
        return float("nan")
    jb = n / 6.0 * (s * s + k * k / 4.0)
    return jb if output == "statistic" else chi2_sf(jb, 2.0)


def autocorrelation(xs, lag=1):
    """Sample autocorrelation at `lag` (statsmodels acf, adjusted=False):
    sum_{t>=lag}((x_t - m)(x_{t-lag} - m)) / sum((x_t - m)^2)."""
    n = len(xs)
    if lag < 1 or n <= lag or _has_nan(xs):
        return float("nan")
    m = fmean(xs)
    den = math.fsum((x - m) ** 2 for x in xs)
    if den <= 0:
        return float("nan")
    num = math.fsum((xs[t] - m) * (xs[t - lag] - m) for t in range(lag, n))
    return num / den


# ======================================================================================
# Pack 11 - retrieval / LLM evals II
# ======================================================================================

def precision_at_k(queries, ranks, rels, k):
    """Mean over queries of (relevant in top-k) / k."""
    if not queries or _has_nan(ranks) or _has_nan(rels) or k < 1:
        return float("nan")
    per = _by_query(queries, ranks, rels)
    return fmean([sum(1 for _, rel in rows[:k] if rel > 0) / k for rows in per.values()])


def map_at_k(queries, ranks, rels, k):
    """MAP@k: per query AP@k = sum(P@i * rel_i, i<=k) / min(R, k) with R = total relevant
    for the query (the recsys convention); zero-relevant queries skipped; averaged."""
    if not queries or _has_nan(ranks) or _has_nan(rels) or k < 1:
        return float("nan")
    per = _by_query(queries, ranks, rels)
    scores = []
    for rows in per.values():
        total_rel = sum(1 for _, rel in rows if rel > 0)
        if total_rel == 0:
            continue
        hits = 0
        ap_terms = []
        for i, (_, rel) in enumerate(rows[:k], start=1):
            if rel > 0:
                hits += 1
                ap_terms.append(hits / i)
        scores.append(math.fsum(ap_terms) / min(total_rel, k))
    return fmean(scores) if scores else float("nan")


def perplexity(logprobs):
    """exp(-mean(logprob)) over a per-token natural-log-probability column."""
    if not logprobs or _has_nan(logprobs):
        return float("nan")
    if any(lp > 0 for lp in logprobs):
        return float("nan")    # log-probabilities must be <= 0
    return dexp(-fmean(logprobs))


def _edit_distance(ref, hyp):
    """Levenshtein distance between two token lists (classic DP)."""
    m, n = len(ref), len(hyp)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[n]


def wer(preds, refs, char_level=False):
    """Corpus word error rate (jiwer): total edit distance / total reference tokens.
    char_level=True gives CER (per-character, whitespace included as jiwer does after
    sentence joining)."""
    if not preds or len(preds) != len(refs):
        return float("nan")
    total_edits = 0
    total_ref = 0
    for p, r in zip(preds, refs):
        if char_level:
            rt, pt = list(r), list(p)
        else:
            rt, pt = r.split(), p.split()
        total_edits += _edit_distance(rt, pt)
        total_ref += len(rt)
    return total_edits / total_ref if total_ref else float("nan")


# ======================================================================================
# Pack QR - quant-risk depth (deterministic functions of a return series / benchmark).
# References: canonical literature formulas computed in numpy/scipy in the generator;
# moments use scipy defaults (biased skew g1, biased excess kurtosis g2).
# ======================================================================================

def _drawdown_series(rets):
    """Per-period drawdown dd_t = equity_t / running_peak_t - 1 (<= 0)."""
    dd = []
    eq = 1.0
    peak = 1.0
    for r in rets:
        eq *= (1.0 + r)
        if eq > peak:
            peak = eq
        dd.append(eq / peak - 1.0)
    return dd


def z_ppf(p):
    """One-sided inverse standard-normal CDF: z with Phi(z) = p (normal_sf decreasing)."""
    if not (0.0 < p < 1.0):
        return float("nan")
    return _bisect_inv(normal_sf, 1.0 - p, -40.0, 40.0)


def _norm_pdf(z):
    return dexp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def ulcer_index(rets):
    """Martin & McCann Ulcer Index: sqrt(mean(dd_t^2)) over the drawdown series (fraction)."""
    if not rets or _has_nan(rets):
        return float("nan")
    dd = _drawdown_series(rets)
    return math.sqrt(math.fsum(d * d for d in dd) / len(dd))


def pain_index(rets):
    """Average drawdown depth: mean(|dd_t|)."""
    if not rets or _has_nan(rets):
        return float("nan")
    dd = _drawdown_series(rets)
    return math.fsum(-d for d in dd) / len(dd)


def martin_ratio(rets, periods):
    """Ulcer Performance Index: annualized (CAGR-style) return / Ulcer Index (rf=0)."""
    if len(rets) < 2 or _has_nan(rets):
        return float("nan")
    growth = pairwise_prod([1.0 + r for r in rets])
    if growth <= 0:
        return float("nan")
    ann = dpow(growth, periods / len(rets)) - 1.0
    ui = ulcer_index(rets)
    if not (ui > 0):
        return float("nan")
    return ann / ui


def recovery_factor(rets):
    """Total return / |max drawdown|."""
    if not rets or _has_nan(rets):
        return float("nan")
    mdd = max_drawdown(rets)
    if not (mdd < 0):
        return float("nan")
    return total_return(rets) / abs(mdd)


def gain_to_pain_ratio(rets):
    """Schwager Gain-to-Pain: sum(r) / |sum(r<0)|."""
    if not rets or _has_nan(rets):
        return float("nan")
    pain = math.fsum(-r for r in rets if r < 0)
    if not (pain > 0):
        return float("nan")
    return math.fsum(rets) / pain


def tail_ratio(rets):
    """|95th pct| / |5th pct| of returns (numpy linear quantile)."""
    if not rets or _has_nan(rets):
        return float("nan")
    lo = quantile(rets, 0.05)
    if not (abs(lo) > 0):
        return float("nan")
    return abs(quantile(rets, 0.95)) / abs(lo)


def gain_loss_ratio(rets):
    """mean(positive returns) / |mean(negative returns)|."""
    if not rets or _has_nan(rets):
        return float("nan")
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    if not wins or not losses:
        return float("nan")
    ml = abs(fmean(losses))
    if not (ml > 0):
        return float("nan")
    return fmean(wins) / ml


def win_loss_ratio(rets):
    """count(r>0) / count(r<0)."""
    if not rets or _has_nan(rets):
        return float("nan")
    nl = sum(1 for r in rets if r < 0)
    if nl == 0:
        return float("nan")
    return sum(1 for r in rets if r > 0) / nl


def kelly_criterion(rets):
    """Kelly fraction: W - (1-W)/R; W = wins/(wins+losses), R = avg win / |avg loss|."""
    if not rets or _has_nan(rets):
        return float("nan")
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    if not wins or not losses:
        return float("nan")
    payoff = fmean(wins) / abs(fmean(losses))
    if not (payoff > 0):
        return float("nan")
    w = len(wins) / (len(wins) + len(losses))
    return w - (1.0 - w) / payoff


def upside_deviation(rets, periods):
    """Annualized upside deviation, target 0: sqrt(mean(max(r,0)^2)) * sqrt(periods)."""
    if not rets or _has_nan(rets):
        return float("nan")
    u2 = math.fsum(max(r, 0.0) ** 2 for r in rets) / len(rets)
    return math.sqrt(u2) * math.sqrt(periods)


def upside_potential_ratio(rets):
    """Sortino-van der Meer-Plantinga UPR, target 0: mean(max(r,0)) / sqrt(mean(min(r,0)^2))."""
    if not rets or _has_nan(rets):
        return float("nan")
    up = math.fsum(max(r, 0.0) for r in rets) / len(rets)
    dd2 = math.fsum(min(r, 0.0) ** 2 for r in rets) / len(rets)
    if not (dd2 > 0):
        return float("nan")
    return up / math.sqrt(dd2)


def kappa_three(rets):
    """Kaplan-Knowles Kappa-3, target 0: mean(r) / (mean(max(-r,0)^3))^(1/3)."""
    if not rets or _has_nan(rets):
        return float("nan")
    lpm3 = math.fsum(max(-r, 0.0) ** 3 for r in rets) / len(rets)
    if not (lpm3 > 0):
        return float("nan")
    return fmean(rets) / dpow(lpm3, 1.0 / 3.0)


def cdar(rets, level):
    """Conditional Drawdown at Risk at `level` (Chekhlov-Uryasev): mean of drawdowns at or
    beyond the (1-level) drawdown quantile, reported as a positive fraction."""
    if not rets or _has_nan(rets) or not (0.5 < level < 1.0):
        return float("nan")
    dd = _drawdown_series(rets)
    cut = quantile(dd, 1.0 - level)
    tail = [d for d in dd if d <= cut]
    return -fmean(tail) if tail else float("nan")


def max_drawdown_duration(rets):
    """Longest run of consecutive periods the equity curve spends below a prior peak."""
    if not rets or _has_nan(rets):
        return float("nan")
    eq = 1.0
    peak = 1.0
    cur = 0
    longest = 0
    for r in rets:
        eq *= (1.0 + r)
        if eq >= peak:
            peak = eq
            cur = 0
        else:
            cur += 1
            if cur > longest:
                longest = cur
    return float(longest)


def parametric_var(rets, level):
    """Gaussian (variance-covariance) VaR: -(mu + Phi^{-1}(1-level)*sigma); positive loss."""
    if len(rets) < 2 or _has_nan(rets) or not (0.5 < level < 1.0):
        return float("nan")
    mu = fmean(rets)
    sd = fstd(rets, 1)
    return -(mu + z_ppf(1.0 - level) * sd)


def parametric_es(rets, level):
    """Gaussian expected shortfall: -(mu - sigma*phi(z_a)/(1-level)), z_a = Phi^{-1}(1-level)."""
    if len(rets) < 2 or _has_nan(rets) or not (0.5 < level < 1.0):
        return float("nan")
    mu = fmean(rets)
    sd = fstd(rets, 1)
    a = 1.0 - level
    return -(mu - sd * _norm_pdf(z_ppf(a)) / a)


def cornish_fisher_var(rets, level):
    """Modified (Cornish-Fisher) VaR: Gaussian VaR with the z-quantile expanded for skewness
    S and excess kurtosis K (Zangari); positive loss."""
    if len(rets) < 4 or _has_nan(rets) or not (0.5 < level < 1.0):
        return float("nan")
    mu = fmean(rets)
    sd = fstd(rets, 1)
    s = skewness(rets)
    k = kurtosis_excess(rets)
    z = z_ppf(1.0 - level)
    zcf = (z + (z * z - 1.0) * s / 6.0 + (z * z * z - 3.0 * z) * k / 24.0
           - (2.0 * z * z * z - 5.0 * z) * s * s / 36.0)
    return -(mu + zcf * sd)


def adjusted_sharpe_ratio(rets):
    """Pezier-White Adjusted Sharpe (per-period): SR*(1 + (S/6)SR - (Kx/24)SR^2)."""
    if len(rets) < 4 or _has_nan(rets):
        return float("nan")
    sd = fstd(rets, 1)
    if not (sd > 0):
        return float("nan")
    sr = fmean(rets) / sd
    s = skewness(rets)
    kx = kurtosis_excess(rets)
    return sr * (1.0 + (s / 6.0) * sr - (kx / 24.0) * sr * sr)


def probabilistic_sharpe_ratio(rets, benchmark_sr=0.0):
    """Bailey & Lopez de Prado PSR: Phi((SR - SR*)*sqrt(T-1)/sqrt(1 - g3*SR + ((g4-1)/4)*SR^2)).
    SR, SR* per-period; g3 biased skew, g4 non-excess kurtosis."""
    if len(rets) < 3 or _has_nan(rets):
        return float("nan")
    t = len(rets)
    sd = fstd(rets, 1)
    if not (sd > 0):
        return float("nan")
    sr = fmean(rets) / sd
    g3 = skewness(rets)
    g4 = kurtosis_excess(rets) + 3.0
    denom = 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr * sr
    if not (denom > 0):
        return float("nan")
    stat = (sr - benchmark_sr) * math.sqrt(t - 1.0) / math.sqrt(denom)
    return 1.0 - normal_sf(stat)


def up_capture_ratio(rets, bench):
    """mean(strategy | bench>0) / mean(bench | bench>0)."""
    if len(rets) != len(bench) or not rets or _has_nan(rets) or _has_nan(bench):
        return float("nan")
    rs = [r for r, b in zip(rets, bench) if b > 0]
    bs = [b for b in bench if b > 0]
    if not bs or fmean(bs) == 0:
        return float("nan")
    return fmean(rs) / fmean(bs)


def down_capture_ratio(rets, bench):
    """mean(strategy | bench<0) / mean(bench | bench<0)."""
    if len(rets) != len(bench) or not rets or _has_nan(rets) or _has_nan(bench):
        return float("nan")
    rs = [r for r, b in zip(rets, bench) if b < 0]
    bs = [b for b in bench if b < 0]
    if not bs or fmean(bs) == 0:
        return float("nan")
    return fmean(rs) / fmean(bs)


def capture_ratio(rets, bench):
    """Up-capture / down-capture."""
    up = up_capture_ratio(rets, bench)
    dn = down_capture_ratio(rets, bench)
    if not (up == up) or not (dn == dn) or dn == 0:
        return float("nan")
    return up / dn


def treynor_ratio(rets, bench, periods):
    """Annualized excess return / beta (rf=0): mean(r)*periods / beta."""
    if len(rets) < 2 or len(rets) != len(bench) or _has_nan(rets) or _has_nan(bench):
        return float("nan")
    b = beta(rets, bench)
    if not (b == b) or b == 0:
        return float("nan")
    return (fmean(rets) * periods) / b


def r_squared(rets, bench):
    """Coefficient of determination vs a benchmark: pearson(r, b)^2."""
    if len(rets) < 2 or len(rets) != len(bench) or _has_nan(rets) or _has_nan(bench):
        return float("nan")
    rho = pearson_r(rets, bench)
    return rho * rho if rho == rho else float("nan")


def active_return(rets, bench, periods):
    """Annualized active return: mean(r - b) * periods."""
    if len(rets) != len(bench) or not rets or _has_nan(rets) or _has_nan(bench):
        return float("nan")
    return fmean([r - b for r, b in zip(rets, bench)]) * periods


# ======================================================================================
# Pack ST - statistics & hypothesis tests (validated vs scipy/statsmodels).
# ======================================================================================

def _tie_pairs(vs):
    s = sorted(vs)
    total = 0
    i = 0
    n = len(s)
    while i < n:
        j = i
        while j < n and s[j] == s[i]:
            j += 1
        t = j - i
        total += t * (t - 1) // 2
        i = j
    return total


def point_biserial(binary, value):
    """Point-biserial correlation = Pearson r between a dichotomous and a continuous column."""
    return pearson_r(binary, value)


def kendall_tau(xs, ys):
    """Kendall's tau-b (tie-corrected), scipy.stats.kendalltau semantics. O(n^2)."""
    n = len(xs)
    if n < 2 or len(ys) != n or _has_nan(xs) or _has_nan(ys):
        return float("nan")
    nc = nd = 0
    for i in range(n):
        xi, yi = xs[i], ys[i]
        for j in range(i + 1, n):
            s = (xi - xs[j]) * (yi - ys[j])
            if s > 0:
                nc += 1
            elif s < 0:
                nd += 1
    n0 = n * (n - 1) // 2
    denom = math.sqrt((n0 - _tie_pairs(xs)) * (n0 - _tie_pairs(ys)))
    if denom <= 0:
        return float("nan")
    return (nc - nd) / denom


def theil_sen_slope(xs, ys):
    """Theil-Sen estimator: median of all pairwise slopes (scipy.stats.theilslopes medslope)."""
    n = len(xs)
    if n < 2 or len(ys) != n or _has_nan(xs) or _has_nan(ys):
        return float("nan")
    slopes = []
    for i in range(n):
        for j in range(i + 1, n):
            dx = xs[j] - xs[i]
            if dx != 0:
                slopes.append((ys[j] - ys[i]) / dx)
    return quantile(slopes, 0.5) if slopes else float("nan")


def cliffs_delta(a, b):
    """Cliff's delta ordinal effect size: (#(a>b) - #(a<b)) / (n_a * n_b)."""
    n1, n2 = len(a), len(b)
    if n1 < 1 or n2 < 1 or _has_nan(a) or _has_nan(b):
        return float("nan")
    gt = lt = 0
    for x in a:
        for y in b:
            if x > y:
                gt += 1
            elif x < y:
                lt += 1
    return (gt - lt) / (n1 * n2)


def rank_biserial(a, b):
    """Wendt rank-biserial from Mann-Whitney U (for sample a): 1 - 2*U / (n1*n2)."""
    n1, n2 = len(a), len(b)
    if n1 < 1 or n2 < 1 or _has_nan(a) or _has_nan(b):
        return float("nan")
    ranks = _avg_ranks(list(a) + list(b))
    u1 = math.fsum(ranks[:n1]) - n1 * (n1 + 1) / 2.0
    return 1.0 - 2.0 * u1 / (n1 * n2)


def eta_squared(groups, values):
    """One-way eta-squared: SS_between / SS_total from raw (group, value) rows."""
    if not groups or len(groups) != len(values) or _has_nan(values):
        return float("nan")
    buckets = {}
    for g, v in zip(groups, values):
        buckets.setdefault(g.strip(), []).append(v)
    if len(buckets) < 2:
        return float("nan")
    grand = fmean(values)
    ssb = math.fsum(len(vs) * (fmean(vs) - grand) ** 2 for vs in buckets.values())
    sst = math.fsum((v - grand) ** 2 for v in values)
    return ssb / sst if sst > 0 else float("nan")


def g_test(groups, outcomes, output="p"):
    """Likelihood-ratio G-test of independence (no continuity correction):
    G = 2 sum O*ln(O/E); p via chi2 with (R-1)(C-1) df (scipy chi2_contingency log-likelihood)."""
    if not groups or len(groups) != len(outcomes):
        return float("nan")
    rows = sorted(set(g.strip() for g in groups))
    cols = sorted(set(o.strip() for o in outcomes))
    nr, nc_ = len(rows), len(cols)
    if nr < 2 or nc_ < 2:
        return float("nan")
    ri = {r: i for i, r in enumerate(rows)}
    cj = {c: i for i, c in enumerate(cols)}
    obs = [[0] * nc_ for _ in range(nr)]
    for g, o in zip(groups, outcomes):
        obs[ri[g.strip()]][cj[o.strip()]] += 1
    n = len(groups)
    rowsum = [sum(obs[i]) for i in range(nr)]
    colsum = [sum(obs[i][j] for i in range(nr)) for j in range(nc_)]
    g_stat = 0.0
    for i in range(nr):
        for j in range(nc_):
            o_ij = obs[i][j]
            if o_ij > 0:
                g_stat += o_ij * dlog(o_ij / (rowsum[i] * colsum[j] / n))
    g_stat *= 2.0
    df = (nr - 1) * (nc_ - 1)
    return g_stat if output == "statistic" else chi2_sf(g_stat, df)


def mcnemar_p(a, b):
    """McNemar's test for paired binary data, asymptotic with Edwards continuity correction:
    (|n10 - n01| - 1)^2 / (n10 + n01), p via chi2(1) (statsmodels mcnemar exact=False, correction=True)."""
    n = len(a)
    if n < 1 or len(b) != n or _has_nan(a) or _has_nan(b):
        return float("nan")
    n10 = sum(1 for x, y in zip(a, b) if x != 0 and y == 0)
    n01 = sum(1 for x, y in zip(a, b) if x == 0 and y != 0)
    if n10 + n01 == 0:
        return float("nan")
    stat = (abs(n10 - n01) - 1.0) ** 2 / (n10 + n01)
    return chi2_sf(stat, 1)


# ======================================================================================
# Pack ST2 - variance / distribution / nonparametric k-sample tests + CIs + multiplicity.
# ======================================================================================

def _bucket(groups, values):
    b = {}
    for g, v in zip(groups, values):
        b.setdefault(g.strip(), []).append(v)
    return b


def _tie_term(sorted_vals):
    """sum(t^3 - t) over tie groups of an ascending list."""
    n = len(sorted_vals)
    tot = 0.0
    i = 0
    while i < n:
        j = i
        while j < n and sorted_vals[j] == sorted_vals[i]:
            j += 1
        t = j - i
        tot += t ** 3 - t
        i = j
    return tot


def levene(groups, values):
    """Levene/Brown-Forsythe test (center='median'); p via F (scipy.stats.levene)."""
    if not groups or len(groups) != len(values) or _has_nan(values):
        return float("nan")
    b = _bucket(groups, values)
    k = len(b)
    if k < 2:
        return float("nan")
    z = {g: [abs(x - quantile(vs, 0.5)) for x in vs] for g, vs in b.items()}
    n = len(values)
    allz = [zz for zs in z.values() for zz in zs]
    zbar = fmean(allz)
    num = math.fsum(len(zs) * (fmean(zs) - zbar) ** 2 for zs in z.values())
    den = math.fsum(math.fsum((zz - fmean(zs)) ** 2 for zz in zs) for zs in z.values())
    if den <= 0:
        return float("nan")
    w = (n - k) / (k - 1) * num / den
    return f_sf(w, k - 1, n - k)


def bartlett(groups, values):
    """Bartlett's test for equal variances; p via chi2 (scipy.stats.bartlett)."""
    if not groups or len(groups) != len(values) or _has_nan(values):
        return float("nan")
    b = _bucket(groups, values)
    k = len(b)
    if k < 2:
        return float("nan")
    ns = [len(vs) for vs in b.values()]
    if any(nj < 2 for nj in ns):
        return float("nan")
    vars = [fvar(vs, ddof=1) for vs in b.values()]
    if any(v <= 0 for v in vars):
        return float("nan")
    n = sum(ns)
    sp2 = math.fsum((nj - 1) * v for nj, v in zip(ns, vars)) / (n - k)
    if sp2 <= 0:
        return float("nan")
    num = (n - k) * dlog(sp2) - math.fsum((nj - 1) * dlog(v) for nj, v in zip(ns, vars))
    c = 1.0 + (1.0 / (3.0 * (k - 1))) * (math.fsum(1.0 / (nj - 1) for nj in ns) - 1.0 / (n - k))
    return chi2_sf(num / c, k - 1)


def fligner(groups, values):
    """Fligner-Killeen test (center='median'); p via chi2 (scipy.stats.fligner)."""
    if not groups or len(groups) != len(values) or _has_nan(values):
        return float("nan")
    b = _bucket(groups, values)
    k = len(b)
    if k < 2:
        return float("nan")
    z, gi = [], []
    for idx, (g, vs) in enumerate(b.items()):
        med = quantile(vs, 0.5)
        for x in vs:
            z.append(abs(x - med))
            gi.append(idx)
    n = len(z)
    ranks = _avg_ranks(z)
    a = [z_ppf(0.5 + r / (2.0 * (n + 1))) for r in ranks]
    abar = fmean(a)
    v = fvar(a, ddof=1)
    if v <= 0:
        return float("nan")
    sums, counts = {}, {}
    for ai, g in zip(a, gi):
        sums[g] = sums.get(g, 0.0) + ai
        counts[g] = counts.get(g, 0) + 1
    stat = math.fsum(counts[g] * (sums[g] / counts[g] - abar) ** 2 for g in counts) / v
    return chi2_sf(stat, k - 1)


def kruskal_wallis(groups, values):
    """Kruskal-Wallis H test, tie-corrected; p via chi2 (scipy.stats.kruskal)."""
    if not groups or len(groups) != len(values) or _has_nan(values):
        return float("nan")
    b = _bucket(groups, values)
    k = len(b)
    if k < 2:
        return float("nan")
    n = len(values)
    ranks = _avg_ranks(values)
    rs, rc = {}, {}
    for r, g in zip(ranks, (gg.strip() for gg in groups)):
        rs[g] = rs.get(g, 0.0) + r
        rc[g] = rc.get(g, 0) + 1
    h = 12.0 / (n * (n + 1)) * math.fsum(rs[g] ** 2 / rc[g] for g in rs) - 3.0 * (n + 1)
    corr = 1.0 - _tie_term(sorted(values)) / (n ** 3 - n)
    if corr <= 0:
        return float("nan")
    return chi2_sf(h / corr, k - 1)


def wilcoxon_signed_rank(a, b):
    """Wilcoxon signed-rank test on paired (a-b); normal approximation, tie-corrected, zeros
    dropped, no continuity correction (scipy.stats.wilcoxon method='approx')."""
    if len(a) != len(b) or not a or _has_nan(a) or _has_nan(b):
        return float("nan")
    d = [x - y for x, y in zip(a, b) if x - y != 0]
    n = len(d)
    if n < 1:
        return float("nan")
    ranks = _avg_ranks([abs(x) for x in d])
    wpos = math.fsum(r for r, x in zip(ranks, d) if x > 0)
    mn = n * (n + 1) / 4.0
    se = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0 - _tie_term(sorted(abs(x) for x in d)) / 48.0)
    if se <= 0:
        return float("nan")
    z = (wpos - mn) / se
    return min(1.0, 2.0 * normal_sf(abs(z)))


def anderson_darling(xs):
    """Anderson-Darling A^2 statistic for normality (scipy.stats.anderson, dist='norm')."""
    n = len(xs)
    if n < 2 or _has_nan(xs):
        return float("nan")
    mu = fmean(xs)
    s = fstd(xs, ddof=1)
    if not (s > 0):
        return float("nan")
    w = sorted((x - mu) / s for x in xs)
    acc = math.fsum((2 * (i + 1) - 1) * (dlog(1.0 - normal_sf(w[i])) + dlog(normal_sf(w[n - 1 - i])))
                    for i in range(n))
    return -n - acc / n


def _wilson(flags, level, bound):
    n = len(flags)
    if n < 1 or _has_nan(flags) or not (0.0 < level < 1.0):
        return float("nan")
    x = sum(1 for f in flags if f != 0)
    phat = x / n
    z = z_ppf(0.5 + level / 2.0)
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (phat + z2 / (2 * n)) / denom
    half = (z / denom) * math.sqrt(phat * (1 - phat) / n + z2 / (4 * n * n))
    return center - half if bound == "lower" else center + half


def wilson_lower(flags, level):
    return _wilson(flags, level, "lower")


def wilson_upper(flags, level):
    return _wilson(flags, level, "upper")


def bh_rejections(pvals, alpha):
    """Count rejected by Benjamini-Hochberg FDR at `alpha` (statsmodels fdr_bh)."""
    m = len(pvals)
    if m < 1 or _has_nan(pvals):
        return float("nan")
    sp = sorted(pvals)
    maxk = 0
    for k in range(1, m + 1):
        if sp[k - 1] <= (k / m) * alpha:
            maxk = k
    return float(maxk)


def holm_rejections(pvals, alpha):
    """Count rejected by Holm-Bonferroni at `alpha` (statsmodels holm)."""
    m = len(pvals)
    if m < 1 or _has_nan(pvals):
        return float("nan")
    sp = sorted(pvals)
    count = 0
    for k in range(1, m + 1):
        if sp[k - 1] <= alpha / (m - k + 1):
            count += 1
        else:
            break
    return float(count)


# ======================================================================================
# Pack RM - risk-model validation: VaR backtesting + distribution shift / discrimination.
# ======================================================================================

def _clnp(c, p):
    return c * dlog(p) if (c > 0 and p > 0) else 0.0


def kupiec_pof(flags, p0, output="p"):
    """Kupiec POF (unconditional coverage) LR test; flags 1 = VaR exception, p0 = expected rate.
    LR = -2[(n-x)ln(1-p0)+x ln p0 - (n-x)ln(1-pi) - x ln pi]; chi2(1)."""
    n = len(flags)
    if n < 1 or _has_nan(flags) or not (0.0 < p0 < 1.0):
        return float("nan")
    x = sum(1 for f in flags if f != 0)
    pi = x / n
    ll0 = (n - x) * dlog(1 - p0) + _clnp(x, p0)
    ll1 = _clnp(n - x, 1 - pi) + _clnp(x, pi)
    lr = -2.0 * (ll0 - ll1)
    if lr < 0:
        lr = 0.0
    return lr if output == "statistic" else chi2_sf(lr, 1)


def _markov_counts(flags):
    n00 = n01 = n10 = n11 = 0
    for prev, cur in zip(flags, flags[1:]):
        p_ = 1 if prev != 0 else 0
        c_ = 1 if cur != 0 else 0
        if p_ == 0 and c_ == 0:
            n00 += 1
        elif p_ == 0 and c_ == 1:
            n01 += 1
        elif p_ == 1 and c_ == 0:
            n10 += 1
        else:
            n11 += 1
    return n00, n01, n10, n11


def christoffersen_independence(flags, output="p"):
    """Christoffersen LR test of independence (first-order Markov) of exceptions; chi2(1)."""
    if len(flags) < 2 or _has_nan(flags):
        return float("nan")
    n00, n01, n10, n11 = _markov_counts(flags)
    t = n00 + n01 + n10 + n11
    if t == 0:
        return float("nan")
    pi = (n01 + n11) / t
    pi01 = n01 / (n00 + n01) if (n00 + n01) > 0 else 0.0
    pi11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0.0
    ll_ind = _clnp(n00 + n10, 1 - pi) + _clnp(n01 + n11, pi)
    ll_mkv = (_clnp(n00, 1 - pi01) + _clnp(n01, pi01)
              + _clnp(n10, 1 - pi11) + _clnp(n11, pi11))
    lr = -2.0 * (ll_ind - ll_mkv)
    if lr < 0:
        lr = 0.0
    return lr if output == "statistic" else chi2_sf(lr, 1)


def christoffersen_cc(flags, p0, output="p"):
    """Christoffersen conditional coverage: LR_uc + LR_ind; chi2(2)."""
    uc = kupiec_pof(flags, p0, "statistic")
    ind = christoffersen_independence(flags, "statistic")
    if uc != uc or ind != ind:
        return float("nan")
    lr = uc + ind
    return lr if output == "statistic" else chi2_sf(lr, 2)


def psi(expected, actual):
    """Population Stability Index: sum (a_i - e_i) ln(a_i/e_i) over normalized bin shares."""
    if len(expected) != len(actual) or not expected or _has_nan(expected) or _has_nan(actual):
        return float("nan")
    se = math.fsum(expected)
    sa = math.fsum(actual)
    if se <= 0 or sa <= 0:
        return float("nan")
    tot = 0.0
    for e, a in zip(expected, actual):
        ep, ap = e / se, a / sa
        if ep <= 0 or ap <= 0:
            return float("nan")
        tot += (ap - ep) * dlog(ap / ep)
    return tot


def information_value(groups, labels):
    """Credit-scoring Information Value: sum (good% - bad%) * ln(good%/bad%) over bins; label 1 = bad."""
    if len(groups) != len(labels) or not groups or _has_nan(labels):
        return float("nan")
    bins = {}
    for g, y in zip(groups, labels):
        b = bins.setdefault(g.strip(), [0, 0])
        b[1 if y != 0 else 0] += 1
    tg = sum(b[0] for b in bins.values())
    tb = sum(b[1] for b in bins.values())
    if tg == 0 or tb == 0:
        return float("nan")
    iv = 0.0
    for b in bins.values():
        dg, db = b[0] / tg, b[1] / tb
        if dg > 0 and db > 0:
            iv += (dg - db) * dlog(dg / db)
    return iv


def kl_divergence(p, q):
    """Kullback-Leibler divergence sum p ln(p/q) over normalized distributions (scipy.stats.entropy)."""
    if len(p) != len(q) or not p or _has_nan(p) or _has_nan(q):
        return float("nan")
    sp, sq = math.fsum(p), math.fsum(q)
    if sp <= 0 or sq <= 0:
        return float("nan")
    tot = 0.0
    for pi, qi in zip(p, q):
        a, b = pi / sp, qi / sq
        if a > 0:
            if b <= 0:
                return float("inf")
            tot += a * dlog(a / b)
    return tot


def js_divergence(p, q):
    """Jensen-Shannon divergence (natural log): 0.5 KL(P||M) + 0.5 KL(Q||M), M = (P+Q)/2."""
    if len(p) != len(q) or not p or _has_nan(p) or _has_nan(q):
        return float("nan")
    sp, sq = math.fsum(p), math.fsum(q)
    if sp <= 0 or sq <= 0:
        return float("nan")
    pp = [x / sp for x in p]
    qq = [x / sq for x in q]
    mm = [(a + b) / 2.0 for a, b in zip(pp, qq)]
    kl_pm = math.fsum(a * dlog(a / m) for a, m in zip(pp, mm) if a > 0)
    kl_qm = math.fsum(a * dlog(a / m) for a, m in zip(qq, mm) if a > 0)
    return 0.5 * kl_pm + 0.5 * kl_qm


def _ecdf_pts(a, b):
    import bisect
    sa, sb = sorted(a), sorted(b)
    allv = sorted(set(sa) | set(sb))
    na, nb = len(sa), len(sb)
    return [(x, bisect.bisect_right(sa, x) / na, bisect.bisect_right(sb, x) / nb) for x in allv]


def wasserstein_1d(a, b):
    """1-D Wasserstein-1 distance between two samples: integral |F_a - F_b| (scipy wasserstein_distance)."""
    if not a or not b or _has_nan(a) or _has_nan(b):
        return float("nan")
    pts = _ecdf_pts(a, b)
    return math.fsum(abs(pts[i][1] - pts[i][2]) * (pts[i + 1][0] - pts[i][0]) for i in range(len(pts) - 1))


def energy_distance(a, b):
    """Energy distance between two samples: sqrt(2 * integral (F_a - F_b)^2) (scipy energy_distance)."""
    if not a or not b or _has_nan(a) or _has_nan(b):
        return float("nan")
    pts = _ecdf_pts(a, b)
    s2 = math.fsum((pts[i][1] - pts[i][2]) ** 2 * (pts[i + 1][0] - pts[i][0]) for i in range(len(pts) - 1))
    return math.sqrt(2.0 * s2)


def ks_2samp(a, b):
    """Two-sample Kolmogorov-Smirnov D statistic: max |F_a - F_b| (scipy.stats.ks_2samp.statistic)."""
    if not a or not b or _has_nan(a) or _has_nan(b):
        return float("nan")
    d = 0.0
    for _, fa, fb in _ecdf_pts(a, b):
        d = max(d, abs(fa - fb))
    return d


# ======================================================================================
# Pack CR - classification & regression depth (validated vs scikit-learn).
# Binary classification metrics read from the (tp, fp, fn, tn) confusion counts.
# ======================================================================================

def g_mean(pred, label):
    """Geometric mean of sensitivity and specificity: sqrt(TPR * TNR)."""
    if not label or _has_nan(pred) or _has_nan(label):
        return float("nan")
    tp, fp, fn, tn = _confusion(pred, label)
    if (tp + fn) == 0 or (tn + fp) == 0:
        return float("nan")
    return math.sqrt((tp / (tp + fn)) * (tn / (tn + fp)))


def youden_j(pred, label):
    """Youden's J / informedness: TPR + TNR - 1."""
    if not label or _has_nan(pred) or _has_nan(label):
        return float("nan")
    tp, fp, fn, tn = _confusion(pred, label)
    if (tp + fn) == 0 or (tn + fp) == 0:
        return float("nan")
    return tp / (tp + fn) + tn / (tn + fp) - 1.0


def markedness(pred, label):
    """Markedness: PPV + NPV - 1."""
    if not label or _has_nan(pred) or _has_nan(label):
        return float("nan")
    tp, fp, fn, tn = _confusion(pred, label)
    if (tp + fp) == 0 or (tn + fn) == 0:
        return float("nan")
    return tp / (tp + fp) + tn / (tn + fn) - 1.0


def negative_predictive_value(pred, label):
    """Negative predictive value: TN / (TN + FN)."""
    if not label or _has_nan(pred) or _has_nan(label):
        return float("nan")
    tp, fp, fn, tn = _confusion(pred, label)
    return tn / (tn + fn) if (tn + fn) > 0 else float("nan")


def false_positive_rate(pred, label):
    if not label or _has_nan(pred) or _has_nan(label):
        return float("nan")
    tp, fp, fn, tn = _confusion(pred, label)
    return fp / (fp + tn) if (fp + tn) > 0 else float("nan")


def false_negative_rate(pred, label):
    if not label or _has_nan(pred) or _has_nan(label):
        return float("nan")
    tp, fp, fn, tn = _confusion(pred, label)
    return fn / (fn + tp) if (fn + tp) > 0 else float("nan")


def false_discovery_rate(pred, label):
    if not label or _has_nan(pred) or _has_nan(label):
        return float("nan")
    tp, fp, fn, tn = _confusion(pred, label)
    return fp / (fp + tp) if (fp + tp) > 0 else float("nan")


def positive_likelihood_ratio(pred, label):
    """LR+ = TPR / FPR (sklearn class_likelihood_ratios[0])."""
    if not label or _has_nan(pred) or _has_nan(label):
        return float("nan")
    tp, fp, fn, tn = _confusion(pred, label)
    if (tp + fn) == 0 or (fp + tn) == 0 or fp == 0:
        return float("nan")
    return (tp / (tp + fn)) / (fp / (fp + tn))


def negative_likelihood_ratio(pred, label):
    """LR- = FNR / TNR (sklearn class_likelihood_ratios[1])."""
    if not label or _has_nan(pred) or _has_nan(label):
        return float("nan")
    tp, fp, fn, tn = _confusion(pred, label)
    if (tp + fn) == 0 or (fp + tn) == 0 or tn == 0:
        return float("nan")
    return (fn / (fn + tp)) / (tn / (tn + fp))


def diagnostic_odds_ratio(pred, label):
    """DOR = (TP*TN)/(FP*FN)."""
    if not label or _has_nan(pred) or _has_nan(label):
        return float("nan")
    tp, fp, fn, tn = _confusion(pred, label)
    if fp == 0 or fn == 0:
        return float("nan")
    return (tp * tn) / (fp * fn)


def threat_score(pred, label):
    """Threat score / critical success index: TP / (TP + FN + FP)."""
    if not label or _has_nan(pred) or _has_nan(label):
        return float("nan")
    tp, fp, fn, tn = _confusion(pred, label)
    den = tp + fn + fp
    return tp / den if den > 0 else float("nan")


def fowlkes_mallows(pred, label):
    """Fowlkes-Mallows (binary): sqrt(PPV * TPR)."""
    if not label or _has_nan(pred) or _has_nan(label):
        return float("nan")
    tp, fp, fn, tn = _confusion(pred, label)
    if (tp + fp) == 0 or (tp + fn) == 0:
        return float("nan")
    return math.sqrt((tp / (tp + fp)) * (tp / (tp + fn)))


def concordance_correlation(pred, actual):
    """Lin's CCC: 2*cov / (var_p + var_a + (mean_p - mean_a)^2), population moments."""
    n = len(pred)
    if n < 1 or len(actual) != n or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    mp, ma = fmean(pred), fmean(actual)
    vp = math.fsum((p - mp) ** 2 for p in pred) / n
    va = math.fsum((a - ma) ** 2 for a in actual) / n
    cov = math.fsum((p - mp) * (a - ma) for p, a in zip(pred, actual)) / n
    denom = vp + va + (mp - ma) ** 2
    return 2.0 * cov / denom if denom > 0 else float("nan")


def huber_loss(pred, actual, delta):
    """Mean Huber loss with threshold delta."""
    if not pred or len(actual) != len(pred) or _has_nan(pred) or _has_nan(actual) or delta <= 0:
        return float("nan")
    tot = 0.0
    for p, a in zip(pred, actual):
        e = abs(p - a)
        tot += 0.5 * e * e if e <= delta else delta * (e - 0.5 * delta)
    return tot / len(pred)


def poisson_deviance(pred, actual):
    """Mean Poisson deviance: 2*mean(a*ln(a/p) - (a-p)) (sklearn mean_poisson_deviance)."""
    if not pred or len(actual) != len(pred) or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    if any(p <= 0 for p in pred) or any(a < 0 for a in actual):
        return float("nan")
    tot = math.fsum(2.0 * ((a * dlog(a / p) if a > 0 else 0.0) - (a - p)) for p, a in zip(pred, actual))
    return tot / len(pred)


def gamma_deviance(pred, actual):
    """Mean Gamma deviance: 2*mean(ln(p/a) + a/p - 1) (sklearn mean_gamma_deviance); a,p>0."""
    if not pred or len(actual) != len(pred) or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    if any(p <= 0 for p in pred) or any(a <= 0 for a in actual):
        return float("nan")
    tot = math.fsum(2.0 * (dlog(p / a) + a / p - 1.0) for p, a in zip(pred, actual))
    return tot / len(pred)


def d2_absolute_error(pred, actual):
    """D2 absolute-error score: 1 - MAE(model) / MAE(median-null) (sklearn d2_absolute_error_score)."""
    if not actual or len(pred) != len(actual) or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    mae_model = math.fsum(abs(p - a) for p, a in zip(pred, actual)) / len(actual)
    med = quantile(actual, 0.5)
    mae_null = math.fsum(abs(a - med) for a in actual) / len(actual)
    return 1.0 - mae_model / mae_null if mae_null > 0 else float("nan")


# ======================================================================================
# Pack AN - analytics / data-quality / robust-stats depth (validated vs scipy/statsmodels).
# ======================================================================================

def variance(xs):
    """Sample variance (ddof=1)."""
    return fvar(xs, 1) if len(xs) > 1 and not _has_nan(xs) else float("nan")


def range_value(xs):
    """Max - min."""
    if not xs or _has_nan(xs):
        return float("nan")
    return max(xs) - min(xs)


def mean_abs_deviation(xs):
    """Mean absolute deviation around the mean: mean(|x - mean|)."""
    if not xs or _has_nan(xs):
        return float("nan")
    m = fmean(xs)
    return math.fsum(abs(x - m) for x in xs) / len(xs)


def median_abs_deviation(xs):
    """Median absolute deviation (scale=1): median(|x - median(x)|) (scipy.stats.median_abs_deviation)."""
    if not xs or _has_nan(xs):
        return float("nan")
    med = quantile(xs, 0.5)
    return quantile([abs(x - med) for x in xs], 0.5)


def trimmed_mean(xs, proportion):
    """Symmetric trimmed mean cutting `proportion` from each tail (scipy.stats.trim_mean)."""
    if not xs or _has_nan(xs) or not (0.0 <= proportion < 0.5):
        return float("nan")
    s = sorted(xs)
    k = int(proportion * len(s))
    core = s[k:len(s) - k]
    return fmean(core) if core else float("nan")


def geometric_mean(xs):
    """Geometric mean: exp(mean(ln x)); positive data (scipy.stats.gmean)."""
    if not xs or _has_nan(xs) or any(x <= 0 for x in xs):
        return float("nan")
    return dexp(math.fsum(dlog(x) for x in xs) / len(xs))


def harmonic_mean(xs):
    """Harmonic mean: n / sum(1/x); positive data (scipy.stats.hmean)."""
    if not xs or _has_nan(xs) or any(x <= 0 for x in xs):
        return float("nan")
    return len(xs) / math.fsum(1.0 / x for x in xs)


def weighted_mean(values, weights):
    """Weighted mean: sum(w*x) / sum(w)."""
    if len(values) != len(weights) or not values or _has_nan(values) or _has_nan(weights):
        return float("nan")
    sw = math.fsum(weights)
    if sw == 0:
        return float("nan")
    return math.fsum(w * x for x, w in zip(values, weights)) / sw


def covariance(xs, ys):
    """Sample covariance (ddof=1)."""
    n = len(xs)
    if n < 2 or len(ys) != n or _has_nan(xs) or _has_nan(ys):
        return float("nan")
    mx, my = fmean(xs), fmean(ys)
    return math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n - 1)


def theil_index(xs):
    """Theil T inequality index: (1/n) sum (x/mean) ln(x/mean); positive data."""
    if not xs or _has_nan(xs) or any(x <= 0 for x in xs):
        return float("nan")
    m = fmean(xs)
    if m <= 0:
        return float("nan")
    return math.fsum((x / m) * dlog(x / m) for x in xs) / len(xs)


def atkinson_index(xs):
    """Atkinson index with inequality aversion epsilon=1: 1 - geomean/mean; positive data."""
    if not xs or _has_nan(xs) or any(x <= 0 for x in xs):
        return float("nan")
    m = fmean(xs)
    if m <= 0:
        return float("nan")
    return 1.0 - geometric_mean(xs) / m


def quartile_coefficient_dispersion(xs):
    """(Q3 - Q1) / (Q3 + Q1)."""
    if not xs or _has_nan(xs):
        return float("nan")
    q1, q3 = quantile(xs, 0.25), quantile(xs, 0.75)
    return (q3 - q1) / (q3 + q1) if (q3 + q1) != 0 else float("nan")


def index_of_dispersion(xs):
    """Fano factor: sample variance / mean."""
    if len(xs) < 2 or _has_nan(xs):
        return float("nan")
    m = fmean(xs)
    return fvar(xs, 1) / m if m != 0 else float("nan")


def uniqueness_ratio(raw, include_null=False):
    """Distinct values / total rows."""
    if not raw:
        return float("nan")
    return distinct_count(raw, include_null) / len(raw)


def ljung_box(xs, lags):
    """Ljung-Box Q at `lags` h: Q = n(n+2) sum_{k=1}^h rho_k^2/(n-k); p via chi2(h)
    (statsmodels acorr_ljungbox)."""
    n = len(xs)
    if n < 3 or _has_nan(xs) or lags < 1 or lags >= n:
        return float("nan")
    q = 0.0
    for k in range(1, lags + 1):
        rho = autocorrelation(xs, k)
        q += rho * rho / (n - k)
    q *= n * (n + 2)
    return chi2_sf(q, lags)


# ======================================================================================
# Pack TS - forecasting / time-series accuracy (documented forecasting definitions).
# Binding `prediction, target`; sequence-order metrics use the row order.
# ======================================================================================

def theil_u1(pred, actual):
    """Theil's U1 inequality coefficient: RMSE / (rms(pred) + rms(actual))."""
    n = len(pred)
    if n < 1 or len(actual) != n or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    rmse = math.sqrt(math.fsum((p - a) ** 2 for p, a in zip(pred, actual)) / n)
    den = math.sqrt(math.fsum(p * p for p in pred) / n) + math.sqrt(math.fsum(a * a for a in actual) / n)
    return rmse / den if den > 0 else float("nan")


def theil_u2(pred, actual):
    """Theil's U2 forecast-accuracy coefficient: sqrt(sum(((p-a)/a_prev)^2)) /
    sqrt(sum(((a-a_prev)/a_prev)^2)) over t>=2; a_prev != 0."""
    n = len(pred)
    if n < 2 or len(actual) != n or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    num = den = 0.0
    for t in range(n - 1):
        if actual[t] == 0:
            return float("nan")
        num += ((pred[t + 1] - actual[t + 1]) / actual[t]) ** 2
        den += ((actual[t + 1] - actual[t]) / actual[t]) ** 2
    if den <= 0:
        return float("nan")
    return math.sqrt(num) / math.sqrt(den)


def rmsse(pred, actual):
    """Root mean squared scaled error (M5): sqrt(mean((a-p)^2) / mean_{t>=2}((a_t - a_{t-1})^2))."""
    n = len(pred)
    if n < 2 or len(actual) != n or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    mse = math.fsum((a - p) ** 2 for p, a in zip(pred, actual)) / n
    denom = math.fsum((actual[t] - actual[t - 1]) ** 2 for t in range(1, n)) / (n - 1)
    return math.sqrt(mse / denom) if denom > 0 else float("nan")


def tracking_signal(pred, actual):
    """Cumulative forecast error / mean absolute deviation: sum(p-a) / mean(|p-a|)."""
    n = len(pred)
    if n < 1 or len(actual) != n or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    mad = math.fsum(abs(p - a) for p, a in zip(pred, actual)) / n
    return math.fsum(p - a for p, a in zip(pred, actual)) / mad if mad > 0 else float("nan")


def mean_directional_accuracy(pred, actual):
    """Fraction of periods whose predicted direction matches the actual direction
    (sign(a_t - a_{t-1}) vs sign(p_t - a_{t-1}))."""
    n = len(pred)
    if n < 2 or len(actual) != n or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    hits = 0
    for t in range(1, n):
        da, dp = actual[t] - actual[t - 1], pred[t] - actual[t - 1]
        if (da > 0 and dp > 0) or (da < 0 and dp < 0) or (da == 0 and dp == 0):
            hits += 1
    return hits / (n - 1)


def relative_absolute_error(pred, actual):
    """RAE: sum|p-a| / sum|a - mean(a)| (error vs the mean-forecast baseline)."""
    n = len(actual)
    if n < 1 or len(pred) != n or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    ma = fmean(actual)
    den = math.fsum(abs(a - ma) for a in actual)
    return math.fsum(abs(p - a) for p, a in zip(pred, actual)) / den if den > 0 else float("nan")


def relative_squared_error(pred, actual):
    """RSE: sum((p-a)^2) / sum((a - mean(a))^2) (= 1 - R^2)."""
    n = len(actual)
    if n < 1 or len(pred) != n or _has_nan(pred) or _has_nan(actual):
        return float("nan")
    ma = fmean(actual)
    den = math.fsum((a - ma) ** 2 for a in actual)
    return math.fsum((p - a) ** 2 for p, a in zip(pred, actual)) / den if den > 0 else float("nan")


def mean_percentage_error(pred, actual):
    """Mean percentage error (signed bias): mean((a - p) / a); a != 0."""
    n = len(actual)
    if n < 1 or len(pred) != n or _has_nan(pred) or _has_nan(actual) or any(a == 0 for a in actual):
        return float("nan")
    return math.fsum((a - p) / a for p, a in zip(pred, actual)) / n


def median_absolute_percentage_error(pred, actual):
    """Median absolute percentage error: median(|p-a| / |a|); a != 0."""
    if not actual or len(pred) != len(actual) or _has_nan(pred) or _has_nan(actual) or any(a == 0 for a in actual):
        return float("nan")
    return quantile([abs(p - a) / abs(a) for p, a in zip(pred, actual)], 0.5)


# ======================================================================================
# Pack FAIR - fairness / bias across a sensitive group (validated vs fairlearn).
# Binding `prediction, label, group`; binary predictions & labels.
# ======================================================================================

def _grp_rates(pred, label, group):
    g = {}
    for p, y, s in zip(pred, label, group):
        d = g.setdefault(s.strip(), [0, 0, 0, 0])
        if p == 1 and y == 1:
            d[0] += 1
        elif p == 1 and y == 0:
            d[1] += 1
        elif p == 0 and y == 1:
            d[2] += 1
        else:
            d[3] += 1
    out = {}
    for s, (tp, fp, fn, tn) in g.items():
        tot = tp + fp + fn + tn
        out[s] = {
            "sel": (tp + fp) / tot if tot else None,
            "tpr": tp / (tp + fn) if (tp + fn) else None,
            "fpr": fp / (fp + tn) if (fp + tn) else None,
            "ppv": tp / (tp + fp) if (tp + fp) else None,
            "acc": (tp + tn) / tot if tot else None,
        }
    return out


def _frange(vals):
    v = [x for x in vals if x is not None]
    return (max(v) - min(v)) if v else float("nan")


def _fratio(vals):
    v = [x for x in vals if x is not None]
    if not v or max(v) == 0:
        return float("nan")
    return min(v) / max(v)


def _fok(pred, label, group):
    return (len(pred) == len(label) == len(group) and bool(pred)
            and not _has_nan(pred) and not _has_nan(label))


def demographic_parity_difference(pred, label, group):
    """max - min selection rate across groups (fairlearn)."""
    if not _fok(pred, label, group):
        return float("nan")
    return _frange([v["sel"] for v in _grp_rates(pred, label, group).values()])


def demographic_parity_ratio(pred, label, group):
    """min / max selection rate across groups (fairlearn)."""
    if not _fok(pred, label, group):
        return float("nan")
    return _fratio([v["sel"] for v in _grp_rates(pred, label, group).values()])


def equalized_odds_difference(pred, label, group):
    """max(TPR range, FPR range) across groups (fairlearn)."""
    if not _fok(pred, label, group):
        return float("nan")
    r = _grp_rates(pred, label, group)
    return max(_frange([v["tpr"] for v in r.values()]), _frange([v["fpr"] for v in r.values()]))


def equalized_odds_ratio(pred, label, group):
    """min(TPR ratio, FPR ratio) across groups (fairlearn)."""
    if not _fok(pred, label, group):
        return float("nan")
    r = _grp_rates(pred, label, group)
    return min(_fratio([v["tpr"] for v in r.values()]), _fratio([v["fpr"] for v in r.values()]))


def equal_opportunity_difference(pred, label, group):
    """max - min TPR across groups."""
    if not _fok(pred, label, group):
        return float("nan")
    return _frange([v["tpr"] for v in _grp_rates(pred, label, group).values()])


def predictive_parity_difference(pred, label, group):
    """max - min PPV (precision) across groups."""
    if not _fok(pred, label, group):
        return float("nan")
    return _frange([v["ppv"] for v in _grp_rates(pred, label, group).values()])


def fpr_parity_difference(pred, label, group):
    """max - min FPR across groups."""
    if not _fok(pred, label, group):
        return float("nan")
    return _frange([v["fpr"] for v in _grp_rates(pred, label, group).values()])


def accuracy_parity_difference(pred, label, group):
    """max - min accuracy across groups."""
    if not _fok(pred, label, group):
        return float("nan")
    return _frange([v["acc"] for v in _grp_rates(pred, label, group).values()])


# ======================================================================================
# Pack BC - survival concordance + clustering-agreement (validated vs lifelines / sklearn).
# ======================================================================================

def concordance_index(times, scores, events):
    """Harrell's C-index (lifelines.utils.concordance_index); events: 1 = observed.
    Concordant when the longer survivor has the higher score; ties in score score 0.5."""
    n = len(times)
    if n < 2 or len(scores) != n or len(events) != n or _has_nan(times) or _has_nan(scores) or _has_nan(events):
        return float("nan")
    num = den = 0.0
    for i in range(n):
        if events[i] != 1:
            continue
        ti, si = times[i], scores[i]
        for j in range(n):
            if ti < times[j]:
                den += 1
                if si < scores[j]:
                    num += 1
                elif si == scores[j]:
                    num += 0.5
    return num / den if den > 0 else float("nan")


def _contingency(a, b):
    tab = {}
    for x, y in zip(a, b):
        row = tab.setdefault(x, {})
        row[y] = row.get(y, 0) + 1
    return tab


def _comb2(x):
    return x * (x - 1) // 2


def _pair_counts(a, b):
    """Returns (sum C(nij,2), sum C(ai,2), sum C(bj,2), C(n,2))."""
    tab = _contingency(a, b)
    n = len(a)
    sum_ij = 0
    bj = {}
    sum_a = 0
    for row in tab.values():
        ai = sum(row.values())
        sum_a += _comb2(ai)
        for y, c in row.items():
            sum_ij += _comb2(c)
            bj[y] = bj.get(y, 0) + c
    sum_b = sum(_comb2(c) for c in bj.values())
    return sum_ij, sum_a, sum_b, _comb2(n)


def _ck_marginals(a, b):
    """Mutual information and the two label entropies (natural log)."""
    tab = _contingency(a, b)
    n = len(a)
    ai = {x: sum(row.values()) for x, row in tab.items()}
    bj = {}
    for row in tab.values():
        for y, c in row.items():
            bj[y] = bj.get(y, 0) + c
    mi = 0.0
    for x, row in tab.items():
        for y, nij in row.items():
            if nij > 0:
                mi += (nij / n) * dlog((nij * n) / (ai[x] * bj[y]))
    hc = -math.fsum((c / n) * dlog(c / n) for c in ai.values() if c > 0)
    hk = -math.fsum((c / n) * dlog(c / n) for c in bj.values() if c > 0)
    return mi, hc, hk


def _ck_ok(a, b):
    return len(a) == len(b) and bool(a) and not _has_nan(a) and not _has_nan(b)


def mutual_info_score(a, b):
    """Mutual information between two labelings (sklearn.metrics.mutual_info_score, natural log)."""
    if not _ck_ok(a, b):
        return float("nan")
    return _ck_marginals(a, b)[0]


def normalized_mutual_info(a, b):
    """Normalized MI, arithmetic average (sklearn normalized_mutual_info_score)."""
    if not _ck_ok(a, b):
        return float("nan")
    mi, hc, hk = _ck_marginals(a, b)
    denom = (hc + hk) / 2.0
    if denom <= 0:
        return 1.0 if mi == 0 else float("nan")
    return mi / denom


def homogeneity_score(a, b):
    """Homogeneity of labeling b w.r.t. true labeling a (sklearn): MI / H(true)."""
    if not _ck_ok(a, b):
        return float("nan")
    mi, hc, hk = _ck_marginals(a, b)
    return 1.0 if hc == 0 else mi / hc


def completeness_score(a, b):
    """Completeness (sklearn): MI / H(pred)."""
    if not _ck_ok(a, b):
        return float("nan")
    mi, hc, hk = _ck_marginals(a, b)
    return 1.0 if hk == 0 else mi / hk


def v_measure_score(a, b):
    """V-measure: harmonic mean of homogeneity and completeness (sklearn)."""
    if not _ck_ok(a, b):
        return float("nan")
    h = homogeneity_score(a, b)
    c = completeness_score(a, b)
    return 0.0 if (h + c) == 0 else 2.0 * h * c / (h + c)


def rand_index(a, b):
    """Rand index (sklearn.metrics.rand_score): agreeing pairs / all pairs."""
    if not _ck_ok(a, b):
        return float("nan")
    sij, sa, sb, tot = _pair_counts(a, b)
    if tot == 0:
        return 1.0
    return (tot + 2 * sij - sa - sb) / tot


def adjusted_rand_index(a, b):
    """Adjusted Rand index (sklearn.metrics.adjusted_rand_score)."""
    if not _ck_ok(a, b):
        return float("nan")
    sij, sa, sb, tot = _pair_counts(a, b)
    if tot == 0:
        return 1.0
    exp = sa * sb / tot
    denom = 0.5 * (sa + sb) - exp
    if denom == 0:
        return 1.0 if sij == exp else 0.0
    return (sij - exp) / denom


def fowlkes_mallows_clustering(a, b):
    """Fowlkes-Mallows index between two labelings (sklearn.metrics.fowlkes_mallows_score)."""
    if not _ck_ok(a, b):
        return float("nan")
    sij, sa, sb, tot = _pair_counts(a, b)
    if sa == 0 or sb == 0:
        return 0.0
    return sij / math.sqrt(sa * sb)


# ======================================================================================
# Pack ENG - performance / SRE depth (validated vs numpy / definitions).
# ======================================================================================

def latency_p75(durations):
    return quantile(durations, 0.75) if durations and not _has_nan(durations) else float("nan")


def latency_p999(durations):
    return quantile(durations, 0.999) if durations and not _has_nan(durations) else float("nan")


def tail_latency_ratio(durations):
    """p99 / p50 latency."""
    if not durations or _has_nan(durations):
        return float("nan")
    p50 = quantile(durations, 0.5)
    return quantile(durations, 0.99) / p50 if p50 != 0 else float("nan")


def latency_stddev(durations):
    return fstd(durations, 1) if len(durations) > 1 and not _has_nan(durations) else float("nan")


def jitter(durations):
    """Mean absolute consecutive difference of the duration series."""
    n = len(durations)
    if n < 2 or _has_nan(durations):
        return float("nan")
    return math.fsum(abs(durations[t] - durations[t - 1]) for t in range(1, n)) / (n - 1)


def slo_attainment(durations, threshold):
    """Fraction of requests meeting the latency SLO threshold."""
    if not durations or _has_nan(durations):
        return float("nan")
    return sum(1 for d in durations if d <= threshold) / len(durations)


def error_budget_burn(flags, target):
    """Observed error rate / target error rate (>1 = budget overspent)."""
    if not flags or _has_nan(flags) or not (target > 0):
        return float("nan")
    return (sum(1 for f in flags if f != 0) / len(flags)) / target


def compression_ratio(original, compressed):
    """sum(original) / sum(compressed)."""
    if len(original) != len(compressed) or not original or _has_nan(original) or _has_nan(compressed):
        return float("nan")
    c = math.fsum(compressed)
    return math.fsum(original) / c if c > 0 else float("nan")


def availability(uptime, downtime):
    """uptime / (uptime + downtime)."""
    if len(uptime) != len(downtime) or not uptime or _has_nan(uptime) or _has_nan(downtime):
        return float("nan")
    up = math.fsum(uptime)
    tot = up + math.fsum(downtime)
    return up / tot if tot > 0 else float("nan")


def mtbf(flags):
    """Mean periods between failures: n / number_of_failures (flag 1 = failure)."""
    if not flags or _has_nan(flags):
        return float("nan")
    f = sum(1 for x in flags if x != 0)
    return len(flags) / f if f > 0 else float("nan")


# ======================================================================================
# Pack QR2 - quant performance depth (return series +/- benchmark; documented conventions).
# ======================================================================================

def _ann_return(rets, periods):
    growth = pairwise_prod([1.0 + r for r in rets])
    if growth <= 0:
        return float("nan")
    return dpow(growth, periods / len(rets)) - 1.0


def pain_ratio(rets, periods):
    """Annualized return / pain index (mean drawdown depth)."""
    if len(rets) < 2 or _has_nan(rets):
        return float("nan")
    ann = _ann_return(rets, periods)
    pi = pain_index(rets)
    return ann / pi if (pi > 0 and ann == ann) else float("nan")


def sterling_ratio(rets, periods):
    """Sterling ratio (Deane): annualized return / (|max drawdown| + 10%)."""
    if len(rets) < 2 or _has_nan(rets):
        return float("nan")
    ann = _ann_return(rets, periods)
    den = abs(max_drawdown(rets)) + 0.10
    return ann / den if (den > 0 and ann == ann) else float("nan")


def burke_ratio(rets, periods):
    """Burke ratio (continuous): annualized return / sqrt(sum(dd_t^2)) over the drawdown series."""
    if len(rets) < 2 or _has_nan(rets):
        return float("nan")
    ann = _ann_return(rets, periods)
    ss = math.sqrt(math.fsum(d * d for d in _drawdown_series(rets)))
    return ann / ss if (ss > 0 and ann == ann) else float("nan")


def m2_measure(rets, bench):
    """Modigliani M2 (per-period, rf=0): (mean(r)/std(r)) * std(benchmark)."""
    if len(rets) < 2 or len(bench) != len(rets) or _has_nan(rets) or _has_nan(bench):
        return float("nan")
    sd = fstd(rets, 1)
    return (fmean(rets) / sd) * fstd(bench, 1) if sd > 0 else float("nan")


def appraisal_ratio(rets, bench):
    """Treynor-Black appraisal ratio (per-period): alpha / std(residuals vs benchmark)."""
    if len(rets) < 2 or len(bench) != len(rets) or _has_nan(rets) or _has_nan(bench):
        return float("nan")
    b = beta(rets, bench)
    if not (b == b):
        return float("nan")
    a = fmean(rets) - b * fmean(bench)
    sr = fstd([r - (a + b * x) for r, x in zip(rets, bench)], 1)
    return a / sr if sr > 0 else float("nan")


def common_sense_ratio(rets):
    """Common sense ratio: tail ratio * profit factor."""
    tr, pf = tail_ratio(rets), profit_factor(rets)
    return tr * pf if (tr == tr and pf == pf) else float("nan")


def rachev_ratio(rets, level):
    """Rachev ratio: upside expected tail (>= level quantile) / downside expected tail (<= 1-level)."""
    if not rets or _has_nan(rets) or not (0.5 < level < 1.0):
        return float("nan")
    lo, hi = quantile(rets, 1.0 - level), quantile(rets, level)
    left = [r for r in rets if r <= lo]
    right = [r for r in rets if r >= hi]
    if not left or not right:
        return float("nan")
    dl = -fmean(left)
    return fmean(right) / dl if dl != 0 else float("nan")


def downside_potential(rets):
    """First lower partial moment, target 0: mean(max(-r, 0))."""
    if not rets or _has_nan(rets):
        return float("nan")
    return math.fsum(max(-r, 0.0) for r in rets) / len(rets)


def upside_potential(rets):
    """First upper partial moment, target 0: mean(max(r, 0))."""
    if not rets or _has_nan(rets):
        return float("nan")
    return math.fsum(max(r, 0.0) for r in rets) / len(rets)


def omega_sharpe_ratio(rets, threshold):
    """Sharpe-Omega: (mean(r) - threshold) / LPM1(threshold)."""
    if not rets or _has_nan(rets):
        return float("nan")
    lpm1 = math.fsum(max(threshold - r, 0.0) for r in rets) / len(rets)
    return (fmean(rets) - threshold) / lpm1 if lpm1 > 0 else float("nan")


# ======================================================================================
# Pack EXP - causal / experimentation (A/B testing; documented definitions / scipy SRM).
# ======================================================================================

def average_treatment_effect(treatment, control):
    """Mean(treatment) - mean(control)."""
    if not treatment or not control or _has_nan(treatment) or _has_nan(control):
        return float("nan")
    return fmean(treatment) - fmean(control)


def risk_difference(treatment, control):
    """Absolute risk difference for binary outcomes: P(1|treatment) - P(1|control)."""
    if not treatment or not control or _has_nan(treatment) or _has_nan(control):
        return float("nan")
    return fmean(treatment) - fmean(control)


def relative_risk_reduction(treatment, control):
    """(P_control - P_treatment) / P_control for binary outcomes."""
    if not treatment or not control or _has_nan(treatment) or _has_nan(control):
        return float("nan")
    mc = fmean(control)
    return (mc - fmean(treatment)) / mc if mc != 0 else float("nan")


def number_needed_to_treat(treatment, control):
    """1 / |risk difference|."""
    if not treatment or not control or _has_nan(treatment) or _has_nan(control):
        return float("nan")
    rd = fmean(treatment) - fmean(control)
    return 1.0 / abs(rd) if rd != 0 else float("nan")


def standardized_mean_difference(treatment, control):
    """SMD balance metric: (mean_t - mean_c) / sqrt((var_t + var_c)/2), ddof=1."""
    if len(treatment) < 2 or len(control) < 2 or _has_nan(treatment) or _has_nan(control):
        return float("nan")
    pooled = (fvar(treatment, 1) + fvar(control, 1)) / 2.0
    return (fmean(treatment) - fmean(control)) / math.sqrt(pooled) if pooled > 0 else float("nan")


def cuped_ate(value, covariate, group):
    """CUPED-adjusted ATE: theta = cov(Y,X)/var(X); Y' = Y - theta(X - meanX);
    ATE = mean(Y'|group!=0) - mean(Y'|group==0)."""
    n = len(value)
    if n < 2 or len(covariate) != n or len(group) != n or _has_nan(value) or _has_nan(covariate) or _has_nan(group):
        return float("nan")
    varx = fvar(covariate, 1)
    if varx <= 0:
        return float("nan")
    theta = covariance(value, covariate) / varx
    mx = fmean(covariate)
    yadj = [y - theta * (x - mx) for y, x in zip(value, covariate)]
    t = [yadj[i] for i in range(n) if group[i] != 0]
    c = [yadj[i] for i in range(n) if group[i] == 0]
    return (fmean(t) - fmean(c)) if (t and c) else float("nan")


def variance_reduction_cuped(value, covariate):
    """Fraction of outcome variance removed by CUPED: 1 - var(Y')/var(Y)."""
    n = len(value)
    if n < 2 or len(covariate) != n or _has_nan(value) or _has_nan(covariate):
        return float("nan")
    vary = fvar(value, 1)
    varx = fvar(covariate, 1)
    if vary <= 0 or varx <= 0:
        return float("nan")
    theta = covariance(value, covariate) / varx
    mx = fmean(covariate)
    yadj = [y - theta * (x - mx) for y, x in zip(value, covariate)]
    return 1.0 - fvar(yadj, 1) / vary


def srm_pvalue(group):
    """Sample-ratio-mismatch chi-square GOF p-value vs an equal split (scipy.stats.chisquare)."""
    if not group:
        return float("nan")
    counts = {}
    for g in group:
        counts[g.strip()] = counts.get(g.strip(), 0) + 1
    k = len(counts)
    if k < 2:
        return float("nan")
    exp = len(group) / k
    chi2 = math.fsum((c - exp) ** 2 / exp for c in counts.values())
    return chi2_sf(chi2, k - 1)


# ======================================================================================
# Pack IR - retrieval / ranking depth + token-overlap text metrics.
# ======================================================================================

def r_precision(queries, ranks, rels):
    """Mean over queries of precision at R (R = number relevant for the query)."""
    if not queries or _has_nan(ranks) or _has_nan(rels):
        return float("nan")
    vals = []
    for rows in _by_query(queries, ranks, rels).values():
        r = sum(1 for _, rel in rows if rel > 0)
        if r == 0:
            continue
        vals.append(sum(1 for _, rel in rows[:r] if rel > 0) / r)
    return fmean(vals) if vals else float("nan")


def f1_at_k(queries, ranks, rels, k):
    """Mean over queries of F1 of precision@k and recall@k (zero-relevant queries skipped)."""
    if not queries or _has_nan(ranks) or _has_nan(rels) or k < 1:
        return float("nan")
    vals = []
    for rows in _by_query(queries, ranks, rels).values():
        r = sum(1 for _, rel in rows if rel > 0)
        if r == 0:
            continue
        hits = sum(1 for _, rel in rows[:k] if rel > 0)
        prec, rec = hits / k, hits / r
        vals.append(2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0)
    return fmean(vals) if vals else float("nan")


def rbp(queries, ranks, rels, p):
    """Rank-biased precision: (1-p) * sum_i rel_i * p^(i-1), per query, averaged."""
    if not queries or _has_nan(ranks) or _has_nan(rels) or not (0.0 < p < 1.0):
        return float("nan")
    vals = []
    for rows in _by_query(queries, ranks, rels).values():
        s, pw = 0.0, 1.0
        for _, rel in rows:
            if rel > 0:
                s += pw
            pw *= p
        vals.append((1.0 - p) * s)
    return fmean(vals) if vals else float("nan")


def mean_average_precision(queries, ranks, rels):
    """Mean over queries of AP = (1/R) sum over relevant ranks of precision-at-that-rank."""
    if not queries or _has_nan(ranks) or _has_nan(rels):
        return float("nan")
    vals = []
    for rows in _by_query(queries, ranks, rels).values():
        r = sum(1 for _, rel in rows if rel > 0)
        if r == 0:
            continue
        hits, ap = 0, 0.0
        for i, (_, rel) in enumerate(rows, start=1):
            if rel > 0:
                hits += 1
                ap += hits / i
        vals.append(ap / r)
    return fmean(vals) if vals else float("nan")


def fallout_at_k(queries, ranks, rels, k):
    """Mean over queries of (nonrelevant in top-k) / (total nonrelevant)."""
    if not queries or _has_nan(ranks) or _has_nan(rels) or k < 1:
        return float("nan")
    vals = []
    for rows in _by_query(queries, ranks, rels).values():
        nonrel = sum(1 for _, rel in rows if rel <= 0)
        if nonrel == 0:
            continue
        vals.append(sum(1 for _, rel in rows[:k] if rel <= 0) / nonrel)
    return fmean(vals) if vals else float("nan")


def _multiset_overlap(a, b):
    rc = {}
    for t in b:
        rc[t] = rc.get(t, 0) + 1
    common = 0
    for t in a:
        if rc.get(t, 0) > 0:
            common += 1
            rc[t] -= 1
    return common


def token_f1(preds, refs):
    """SQuAD-style token-level F1 (multiset overlap on normalized tokens), averaged."""
    if len(preds) != len(refs) or not preds:
        return float("nan")
    vals = []
    for p, r in zip(preds, refs):
        pt, rt = _em_normalize(p).split(), _em_normalize(r).split()
        if not pt and not rt:
            vals.append(1.0)
            continue
        if not pt or not rt:
            vals.append(0.0)
            continue
        c = _multiset_overlap(pt, rt)
        if c == 0:
            vals.append(0.0)
            continue
        prec, rec = c / len(pt), c / len(rt)
        vals.append(2 * prec * rec / (prec + rec))
    return fmean(vals)


def token_jaccard(preds, refs):
    """Token-set Jaccard (whitespace tokens), averaged over examples."""
    if len(preds) != len(refs) or not preds:
        return float("nan")
    vals = []
    for p, r in zip(preds, refs):
        a, b = set(p.split()), set(r.split())
        if not a and not b:
            vals.append(1.0)
            continue
        u = len(a | b)
        vals.append(len(a & b) / u if u else 0.0)
    return fmean(vals)


def token_dice(preds, refs):
    """Token-set Sorensen-Dice coefficient (whitespace tokens), averaged."""
    if len(preds) != len(refs) or not preds:
        return float("nan")
    vals = []
    for p, r in zip(preds, refs):
        a, b = set(p.split()), set(r.split())
        d = len(a) + len(b)
        vals.append(2 * len(a & b) / d if d else 1.0)
    return fmean(vals)


# ======================================================================================
# Pack FI - fixed-income analytics. Bind a cashflow column and a (year) time column;
# discrete discounting PV_i = CF_i / (1+y)**t_i (documented closed forms).
# ======================================================================================

def _pv_terms(cashflows, times, y):
    return [cf / (1.0 + y) ** t for cf, t in zip(cashflows, times)]


def _fi_ok(cashflows, times):
    return bool(cashflows) and len(times) == len(cashflows) and not _has_nan(cashflows) and not _has_nan(times)


def bond_price(cashflows, times, y):
    """Present value of a cashflow stream: sum CF_i / (1+y)**t_i."""
    if not _fi_ok(cashflows, times) or y <= -1.0:
        return float("nan")
    return math.fsum(_pv_terms(cashflows, times, y))


def macaulay_duration(cashflows, times, y):
    """Macaulay duration: sum t_i * PV_i / sum PV_i (years)."""
    if not _fi_ok(cashflows, times) or y <= -1.0:
        return float("nan")
    pv = _pv_terms(cashflows, times, y)
    p = math.fsum(pv)
    if p == 0:
        return float("nan")
    return math.fsum(t * v for t, v in zip(times, pv)) / p


def modified_duration(cashflows, times, y):
    """Modified duration: Macaulay duration / (1+y)."""
    d = macaulay_duration(cashflows, times, y)
    return float("nan") if d != d else d / (1.0 + y)


def convexity(cashflows, times, y):
    """Convexity: sum t_i (t_i+1) PV_i / (P (1+y)**2)."""
    if not _fi_ok(cashflows, times) or y <= -1.0:
        return float("nan")
    pv = _pv_terms(cashflows, times, y)
    p = math.fsum(pv)
    if p == 0:
        return float("nan")
    num = math.fsum(t * (t + 1.0) * v for t, v in zip(times, pv))
    return num / (p * (1.0 + y) ** 2)


def dv01(cashflows, times, y):
    """Dollar value of a basis point: modified duration * price * 1e-4."""
    p = bond_price(cashflows, times, y)
    md = modified_duration(cashflows, times, y)
    return float("nan") if (p != p or md != md) else md * p * 1e-4


def weighted_average_life(cashflows, times):
    """Cashflow-weighted average time: sum t_i CF_i / sum CF_i (years, undiscounted)."""
    if not _fi_ok(cashflows, times):
        return float("nan")
    s = math.fsum(cashflows)
    if s == 0:
        return float("nan")
    return math.fsum(t * cf for t, cf in zip(times, cashflows)) / s


def yield_to_maturity(cashflows, times, price):
    """Internal yield y solving sum CF_i/(1+y)**t_i = price, bisection on [-0.9999, 10]."""
    if not _fi_ok(cashflows, times) or price <= 0:
        return float("nan")

    def f(y):
        return math.fsum(_pv_terms(cashflows, times, y)) - price

    lo, hi = -0.9999, 10.0
    flo, fhi = f(lo), f(hi)
    if flo != flo or fhi != fhi or flo * fhi > 0:
        return float("nan")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if fm == 0.0:
            return mid
        if flo * fm < 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return 0.5 * (lo + hi)


# ======================================================================================
# Pack OPT - Black-Scholes option pricing & Greeks (analytic, non-dividend; q=0).
# Per-position columns S (spot), K (strike), T (years), sigma (vol), r (rate) and a
# signed quantity; each recipe returns the portfolio aggregate book value / book Greek
# = sum_i qty_i * f_i. Calls vs puts via an explicit flag. Greeks are raw (vega per
# 1.00 vol, rho per 1.00 rate, theta per year). Validated against a scipy.stats.norm
# closed-form Black-Scholes and scipy.optimize.brentq for implied vol.
# ======================================================================================

def _norm_cdf(x):
    """Standard normal CDF P(Z<=x) via the deterministic erfc."""
    return normal_sf(-x)


def _bs_ok(*cols):
    n = len(cols[0])
    return n > 0 and all(len(c) == n for c in cols) and not any(_has_nan(c) for c in cols)


def _bs_d1d2(s, k, t, v, r):
    rt = v * math.sqrt(t)
    d1 = (dlog(s / k) + (r + 0.5 * v * v) * t) / rt
    return d1, d1 - rt


def _bs_px(s, k, t, v, r, is_call):
    d1, d2 = _bs_d1d2(s, k, t, v, r)
    disc = dexp(-r * t)
    if is_call:
        return s * _norm_cdf(d1) - k * disc * _norm_cdf(d2)
    return k * disc * _norm_cdf(-d2) - s * _norm_cdf(-d1)


def _bs_delta_pos(s, k, t, v, r, is_call):
    d1, _ = _bs_d1d2(s, k, t, v, r)
    return _norm_cdf(d1) if is_call else _norm_cdf(d1) - 1.0


def _bs_gamma_pos(s, k, t, v, r, is_call):
    d1, _ = _bs_d1d2(s, k, t, v, r)
    return _norm_pdf(d1) / (s * v * math.sqrt(t))


def _bs_vega_pos(s, k, t, v, r, is_call):
    d1, _ = _bs_d1d2(s, k, t, v, r)
    return s * _norm_pdf(d1) * math.sqrt(t)


def _bs_theta_pos(s, k, t, v, r, is_call):
    d1, d2 = _bs_d1d2(s, k, t, v, r)
    disc = dexp(-r * t)
    decay = -s * _norm_pdf(d1) * v / (2.0 * math.sqrt(t))
    if is_call:
        return decay - r * k * disc * _norm_cdf(d2)
    return decay + r * k * disc * _norm_cdf(-d2)


def _bs_rho_pos(s, k, t, v, r, is_call):
    d1, d2 = _bs_d1d2(s, k, t, v, r)
    disc = dexp(-r * t)
    if is_call:
        return k * t * disc * _norm_cdf(d2)
    return -k * t * disc * _norm_cdf(-d2)


def _bs_vanna_pos(s, k, t, v, r, is_call):
    d1, d2 = _bs_d1d2(s, k, t, v, r)
    return -_norm_pdf(d1) * d2 / v


def _bs_volga_pos(s, k, t, v, r, is_call):
    d1, d2 = _bs_d1d2(s, k, t, v, r)
    return s * _norm_pdf(d1) * math.sqrt(t) * d1 * d2 / v


def _bs_book(S, K, T, sig, r, qty, is_call, fn):
    if not _bs_ok(S, K, T, sig, r, qty):
        return float("nan")
    parts = []
    for s, k, t, v, rr, q in zip(S, K, T, sig, r, qty):
        if s <= 0 or k <= 0 or t <= 0 or v <= 0:
            return float("nan")
        parts.append(q * fn(s, k, t, v, rr, is_call))
    return math.fsum(parts)


def bs_value(S, K, T, sig, r, qty, is_call):
    """Book value sum_i qty_i * Black-Scholes price_i."""
    return _bs_book(S, K, T, sig, r, qty, is_call, _bs_px)


def bs_delta(S, K, T, sig, r, qty, is_call):
    """Book delta sum_i qty_i * dPrice/dS_i."""
    return _bs_book(S, K, T, sig, r, qty, is_call, _bs_delta_pos)


def bs_gamma(S, K, T, sig, r, qty, is_call):
    """Book gamma sum_i qty_i * d2Price/dS2_i (call=put)."""
    return _bs_book(S, K, T, sig, r, qty, is_call, _bs_gamma_pos)


def bs_vega(S, K, T, sig, r, qty, is_call):
    """Book vega sum_i qty_i * dPrice/dsigma_i, raw per 1.00 vol (call=put)."""
    return _bs_book(S, K, T, sig, r, qty, is_call, _bs_vega_pos)


def bs_theta(S, K, T, sig, r, qty, is_call):
    """Book theta sum_i qty_i * dPrice/dt_i, per calendar year."""
    return _bs_book(S, K, T, sig, r, qty, is_call, _bs_theta_pos)


def bs_rho(S, K, T, sig, r, qty, is_call):
    """Book rho sum_i qty_i * dPrice/dr_i, raw per 1.00 rate."""
    return _bs_book(S, K, T, sig, r, qty, is_call, _bs_rho_pos)


def bs_vanna(S, K, T, sig, r, qty, is_call):
    """Book vanna sum_i qty_i * d2Price/dSdsigma_i (call=put)."""
    return _bs_book(S, K, T, sig, r, qty, is_call, _bs_vanna_pos)


def bs_volga(S, K, T, sig, r, qty, is_call):
    """Book volga / vomma sum_i qty_i * d2Price/dsigma2_i (call=put)."""
    return _bs_book(S, K, T, sig, r, qty, is_call, _bs_volga_pos)


def _bs_implied_one(s, k, t, r, price, is_call):
    """Implied vol of a single option by bisection on the monotone price(sigma)."""
    def f(v):
        return _bs_px(s, k, t, v, r, is_call) - price

    lo, hi = 1e-6, 10.0
    flo, fhi = f(lo), f(hi)
    if flo != flo or fhi != fhi or flo * fhi > 0:
        return float("nan")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if fm == 0.0:
            return mid
        if flo * fm < 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return 0.5 * (lo + hi)


def bs_implied_vol(S, K, T, r, price, is_call):
    """Mean Black-Scholes implied vol across the option rows (each solved independently)."""
    if not _bs_ok(S, K, T, r, price):
        return float("nan")
    ivs = []
    for s, k, t, rr, p in zip(S, K, T, r, price):
        if s <= 0 or k <= 0 or t <= 0 or p <= 0:
            return float("nan")
        iv = _bs_implied_one(s, k, t, rr, p, is_call)
        if iv != iv:
            return float("nan")
        ivs.append(iv)
    return fmean(ivs)


# ======================================================================================
# Pack ES - expected-shortfall / VaR backtesting. Bind a realized return column with the
# day's predicted VaR (and ES), both POSITIVE loss fractions; level via convention. An
# exception is a day whose realized loss exceeds VaR: -ret_t > VaR_t. Complements the
# Kupiec / Christoffersen exception-count suite. Validated against the documented
# Acerbi-Szekely (2014) and Basel (1996) closed forms recomputed in numpy.
# ======================================================================================

def _es_ok(*cols):
    n = len(cols[0])
    return n > 0 and all(len(c) == n for c in cols) and not any(_has_nan(c) for c in cols)


def _es_exceptions(rets, var):
    """Indices where the realized loss exceeds the predicted VaR (positive-loss convention)."""
    return [i for i, (x, v) in enumerate(zip(rets, var)) if -x > v]


def var_breach_rate(rets, var):
    """Realized VaR exception fraction: count(-ret > VaR) / N."""
    if not _es_ok(rets, var):
        return float("nan")
    return len(_es_exceptions(rets, var)) / len(rets)


def realized_shortfall(rets, var):
    """Mean realized loss on exception days: mean(-ret_t | -ret_t > VaR_t)."""
    if not _es_ok(rets, var):
        return float("nan")
    exc = _es_exceptions(rets, var)
    if not exc:
        return float("nan")
    return fmean([-rets[i] for i in exc])


def expected_exceedance(rets, var):
    """Mean overshoot beyond VaR on exception days: mean((-ret_t) - VaR_t | exception)."""
    if not _es_ok(rets, var):
        return float("nan")
    exc = _es_exceptions(rets, var)
    if not exc:
        return float("nan")
    return fmean([(-rets[i]) - var[i] for i in exc])


def basel_traffic_light(rets, var):
    """Basel (1996) backtesting plus-factor from the VaR exception count: 0-4 green -> 0.00;
    5..9 yellow -> 0.40/0.50/0.65/0.75/0.85; >=10 red -> 1.00."""
    if not _es_ok(rets, var):
        return float("nan")
    x = len(_es_exceptions(rets, var))
    if x <= 4:
        return 0.0
    if x >= 10:
        return 1.0
    return {5: 0.40, 6: 0.50, 7: 0.65, 8: 0.75, 9: 0.85}[x]


def acerbi_szekely_z1(rets, var, es, level):
    """Acerbi-Szekely (2014) Test 1: mean(L_t/ES_t) - 1 over exception days, L_t = -ret_t.
    0 = ES calibrated, >0 = ES underestimated; conditional on the exceptions (independent of
    their count)."""
    if not _es_ok(rets, var, es) or not (0.5 < level < 1.0):
        return float("nan")
    exc = _es_exceptions(rets, var)
    if not exc:
        return float("nan")
    ratios = []
    for i in exc:
        if es[i] <= 0:
            return float("nan")
        ratios.append((-rets[i]) / es[i])
    return fmean(ratios) - 1.0


def acerbi_szekely_z2(rets, var, es, level):
    """Acerbi-Szekely (2014) Test 2: (1/(N*(1-level))) * sum_t I_t * L_t/ES_t - 1.
    0 = calibrated; jointly senses the frequency and the magnitude of breaches."""
    if not _es_ok(rets, var, es) or not (0.5 < level < 1.0):
        return float("nan")
    parts = []
    for i in _es_exceptions(rets, var):
        if es[i] <= 0:
            return float("nan")
        parts.append((-rets[i]) / es[i])
    return math.fsum(parts) / (len(rets) * (1.0 - level)) - 1.0


def es_backtest_ratio(rets, var, es):
    """Aggregate realized/predicted ES on exception days: sum(L_t) / sum(ES_t). ~1 = calibrated."""
    if not _es_ok(rets, var, es):
        return float("nan")
    exc = _es_exceptions(rets, var)
    if not exc:
        return float("nan")
    den = math.fsum(es[i] for i in exc)
    if den <= 0:
        return float("nan")
    return math.fsum(-rets[i] for i in exc) / den


# ======================================================================================
# Pack CR - credit / default risk (analytic). Portfolio expected / unexpected loss from
# per-name PD/LGD/EAD columns; Altman bankruptcy Z-scores from the financial ratios;
# Merton structural distance-to-default and its implied PD. Validated against numpy dot
# products, the definitional Altman weights, and a scipy.stats.norm Merton recompute.
# ======================================================================================

def _cr_ok(*cols):
    n = len(cols[0])
    return n > 0 and all(len(c) == n for c in cols) and not any(_has_nan(c) for c in cols)


def expected_loss(pd, lgd, ead):
    """Portfolio expected loss: sum_i PD_i * LGD_i * EAD_i."""
    if not _cr_ok(pd, lgd, ead):
        return float("nan")
    return math.fsum(p * l * e for p, l, e in zip(pd, lgd, ead))


def expected_loss_rate(pd, lgd, ead):
    """Portfolio EL as a fraction of exposure: sum(PD*LGD*EAD) / sum(EAD)."""
    if not _cr_ok(pd, lgd, ead):
        return float("nan")
    tot = math.fsum(ead)
    if tot == 0:
        return float("nan")
    return math.fsum(p * l * e for p, l, e in zip(pd, lgd, ead)) / tot


def weighted_lgd(lgd, ead):
    """Exposure-weighted loss-given-default: sum(LGD*EAD) / sum(EAD)."""
    if not _cr_ok(lgd, ead):
        return float("nan")
    tot = math.fsum(ead)
    if tot == 0:
        return float("nan")
    return math.fsum(l * e for l, e in zip(lgd, ead)) / tot


def unexpected_loss(pd, lgd, ead):
    """Sum of standalone unexpected losses: sum_i EAD_i*LGD_i*sqrt(PD_i*(1-PD_i)) -
    a diversification-free (zero default-correlation) aggregate."""
    if not _cr_ok(pd, lgd, ead):
        return float("nan")
    parts = []
    for p, l, e in zip(pd, lgd, ead):
        if not (0.0 <= p <= 1.0):
            return float("nan")
        parts.append(e * l * math.sqrt(p * (1.0 - p)))
    return math.fsum(parts)


def altman_z(x1, x2, x3, x4, x5):
    """Altman (1968) Z-score, decimal-ratio form 1.2X1+1.4X2+3.3X3+0.6X4+1.0X5, averaged
    over the firms (rows). X1 WC/TA, X2 RE/TA, X3 EBIT/TA, X4 MVE/TL, X5 sales/TA."""
    if not _cr_ok(x1, x2, x3, x4, x5):
        return float("nan")
    zs = [1.2 * a + 1.4 * b + 3.3 * c + 0.6 * d + 1.0 * e
          for a, b, c, d, e in zip(x1, x2, x3, x4, x5)]
    return fmean(zs)


def altman_z_prime(x1, x2, x3, x4):
    """Altman Z''-score (emerging-market / non-manufacturing): 6.56X1+3.26X2+6.72X3+1.05X4,
    averaged over the firms. X4 here is book equity / total liabilities."""
    if not _cr_ok(x1, x2, x3, x4):
        return float("nan")
    zs = [6.56 * a + 3.26 * b + 6.72 * c + 1.05 * d for a, b, c, d in zip(x1, x2, x3, x4)]
    return fmean(zs)


def _merton_dd(v, d, mu, sigma, t):
    return (dlog(v / d) + (mu - 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))


def merton_distance_to_default(asset_value, debt, drift, vol, time):
    """Merton structural distance-to-default, averaged over firms:
    DD = (ln(V/D) + (mu - 0.5 sigma^2) T) / (sigma sqrt(T))."""
    cols = (asset_value, debt, drift, vol, time)
    if not _cr_ok(*cols):
        return float("nan")
    dds = []
    for v, d, mu, s, t in zip(*cols):
        if v <= 0 or d <= 0 or s <= 0 or t <= 0:
            return float("nan")
        dds.append(_merton_dd(v, d, mu, s, t))
    return fmean(dds)


def merton_pd(asset_value, debt, drift, vol, time):
    """Merton implied default probability, averaged over firms: PD = N(-DD)."""
    cols = (asset_value, debt, drift, vol, time)
    if not _cr_ok(*cols):
        return float("nan")
    pds = []
    for v, d, mu, s, t in zip(*cols):
        if v <= 0 or d <= 0 or s <= 0 or t <= 0:
            return float("nan")
        pds.append(_norm_cdf(-_merton_dd(v, d, mu, s, t)))
    return fmean(pds)


# ======================================================================================
# Pack PA - portfolio construction & attribution. Per-segment portfolio/benchmark weight
# and return columns drive Brinson-Hood-Beebower attribution; weight vectors drive active
# share, turnover and the effective number of bets. All definitional weighted sums.
# ======================================================================================

def _pa_ok(*cols):
    n = len(cols[0])
    return n > 0 and all(len(c) == n for c in cols) and not any(_has_nan(c) for c in cols)


def brinson_allocation(wp, wb, rb):
    """Brinson-Hood-Beebower allocation effect: sum_i (wp_i - wb_i) * rb_i."""
    if not _pa_ok(wp, wb, rb):
        return float("nan")
    return math.fsum((p - b) * r for p, b, r in zip(wp, wb, rb))


def brinson_selection(wb, rp, rb):
    """BHB selection effect: sum_i wb_i * (rp_i - rb_i)."""
    if not _pa_ok(wb, rp, rb):
        return float("nan")
    return math.fsum(b * (p - r) for b, p, r in zip(wb, rp, rb))


def brinson_interaction(wp, wb, rp, rb):
    """BHB interaction effect: sum_i (wp_i - wb_i)(rp_i - rb_i)."""
    if not _pa_ok(wp, wb, rp, rb):
        return float("nan")
    return math.fsum((a - b) * (c - d) for a, b, c, d in zip(wp, wb, rp, rb))


def brinson_total_active(wp, wb, rp, rb):
    """Total active return sum_i wp_i rp_i - sum_i wb_i rb_i (= allocation+selection+interaction)."""
    if not _pa_ok(wp, wb, rp, rb):
        return float("nan")
    return math.fsum(p * r for p, r in zip(wp, rp)) - math.fsum(b * r for b, r in zip(wb, rb))


def active_share(wp, wb):
    """Active share vs the benchmark: 0.5 * sum_i |wp_i - wb_i|."""
    if not _pa_ok(wp, wb):
        return float("nan")
    return 0.5 * math.fsum(abs(p - b) for p, b in zip(wp, wb))


def portfolio_turnover(w_prev, w_curr):
    """One-sided turnover between two weight vectors: 0.5 * sum_i |w_curr_i - w_prev_i|."""
    if not _pa_ok(w_prev, w_curr):
        return float("nan")
    return 0.5 * math.fsum(abs(c - p) for p, c in zip(w_prev, w_curr))


def effective_number_of_bets(weight):
    """Naive effective number of positions (inverse Herfindahl): (sum w)^2 / sum w^2."""
    if not _pa_ok(weight):
        return float("nan")
    s = math.fsum(weight)
    s2 = math.fsum(w * w for w in weight)
    if s2 == 0:
        return float("nan")
    return s * s / s2


# ======================================================================================
# Pack RC - rates / curve analytics. A zero (spot) curve given as rate + tenor columns
# yields par yields, annuity factors and forward rates; a zero curve plus cashflows
# yields a multi-curve PV; effective duration / convexity come from bumping a single
# yield by +/-1bp and repricing. Discrete annual compounding DF_i = 1/(1+z_i)^t_i,
# matching the Pack FI conventions. Validated against numpy recomputes.
# ======================================================================================

def _rc_ok(*cols):
    n = len(cols[0])
    return n > 0 and all(len(c) == n for c in cols) and not any(_has_nan(c) for c in cols)


def _discount_factors(zero, time):
    return [1.0 / (1.0 + z) ** t for z, t in zip(zero, time)]


def annuity_factor(zero, time):
    """PV of $1 per period from the zero curve: sum_i 1/(1+z_i)^t_i."""
    if not _rc_ok(zero, time) or any(z <= -1.0 for z in zero):
        return float("nan")
    return math.fsum(_discount_factors(zero, time))


def par_yield(zero, time):
    """Annual-pay par coupon from the zero curve: (1 - DF_n) / sum_i DF_i."""
    if not _rc_ok(zero, time) or any(z <= -1.0 for z in zero):
        return float("nan")
    df = _discount_factors(zero, time)
    s = math.fsum(df)
    if s == 0:
        return float("nan")
    return (1.0 - df[-1]) / s


def forward_rate(zero, time):
    """Implied forward rate between the final two curve tenors:
    ((1+z2)^t2 / (1+z1)^t1)^(1/(t2-t1)) - 1."""
    if not _rc_ok(zero, time) or len(zero) < 2:
        return float("nan")
    z1, z2, t1, t2 = zero[-2], zero[-1], time[-2], time[-1]
    if z1 <= -1.0 or z2 <= -1.0 or t2 == t1:
        return float("nan")
    g = (1.0 + z2) ** t2 / (1.0 + z1) ** t1
    if g <= 0:
        return float("nan")
    return g ** (1.0 / (t2 - t1)) - 1.0


def curve_pv(cashflow, zero, time):
    """Present value of a cashflow stream under a zero curve: sum_i CF_i/(1+z_i)^t_i."""
    if not _rc_ok(cashflow, zero, time) or any(z <= -1.0 for z in zero):
        return float("nan")
    return math.fsum(cf / (1.0 + z) ** t for cf, z, t in zip(cashflow, zero, time))


def effective_duration(cashflow, time, y, bump=1e-4):
    """Bump-and-reprice effective duration: (P(y-d) - P(y+d)) / (2 P(y) d), d = 1bp."""
    p0 = bond_price(cashflow, time, y)
    pu = bond_price(cashflow, time, y + bump)
    pd = bond_price(cashflow, time, y - bump)
    if p0 != p0 or pu != pu or pd != pd or p0 == 0:
        return float("nan")
    return (pd - pu) / (2.0 * p0 * bump)


def effective_convexity(cashflow, time, y, bump=1e-4):
    """Bump-and-reprice effective convexity: (P(y+d) + P(y-d) - 2P(y)) / (P(y) d^2), d = 1bp."""
    p0 = bond_price(cashflow, time, y)
    pu = bond_price(cashflow, time, y + bump)
    pd = bond_price(cashflow, time, y - bump)
    if p0 != p0 or pu != pu or pd != pd or p0 == 0:
        return float("nan")
    return (pu + pd - 2.0 * p0) / (p0 * bump * bump)


# ======================================================================================
# Pack FM - fund / LP economics. Capital-call (contribution) and distribution columns,
# with residual NAV / committed / carry conventions, give the LP performance multiples
# allocators and ODD teams quote: DPI, RVPI, TVPI, called %, carry and realization. All
# definitional ratios under correctly-rounded summation.
# ======================================================================================

def _fm_ok(*cols):
    n = len(cols[0])
    return n > 0 and all(len(c) == n for c in cols) and not any(_has_nan(c) for c in cols)


def dpi(contribution, distribution):
    """Distributions to paid-in: sum(distribution) / sum(contribution)."""
    if not _fm_ok(contribution, distribution):
        return float("nan")
    c = math.fsum(contribution)
    if c <= 0:
        return float("nan")
    return math.fsum(distribution) / c


def rvpi(contribution, nav):
    """Residual value to paid-in: NAV / sum(contribution)."""
    if not _fm_ok(contribution):
        return float("nan")
    c = math.fsum(contribution)
    if c <= 0:
        return float("nan")
    return nav / c


def tvpi(contribution, distribution, nav):
    """Total value to paid-in: (sum(distribution) + NAV) / sum(contribution)."""
    if not _fm_ok(contribution, distribution):
        return float("nan")
    c = math.fsum(contribution)
    if c <= 0:
        return float("nan")
    return (math.fsum(distribution) + nav) / c


def called_pct(contribution, committed):
    """Called / drawn fraction of the commitment: sum(contribution) / committed."""
    if not _fm_ok(contribution) or committed <= 0:
        return float("nan")
    return math.fsum(contribution) / committed


def carried_interest(contribution, distribution, carry_rate):
    """European-waterfall carry on the net gain: rate * max(sum(dist) - sum(contrib), 0)."""
    if not _fm_ok(contribution, distribution) or not (0.0 <= carry_rate <= 1.0):
        return float("nan")
    gain = math.fsum(distribution) - math.fsum(contribution)
    return carry_rate * gain if gain > 0 else 0.0


def realization_ratio(distribution, nav):
    """Fraction of total value already realized in cash: sum(dist) / (sum(dist) + NAV)."""
    if not _fm_ok(distribution):
        return float("nan")
    d = math.fsum(distribution)
    tot = d + nav
    if tot <= 0:
        return float("nan")
    return d / tot


# ======================================================================================
# Pack LQ - liquidity / microstructure. Price-impact and spread estimators desks and ODD
# teams quote: Amihud illiquidity, Amivest liquidity, Roll's effective spread from serial
# covariance, Kyle's lambda price-impact slope, VWAP and the relative quoted spread. All
# definitional / documented closed forms. Validated against numpy recomputes.
# ======================================================================================

def _lq_ok(*cols):
    n = len(cols[0])
    return n > 0 and all(len(c) == n for c in cols) and not any(_has_nan(c) for c in cols)


def amihud_illiquidity(ret, dollar_volume):
    """Amihud (2002) illiquidity: mean(|ret_t| / dollar_volume_t) over the days."""
    if not _lq_ok(ret, dollar_volume) or any(v <= 0 for v in dollar_volume):
        return float("nan")
    return fmean([abs(r) / v for r, v in zip(ret, dollar_volume)])


def amivest_liquidity(ret, dollar_volume):
    """Amivest liquidity ratio: sum(dollar_volume) / sum(|ret|) over nonzero-return days."""
    if not _lq_ok(ret, dollar_volume):
        return float("nan")
    num = math.fsum(v for r, v in zip(ret, dollar_volume) if r != 0.0)
    den = math.fsum(abs(r) for r in ret if r != 0.0)
    if den <= 0:
        return float("nan")
    return num / den


def roll_spread(price):
    """Roll (1984) effective spread: 2*sqrt(-cov(dp_t, dp_{t-1})), nan if the serial
    covariance of price changes is non-negative."""
    if not _lq_ok(price) or len(price) < 3:
        return float("nan")
    d = [price[i] - price[i - 1] for i in range(1, len(price))]
    c = covariance(d[:-1], d[1:])
    if c != c or c >= 0:
        return float("nan")
    return 2.0 * math.sqrt(-c)


def kyle_lambda(price_change, signed_volume):
    """Kyle's lambda price-impact slope: cov(dp, q) / var(q) (OLS slope of dp on signed flow)."""
    if not _lq_ok(price_change, signed_volume) or len(price_change) < 2:
        return float("nan")
    vq = covariance(signed_volume, signed_volume)
    if vq != vq or vq == 0:
        return float("nan")
    return covariance(price_change, signed_volume) / vq


def vwap(price, volume):
    """Volume-weighted average price: sum(price_i * volume_i) / sum(volume_i)."""
    if not _lq_ok(price, volume):
        return float("nan")
    tot = math.fsum(volume)
    if tot == 0:
        return float("nan")
    return math.fsum(p * v for p, v in zip(price, volume)) / tot


def relative_spread(bid, ask):
    """Mean relative quoted spread: mean((ask_t - bid_t) / midpoint_t), midpoint=(ask+bid)/2."""
    if not _lq_ok(bid, ask):
        return float("nan")
    vals = []
    for b, a in zip(bid, ask):
        mid = 0.5 * (a + b)
        if mid <= 0:
            return float("nan")
        vals.append((a - b) / mid)
    return fmean(vals)


# ======================================================================================
# Pack AB - multiple-testing corrections (experiment / A-B depth). A p-value column and a
# family alpha give the rejection count under each procedure; complements the existing
# Benjamini-Hochberg and Holm-Bonferroni. Validated against statsmodels.multipletests.
# ======================================================================================

def bonferroni_rejections(pvals, alpha):
    """Count rejected by Bonferroni at family alpha: p_i <= alpha/m."""
    m = len(pvals)
    if m < 1 or _has_nan(pvals):
        return float("nan")
    thr = alpha / m
    return float(sum(1 for p in pvals if p <= thr))


def sidak_rejections(pvals, alpha):
    """Count rejected by single-step Sidak: p_i <= 1-(1-alpha)^(1/m)."""
    m = len(pvals)
    if m < 1 or _has_nan(pvals):
        return float("nan")
    thr = 1.0 - (1.0 - alpha) ** (1.0 / m)
    return float(sum(1 for p in pvals if p <= thr))


def holm_sidak_rejections(pvals, alpha):
    """Count rejected by step-down Holm-Sidak: sorted p_(k) <= 1-(1-alpha)^(1/(m-k+1))."""
    m = len(pvals)
    if m < 1 or _has_nan(pvals):
        return float("nan")
    sp = sorted(pvals)
    count = 0
    for k in range(1, m + 1):
        if sp[k - 1] <= 1.0 - (1.0 - alpha) ** (1.0 / (m - k + 1)):
            count += 1
        else:
            break
    return float(count)


def hochberg_rejections(pvals, alpha):
    """Count rejected by Hochberg step-up (Simes-Hochberg): largest k with p_(k) <= alpha/(m-k+1)."""
    m = len(pvals)
    if m < 1 or _has_nan(pvals):
        return float("nan")
    sp = sorted(pvals)
    maxk = 0
    for k in range(1, m + 1):
        if sp[k - 1] <= alpha / (m - k + 1):
            maxk = k
    return float(maxk)


def benjamini_yekutieli(pvals, alpha):
    """Count rejected by Benjamini-Yekutieli FDR: BH with the c(m)=sum_{i=1}^m 1/i penalty."""
    m = len(pvals)
    if m < 1 or _has_nan(pvals):
        return float("nan")
    c = math.fsum(1.0 / i for i in range(1, m + 1))
    sp = sorted(pvals)
    maxk = 0
    for k in range(1, m + 1):
        if sp[k - 1] <= (k / (m * c)) * alpha:
            maxk = k
    return float(maxk)


# ======================================================================================
# Pack TS - time-series / return diagnostics. The Lo-MacKinlay variance ratio (random-walk
# / mean-reversion), the Wald-Wolfowitz runs test (sign randomness, continuity-corrected),
# and Engle's ARCH-LM(1) test for volatility clustering. Validated against documented
# closed forms and statsmodels (runstest_1samp, het_arch).
# ======================================================================================

def variance_ratio(rets, q):
    """Lo-MacKinlay (1988) overlapping unbiased variance ratio VR(q): sigma_c^2 / sigma_a^2,
    1 for a random walk, <1 mean-reverting, >1 trending. q-period vs 1-period variance."""
    n = len(rets)
    if not rets or _has_nan(rets) or q < 2 or n <= q:
        return float("nan")
    mu = fmean(rets)
    sa = math.fsum((r - mu) ** 2 for r in rets) / (n - 1)
    if sa == 0:
        return float("nan")
    m = q * (n - q + 1) * (1.0 - q / n)
    if m <= 0:
        return float("nan")
    parts = []
    for t in range(q - 1, n):
        s = math.fsum(rets[t - q + 1:t + 1])
        parts.append((s - q * mu) ** 2)
    sc = math.fsum(parts) / m
    return sc / sa


def runs_test(xs, cutoff=0.0):
    """Wald-Wolfowitz runs test z-statistic for sign randomness (indicator x_t >= cutoff).
    Matches statsmodels runstest_1samp: the SAS 0.5 continuity correction is applied only
    for n < 50."""
    n = len(xs)
    if n < 2 or _has_nan(xs):
        return float("nan")
    ind = [1 if v >= cutoff else 0 for v in xs]
    n1 = sum(ind)
    n2 = n - n1
    if n1 == 0 or n2 == 0:
        return float("nan")
    runs = 1 + sum(1 for i in range(1, n) if ind[i] != ind[i - 1])
    exp = 2.0 * n1 * n2 / n + 1.0
    var = 2.0 * n1 * n2 * (2.0 * n1 * n2 - n) / (n * n * (n - 1))
    if var <= 0:
        return float("nan")
    rdemean = runs - exp
    if n >= 50:
        z = rdemean
    elif rdemean > 0.5:
        z = rdemean - 0.5
    elif rdemean < 0.5:
        z = rdemean + 0.5
    else:
        z = 0.0
    return z / math.sqrt(var)


def arch_lm(resid):
    """Engle ARCH-LM(1) statistic: nobs * R^2 from regressing squared residuals on their
    first lag (with intercept); chi-square(1) under no ARCH effect (statsmodels het_arch)."""
    n = len(resid)
    if n < 3 or _has_nan(resid):
        return float("nan")
    e2 = [r * r for r in resid]
    y = e2[1:]
    x = e2[:-1]
    nn = len(y)
    mx, my = fmean(x), fmean(y)
    sxx = math.fsum((a - mx) ** 2 for a in x)
    if sxx == 0:
        return float("nan")
    b = math.fsum((a - mx) * (c - my) for a, c in zip(x, y)) / sxx
    a0 = my - b * mx
    ssr = math.fsum((c - (a0 + b * a)) ** 2 for a, c in zip(x, y))
    sst = math.fsum((c - my) ** 2 for c in y)
    if sst == 0:
        return float("nan")
    return nn * (1.0 - ssr / sst)
