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
_AUC_METRICS = {"auc", "roc_auc"}         # deflated-AUC selection-overfit applies to an ROC-AUC claim
_PBO_FAIL = 0.5                            # PBO > 0.5  => the IS-winner is typically an OOS also-ran
_DSR_FAIL_P = 0.05                         # 1 - DSR > 0.05 => the edge doesn't clear the deflated benchmark
_PBO_SPLITS = 8                            # CSCV partitions (even); needs T >= 8 rows

_SELECTION_RE = re.compile(
    r"best (of|sharpe|return|strateg)|top (strateg|config|model|\d)|optimi[sz]ed|robust edge|"
    r"survived|selected from|out.?of.?sample|held.?out|grid.?search", re.I)
# the AUC selection SIGNAL is stricter than the broad survival assertion: bare OOS / held-out words assert
# SCOPE, not a multiple-testing search, so they must NOT alone trigger the deflated-AUC haircut (else a
# clean "auc 0.94 held-out" would be wrongly haircut). A genuine model/threshold search is required.
_AUC_SELECTION_RE = re.compile(
    r"best (auc|of|model|config|threshold)|top (\d|model|config)|optimi[sz]ed|tuned|grid.?search|"
    r"selected from|sweep|hyper.?param|robust edge|leaderboard", re.I)
_TRIALS_NAME = re.compile(r"^(trials|grid_?search|sweep|configs?|candidates?)\.csv$", re.I)


def _read_matrix(path):
    """A CSV of per-period performance: rows = periods, columns = candidate strategies. Returns
    (header, rows-of-floats); non-numeric cells -> NaN."""
    if not PS.within_cap(path):
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
    """Describe the multiple-testing signal, or None (NOT-APPLICABLE). Fires for a Sharpe headline (DSR/PBO)
    or an ROC-AUC headline (the deflated-AUC selection-overfit haircut)."""
    m = _headline(contract)
    if not m or m.get("metric_id") not in (_SHARPE_METRICS | _AUC_METRICS):
        return None
    n_decl = contract.get("trials")
    artifact = contract.get("trials_artifact") or _detect_trials_artifact(base)
    # AUC uses the strict selection regex (a real search), Sharpe the broad one; for AUC, a merely
    # auto-detected returns matrix is not a signal (the AUC rail only consumes an EXPLICIT AUC-values
    # artifact), so the signal there must come from trials:N, an explicit trials_artifact, or selection.
    is_auc = m.get("metric_id") in _AUC_METRICS
    selection = bool((_AUC_SELECTION_RE if is_auc else _SELECTION_RE).search(claim_text or ""))
    if is_auc:
        explicit_artifact = bool(contract.get("trials_artifact"))
        if n_decl is None and not explicit_artifact and not selection:
            return None
    elif n_decl is None and not artifact and not selection:
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


def _auc_score_label(contract, base):
    """(scores, labels) from the headline AUC artifact via its {score,label} binding, or None. Labels
    coerced to 0/1; needs >=4 rows and both classes present for a meaningful DeLong SE."""
    m = _headline(contract)
    if not m:
        return None
    bind = m.get("binding") or {}
    scol, lcol = bind.get("score"), bind.get("label")
    if not scol or not lcol:
        return None
    try:
        header, rows = _read_matrix(PS.safe_join(base, m.get("artifact", "")))
    except ValueError:
        return None
    if scol not in header or lcol not in header:
        return None
    si, li = header.index(scol), header.index(lcol)
    scores, labels = [], []
    for r in rows:
        if si < len(r) and li < len(r) and r[si] == r[si] and r[li] == r[li]:
            scores.append(r[si])
            labels.append(1 if r[li] >= 0.5 else 0)
    npos = sum(labels)
    if len(scores) < 4 or npos == 0 or npos == len(labels):
        return None
    return scores, labels


def _auc_trials_vec(base, artifact):
    """A trials artifact read as a flat vector of per-trial AUC values (the first column's finite cells in
    [0,1]). Used only for AUC headlines and only when EXPLICITLY declared as trials_artifact (so an
    auto-detected returns matrix from the Sharpe path is never misread as AUC values)."""
    try:
        header, rows = _read_matrix(PS.safe_join(base, artifact))
    except ValueError:
        return None
    vec = [r[0] for r in rows if r and r[0] == r[0] and 0.0 <= r[0] <= 1.0]
    return vec if len(vec) >= 2 else None


def _assess_auc(contract, base, claim_id, sig):
    """Deflated-AUC selection-overfit (the Sharpe DSR transplanted onto ROC-AUC). N from declared trials /
    an explicitly-declared AUC-values artifact / selection language (NEVER guessed); SE from the cross-trial
    SD of the leaderboard AUCs (the truer DSR analog, when observable) or the per-trial DeLong SE of the
    headline score+label. AUC=1.0 (DeLong SE->0) is guarded as degenerate, never a false pass."""
    sl = _auc_score_label(contract, base)
    auc_val = N.auc(*sl) if sl else None
    se_delong = N.auc_delong_se(*sl) if sl else float("nan")
    n_decl = sig.get("n_declared")
    vec = _auc_trials_vec(base, contract["trials_artifact"]) if contract.get("trials_artifact") else None
    if vec is not None:
        n_trials, se = len(vec), N.fstd(vec, ddof=1)
        if auc_val is None or auc_val != auc_val:
            auc_val = max(vec)  # the selected (best) AUC, when the headline score+label aren't bound
    elif isinstance(n_decl, int) and n_decl >= 2 and sl is not None:
        n_trials, se = n_decl, se_delong
    else:
        return [_finding(
            claim_id, "uncountable-auc", "minor", "uncountable",
            "a model/threshold search is implied (%s) but the trial count N is not countable as given - the "
            "AUC selection-overfit haircut cannot be assessed"
            % ("selection language" if sig.get("selection") else "no trials:N and no AUC-values artifact"),
            "declare trials:N in verify.yaml, or emit the per-trial AUC values (one column), then re-verify")]
    if auc_val is None or auc_val != auc_val or not (se > 0.0):
        return []  # AUC=1.0 perfect separation (DeLong SE->0) or unreadable -> degenerate, cannot deflate
    dauc = N.deflated_auc(auc_val, se, n_trials)
    if dauc != dauc or (1.0 - dauc) <= _DSR_FAIL_P:
        return []  # clears the N-trial selection bar (or undefined) -> clean
    bar = N.expected_max_auc(n_trials, se)
    note = " (N<10: the deflation is unreliable at this trial count)" if n_trials < 10 else ""
    return [_finding(
        claim_id, "auc-selection", "blocker", "authoritative",
        "the AUC %.4f does not clear the %d-trial selection bar: DAUC=%.3f (1-DAUC=%.3f > %.2f); the expected "
        "best-of-%d no-skill AUC is %.4f (SE=%.4f)%s - the reported AUC is within reach of selecting the best "
        "of %d trials by chance." % (auc_val, n_trials, dauc, 1.0 - dauc, _DSR_FAIL_P, n_trials, bar, se, note,
                                     n_trials),
        "report the deflated AUC / a permutation p-value alongside the headline, or show the AUC holds on a "
        "fresh held-out set after correcting for the %d-model search" % n_trials)]


def _assess(contract, base, claim_id, sig):
    m = _headline(contract)
    if m and m.get("metric_id") in _AUC_METRICS:
        return _assess_auc(contract, base, claim_id, sig)
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
