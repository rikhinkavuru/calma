"""calma.data_snooping_checks - V2: study-wide multiple-testing / the Harvey-Liu-Zhu (HLZ) haircut.
On the findings rail, called from calma._assemble_ledger like the other validity families. Pure stdlib
(uses numeric.py's deterministic normal CDF / inverse - NO platform transcendental in the value path).

THE M4 GAP this closes: overfitting_checks runs DSR/PBO on a SINGLE strategy's trials matrix. V2
operates at the STUDY level - when a result is the best (or one) of N strategies/tests tried across a
whole study, the multiplicity must be corrected and the Sharpe HAIRCUT. HLZ ("...and the Cross-Section
of Expected Returns", RFS 2016; Harvey-Liu "Backtesting", JPM 2015): the t>2.0 bar is obsolete; a new
factor needs t > 3.0 after the multiple-testing haircut.

STATISTICS (exact, cited):
  - observed two-sided p from the t-stat: t = SR*sqrt(T); p = 2*(1 - Phi(|t|)).
  - multiplicity corrections over the N tests, for the disclosed (most-significant) result:
      Bonferroni:  p_adj = min(N*p, 1).
      Holm:        reject p_(k) iff p_(k) <= alpha/(N+1-k); for the rank-1 best, p_adj = min(N*p, 1).
      BHY (FDR, arbitrary dependence): c(N) = sum_{i=1..N} 1/i; for the rank-1 best, p_adj = p*N*c(N).
    HLZ use alpha_w=5% (Holm/Bonferroni FWER) and alpha_d=1% (BHY FDR).
  - the adjusted t recovers from the adjusted p: t_adj = Phi^-1(1 - p_adj/2). The HAIRCUT is
    (SR - SR_adj)/SR = (t - t_adj)/t (SR proportional to t for fixed T) - emergently nonlinear (a low
    SR is haircut far more than a high one). Implied t_adj < 3.0 -> not supported study-wide.
  - cross-check: this is the STUDY-level complement to overfitting's single-strategy DSR/PBO (the False
    Strategy Theorem deflation, E[max_N]); both can fire, both only DEGRADE.

N (#trials) and the per-test stats are the honest, hardest inputs. When a study is signalled but N is
NOT declared (no `trials` and no `trials_matrix`), the finding is "unverifiable (N not declared)" - N is
NEVER guessed (mirrors overfitting's discipline).

The `study` contract block:
  study:
    trials: 50                # N: the number of strategies/tests actually tried
    sharpe: 1.0               # the reported (best) per-period or annualised SR ...
    periods: 12               # ... measured over T periods (t = sharpe*sqrt(periods))
    # OR  t_stat: 3.46        # the observed t directly (overrides sharpe/periods)
    # OR  trials_matrix: "trials.csv"   # per-strategy returns -> N = #columns, best per-period Sharpe

Library: run_checks(contract, base, claim_id, claim_text) -> [finding,...];
apply_validity(claims, findings, contract, claim_text, base=None); family_status(contract, findings).
"""
import csv
import math
import os
import re

import numeric as N
import verdict as V

T_CRIT = 3.0          # HLZ: a new factor needs t > 3.0 after the multiple-testing haircut
_MAX_TRIALS = 10_000_000  # bound the harmonic sum on a hostile declared N

# the claim asserts the result is a GENUINE / significant / robust finding (the thing data-snooping
# invalidates) - keyed on the claim TEXT, mirroring the other families' scope guards.
_ASSERTS_RE = re.compile(
    r"statistically significant|\bsignificant\b|genuine|robust|real (edge|alpha|factor|effect|anomaly)|"
    r"new factor|true (edge|alpha|factor)|holds (up|out)|survives|stands up|not (data.?mined|spurious|"
    r"overfit)|\bt.?stat", re.I)


def study(contract):
    s = contract.get("study")
    return s if isinstance(s, dict) else None


def _harmonic(n):
    return sum(1.0 / i for i in range(1, int(n) + 1))


def _two_sided_p(t):
    return min(1.0, max(0.0, 2.0 * N.normal_sf(abs(t))))


def _adj_t(p_adj):
    """The t implied by a two-sided adjusted p. p>=1 -> t=0 (no significance); p->0 -> recover a large t."""
    p_adj = min(1.0, max(p_adj, 0.0))
    if p_adj >= 1.0:
        return 0.0
    if p_adj <= 0.0:
        return float("inf")
    return N.z_ppf(1.0 - p_adj / 2.0)


def haircut(t, n_trials):
    """The HLZ multiple-testing haircut for a single disclosed best result among n_trials tests.
    Returns {t, p, c_n, methods:{bonferroni|holm|bhy: {p_adj, t_adj, haircut}}}. Deterministic."""
    p = _two_sided_p(t)
    n = max(int(n_trials), 1)
    cN = _harmonic(n)
    out = {"t": t, "p": p, "c_n": cN, "methods": {}}
    for name, p_adj in (("bonferroni", min(1.0, n * p)),
                        ("holm", min(1.0, n * p)),         # rank-1 Holm == Bonferroni for the single best
                        ("bhy", min(1.0, p * n * cN))):
        ta = _adj_t(p_adj)
        hc = ((t - ta) / t) if t > 0 and ta == ta and ta != float("inf") else 0.0
        out["methods"][name] = {"p_adj": p_adj, "t_adj": ta, "haircut": max(0.0, hc)}
    return out


def _trials_from_matrix(contract, base, s):
    """N = #columns of a declared per-strategy returns matrix; the best per-period Sharpe sets t when no
    sharpe/t is declared. Returns (n, best_sr) or (None, None)."""
    rel = s.get("trials_matrix")
    if not rel:
        return None, None
    path = os.path.realpath(os.path.join(base, rel))
    rb = os.path.realpath(base)
    if path != rb and not path.startswith(rb + os.sep):
        return None, None  # path escape
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, newline="") as fh:
            rd = csv.reader(fh)
            header = next(rd, [])
            rows = []
            for r in rd:
                vals = []
                for x in r:
                    try:
                        vals.append(float(x))
                    except (TypeError, ValueError):
                        vals.append(float("nan"))
                rows.append(vals)
    except (OSError, StopIteration, csv.Error):
        return None, None
    rows = [r for r in rows if r]
    if not rows or len(rows[0]) < 2:
        return None, None
    ncol = len(rows[0])
    best = None
    for j in range(ncol):
        col = [r[j] for r in rows if j < len(r) and r[j] == r[j]]
        if len(col) < 2:
            continue
        sd = N.fstd(col, ddof=1)
        if sd > 0.0:
            sr = N.fmean(col) / sd
            best = sr if best is None else max(best, sr)
    return ncol, best


def _n_and_t(contract, base, s):
    """(n_trials, t_stat, sr) honestly derived from the study block. Any of these may be None when not
    declared - the caller turns a missing N into the 'unverifiable' finding (never guesses)."""
    n = s.get("trials")
    n = int(n) if isinstance(n, (int, float)) and n >= 1 else None
    sr = s.get("sharpe")
    periods = s.get("periods")
    t = s.get("t_stat")
    if (n is None or t is None) and s.get("trials_matrix"):
        mn, mbest = _trials_from_matrix(contract, base, s)
        if n is None:
            n = mn
        if t is None and sr is None and mbest is not None and periods:
            sr = mbest
    if t is None and isinstance(sr, (int, float)) and isinstance(periods, (int, float)) and periods > 0:
        t = float(sr) * math.sqrt(float(periods))
    if isinstance(t, (int, float)):
        t = float(t)
    else:
        t = None
    if n is not None and n > _MAX_TRIALS:
        n = _MAX_TRIALS
    return n, t, (float(sr) if isinstance(sr, (int, float)) else None)


def _finding(claim_id, kind, severity, vclass, locator, unblock):
    return {
        "id": "f-%s-snoop-%s" % (claim_id, kind), "claim_id": claim_id, "dimension": "data-snooping",
        "severity": severity, "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": locator, "unblock": unblock,
        "reverify": {"kind": "artifact-recheck", "source": "study",
                     "expected": "the multiple-testing-adjusted t exceeds 3.0 (survives the haircut)"},
        "validity_class": vclass, "snoop_kind": kind,
    }


def run_checks(contract, base, claim_id="c1", claim_text=None):
    """Study-wide multiple-testing findings. SILENT unless a `study` block is declared. With N + a test
    statistic it runs the HLZ haircut and fires iff the adjusted t falls below 3.0; with N uncountable it
    fires an 'unverifiable' finding (N never guessed). apply_validity sets the final verdict."""
    s = study(contract)
    if not s:
        return []
    try:
        return _assess(contract, base, claim_id, s)
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
        return []


def _assess(contract, base, claim_id, s):
    n, t, sr = _n_and_t(contract, base, s)
    if n is None or n < 2:
        if n is not None and n < 2:
            return []  # a genuinely single test (N<2): no multiplicity to correct -> clean
        return [_finding(
            claim_id, "unverifiable", "minor", "unverifiable",
            "a multi-strategy study is declared but the trial count N is not countable (no `trials` and "
            "no readable `trials_matrix`) - the multiple-testing haircut cannot be computed",
            "declare study.trials:N (the number of strategies/tests tried), or emit the per-strategy "
            "returns matrix as study.trials_matrix, then re-verify")]
    if t is None:
        return [_finding(
            claim_id, "unverifiable", "minor", "unverifiable",
            "study.trials=%d is declared but no test statistic is given (need study.t_stat, or "
            "study.sharpe + study.periods) - the haircut cannot be computed" % n,
            "declare the reported t-stat (study.t_stat) or the Sharpe + period count "
            "(study.sharpe, study.periods), then re-verify")]
    hc = haircut(t, n)
    holm_t = hc["methods"]["holm"]["t_adj"]
    if holm_t >= T_CRIT:
        return []  # survives the study-wide correction -> clean (data-snooping checked, nothing fired)
    b, h, y = hc["methods"]["bonferroni"], hc["methods"]["holm"], hc["methods"]["bhy"]
    locator = ("the edge does not survive study-wide multiple-testing over N=%d tests: observed t=%.2f "
               "(p=%.2g) haircuts to t=%.2f (Bonferroni/Holm, %.0f%% Sharpe haircut) / t=%.2f (BHY FDR) "
               "- below the t>3.0 bar a new factor needs (Harvey-Liu-Zhu)"
               % (n, t, hc["p"], h["t_adj"], 100.0 * h["haircut"], y["t_adj"]))
    return [_finding(
        claim_id, "multiple-testing", "blocker", "authoritative", locator,
        "report the multiple-testing-adjusted t / haircut Sharpe alongside the headline, or show the "
        "edge clears t>3.0 after correcting for the %d-test study" % n)]


def _applicable(contract):
    return bool(study(contract))


def family_status(contract, findings):
    """Honest scope.families.data-snooping status."""
    if not _applicable(contract):
        return "not-applicable"
    return "flagged" if any(f.get("dimension") == "data-snooping" and f.get("snoop_kind") for f in findings) \
        else "checked"


def _claim_asserts_significance(claim_text):
    return bool(isinstance(claim_text, str) and _ASSERTS_RE.search(claim_text))


def apply_validity(claims, findings, contract, claim_text, base=None):
    """Promote the headline per the data-snooping findings + claim scope. Conservative: only a REPRODUCED
    number (CONFIRMED/CAVEATS) is promoted, and only DOWN. An authoritative haircut (t<3.0) under a claim
    asserting the result is significant/genuine/robust -> INVALIDATED("data-snooping"); a bare reproduced
    number -> CAVEAT. An 'unverifiable' (N undisclosed) under an asserting claim -> CAN'T-CONFIRM; bare ->
    CAVEAT. REFUTED is never manufactured here."""
    snoop = [f for f in findings if f.get("dimension") == "data-snooping" and f.get("snoop_kind")]
    if not snoop or not claims:
        return
    head = next((c for c in claims if c.get("headline")), claims[0])
    if head.get("verdict") not in (V.CONFIRMED, V.CAVEATS):
        return
    vi = head.get("verdict_inputs") or {}
    asserts = _claim_asserts_significance(claim_text)
    auth = [f for f in snoop if f.get("validity_class") == "authoritative"]
    unver = [f for f in snoop if f.get("validity_class") == "unverifiable"]
    if auth:
        if asserts:
            for f in auth:
                f["claim_id"] = head["id"]
            vi["validity_invalidated"] = True
            vi["oos_claim_asserted"] = True
            head["driving_dimension"] = "data-snooping"
        else:
            for f in auth:
                f["severity"] = "minor"
            vi["soft_validity_caveat"] = True
    elif unver:
        if asserts:
            vi["validity_unresolved"] = True   # claimed-significant but N uncountable -> CAN'T-CONFIRM
            head["driving_dimension"] = "data-snooping"
        else:
            vi["soft_validity_caveat"] = True
    else:
        return
    head["verdict_inputs"] = vi
    head["verdict"] = V.verdict(vi)
    head["headline_confidence"] = V.confidence(vi, head["verdict"])
