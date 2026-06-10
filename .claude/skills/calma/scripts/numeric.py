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
