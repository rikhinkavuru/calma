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
  - regime drift (B1): the return series' first half vs second half are a materially different
    distribution (two-sample KS rejection + a variance-regime shift or a mean-sign flip) - a single-
    window backtest may not be robust. Defers to the authoritative regime family when that one fires.
  - undeclared-split leakage (B1): NO split is declared, yet the artifacts carry an evident train/test
    structure (train/test files or a split column) AND test rows duplicate training rows. Names the exact
    `split:` block to declare for the authoritative INVALIDATED.
  - train/test loss gap (B1): a training-history artifact whose converged val/test loss far exceeds the
    train loss - the classic overfitting signature - flagged without a declared trials/split block.

HONESTY INVARIANT - these are HEURISTICS, never proof. A high Sharpe or a smooth curve is suspicious,
not wrong. So this family is SOFT-ONLY: it can DEGRADE a would-be CONFIRMED to CONFIRMED-WITH-CAVEATS
(soft_validity_caveat) and surface a precise "here's what to check" finding - it can NEVER reach
INVALIDATED or REFUTED. That stays the job of the authoritative families (which need the declared
structure) and the gap-gated recompute path. A smell buys margin and tells you where to look; it does
not catch a liar. The caveat is informational: the number still reproduced.

Scope: the Sharpe / smooth / regime smells need a bound `return` column (a trading series); the
undeclared-split + loss-gap smells fire on a NON-return (ML / tabular) result instead. ABSTAINS without
enough history / structure. No contract block required - the whole point is that nothing is volunteered.

Library: run_checks(contract, base, claim_id, claim_text) -> [finding,...];
apply_validity(claims, findings, contract, claim_text, base=None); family_status(contract, findings).
"""
import csv
import os
import re

import leakage_checks as LC   # reuse the EXACT row-hashing for the undeclared-split overlap smell
import numeric as N
import verdict as V

_MIN_OBS = 24          # enough points for a meaningful per-period Sharpe + a lag-1 autocorrelation
_HI_SHARPE = 1.0       # per-period Sharpe above this is implausible at any sub-annual frequency
                       # (x sqrt(252) daily ~= 15.9, x sqrt(52) weekly ~= 7.2, x sqrt(12) monthly ~= 3.5)
_HI_AUTOCORR = 0.35    # lag-1 serial correlation above this is the return-smoothing / stale-mark smell;
                       # liquid period-over-period returns sit near zero
# annualization factors (literal so the locator stays dependency-free and bit-identical cross-platform)
_ANN_DAILY, _ANN_WEEKLY, _ANN_MONTHLY = 15.87, 7.21, 3.46

# --- B1 thin-input broadening: regime-drift + undeclared-split-leak + train/test-loss-gap smells ----
_MIN_OBS_REGIME = 20   # >= 10 points per half for a meaningful two-sample KS + a variance ratio
_REGIME_KS_ALPHA = 0.01  # KS p below this = the two halves are a real distribution shift (strict: avoid
                         # crying wolf on the vol-clustering every return series has)
_REGIME_VAR_RATIO = 2.5  # |second-half var / first-half var| beyond this (or its reciprocal) is the
                         # variance-regime corroboration the KS rejection needs to fire
_SMELL_ROW_CAP = 100000  # cap rows hashed for the overlap smell - it is a heuristic, kept cheap
_LOSS_GAP_FRAC = 0.25    # a val/test loss exceeding train loss by > this (relative) is an overfit smell
_SPLIT_COL_RE = re.compile(r"^(split|fold|partition|subset|is_?train|is_?test)$", re.I)
_TRAIN_LOSS_RE = re.compile(r"^(train|training)[_-]?(loss|error)$", re.I)
_TEST_LOSS_RE = re.compile(r"^(val|valid|validation|test|holdout|eval)[_-]?(loss|error)$", re.I)


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


def check_regime_drift(contract, base, claim_id="c1", findings=None):
    """SOFT non-stationarity smell: the bound return series' first half vs second half come from
    materially different distributions (a two-sample KS rejection corroborated by a variance-regime
    shift or a mean-sign flip). Fires from the series ALONE - no windows block or robustness claim
    needed - so it narrows the cooperation wall the authoritative regime family (which needs one)
    leaves open. Suppressed when that authoritative family already flagged, to avoid double-counting."""
    if findings and any(f.get("dimension") == "regime" for f in findings):
        return None  # the authoritative walk-forward family already flagged it; don't pile on
    rets = _returns(contract, base)
    if not rets or len(rets) < _MIN_OBS_REGIME:
        return None
    half = len(rets) // 2
    a, b = rets[:half], rets[half:]
    va, vb = N.fvar(a), N.fvar(b)
    p, d = N.ks_p(a, b), N.ks_2samp(a, b)
    if not (p == p) or p >= _REGIME_KS_ALPHA:
        return None  # halves are not distinguishable -> within noise, no false alarm
    ratio = (vb / va) if va > 0 else float("inf")
    mean_flip = (N.fmean(a) > 0) != (N.fmean(b) > 0)
    if not (ratio > _REGIME_VAR_RATIO or ratio < 1.0 / _REGIME_VAR_RATIO or mean_flip):
        return None  # a KS rejection without a variance/mean regime shift is too weak to surface
    return {
        "id": "f-%s-plausibility-regime" % claim_id, "claim_id": claim_id, "dimension": "plausibility",
        "severity": "minor", "status": "open", "confidence": "heuristic", "fixable_by": "author",
        "locator": ("statistical smell: the return series is not stationary across its own span - first "
                    "half (mean %.4f, vol %.4f) vs second half (mean %.4f, vol %.4f) differ (two-sample "
                    "KS D=%.3f, p=%.4f). A single-window backtest may be regime-dependent; the out-of-"
                    "sample half need not behave like the in-sample half"
                    % (N.fmean(a), va ** 0.5, N.fmean(b), vb ** 0.5, d, p)),
        "unblock": ("validate walk-forward (rolling in-sample/out-of-sample windows) and report the OOS "
                    "distribution, or scope the claim to the regime the edge actually holds in; declare a "
                    "windows block for the authoritative walk-forward verdict"),
        "reverify": {"kind": "requires-reexecution", "source": "windows",
                     "expected": "the metric is consistent across walk-forward windows"},
        "validity_class": "heuristic", "plausibility_kind": "regime-drift",
    }


def _infer_split(contract):
    """Detect an UNDECLARED train/test structure from the contract's artifacts: train.csv + test.csv, a
    *_train.csv / *_test.csv pair (which also catches y_train.csv / y_test.csv), or a single file with a
    split/fold column. Returns (split_dict, evidence_str) or (None, None). Mirrors draft_contract's
    detection, kept local so the validity layer never imports the drafting layer."""
    arts = contract.get("artifacts") or []
    paths = [a.get("path") for a in arts if a.get("path")]
    bn = {os.path.basename(p).lower(): p for p in paths}
    if "train.csv" in bn and "test.csv" in bn:
        return {"train": bn["train.csv"], "test": bn["test.csv"]}, "train.csv + test.csv"
    for p in paths:
        b = os.path.basename(p).lower()
        if b.endswith("_train.csv"):
            stem = b[:-len("_train.csv")]
            mate = next((q for q in paths if os.path.basename(q).lower() == stem + "_test.csv"), None)
            if mate:
                return {"train": p, "test": mate}, "%s_train.csv + %s_test.csv" % (stem, stem)
    for a in arts:
        col = next((c for c in (a.get("columns") or {}) if _SPLIT_COL_RE.search(c)), None)
        if col:
            return {"file": a.get("path"), "column": col}, "split column %r in %s" % (col, a.get("path"))
    return None, None


def check_undeclared_split_leak(contract, base, claim_id="c1"):
    """SOFT leakage smell: when NO split is declared but the artifacts carry an evident train/test
    structure AND test rows duplicate training rows, flag it as a CAVEAT - never INVALIDATED, because the
    split was INFERRED, not declared (Calma never guesses a verdict-flipping scope; a false catch is the
    worst failure). The fix names the exact `split:` block to declare for the authoritative verdict."""
    if contract.get("split") or _binds_return(contract):
        return None  # a declared split -> the authoritative leakage family; a return series -> not the leakage smell
    inferred, evidence = _infer_split(contract)
    if not inferred:
        return None
    try:
        d = LC._load_split({"split": inferred}, base)
    except (OSError, ValueError, KeyError, IndexError, csv.Error):
        d = None
    if not d or not d.get("test") or not d.get("train"):
        return None
    excl = (d["split_col"],) if d.get("split_col") else ()
    train = set(LC._canon_hash(d["train_h"], d["train"][:_SMELL_ROW_CAP], excl))
    test_h = LC._canon_hash(d["test_h"], d["test"][:_SMELL_ROW_CAP], excl)
    if not test_h:
        return None
    overlap = sum(1 for h in test_h if h in train)
    if overlap == 0:
        return None
    mag = overlap / len(test_h)
    return {
        "id": "f-%s-plausibility-split-leak" % claim_id, "claim_id": claim_id, "dimension": "plausibility",
        "severity": "minor", "status": "open", "confidence": "heuristic", "fixable_by": "author",
        "locator": ("statistical smell: an undeclared train/test split is detectable (%s), and %d of %d "
                    "sampled test rows (%.1f%%) are exact duplicates of training rows - a leakage "
                    "signature. Reported as a CAVEAT, not INVALIDATED, because the split was inferred from "
                    "the file layout, not declared" % (evidence, overlap, len(test_h), 100 * mag)),
        "unblock": ("declare the split so the authoritative leakage check can run (and, if confirmed, "
                    "reach INVALIDATED): split: {%s}; then rebuild it so no test row also appears in training"
                    % ", ".join("%s: %s" % (k, v) for k, v in inferred.items())),
        "reverify": {"kind": "requires-reexecution", "source": "split",
                     "expected": "no train/test row overlap once the split is declared and rebuilt"},
        "validity_class": "heuristic", "plausibility_kind": "undeclared-split-leak", "magnitude": mag,
    }


def _final_float(header, rows, col):
    """The last parseable float in `col` (the converged train / val loss). None if absent/unparseable."""
    if col not in header:
        return None
    j, val = header.index(col), None
    for r in rows:
        if j < len(r):
            try:
                val = float(r[j])
            except (TypeError, ValueError):
                pass
    return val


def check_train_test_loss_gap(contract, base, claim_id="c1"):
    """SOFT overfit smell: a training-history artifact carrying BOTH a train-loss and a val/test-loss
    column whose converged gap is large -> the classic overfitting signature, flagged from the artifact
    alone (no declared trials/split block). CAVEAT, never INVALIDATED."""
    if _binds_return(contract):
        return None
    for a in (contract.get("artifacts") or []):
        cols = list(a.get("columns") or {})
        tr_col = next((c for c in cols if _TRAIN_LOSS_RE.match(c)), None)
        te_col = next((c for c in cols if _TEST_LOSS_RE.match(c)), None)
        if not tr_col or not te_col:
            continue
        try:
            path = _safe_join(base, a.get("path", ""))
        except ValueError:
            continue
        if not os.path.isfile(path):
            continue
        try:
            with open(path, newline="") as fh:
                rd = csv.reader(fh)
                header = next(rd, [])
                rows = [r for _, r in zip(range(_SMELL_ROW_CAP), rd)]
        except (OSError, csv.Error, StopIteration):
            continue
        tr, te = _final_float(header, rows, tr_col), _final_float(header, rows, te_col)
        if tr is None or te is None or not (tr == tr) or not (te == te) or tr <= 0:
            continue
        gap = (te - tr) / tr
        if gap <= _LOSS_GAP_FRAC:
            continue
        return {
            "id": "f-%s-plausibility-loss-gap" % claim_id, "claim_id": claim_id, "dimension": "plausibility",
            "severity": "minor", "status": "open", "confidence": "heuristic", "fixable_by": "author",
            "locator": ("statistical smell: the training history shows a large train/validation loss gap "
                        "(%s %.4f vs %s %.4f, +%.0f%%) - the classic overfitting signature: the model fits "
                        "the training set far better than held-out data" % (tr_col, tr, te_col, te, 100 * gap)),
            "unblock": ("declare the trials/split block so the deflated Sharpe / PBO (overfitting) or the "
                        "held-out leakage check runs authoritatively, and report the held-out metric"),
            "reverify": {"kind": "requires-reexecution", "source": "trials",
                         "expected": "the held-out metric holds once overfitting is controlled"},
            "validity_class": "heuristic", "plausibility_kind": "train-test-loss-gap", "magnitude": gap,
        }
    return None


# return-series smells gate on a `return` binding; the artifact-structure smells fire only when there is
# NO return binding (an ML / tabular result), and self-gate to None when their structure isn't present.
_RETURN_CHECKS = (check_high_sharpe, check_smooth_curve)
_ARTIFACT_CHECKS = (check_undeclared_split_leak, check_train_test_loss_gap)


def run_checks(contract, base, claim_id="c1", claim_text=None, findings=None):
    """Thin-input smells - NO contract block required, every one SOFT (degrades to CAVEATS, never
    INVALIDATED). Return series: implausible Sharpe / too-smooth curve / regime drift. ML or tabular
    artifacts: undeclared-split leakage / a train-test loss gap. Fail-soft: a check that errors is
    skipped. `findings` (the accumulated ledger findings) lets the regime smell defer to the
    authoritative regime family when it already fired."""
    out = []
    if _binds_return(contract):
        cks = list(_RETURN_CHECKS) + [lambda c, b, cid: check_regime_drift(c, b, cid, findings)]
    else:
        cks = list(_ARTIFACT_CHECKS)
    for fn in cks:
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
    # "checked" wherever the thin-input layer COULD fire: a return series, or an inferable train/test
    # split structure it inspects; otherwise there was nothing thin-input to smell.
    if _binds_return(contract) or _infer_split(contract)[0]:
        return "checked"
    return "not-applicable"


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
