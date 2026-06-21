"""calma.overfitting_checks - multiple-testing / backtest-overfitting catches on the findings rail
(dimension "overfitting", an EXEC dimension), called from calma._assemble_ledger like leakage_checks.

The honest scope is narrow by design (the engagement lattice):
  - NO search signal                          -> NOT-APPLICABLE, SILENT (the ordinary single backtest).
  - search signal + a COUNTABLE N             -> run DSR (Bailey-LdP) + PBO/CSCV (Bailey-et-al):
        survives                              -> clean (no finding);
        fails (PBO>0.5 or 1-DSR>0.05) + claim asserts survival/OOS  -> INVALIDATED;
        fails + a bare reproduced number      -> CONFIRMED-WITH-CAVEATS (the number is literally true).
  - search signal + N NOT countable + claim asserts survival/OOS    -> CAN'T-CONFIRM ("declare trials:N").
  - search signal + N NOT countable + a bare reproduced number      -> CONFIRMED-WITH-CAVEATS.

A "search signal" is: a `trials:N` declared, a trials/grid-search artifact (or one auto-detected by
name), OR selection language in the claim ("best of N", "optimized", "robust edge", ...). N is NEVER
guessed: it is the declared `trials` or the column count of a trials artifact; absent -> uncountable.

Like leakage, REFUTED is never manufactured here - the raw DSR/PBO numbers drive INVALIDATED / CAN'T-
CONFIRM / CAVEAT through the shared verdict-input promotion. (REFUTED on overfitting is the recipe-rail
path: a user claims a deflated number and it is recomputed - deferred.)

Library: run_checks(contract, base, claim_id, claim_text) -> [finding,...];
apply_validity(claims, findings, contract, claim_text).
"""
import csv
import os
import re

import numeric as N
import pathsafe as PS
import verdict as V

_SHARPE_METRICS = {"sharpe"}              # DSR/PBO apply to a per-period Sharpe claim
_PBO_FAIL = 0.5                            # PBO > 0.5  => the IS-winner is typically an OOS also-ran
_DSR_FAIL_P = 0.05                         # 1 - DSR > 0.05 => the edge doesn't clear the deflated benchmark
_PBO_SPLITS = 8                            # CSCV partitions (even); needs T >= 8 rows

_SELECTION_RE = re.compile(
    r"best (of|sharpe|return|strateg)|top (strateg|config|model|\d)|optimi[sz]ed|robust edge|"
    r"survived|selected from|out.?of.?sample|held.?out|grid.?search", re.I)
_TRIALS_NAME = re.compile(r"^(trials|grid_?search|sweep|configs?|candidates?)\.csv$", re.I)


def _read_matrix(path):
    """A CSV of per-period performance: rows = periods, columns = candidate strategies. Returns
    (header, rows-of-floats); non-numeric cells -> NaN."""
    if not os.path.isfile(path):
        return [], []  # FIFO/socket/device: never open() (would block); treated as unreadable
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
        return header, rows
    except (OSError, StopIteration):
        return [], []


def _detect_trials_artifact(base):
    try:
        for n in sorted(os.listdir(base)):
            if _TRIALS_NAME.match(n):
                return n
    except OSError:
        pass
    return None


def _headline(contract):
    mets = contract.get("metrics") or []
    for m in mets:
        if m.get("headline") and m.get("claimed_value") is not None:
            return m
    for m in mets:
        if m.get("claimed_value") is not None:
            return m
    return mets[0] if mets else None


def _per_period_sharpe(rets):
    """PER-PERIOD Sharpe = mean/std (ddof=1) of the RAW returns - never an annualised SR. DSR's n is the
    number of periods, so the SR fed to it must be per-period (the wiring assertion the rail must honor)."""
    if len(rets) < 2:
        return None
    sd = N.fstd(rets, ddof=1)
    if not (sd > 0.0):
        return None
    return N.fmean(rets) / sd


def _returns(contract, base):
    m = _headline(contract)
    if not m:
        return None
    rcol = (m.get("binding") or {}).get("return")
    if not rcol:
        return None
    try:  # L1: contain the artifact path
        header, rows = _read_matrix(PS.safe_join(base, m.get("artifact", "")))
    except ValueError:
        return None
    if rcol not in header:
        return None
    j = header.index(rcol)
    return [r[j] for r in rows if j < len(r) and r[j] == r[j]]


def _trials_stats(contract, base, artifact):
    """From a trials matrix: N (column count), var_sr (sample variance of the per-strategy per-period
    Sharpes), and the matrix (for PBO). Returns None if not countable (<2 strategies / unreadable)."""
    try:  # L1: contain the artifact path
        header, M = _read_matrix(PS.safe_join(base, artifact))
    except ValueError:
        return None
    M = [r for r in M if r]
    if not M or len(M[0]) < 2:
        return None
    ncol = len(M[0])
    sharpes = []
    for j in range(ncol):
        col = [r[j] for r in M if j < len(r) and r[j] == r[j]]
        s = _per_period_sharpe(col)
        if s is not None:
            sharpes.append(s)
    if len(sharpes) < 2:
        return None
    return {"N": ncol, "var_sr": N.fvar(sharpes, ddof=1), "matrix": M}


def search_signal(contract, base, claim_text):
    """Describe the multiple-testing signal, or None (NOT-APPLICABLE). Only fires for a Sharpe headline."""
    m = _headline(contract)
    if not m or m.get("metric_id") not in _SHARPE_METRICS:
        return None
    n_decl = contract.get("trials")
    artifact = contract.get("trials_artifact") or _detect_trials_artifact(base)
    selection = bool(_SELECTION_RE.search(claim_text or ""))
    if n_decl is None and not artifact and not selection:
        return None
    return {"n_declared": n_decl, "artifact": artifact, "selection": selection}


def _finding(claim_id, kind, severity, vclass, locator, unblock):
    return {
        "id": "f-%s-overfit-%s" % (claim_id, kind), "claim_id": claim_id, "dimension": "overfitting",
        "severity": severity, "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": locator, "unblock": unblock,
        "reverify": {"kind": "requires-reexecution", "source": "trials",
                     "expected": "the edge survives multiple-testing correction (PBO<=0.5 and DSR significant)"},
        "validity_class": vclass, "overfit_kind": kind,
    }


def run_checks(contract, base, claim_id="c1", claim_text=None):
    """Overfitting findings. SILENT (returns []) unless a search signal is present. With a countable N
    it runs DSR/PBO and fires an authoritative finding iff the edge fails; with an uncountable N it
    fires an 'uncountable' finding carrying the declare-N fix. apply_validity sets the final verdict."""
    sig = None
    try:
        sig = search_signal(contract, base, claim_text)
    except (OSError, ValueError, KeyError, TypeError):
        sig = None
    if not sig:
        return []
    try:
        return _assess(contract, base, claim_id, sig)
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
        return []


def _assess(contract, base, claim_id, sig):
    stats = _trials_stats(contract, base, sig["artifact"]) if sig.get("artifact") else None
    n_decl = sig.get("n_declared")
    var_decl = contract.get("var_sr")
    # ---- countable? N + (a PBO matrix and/or var_sr for DSR) ----
    if stats is not None:
        n_trials, var_sr, matrix = stats["N"], stats["var_sr"], stats["matrix"]
    elif isinstance(n_decl, int) and n_decl >= 2 and isinstance(var_decl, (int, float)):
        n_trials, var_sr, matrix = n_decl, float(var_decl), None
    else:
        # a sweep is signalled but N is not countable as given - never guess it
        return [_finding(
            claim_id, "uncountable", "minor", "uncountable",
            "a parameter search is implied (%s) but the trial count N is not countable as given - "
            "overfitting cannot be assessed" % ("selection language" if sig.get("selection")
                                                else "trials artifact present but unreadable/underspecified"),
            "declare trials:N in verify.yaml, or emit the grid-search log (a per-period returns matrix, "
            "one column per candidate), then re-verify")]

    pbo = N.pbo_cscv(matrix, _PBO_SPLITS) if matrix is not None else float("nan")
    rets = _returns(contract, base)
    dsr = float("nan")
    if rets is not None:
        sr = _per_period_sharpe(rets)
        if sr is not None:
            # WIRING ASSERTION: sr is PER-PERIOD (mean/std of raw returns) and n_obs is the period count.
            dsr = N.deflated_sharpe_ratio(sr, len(rets), N.skewness(rets), N.kurtosis_excess(rets),
                                          n_trials, var_sr)
    pbo_fails = (pbo == pbo) and pbo > _PBO_FAIL
    dsr_fails = (dsr == dsr) and (1.0 - dsr) > _DSR_FAIL_P
    if not pbo_fails and not dsr_fails:
        return []  # the edge survives multiple-testing -> clean (overfitting checked, nothing fired)
    bits = []
    if pbo == pbo:
        bits.append("PBO=%.3f" % pbo)
    if dsr == dsr:
        bits.append("DSR=%.3f (1-DSR=%.3f)" % (dsr, 1.0 - dsr))
    return [_finding(
        claim_id, "multiple-testing", "blocker", "authoritative",
        "the edge does not survive multiple-testing correction over N=%d trials: %s"
        % (n_trials, ", ".join(bits)),
        "report the deflated Sharpe / PBO alongside the headline, or show the edge holds out-of-sample "
        "after correcting for the %d-strategy search" % n_trials)]


def _claim_asserts_survival(contract, claim_text):
    """Does the CLAIM assert a selected/robust/OOS edge (the thing overfitting would invalidate)? Keyed
    on the claim TEXT only - a trials artifact / declared N is the search SIGNAL (it makes the sweep
    DETECTED), not a survival assertion. A bare reproduced number next to a detected sweep is a caveat,
    not an invalidation; only a claim that asserts the survived/selected edge is invalidated."""
    return bool(_SELECTION_RE.search(claim_text or ""))


def family_status(contract, base, findings, claim_text):
    """Honest scope.families.overfitting status."""
    try:
        applicable = bool(search_signal(contract, base, claim_text))
    except (OSError, ValueError, KeyError, TypeError):
        applicable = False
    if not applicable:
        return "not-applicable"
    return "flagged" if any(f.get("dimension") == "overfitting" for f in findings) else "checked"


def apply_validity(claims, findings, contract, claim_text):
    """Promote the headline claim per the overfitting findings + claim scope. Only a REPRODUCED number
    (CONFIRMED/CAVEATS) is promoted, and only DOWN (INVALIDATED / CAN'T-CONFIRM / CAVEAT). Mirrors the
    leakage scope-guard: INVALIDATED requires the claim to assert the survived/selected edge."""
    over = [f for f in findings if f.get("dimension") == "overfitting"]
    if not over or not claims:
        return
    head = next((c for c in claims if c.get("headline")), claims[0])
    if head.get("verdict") not in (V.CONFIRMED, V.CAVEATS):
        return
    auth = [f for f in over if f.get("validity_class") == "authoritative"]
    uncountable = [f for f in over if f.get("validity_class") == "uncountable"]
    vi = head.get("verdict_inputs") or {}
    asserts = _claim_asserts_survival(contract, claim_text)
    if auth:
        if asserts:
            vi["validity_invalidated"] = True
            vi["oos_claim_asserted"] = True
            head["driving_dimension"] = "overfitting"
            for f in auth:
                f["claim_id"] = head["id"]
        else:
            for f in auth:  # a bare reproduced number: the edge is a noted caveat, not invalidating
                f["severity"] = "minor"
            vi["soft_validity_caveat"] = True
    elif uncountable:
        if asserts:
            vi["validity_unresolved"] = True   # a claimed-robust edge we cannot count -> CAN'T-CONFIRM
        else:
            vi["soft_validity_caveat"] = True   # a bare number with a detected-but-uncounted sweep -> CAVEAT
    else:
        return
    head["verdict_inputs"] = vi
    head["verdict"] = V.verdict(vi)
    head["headline_confidence"] = V.confidence(vi, head["verdict"])
