"""calma.distribution_shift_checks - V5: covariate / target distributional shift. On the findings rail,
called from calma._assemble_ledger like the other validity families. Pure stdlib (numeric.py's
deterministic two-sample KS + PSI). A model validated on a TRAIN distribution that differs from the
TEST/deployment distribution is not the in-distribution / generalizing claim asserted.

Method (reuses the `split` train/test files + `keys.target`):
  - per shared numeric column, a two-sample Kolmogorov-Smirnov test (numeric.ks_2samp / ks_p) AND the
    Population Stability Index (numeric.psi over train-decile bins) between train and test.
  - a column shifts when KS p < 0.01 OR PSI > 0.25 (the standard "significant population shift" bar).
    A shift on the `keys.target` column is TARGET (label/prior) shift; on any other column, COVARIATE
    shift.

Scope (mirrors leakage_checks): a material shift under an "in-distribution / generalizes / no
distribution shift / holds in deployment" claim -> INVALIDATED("distribution-shift"); the same finding
next to a bare reproduced number -> a CAVEAT. ABSTAINS without a readable train+test split. REFUTED is
never manufactured here.

Library: run_checks(contract, base, claim_id, claim_text) -> [finding,...];
apply_validity(claims, findings, contract, claim_text, base=None); family_status(contract, findings).
"""
import csv
import os
import re

import numeric as N
import pathsafe as PS
import verdict as V

_KS_ALPHA = 0.01     # KS p below this is a significant shift
_PSI_SHIFT = 0.25    # PSI above this is a significant population shift (industry standard: >0.25 = major)
_MIN_ROWS = 12       # need enough rows per side for a meaningful KS / PSI
_PSI_BINS = 10
_MAX_ROWS = 2_000_000

_GENERALIZE_RE = re.compile(
    r"in.?distribution|generaliz|out.?of.?distribution|\bood\b|holds (in|at) (deployment|production|test)|"
    r"no (distribution|covariate|dataset|population) shift|i\.?i\.?d\.?|representative (test|sample|"
    r"holdout)|same distribution|deploy(s|ment)? (cleanly|safely)|transfers", re.I)


def _safe_join(base, rel):
    """Resolve rel under base; refuse escapes (abs path / .. traversal / symlink-out). Delegates to the
    shared guard (pathsafe) so there is ONE audited containment implementation (L1)."""
    return PS.safe_join(base, rel)


def _read(path):
    if not PS.within_cap(path):
        return [], []
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            rd = csv.reader(fh)
            header = next(rd, [])
            rows = []
            for r in rd:
                rows.append(r)
                if len(rows) >= _MAX_ROWS:
                    break
        return header, rows
    except (OSError, StopIteration, csv.Error):
        return [], []


def _numeric_col(header, rows, name):
    """The column as floats, dropping non-numeric cells. None if the column is absent or non-numeric."""
    if name not in header:
        return None
    i = header.index(name)
    out = []
    for r in rows:
        if i < len(r):
            try:
                out.append(float(r[i]))
            except (TypeError, ValueError):
                pass
    return out if out else None


def _load_split(contract, base):
    sp = contract.get("split") or {}
    if not (sp.get("train") and sp.get("test")):
        return None
    try:
        th, tr = _read(_safe_join(base, sp["train"]))
        eh, te = _read(_safe_join(base, sp["test"]))
    except ValueError:
        return None
    if not th or not eh or len(tr) < _MIN_ROWS or len(te) < _MIN_ROWS:
        return None
    return {"th": th, "tr": tr, "eh": eh, "te": te}


def _psi_raw(train, test, bins=_PSI_BINS):
    """PSI over `bins` equal-count bins cut on the TRAIN sample's quantiles (deterministic). Reuses
    numeric.psi (which normalizes shares). Returns nan when train is degenerate (all-equal)."""
    s = sorted(train)
    edges = []
    for q in range(1, bins):
        edges.append(s[min(len(s) - 1, (q * len(s)) // bins)])
    if not edges or edges[0] == s[-1]:  # degenerate (constant) train column
        return float("nan")

    def counts(xs):
        c = [0] * bins
        for x in xs:
            b = 0
            while b < len(edges) and x > edges[b]:
                b += 1
            c[b] += 1
        return [v + 0.5 for v in c]  # +0.5 Laplace so an empty bin doesn't make PSI infinite
    return N.psi(counts(train), counts(test))


# identifier / key / time columns are NOT features - a shift on a row id (disjoint train/test id ranges
# by construction) is meaningless and must never be flagged as a covariate shift.
_ID_LIKE = re.compile(
    r"^(id|ids|index|idx|key|row|row_?id|rowid|uuid|guid|permno|gvkey|cusip|sedol|isin|ticker|symbol|"
    r"name|date|datetime|timestamp|time|dt|period|split|fold)$", re.I)


def _check_columns(contract, shared):
    """The columns whose distribution to compare. Prefer a DECLARED feature list (contract.features or
    keys.features) + the target; else every shared numeric column that isn't an identifier/key/time
    column. The spec checks FEATURE/TARGET distributions - never a row id."""
    keys = contract.get("keys") or {}
    target = keys.get("target")
    declared = contract.get("features") or keys.get("features")
    if isinstance(declared, (list, tuple)) and declared:
        cols = [c for c in declared if c in shared]
        if target and target in shared and target not in cols:
            cols.append(target)
        return cols, target
    split_col = keys.get("split") or (contract.get("split") or {}).get("split_col")
    id_col = keys.get("id")
    cols = [c for c in shared if c != split_col and c != id_col and not _ID_LIKE.match(c)]
    return cols, target


def _shifted_columns(contract, base):
    """[(column, is_target, ks_d, ks_p, psi)] for every checked FEATURE/TARGET column that materially
    shifts. Identifier/key/time columns are excluded (a disjoint train/test id range is not a shift)."""
    d = _load_split(contract, base)
    if not d:
        return None
    shared_all = [c for c in d["th"] if c in d["eh"]]
    shared, target = _check_columns(contract, shared_all)
    out = []
    for col in shared:
        tr = _numeric_col(d["th"], d["tr"], col)
        te = _numeric_col(d["eh"], d["te"], col)
        if not tr or not te or len(tr) < _MIN_ROWS or len(te) < _MIN_ROWS:
            continue
        p = N.ks_p(tr, te)
        psi = _psi_raw(tr, te)
        shifted = (p == p and p < _KS_ALPHA) or (psi == psi and psi > _PSI_SHIFT)
        if shifted:
            out.append((col, col == target, N.ks_2samp(tr, te), p, psi))
    return out


def check_shift(contract, base, claim_id="c1"):
    cols = _shifted_columns(contract, base)
    if cols is None or not cols:
        return None
    has_target = any(is_t for (_, is_t, _, _, _) in cols)
    kind = "target-shift" if has_target else "covariate-shift"
    parts = []
    for (col, is_t, d, p, psi) in cols[:6]:
        psi_s = ("%.3f" % psi) if psi == psi else "n/a"
        parts.append("%s%s (KS D=%.3f, p=%.4f, PSI=%s)" % (col, " [target]" if is_t else "", d, p, psi_s))
    return {
        "id": "f-%s-distshift" % claim_id, "claim_id": claim_id, "dimension": "distribution-shift",
        "severity": "major", "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": ("distributional shift (%s): train and test differ on %d column(s): %s - a result "
                    "validated on the train distribution does not generalize to a shifted test/"
                    "deployment distribution" % (kind, len(cols), "; ".join(parts))),
        "unblock": ("re-validate on a test sample drawn from the deployment distribution, or scope the "
                    "claim to the train distribution; report the shift (KS / PSI) alongside the metric"),
        "reverify": {"kind": "artifact-recheck", "source": "split",
                     "expected": "train and test feature/target distributions are not materially shifted"},
        "validity_class": "authoritative", "shift_kind": kind,
    }


def run_checks(contract, base, claim_id="c1", claim_text=None):
    """Distribution-shift findings. ACTIVATES only when a readable train+test `split` is declared AND the
    CLAIM asserts generalization / in-distribution (the property a shift would invalidate) - so a split
    used for some OTHER purpose (e.g. a leakage check) with an incidental covariate shift but no
    generalization claim is not flagged as collateral (mirrors regime_checks' claim-gated activation).
    Fail-soft: any error is skipped."""
    if not (contract.get("split") or {}).get("train"):
        return []
    if not _asserts_generalizes(claim_text):
        return []
    try:
        f = check_shift(contract, base, claim_id)
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError, IndexError):
        f = None
    return [f] if f else []


def family_status(contract, findings):
    """Honest scope.families.distribution-shift status. A fired finding -> 'flagged'; otherwise
    NOT-APPLICABLE (the family only runs under a generalization claim, so it positively reports only
    when it caught a shift)."""
    return "flagged" if any(f.get("dimension") == "distribution-shift" for f in findings) \
        else "not-applicable"


def _asserts_generalizes(claim_text):
    return bool(isinstance(claim_text, str) and _GENERALIZE_RE.search(claim_text))


def apply_validity(claims, findings, contract, claim_text, base=None):
    """Promote the headline per the distribution-shift findings + claim scope. Conservative: only a
    REPRODUCED number is promoted, and only DOWN. A material shift under an in-distribution/generalizes
    claim -> INVALIDATED("distribution-shift"); the same finding next to a bare number -> a CAVEAT."""
    sh = [f for f in findings if f.get("dimension") == "distribution-shift" and f.get("shift_kind")]
    if not sh or not claims:
        return
    head = next((c for c in claims if c.get("headline")), claims[0])
    if head.get("verdict") not in (V.CONFIRMED, V.CAVEATS):
        return
    vi = head.get("verdict_inputs") or {}
    if _asserts_generalizes(claim_text):
        for f in sh:
            f["severity"] = "blocker"
            f["claim_id"] = head["id"]
        vi["validity_invalidated"] = True
        vi["oos_claim_asserted"] = True
        head["driving_dimension"] = "distribution-shift"
    else:
        vi["soft_validity_caveat"] = True
    head["verdict_inputs"] = vi
    head["verdict"] = V.verdict(vi)
    head["headline_confidence"] = V.confidence(vi, head["verdict"])
