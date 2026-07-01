"""calma.spike.core.interval — prediction intervals for stochastic claims (feature 6).

Some correct repos are simply unseeded: every run gives a slightly different number, so the empirical k≥2 check
flags NON-DETERMINISTIC and refuses to CONFIRM even when the code is right. This builds a prediction interval
for a FUTURE single run from the repo's own run-to-run values, so a claimed number CONSISTENT with that
distribution can reach a distinct CONFIRMED-STOCHASTIC verdict (never the hard CONFIRMED), and one plainly
outside it is REFUTED.

FCR discipline: the interval is over the repo's OWN produced values (each run's headline number), so a
fabricated claim that matches no run falls outside → REFUTED, not confirmed. Below `k_min` runs there is no
power → `enough=False` → the caller stays INCONCLUSIVE (fail-closed). Pure stdlib (`statistics.NormalDist`).
"""
from __future__ import annotations

import math
import statistics

from . import tolerance as T

# two-sided Student-t critical values at 99% (one-tail 0.005), df = 1..30. df>30 → the normal limit (inflated).
_T99 = {1: 63.657, 2: 9.925, 3: 5.841, 4: 4.604, 5: 4.032, 6: 3.707, 7: 3.499, 8: 3.355, 9: 3.250,
        10: 3.169, 11: 3.106, 12: 3.055, 13: 3.012, 14: 2.977, 15: 2.947, 16: 2.921, 17: 2.898, 18: 2.878,
        19: 2.861, 20: 2.845, 21: 2.831, 22: 2.819, 23: 2.807, 24: 2.797, 25: 2.787, 26: 2.779, 27: 2.771,
        28: 2.763, 29: 2.756, 30: 2.750}


def _t_crit(df: int, coverage: float) -> float:
    if coverage <= 0.99:
        if df in _T99:
            return _T99[df]
        if df > 30:
            return 2.576
    z = statistics.NormalDist().inv_cdf(1 - (1 - coverage) / 2)
    return z * (1 + 2.0 / max(1, df))       # small-sample inflation when we fall back to the normal quantile


def predict_interval(values, coverage: float = 0.99, k_min: int = 5) -> dict:
    """Prediction interval for a future single run. Returns {lo, hi, center, sd, n, enough, method}. The
    interval is the WIDER of a Student-t future-observation interval and a nonparametric min/max envelope
    widened by the observed range — conservative against under-covering (which would false-REFUTE a correct
    unseeded number). `enough` is False below k_min (no power → caller stays INCONCLUSIVE)."""
    vals = [float(v) for v in (values or []) if isinstance(v, (int, float)) and v == v]
    n = len(vals)
    if n < 2:
        return {"lo": None, "hi": None, "center": (vals[0] if vals else None), "sd": 0.0, "n": n,
                "enough": False, "method": "insufficient"}
    mean = statistics.fmean(vals)
    sd = statistics.stdev(vals)
    t = _t_crit(n - 1, coverage)
    half_t = t * sd * math.sqrt(1 + 1.0 / n)
    lo_t, hi_t = mean - half_t, mean + half_t
    rng = max(vals) - min(vals)
    lo_np, hi_np = min(vals) - 0.5 * rng, max(vals) + 0.5 * rng
    lo, hi = min(lo_t, lo_np), max(hi_t, hi_np)
    return {"lo": lo, "hi": hi, "center": mean, "sd": sd, "n": n, "enough": n >= k_min,
            "obs_lo": min(vals), "obs_hi": max(vals), "method": "t+envelope", "coverage": coverage}


def contains(interval: dict, claimed_raw) -> bool:
    """Is the as-written `claimed_raw` inside the interval? Rounding-aware at the edges (a claim '0.83' is
    accepted if its rounding band overlaps [lo, hi])."""
    if not interval or interval.get("lo") is None:
        return False
    val, decimals, _kind = T.parse_claim(claimed_raw)
    if val is None:
        return False
    # CONFIRMED-STOCHASTIC must affirm only a claim the code ACTUALLY produced — not an extrapolated tail of the
    # t+envelope prediction interval (which, especially at small k, extends beyond every observed run and would
    # affirm a favorable never-produced value, exactly the seed-cherry-picking risk the doctrine warns about).
    # So `contains` checks the OBSERVED run range [obs_lo, obs_hi], widened only by the claim's own rounding
    # pad. (The wider prediction interval is still used by `outside_by_margin` to decide REFUTED vs the
    # fail-closed INCONCLUSIVE near-edge band.)
    lo = interval.get("obs_lo", interval["lo"])
    hi = interval.get("obs_hi", interval["hi"])
    if decimals == 0 and abs(val) <= 1.0:
        pad = 5e-4 * max(abs(val), 1.0)
    elif decimals is not None:
        pad = 0.5 * (10 ** (-decimals)) + 1e-9
    else:
        pad = 5e-4 * max(abs(val), 1.0)
    return (lo - pad) <= val <= (hi + pad)


def outside_by_margin(interval: dict, claimed_raw, margin: float = 0.5) -> bool:
    """Is the claim CLEARLY outside the interval — beyond `margin`×(interval width) past an edge? Used to REFUTE
    a stochastic claim only when it is unambiguously not from the distribution; the near-edge band stays
    INCONCLUSIVE (never a false-refute)."""
    if not interval or interval.get("lo") is None:
        return False
    val, _dec, _kind = T.parse_claim(claimed_raw)
    if val is None:
        return False
    w = (interval["hi"] - interval["lo"]) or abs(interval.get("center") or 0.0) or 1.0
    return val < interval["lo"] - margin * w or val > interval["hi"] + margin * w
