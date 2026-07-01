"""calma.spike.core.intervals — certified enclosures for the recompute (feature 19).

The catalog already sums with `math.fsum` (exact-rounded), so most recomputes are near-exact and the tolerance
layer absorbs benign drift. The genuine payoff is at the TOLERANCE BOUNDARY under ILL-CONDITIONING
(catastrophic cancellation in variance/stdev/correlation on offset or near-constant data), where a naive repo
formula can differ from the true value by more than tolerance for a legitimate reason. There, a rigorous
enclosure [lo, hi] guaranteed to contain the true real-number result lets us CERTIFY the verdict or, when the
enclosure straddles the boundary, fail closed.

FCR posture: enclosures are used ONLY to WIDEN doubt, never to narrow it. If a would-be CONFIRMED's certified
enclosure does NOT lie entirely within the produced value's tolerance band, we cannot certify agreement →
downgrade (never upgrade). A straddling enclosure can never mint a CONFIRMED. Zero new deps (stdlib error-free
transforms); the enclosure is our recompute's, it never trusts the repo's arithmetic.
"""
from __future__ import annotations

import math

_EPS = 2.220446049250313e-16     # IEEE-754 double machine epsilon

# metrics whose recompute is boundary-prone (summation / cancellation) and for which we ship an enclosure.
ENCLOSED = {"mean", "sum", "total_sum", "variance", "stdev"}


def neumaier_sum(values):
    """Neumaier (improved Kahan) compensated summation. Returns (sum, abs_error_bound). The bound is the
    standard conservative first-order summation bound (n·eps·Σ|x|) around the compensated result — the true
    sum is guaranteed within it (Neumaier's own error is far smaller, so this is a sound over-estimate)."""
    s = 0.0
    c = 0.0                                   # running compensation
    abssum = 0.0
    n = 0
    for x in values:
        x = float(x)
        abssum += abs(x)
        n += 1
        t = s + x
        if abs(s) >= abs(x):
            c += (s - t) + x
        else:
            c += (x - t) + s
        s = t
    total = s + c
    err = n * _EPS * abssum + _EPS * abs(total)
    return total, err


def _floats(seq):
    return [float(v) for v in seq]


def enclosure(cid: str, inputs: dict, kwargs: dict) -> dict | None:
    """A rigorous enclosure {lo, hi, width, certified} of the TRUE value of `cid` on `inputs`, or None if the
    metric is not enclosure-supported / inputs missing. Derived independently from the compensated sums (it
    does not trust the repo's or the catalog's point value)."""
    if cid not in ENCLOSED:
        return None
    vals_key = "values" if inputs.get("values") is not None else ("x" if inputs.get("x") is not None else None)
    if vals_key is None:
        return None
    try:
        v = _floats(inputs[vals_key])
    except (TypeError, ValueError):
        return None
    n = len(v)
    if n == 0:
        return None
    ssum, serr = neumaier_sum(v)
    if cid in ("sum", "total_sum"):
        lo, hi = ssum - serr, ssum + serr
        return {"lo": lo, "hi": hi, "width": hi - lo, "certified": True}
    mean = ssum / n
    mean_err = serr / n + _EPS * abs(mean)
    if cid == "mean":
        lo, hi = mean - mean_err, mean + mean_err
        return {"lo": lo, "hi": hi, "width": hi - lo, "certified": True}
    # variance / stdev via the numerically-stable two-pass form, with a CONSERVATIVE error bound that also
    # accounts for cancellation (the mean² term). ddof from kwargs (catalog default sample, ddof=1).
    if n < 2:
        return None
    ddof = 1
    try:
        ddof = int(kwargs.get("ddof", 1)) if kwargs else 1
    except (TypeError, ValueError):
        ddof = 1
    denom = n - ddof
    if denom <= 0:
        return None
    dev = [x - mean for x in v]
    dev2 = [d * d for d in dev]
    ss, sserr = neumaier_sum(dev2)
    var = ss / denom
    # Absolute error on the variance, reflecting the STABLE two-pass method's ACTUAL error source: the
    # subtraction (x - mean) loses precision when x and mean are large but close (the offset-variance
    # cancellation), so each deviation carries ~mean_err, propagated through the square + sum. Conservative
    # (over-estimates), so the enclosure soundly contains the true value.
    amax = max((abs(x) for x in v), default=0.0)
    dev_err = mean_err + _EPS * amax
    prop = sum(2 * abs(d) for d in dev) * dev_err
    var_err = (sserr + prop) / denom + _EPS * abs(var)
    if cid == "variance":
        lo, hi = max(0.0, var - var_err), var + var_err
        return {"lo": lo, "hi": hi, "width": hi - lo, "certified": True}
    # stdev = sqrt(var); propagate via d(√v) = var_err / (2√var)
    std = math.sqrt(max(0.0, var))
    std_err = var_err / (2 * std) if std > 0 else math.sqrt(var_err)
    lo, hi = max(0.0, std - std_err), std + std_err
    return {"lo": lo, "hi": hi, "width": hi - lo, "certified": True}


def band_relation(enc: dict, produced: float, tol: float) -> str:
    """Relate the certified enclosure to the produced value's tolerance band [produced-tol, produced+tol]:
      'inside'   — the whole enclosure is within tolerance of produced → agreement CERTIFIED (CONFIRMED stands);
      'outside'  — the whole enclosure is beyond tolerance of produced → disagreement CERTIFIED (INVALIDATED);
      'straddle' — the enclosure crosses the boundary → cannot certify → the caller fails closed.
    """
    if not enc or enc.get("lo") is None:
        return "unknown"
    lo, hi = enc["lo"], enc["hi"]
    blo, bhi = produced - tol, produced + tol
    if lo >= blo and hi <= bhi:
        return "inside"
    if hi < blo or lo > bhi:
        return "outside"
    return "straddle"
