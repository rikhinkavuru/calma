"""calma.plausibility_checks - V6: thin-input statistical "smell" flags. On the findings rail, called
from calma._assemble_ledger like the other validity families. Pure stdlib (numeric.py's deterministic
Sharpe + Pearson). These are the ONLY checks that need NO declared block: they fire from the bound
return series alone, so they narrow the "cooperation wall" (every other family stays silent until the
producer declares the structure - split / trials / frictions / corpus / windows - that exposes its own
flaw). Here nothing has to be volunteered.

What it flags (deterministic arithmetic, never a model):
  - implausibly-high Sharpe: a per-period Sharpe so high it is implausible at any sub-annual frequency
    (selection bias / look-ahead / in-sample fit are the usual causes). The locator annualizes it at
    daily/weekly/monthly so the reader can sanity-check the periodicity + annualization convention.
  - too-smooth equity curve: high positive lag-1 serial correlation of returns - the Getmansky-Lo-
    Makarov return-smoothing signature (stale / illiquid marks, or a synthetic curve), which inflates
    Sharpe and hides drawdown.

HONESTY INVARIANT - these are HEURISTICS, never proof. A high Sharpe or a smooth curve is suspicious,
not wrong. So this family is SOFT-ONLY: it can DEGRADE a would-be CONFIRMED to CONFIRMED-WITH-CAVEATS
(soft_validity_caveat) and surface a precise "here's what to check" finding - it can NEVER reach
INVALIDATED or REFUTED. That stays the job of the authoritative families (which need the declared
structure) and the gap-gated recompute path. A smell buys margin and tells you where to look; it does
not catch a liar. The caveat is informational: the number still reproduced.

Scope: applicable whenever the headline metric binds a `return` column (a trading / backtest series);
silent on accuracy / AUC / RMSE / etc. ABSTAINS without enough history. No contract block required.

Library: run_checks(contract, base, claim_id, claim_text) -> [finding,...];
apply_validity(claims, findings, contract, claim_text, base=None); family_status(contract, findings).
"""
import csv
import os

import numeric as N
import verdict as V

_MIN_OBS = 24          # enough points for a meaningful per-period Sharpe + a lag-1 autocorrelation
_HI_SHARPE = 1.0       # per-period Sharpe above this is implausible at any sub-annual frequency
                       # (x sqrt(252) daily ~= 15.9, x sqrt(52) weekly ~= 7.2, x sqrt(12) monthly ~= 3.5)
_HI_AUTOCORR = 0.35    # lag-1 serial correlation above this is the return-smoothing / stale-mark smell;
                       # liquid period-over-period returns sit near zero
# annualization factors (literal so the locator stays dependency-free and bit-identical cross-platform)
_ANN_DAILY, _ANN_WEEKLY, _ANN_MONTHLY = 15.87, 7.21, 3.46


def _headline(contract):
    mets = contract.get("metrics") or []
    for m in mets:
        if m.get("headline") and m.get("claimed_value") is not None:
            return m
    for m in mets:
        if m.get("headline"):
            return m
    return mets[0] if mets else None


def _binds_return(contract):
    m = _headline(contract)
    return bool(m and (m.get("binding") or {}).get("return"))


def _safe_join(base, rel):
    full = os.path.realpath(os.path.join(base, rel))
    rb = os.path.realpath(base)
    if full != rb and not full.startswith(rb + os.sep):
        raise ValueError("path escapes the contract base: %r" % rel)
    return full


def _returns(contract, base):
    m = _headline(contract)
    if not m:
        return None
    rcol = (m.get("binding") or {}).get("return")
    if not rcol:
        return None
    try:
        path = _safe_join(base, m.get("artifact", ""))
    except ValueError:
        return None
    if not os.path.isfile(path):
        return None
    try:
        with open(path, newline="") as fh:
            rd = csv.reader(fh)
            header = next(rd, [])
            if rcol not in header:
                return None
            j = header.index(rcol)
            out = []
            for r in rd:
                if j < len(r):
                    try:
                        out.append(float(r[j]))
                    except (TypeError, ValueError):
                        pass
        return out
    except (OSError, StopIteration, csv.Error):
        return None


def _lag1_autocorr(rets):
    """Deterministic lag-1 serial correlation via numeric.pearson_r(rets[:-1], rets[1:]). None if the
    series has no variance (a constant series has undefined correlation - never a smell)."""
    if len(rets) < 3:
        return None
    if N.fstd(rets, 1) == 0.0:
        return None
    r = N.pearson_r(rets[:-1], rets[1:])
    return r if r == r else None  # NaN guard


def check_high_sharpe(contract, base, claim_id="c1"):
    """A per-period Sharpe so high it is implausible at any sub-annual frequency. Heuristic (soft)."""
    rets = _returns(contract, base)
    if not rets or len(rets) < _MIN_OBS:
        return None
    sr = N.sharpe(rets, 1)[0]
    if not (sr == sr) or sr <= _HI_SHARPE:
        return None
    return {
        "id": "f-%s-plausibility-sharpe" % claim_id, "claim_id": claim_id, "dimension": "plausibility",
        "severity": "minor", "status": "open", "confidence": "heuristic", "fixable_by": "author",
        "locator": ("statistical smell: per-period Sharpe %.2f is implausibly high - if these are daily "
                    "returns it annualizes to ~%.1f (x sqrt(252)), weekly ~%.1f, monthly ~%.1f. A real "
                    "edge this strong is rare; the usual causes are selection bias, look-ahead, or an "
                    "in-sample fit reported as out-of-sample"
                    % (sr, sr * _ANN_DAILY, sr * _ANN_WEEKLY, sr * _ANN_MONTHLY)),
        "unblock": ("confirm the periodicity and annualization convention, then validate out-of-sample "
                    "(walk-forward) or declare the trials block so the deflated Sharpe / PBO can run"),
        "reverify": {"kind": "artifact-recheck", "source": "returns",
                     "expected": "the Sharpe is plausible for the declared periodicity and is reproduced out-of-sample"},
        "validity_class": "heuristic", "plausibility_kind": "high-sharpe",
    }


def check_smooth_curve(contract, base, claim_id="c1"):
    """High positive lag-1 serial correlation of returns - the return-smoothing / stale-mark smell. Soft."""
    rets = _returns(contract, base)
    if not rets or len(rets) < _MIN_OBS:
        return None
    ac = _lag1_autocorr(rets)
    if ac is None or ac <= _HI_AUTOCORR:
        return None
    return {
        "id": "f-%s-plausibility-smooth" % claim_id, "claim_id": claim_id, "dimension": "plausibility",
        "severity": "minor", "status": "open", "confidence": "heuristic", "fixable_by": "author",
        "locator": ("statistical smell: the equity curve is suspiciously smooth - lag-1 serial "
                    "correlation of returns is %.2f (liquid period-over-period returns sit near zero). "
                    "This is the return-smoothing signature of stale or illiquid marks, which inflates "
                    "Sharpe and understates drawdown" % ac),
        "unblock": ("mark to liquid prices / use point-in-time fills, or unsmooth the series (e.g. "
                    "Getmansky-Lo-Makarov) and recompute the risk-adjusted number on the unsmoothed returns"),
        "reverify": {"kind": "artifact-recheck", "source": "returns",
                     "expected": "lag-1 return autocorrelation is near zero on liquid marks"},
        "validity_class": "heuristic", "plausibility_kind": "smooth-curve",
    }


_CHECKS = (check_high_sharpe, check_smooth_curve)


def run_checks(contract, base, claim_id="c1", claim_text=None):
    """Thin-input smells off the bound return series. Applicable whenever the headline binds a `return`
    column - NO contract block required. Fail-soft: any check that errors is skipped."""
    if not _binds_return(contract):
        return []
    out = []
    for fn in _CHECKS:
        try:
            f = fn(contract, base, claim_id)
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError, IndexError):
            f = None
        if f:
            out.append(f)
    return out


def family_status(contract, findings):
    """A fired smell -> 'flagged'; a return series with no smell -> 'checked'; otherwise NOT-APPLICABLE.
    NOTE: this family is intentionally NOT listed in scope.not_verified - a heuristic flag layer that
    finds nothing is not an authoritative coverage gap the way a missing split / trials block is."""
    if any(f.get("dimension") == "plausibility" for f in findings):
        return "flagged"
    return "checked" if _binds_return(contract) else "not-applicable"


def apply_validity(claims, findings, contract, claim_text, base=None):
    """Promote the headline per the plausibility findings. SOFT-ONLY and CONSERVATIVE: only a REPRODUCED
    number (CONFIRMED/CAVEATS) is touched, and only DOWN to a CAVEAT (soft_validity_caveat). This family
    NEVER sets validity_invalidated / oos_claim_asserted and NEVER drives the dimension - a smell is a
    heads-up, not a verdict. claim_text is unused (a smell fires regardless of what the claim asserts)."""
    sm = [f for f in findings if f.get("dimension") == "plausibility"]
    if not sm or not claims:
        return
    head = next((c for c in claims if c.get("headline")), claims[0])
    if head.get("verdict") not in (V.CONFIRMED, V.CAVEATS):
        return
    vi = head.get("verdict_inputs") or {}
    vi["soft_validity_caveat"] = True
    head["verdict_inputs"] = vi
    head["verdict"] = V.verdict(vi)
    head["headline_confidence"] = V.confidence(vi, head["verdict"])
