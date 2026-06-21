"""calma.regime_checks - V3: walk-forward / regime robustness. On the findings rail, called from
calma._assemble_ledger like the other validity families. Pure stdlib (numeric.py's deterministic KS
two-sample + Sharpe). A result that holds only in ONE regime / window is not the robust claim asserted.

Method:
  - Walk-forward IS/OOS: split the return series into an in-sample (early) and out-of-sample (late)
    half; a meaningful in-sample edge that COLLAPSES out-of-sample (the PBO intuition applied across
    TIME) is not robust. Reported: the IS vs OOS Sharpe + cumulative return.
  - Regime-shift: a two-sample Kolmogorov-Smirnov test of the return distribution across the two halves
    (numeric.ks_2samp / ks_p); a low p corroborates that the OOS collapse is a genuine regime shift, not
    sampling noise. The result is concentrated in one regime.

Scope: applicable when a `windows` block is declared OR the CLAIM asserts robustness / walk-forward /
out-of-sample / consistency-across-regimes (auto-windows the series then). ABSTAINS without enough
history. Promotion (mirrors the other families): an OOS collapse under a robustness/walk-forward claim
-> INVALIDATED("regime"); the same finding next to a bare reproduced number (windows block declared,
no robustness assertion) -> a CAVEAT. REFUTED is never manufactured here.

Library: run_checks(contract, base, claim_id, claim_text) -> [finding,...];
apply_validity(claims, findings, contract, claim_text, base=None); family_status(contract, findings).
"""
import csv
import os
import re

import numeric as N
import pathsafe as PS
import verdict as V

_MIN_OBS = 20          # need >= 10 per half for a meaningful KS / Sharpe split
_MIN_IS_SR = 0.05      # the in-sample per-period Sharpe must be a real edge before "it collapsed" means anything
_DEGRADE_FRAC = 0.25   # OOS Sharpe below this fraction of IS Sharpe is a collapse
_KS_ALPHA = 0.10       # the regime shift must be statistically visible (corroborates the collapse)

_ROBUST_RE = re.compile(
    r"robust (across|over|to|in) (the )?(regime|time|period|sample|window|market)|walk.?forward|"
    r"out.?of.?sample|\boos\b|consistent (across|over|through) (time|regime|period|the sample|market)|"
    r"holds (across|in every|out of sample|through)|every regime|all regimes|stable across|"
    r"regime.?(robust|independent|agnostic)|persists (across|over|out)", re.I)


def _safe_join(base, rel):
    """Resolve rel under base; refuse escapes (abs path / .. traversal / symlink-out). Delegates to the
    shared guard (pathsafe) so there is ONE audited containment implementation (L1)."""
    return PS.safe_join(base, rel)


def _headline(contract):
    mets = contract.get("metrics") or []
    for m in mets:
        if m.get("headline") and m.get("claimed_value") is not None:
            return m
    for m in mets:
        if m.get("headline"):
            return m
    return mets[0] if mets else None


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
    if not PS.within_cap(path):
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


def _applicable(contract, claim_text):
    if contract.get("windows"):
        return True
    # claim_text may be a non-string (the replay path passes the claimed numeric) - a numeric claim
    # carries no NL robustness assertion, so coerce to "" rather than crash on the regex.
    return bool(isinstance(claim_text, str) and _ROBUST_RE.search(claim_text))


def check_regime(contract, base, claim_id="c1", claim_text=None):
    """Walk-forward IS/OOS collapse + a corroborating regime-shift KS test. Authoritative."""
    rets = _returns(contract, base)
    if not rets or len(rets) < _MIN_OBS:
        return None  # ABSTAIN: not enough history to split
    half = len(rets) // 2
    is_r, oos_r = rets[:half], rets[half:]
    is_sr = N.sharpe(is_r, 1)[0]
    oos_sr = N.sharpe(oos_r, 1)[0]
    if not (is_sr == is_sr) or is_sr <= _MIN_IS_SR:
        return None  # no in-sample edge to collapse -> nothing to flag
    collapses = (oos_sr != oos_sr) or oos_sr < _DEGRADE_FRAC * is_sr
    if not collapses:
        return None
    p = N.ks_p(is_r, oos_r)
    d = N.ks_2samp(is_r, oos_r)
    if not (p == p) or p >= _KS_ALPHA:
        return None  # the halves are not distinguishable -> the "collapse" is within noise; no false alarm
    is_cr, oos_cr = N.total_return(is_r), N.total_return(oos_r)
    return {
        "id": "f-%s-regime" % claim_id, "claim_id": claim_id, "dimension": "regime",
        "severity": "major", "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": ("walk-forward: the edge holds in-sample (Sharpe %.3f, return %.4f over the first "
                    "half) but collapses out-of-sample (Sharpe %.3f, return %.4f) - a two-sample KS test "
                    "rejects equal distributions (D=%.3f, p=%.4f), so the result is concentrated in one "
                    "regime, not robust across the sample" % (is_sr, is_cr, oos_sr, oos_cr, d, p)),
        "unblock": ("validate walk-forward (rolling IS/OOS) and report the OOS Sharpe distribution, or "
                    "scope the claim to the regime the edge actually holds in"),
        "reverify": {"kind": "requires-reexecution", "source": "windows",
                     "expected": "the OOS Sharpe is consistent with the in-sample edge across windows"},
        "validity_class": "authoritative", "regime_kind": "walk-forward",
    }


def run_checks(contract, base, claim_id="c1", claim_text=None):
    """Regime/walk-forward findings. SILENT unless a `windows` block is declared OR the claim asserts
    robustness/walk-forward. Fail-soft: any check that errors is skipped."""
    if not _applicable(contract, claim_text):
        return []
    try:
        f = check_regime(contract, base, claim_id, claim_text)
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError, IndexError):
        f = None
    return [f] if f else []


def family_status(contract, findings):
    """Honest scope.families.regime status. A fired finding -> 'flagged' (even when the family was
    activated by a robustness claim rather than a declared `windows` block); a declared `windows` block
    with no finding -> 'checked'; otherwise NOT-APPLICABLE."""
    if any(f.get("dimension") == "regime" for f in findings):
        return "flagged"
    return "checked" if contract.get("windows") else "not-applicable"


def apply_validity(claims, findings, contract, claim_text, base=None):
    """Promote the headline per the regime findings + claim scope. Conservative: only a REPRODUCED number
    (CONFIRMED/CAVEATS) is promoted, and only DOWN. An OOS collapse under a robustness/walk-forward claim
    -> INVALIDATED("regime"); the same finding next to a bare reproduced number -> a CAVEAT."""
    reg = [f for f in findings if f.get("dimension") == "regime"]
    if not reg or not claims:
        return
    head = next((c for c in claims if c.get("headline")), claims[0])
    if head.get("verdict") not in (V.CONFIRMED, V.CAVEATS):
        return
    vi = head.get("verdict_inputs") or {}
    if isinstance(claim_text, str) and _ROBUST_RE.search(claim_text):
        for f in reg:
            f["severity"] = "blocker"
            f["claim_id"] = head["id"]
        vi["validity_invalidated"] = True
        vi["oos_claim_asserted"] = True
        head["driving_dimension"] = "regime"
    else:
        vi["soft_validity_caveat"] = True
    head["verdict_inputs"] = vi
    head["verdict"] = V.verdict(vi)
    head["headline_confidence"] = V.confidence(vi, head["verdict"])
