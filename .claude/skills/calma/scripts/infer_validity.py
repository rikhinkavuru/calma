"""calma.infer_validity - M-8b.2: PROMOTE an inferred-from-artifacts validity signal to FLAG_FOR_DECLARATION
when the evidence is strong + multi-signal AND the producer declared nothing. The loud, IC-visible cousin of
plausibility_checks: same detection, but a DEMAND to declare the block, not a soft caveat. This closes the
kill-shot hole — declaring nothing while the data screams "train/test leak" no longer sails through on a
caveat; it yields a FLAG the merge gate / IC view treats as "not clean, action required."

Three detectors, each with a FALSE-POSITIVE governor and each SUPPRESSED when the authoritative family
declared (no double jeopardy):
  1. Inferred train/test split (leakage / look-ahead). Reuses plausibility_checks._infer_split +
     leakage_checks._canon_hash row-overlap. Promotion: an UNDECLARED split structure AND a real row-overlap
     AND the claim asserts OOS/held-out/generalization (leakage_checks._OOS_RE) -> FLAG. Governor: BOTH a
     detectable split AND a real overlap on the actual rows — never on file layout alone.
  2. Inferred regime structure (single-window fragility). Reuses the first/second-half two-sample KS.
     Promotion: a STRONG KS rejection (p << the smell alpha) + a variance-regime shift, with a forward/
     robust return-edge claim -> FLAG ("declare a windows: block"). Governor: strong KS + variance ratio,
     not the weak smell threshold.
  3. Inferred multiple-testing (selection / overfitting). Promotion: an UNDECLARED trials-shaped sibling
     artifact (a numeric matrix of many equal-length columns) co-occurring with an implausibly-high
     per-period Sharpe -> FLAG ("declare trials:N"). Governor: requires the matrix shape, not Sharpe alone.

INVARIANTS (CANONICAL-DECISIONS §3 / spec 04 M-8b.2):
  - apply_validity sets verdict_inputs.flag_for_declaration=True + inferred_structure="<which>"; V.verdict
    maps it to FLAG_FOR_DECLARATION. It NEVER sets validity_invalidated — the verdict-FLIP stays declaration-
    gated (Calma never guesses a verdict-flipping scope). Only a REPRODUCED (CONFIRMED/CAVEATS) headline is
    ever promoted; an authoritative REFUTED/INVALIDATED already decided -> untouched.
  - Each FLAG finding is a BLOCKING-severity finding of its dimension, linked to the headline claim, naming
    the EXACT block to declare — so the ledger validates the FLAG claim (ledger.semantic_validate).
  - Pure stdlib; reuses plausibility_checks + leakage_checks detection (never re-implements row hashing).

Library: run_checks(contract, base, claim_id, claim_text, findings) -> [finding,...];
apply_validity(claims, findings, contract, claim_text, base=None); family_status(contract, findings).
"""
import csv
import os
import re

import leakage_checks as LC
import numeric as N
import pathsafe as PS
import plausibility_checks as PLC
import verdict as V

# Governors — STRICTER than the plausibility-smell thresholds, because a FLAG is louder than a caveat.
_FLAG_OVERLAP_FRAC = 0.01                       # >=1% of sampled test rows duplicating train rows = real overlap
_FLAG_KS_ALPHA = PLC._REGIME_KS_ALPHA / 10.0    # p << the smell alpha: a STRONG (not weak) regime rejection
_FLAG_MIN_TRIALS_COLS = 8                       # a trials matrix needs >= this many equal-length numeric cols
_MATRIX_SAMPLE_ROWS = 50                        # rows sampled to confirm the matrix is numeric + rectangular

# the headline must assert a forward/robust edge for the regime flag to be invalidating (a bare in-window
# number is not a forward claim). Distinct from leakage's _OOS_RE — robustness/forward, not held-out.
_FORWARD_RE = re.compile(r"robust|out.?of.?sample|\boos\b|forward|walk.?forward|generaliz|consistent|"
                         r"holds|stable|future|going.?forward|live", re.I)


def _headline_claim_id(claims):
    head = next((c for c in claims if c.get("headline")), claims[0]) if claims else None
    return head["id"] if head else "c1"


# ---- Detector 1: inferred train/test split + real overlap + an OOS claim -> FLAG ----
def flag_inferred_split(contract, base, claim_text, claim_id="c1", findings=None):
    if contract.get("split"):
        return None                                  # a declared split -> the authoritative leakage family
    if findings and any(f.get("dimension") == "leakage" and f.get("validity_class") == "authoritative"
                        for f in (findings or [])):
        return None                                  # leakage already adjudicated -> no double jeopardy
    if not (claim_text and LC._OOS_RE.search(claim_text)):
        return None                                  # not an OOS claim -> an overlap isn't invalidating
    inferred, evidence = PLC._infer_split(contract)
    if not inferred:
        return None
    try:
        d = LC._load_split({"split": inferred}, base)
    except (OSError, ValueError, KeyError, IndexError, csv.Error):
        d = None
    if not d or not d.get("test") or not d.get("train"):
        return None
    excl = (d["split_col"],) if d.get("split_col") else ()
    train = set(LC._canon_hash(d["train_h"], d["train"][:PLC._SMELL_ROW_CAP], excl))
    test_h = LC._canon_hash(d["test_h"], d["test"][:PLC._SMELL_ROW_CAP], excl)
    if not test_h:
        return None
    overlap = sum(1 for h in test_h if h in train)
    mag = overlap / len(test_h)
    if mag < _FLAG_OVERLAP_FRAC:                     # GOVERNOR: a REAL overlap, not layout alone
        return None
    return {
        "id": "f-%s-inferred-split-flag" % claim_id, "claim_id": claim_id, "dimension": "leakage",
        "severity": "major", "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": ("FLAG_FOR_DECLARATION: the claim asserts out-of-sample, but an UNDECLARED train/test "
                    "split is detectable (%s) and %d of %d sampled test rows (%.1f%%) are exact duplicates "
                    "of training rows — the held-out result would be invalid if this is what it looks like. "
                    "Nothing was declared, so this is a demand to declare, not a verdict."
                    % (evidence, overlap, len(test_h), 100 * mag)),
        "unblock": ("declare the split: {%s} block so the authoritative leakage check runs (and, if "
                    "confirmed on the declared split, reaches INVALIDATED); if the overlap is intended "
                    "(in-sample), declare that scope and the flag clears"
                    % ", ".join("%s: %s" % (k, v) for k, v in inferred.items())),
        "reverify": {"kind": "requires-reexecution", "source": "split",
                     "expected": "declare the split, then no test row also appears in training"},
        "validity_class": "inferred-flag", "inferred_structure": "train/test split", "magnitude": mag,
    }


# ---- Detector 2: a STRONG regime break + a forward/robust return-edge claim -> FLAG ----
def flag_inferred_regime(contract, base, claim_text, claim_id="c1", findings=None):
    if contract.get("windows"):
        return None                                  # a declared windows block -> the authoritative family
    if findings and any(f.get("dimension") == "regime" and f.get("validity_class") == "authoritative"
                        for f in (findings or [])):
        return None
    if not PLC._binds_return(contract):
        return None
    if not (claim_text and _FORWARD_RE.search(claim_text)):
        return None                                  # a bare in-window number is not a forward claim
    rets = PLC._returns(contract, base)
    if not rets or len(rets) < PLC._MIN_OBS_REGIME:
        return None
    half = len(rets) // 2
    a, b = rets[:half], rets[half:]
    va, vb = N.fvar(a), N.fvar(b)
    p = N.ks_p(a, b)
    if not (p == p) or p >= _FLAG_KS_ALPHA:          # GOVERNOR: a STRONG rejection, not the smell alpha
        return None
    ratio = (vb / va) if va > 0 else float("inf")
    if not (ratio > PLC._REGIME_VAR_RATIO or ratio < 1.0 / PLC._REGIME_VAR_RATIO):
        return None                                  # KS without a variance-regime shift is too weak
    d = N.ks_2samp(a, b)
    return {
        "id": "f-%s-inferred-regime-flag" % claim_id, "claim_id": claim_id, "dimension": "regime",
        "severity": "major", "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": ("FLAG_FOR_DECLARATION: the claim asserts a robust/forward edge, but the return series "
                    "is strongly non-stationary across its own span — first half (mean %.4f, vol %.4f) vs "
                    "second half (mean %.4f, vol %.4f) reject the same-distribution null (two-sample KS "
                    "D=%.3f, p=%.4g) with a %.1fx variance-regime shift. A single-window edge need not hold "
                    "forward. Nothing was declared, so this is a demand to declare a walk-forward scope."
                    % (N.fmean(a), va ** 0.5, N.fmean(b), vb ** 0.5, d, p,
                       ratio if ratio >= 1 else (1.0 / ratio if ratio else float("inf")))),
        "unblock": ("declare a windows: block (rolling in-sample/out-of-sample) so the authoritative "
                    "walk-forward check runs and reports the OOS distribution; or scope the claim to the "
                    "regime the edge actually holds in"),
        "reverify": {"kind": "requires-reexecution", "source": "windows",
                     "expected": "the metric is consistent across declared walk-forward windows"},
        "validity_class": "inferred-flag", "inferred_structure": "windows",
    }


# ---- Detector 3: an undeclared trials-matrix sibling + an implausibly-high Sharpe -> FLAG ----
def _matrix_shape(path):
    """(ncols, nrows_sampled) if `path` reads as a numeric matrix of many equal-length columns, else None.
    A trials artifact is a returns matrix: each column is one trial's series. Bounded read; fail-soft."""
    if not PS.within_cap(path):
        return None
    try:
        with open(path, newline="") as fh:
            rd = csv.reader(fh)
            header = next(rd, None)
            if not header or len(header) < _FLAG_MIN_TRIALS_COLS:
                return None
            ncols = len(header)
            numeric_rows = 0
            sampled = 0
            for _, row in zip(range(_MATRIX_SAMPLE_ROWS), rd):
                sampled += 1
                if len(row) != ncols:
                    return None                       # ragged -> not a clean matrix
                ok = 0
                for v in row:
                    try:
                        float(v)
                        ok += 1
                    except (TypeError, ValueError):
                        pass
                if ok >= max(_FLAG_MIN_TRIALS_COLS, int(0.9 * ncols)):
                    numeric_rows += 1
    except (OSError, csv.Error, StopIteration):
        return None
    if sampled == 0 or numeric_rows < sampled:        # every sampled row must be (almost) all-numeric
        return None
    return ncols, sampled


def flag_inferred_trials(contract, base, claim_text, claim_id="c1", findings=None):
    if contract.get("trials") or contract.get("study"):
        return None                                  # declared -> the authoritative data-snooping family
    if findings and any(f.get("dimension") in ("data-snooping", "selection", "overfitting")
                        and f.get("validity_class") == "authoritative" for f in (findings or [])):
        return None
    if not PLC._binds_return(contract):
        return None
    rets = PLC._returns(contract, base)
    if not rets or len(rets) < PLC._MIN_OBS:
        return None
    sr = N.sharpe(rets, 1)[0]
    if not (sr == sr) or sr <= PLC._HI_SHARPE:        # GOVERNOR: needs the implausible-Sharpe co-signal
        return None
    head = PLC._headline(contract)
    head_art = (head or {}).get("artifact")
    for a in (contract.get("artifacts") or []):
        ap = a.get("path")
        if not ap or ap == head_art:                 # the matrix must be a SIBLING, not the headline file
            continue
        try:
            shape = _matrix_shape(PS.safe_join(base, ap))
        except ValueError:
            shape = None
        if not shape:
            continue
        ncols, nrows = shape
        return {
            "id": "f-%s-inferred-trials-flag" % claim_id, "claim_id": claim_id, "dimension": "data-snooping",
            "severity": "major", "status": "open", "confidence": "deterministic", "fixable_by": "author",
            "locator": ("FLAG_FOR_DECLARATION: the headline Sharpe is implausibly high (%.2f per period) and "
                        "an UNDECLARED trials matrix is present alongside it (%s: %d numeric columns of "
                        "equal length — the shape of a best-of-N selection). If the headline is the best of "
                        "those trials, it is selection-overfit. Nothing was declared, so this is a demand to "
                        "declare the trials, not a verdict." % (sr, os.path.basename(ap), ncols)),
            "unblock": ("declare trials: %d (or trials_artifact: %s) so the deflated-Sharpe / PBO "
                        "(probability of backtest overfitting) check runs authoritatively on the candidate "
                        "set; if the headline was pre-registered (not selected), declare that" % (ncols, ap)),
            "reverify": {"kind": "requires-reexecution", "source": "trials",
                         "expected": "the deflated Sharpe over the declared trials still clears the bar"},
            "validity_class": "inferred-flag", "inferred_structure": "trials",
        }
    return None


_DETECTORS = (flag_inferred_split, flag_inferred_regime, flag_inferred_trials)


def run_checks(contract, base, claim_id="c1", claim_text=None, findings=None):
    """Run the three inference detectors. Each is independently gated + governed; a detector that errors is
    skipped (fail-soft). Returns the FLAG findings (validity_class='inferred-flag')."""
    out = []
    for fn in _DETECTORS:
        try:
            f = fn(contract, base, claim_text, claim_id, findings)
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError, IndexError, csv.Error):
            f = None
        if f:
            out.append(f)
    return out


def family_status(contract, findings):
    return "flagged" if any(f.get("validity_class") == "inferred-flag" for f in findings) else "not-applicable"


def apply_validity(claims, findings, contract, claim_text, base=None):
    """Promote a reproduced headline to FLAG_FOR_DECLARATION on an inferred-flag finding. CONSERVATIVE: only
    a CONFIRMED/CAVEATS headline is touched (an authoritative REFUTED/INVALIDATED already decided), and it
    NEVER sets validity_invalidated (the verdict-flip stays declaration-gated). Links every flag finding to
    the headline claim and drives the headline's dimension from the first (loudest-listed) flag, so the FLAG
    claim carries the linked blocking finding the ledger requires."""
    flags = [f for f in findings if f.get("validity_class") == "inferred-flag"]
    if not flags or not claims:
        return
    head = next((c for c in claims if c.get("headline")), claims[0])
    if head.get("verdict") not in (V.CONFIRMED, V.CAVEATS):
        return
    driver = flags[0]
    vi = head.get("verdict_inputs") or {}
    vi["flag_for_declaration"] = True
    vi["inferred_structure"] = driver.get("inferred_structure") or "the undeclared"
    vi.pop("validity_invalidated", None)             # belt-and-suspenders: the flip stays declaration-gated
    head["driving_dimension"] = driver["dimension"]
    for f in flags:                                  # link every flag to the headline claim (no orphans)
        f["claim_id"] = head["id"]
    head["verdict_inputs"] = vi
    head["verdict"] = V.verdict(vi)
    head["headline_confidence"] = V.confidence(vi, head["verdict"])
    head["reproduction_or_reverify"] = driver.get("reverify")
