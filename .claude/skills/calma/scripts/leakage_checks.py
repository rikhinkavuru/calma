"""calma.leakage_checks - data-leakage catches on the findings rail (additive, off the bound
artifacts), called from calma._assemble_ledger like backtest_checks.run_checks. Dimension: "leakage"
(an EXEC dimension, so every finding re-verifies by artifact-recheck / re-execution, never static-reread).

What it catches, deterministic arithmetic only (no model):
  - train/test ROW overlap   - hash each row (canonical column order, sha256); a shared hash is the
    same data row in both sets -> the held-out number isn't held-out. Authoritative.
  - entity/ID overlap        - a declared id value appears in both train and test. Authoritative.
  - temporal look-ahead      - a test row at/before the last training time (optional embargo). Authoritative.
  - duplicate inflation      - exact duplicate rows WITHIN the eval set (inflates the effective sample). Soft.
  - target leakage           - a feature column that EQUALS the target (authoritative) or is ~perfectly
    correlated with it (|pearson_r| >= 0.999, LABELED HEURISTIC -> soft).

The verdict effect is applied by `apply_validity` (called from _assemble_ledger): an authoritative
finding on an OUT-OF-SAMPLE claim degrades the reproduced headline to INVALIDATED; if the claim type is
indeterminate -> CAN'T-CONFIRM (declare the scope); if the claim is explicitly in-sample, or the finding
is a heuristic/duplicate, -> CONFIRMED-WITH-CAVEATS. REFUTED is never manufactured here - that stays the
gap-gated recompute path (and the leakage-corrected re-run, Step 4).

Library: run_checks(contract, base, claim_id="c1") -> [finding, ...] ; apply_validity(claims, findings,
contract, claim_text) ; oos_status(contract, claim_text) -> "oos"|"in-sample"|"indeterminate".
"""
import csv
import hashlib
import os
import re

import numeric as N
import verdict as V

_HEUR_CORR = 0.999  # |pearson_r| at/above which a feature is flagged as ~perfectly target-correlated

_OOS_RE = re.compile(r"held.?out|out.?of.?sample|\boos\b|test[\s-]?set|generaliz|unseen|validation", re.I)
_INSAMPLE_RE = re.compile(
    r"in.?sample|training (set|accuracy|error)|train(ing)? accuracy|resubstitution|fit on all|apparent error",
    re.I)
_ID_NAME = re.compile(r"(^id$|^idx$|^index$|_id$|uuid|guid|^key$|sample_?id|row_?id|entity)", re.I)
_TEST_TOKEN = re.compile(r"^(test|val|valid|validation|holdout|hold-out|oos|eval)$", re.I)
_TRAIN_TOKEN = re.compile(r"^(train|training|fit|in-?sample|is)$", re.I)


# ---- io ----------------------------------------------------------------------

def _read(path):
    if not os.path.isfile(path):
        return [], []  # FIFO/socket/device: never open() (would block); treated as unreadable
    try:
        with open(path, newline="") as fh:
            rd = csv.reader(fh)
            header = next(rd, [])
            rows = [r for r in rd]
        return header, rows
    except (OSError, StopIteration):
        return [], []


def _col(header, rows, name):
    if name not in header:
        return []
    i = header.index(name)
    return [(r[i] if i < len(r) else "") for r in rows]


def _floats(vals):
    out = []
    for v in vals:
        try:
            out.append(float(str(v).strip()))
        except (TypeError, ValueError):
            out.append(float("nan"))
    return out


def _canon_hash(header, rows, exclude=()):
    """sha256 per row over the row's columns in CANONICAL (sorted) order - so train and test hash the
    same content the same way regardless of column order. `exclude` drops the split column."""
    cols = [c for c in sorted(header) if c not in exclude]
    idx = [header.index(c) for c in cols]
    out = []
    for r in rows:
        payload = "\x1f".join("%s=%s" % (cols[j], r[idx[j]] if idx[j] < len(r) else "")
                              for j in range(len(cols)))
        out.append(hashlib.sha256(payload.encode("utf-8")).hexdigest())
    return out


def _headline_metric(contract):
    mets = contract.get("metrics") or []
    for m in mets:
        if m.get("headline") and m.get("claimed_value") is not None:
            return m
    for m in mets:
        if m.get("claimed_value") is not None:
            return m
    return mets[0] if mets else None


def _load_split(contract, base):
    """Return {train_h, train, test_h, test, split_col} or None. Two-file form (split.train/test) or
    single-file form (split.file + split.column, partitioned by test_value or a test-looking token)."""
    sp = contract.get("split") or {}
    if sp.get("train") and sp.get("test"):
        th, tr = _read(os.path.join(base, sp["train"]))
        eh, er = _read(os.path.join(base, sp["test"]))
        if th and eh:
            return {"train_h": th, "train": tr, "test_h": eh, "test": er, "split_col": None}
        return None
    if sp.get("file") and sp.get("column"):
        h, rows = _read(os.path.join(base, sp["file"]))
        if not h or sp["column"] not in h:
            return None
        ci = h.index(sp["column"])
        tv = sp.get("test_value")
        train, test = [], []
        for r in rows:
            v = (r[ci] if ci < len(r) else "")
            if tv is not None:
                is_test = str(v).strip() == str(tv).strip()
            elif _TEST_TOKEN.match(str(v).strip()):
                is_test = True
            elif _TRAIN_TOKEN.match(str(v).strip()):
                is_test = False
            else:
                is_test = False  # unknown token -> treat as train (conservative; never invents test rows)
            (test if is_test else train).append(r)
        if train and test:
            return {"train_h": h, "train": train, "test_h": h, "test": test, "split_col": sp["column"]}
    return None


# ---- detectors (pure detection; severity reflects authoritativeness, not yet the OOS scope) -------

def _finding(claim_id, kind, severity, vclass, magnitude, locator, unblock, source):
    return {
        "id": "f-%s-leak-%s" % (claim_id, kind), "claim_id": claim_id, "dimension": "leakage",
        "severity": severity, "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": locator, "unblock": unblock,
        "reverify": {"kind": "artifact-recheck", "source": source,
                     "expected": "no train/test contamination on re-check"},
        "validity_class": vclass, "leakage_kind": kind, "magnitude": magnitude,
    }


def check_row_overlap(d, claim_id="c1"):
    if not d or not d["test"]:
        return None
    excl = (d["split_col"],) if d["split_col"] else ()
    train = set(_canon_hash(d["train_h"], d["train"], excl))
    test_h = _canon_hash(d["test_h"], d["test"], excl)
    overlap = sum(1 for h in test_h if h in train)
    if overlap == 0:
        return None
    mag = overlap / len(test_h)
    return _finding(
        claim_id, "row-overlap", "blocker", "authoritative", mag,
        "held-out set is contaminated: %d of %d test rows (%.1f%%) are exact duplicates of training rows"
        % (overlap, len(test_h), 100 * mag),
        "rebuild the split so no test row also appears in training, then re-evaluate", "rows")


def check_id_overlap(d, contract, claim_id="c1"):
    idcol = (contract.get("keys") or {}).get("id")
    if not d or not idcol or idcol not in d["train_h"] or idcol not in d["test_h"]:
        return None
    train = set(v for v in _col(d["train_h"], d["train"], idcol) if str(v).strip() != "")
    test = [v for v in _col(d["test_h"], d["test"], idcol) if str(v).strip() != ""]
    if not test:
        return None
    overlap = sum(1 for v in test if v in train)
    if overlap == 0:
        return None
    mag = overlap / len(test)
    return _finding(
        claim_id, "id-overlap", "blocker", "authoritative", mag,
        "entity leakage: %d of %d test ids (%.1f%%) also appear in training (key %r)"
        % (overlap, len(test), 100 * mag, idcol),
        "use a group-aware split so no entity/id spans train and test, then re-evaluate", idcol)


def _parse_times(train_vals, test_vals):
    """Both columns parsed as floats if EVERY value parses, else both kept as strings (ISO dates sort
    lexically). Returns (train, test, numeric: bool)."""
    def allnum(vs):
        for v in vs:
            try:
                float(str(v).strip())
            except (TypeError, ValueError):
                return False
        return bool(vs)
    if allnum(train_vals) and allnum(test_vals):
        return [float(v) for v in train_vals], [float(v) for v in test_vals], True
    return [str(v).strip() for v in train_vals], [str(v).strip() for v in test_vals], False


def check_temporal(d, contract, claim_id="c1"):
    tcol = (contract.get("keys") or {}).get("time")
    if not d or not tcol or tcol not in d["train_h"] or tcol not in d["test_h"]:
        return None
    tr = [v for v in _col(d["train_h"], d["train"], tcol) if str(v).strip() != ""]
    te = [v for v in _col(d["test_h"], d["test"], tcol) if str(v).strip() != ""]
    if not tr or not te:
        return None
    tr, te, numeric = _parse_times(tr, te)
    mx = max(tr)
    embargo = (contract.get("split") or {}).get("embargo")
    if numeric and isinstance(embargo, (int, float)):
        viol = sum(1 for v in te if v <= mx + embargo)
    else:
        viol = sum(1 for v in te if v <= mx)
    if viol == 0:
        return None
    mag = viol / len(te)
    return _finding(
        claim_id, "temporal", "blocker", "authoritative", mag,
        "look-ahead: %d of %d test rows (%.1f%%) are at or before the last training time (%s, key %r)"
        % (viol, len(te), 100 * mag, mx, tcol),
        "use a time-ordered split (test strictly after training, plus any required embargo), then re-evaluate",
        tcol)


def check_dup_inflation(d, claim_id="c1"):
    if not d or not d["test"]:
        return None
    excl = (d["split_col"],) if d["split_col"] else ()
    h = _canon_hash(d["test_h"], d["test"], excl)
    dup = len(h) - len(set(h))
    if dup == 0:
        return None
    mag = dup / len(h)
    return _finding(
        claim_id, "dup-inflation", "minor", "soft", mag,
        "the evaluation set has %d exact duplicate rows of %d (%.1f%%), inflating the effective sample"
        % (dup, len(h), 100 * mag),
        "de-duplicate the evaluation set (or confirm the duplicates are intended), then re-evaluate", "rows")


def _target_table(d, contract, base):
    """The (header, rows) the target-leakage check runs over: the eval/test split if present, else the
    artifact that carries the declared target column."""
    if d:
        return d["test_h"], d["test"]
    tgt = (contract.get("keys") or {}).get("target")
    if not tgt:
        return [], []
    for a in contract.get("artifacts") or []:
        cols = a.get("columns") or {}
        if tgt in cols:
            return _read(os.path.join(base, a.get("path", "")))
    return [], []


def check_target_leakage(d, contract, base, claim_id="c1"):
    keys = contract.get("keys") or {}
    tgt = keys.get("target")
    if not tgt:
        return None
    header, rows = _target_table(d, contract, base)
    if not header or tgt not in header or not rows:
        return None
    # the model's OWN prediction column being ~perfectly correlated with the label is the model
    # WORKING, not leakage - exclude any column the contract's metrics bind as a prediction/score/
    # prob before the heuristic. Hand-authored contracts (and the shipped leakage-heldout demo) list
    # `score` in features; the auto-drafter already drops these via draft_contract._NON_FEATURE_TAGS.
    _PRED_TAGS = ("prediction", "score", "prob", "probs", "pred", "yhat", "y_pred")
    pred_cols = set()
    for _m in contract.get("metrics", []):
        _b = _m.get("binding") or {}
        for _t in _PRED_TAGS:
            if _b.get(_t):
                pred_cols.add(str(_b[_t]))
    feats = [f for f in (contract.get("features") or [])
             if f in header and f != tgt and f not in pred_cols]
    if not feats:
        return None
    tvals = _col(header, rows, tgt)
    tnum = _floats(tvals)
    exact, heur = [], []
    for f in feats:
        fvals = _col(header, rows, f)
        if all(str(a).strip() == str(b).strip() for a, b in zip(fvals, tvals)) and fvals:
            exact.append(f)
            continue
        fnum = _floats(fvals)
        pairs = [(a, b) for a, b in zip(fnum, tnum) if a == a and b == b]
        if len(pairs) >= 3:
            r = N.pearson_r([a for a, _ in pairs], [b for _, b in pairs])
            if r == r and abs(r) >= _HEUR_CORR:
                heur.append((f, r))
    if exact:
        return _finding(
            claim_id, "target", "blocker", "authoritative", 1.0,
            "target leakage: feature %s is identical to the target %r - the model can read the answer"
            % (", ".join(repr(f) for f in exact), tgt),
            "drop the leaking feature(s) and re-train/re-evaluate", exact[0])
    if heur:
        f, r = heur[0]
        return _finding(
            claim_id, "target-corr", "minor", "soft", abs(r),
            "possible target leakage (HEURISTIC): feature %r is near-perfectly correlated with the target "
            "%r (|r|=%.4f) - confirm it is a legitimate predictor, not a proxy for the label" % (f, tgt, abs(r)),
            "confirm %r is available at prediction time and is not derived from the target; else drop it" % f,
            f)


def _split_declared_files(contract):
    """The rel-paths a DECLARED split references (two-file or single-file form), or [] if no split
    is declared. Used to tell 'declared-but-unreadable' apart from 'absent' and 'readable'."""
    sp = contract.get("split") or {}
    if sp.get("train") and sp.get("test"):
        return [sp["train"], sp["test"]]
    if sp.get("file") and sp.get("column"):
        return [sp["file"]]
    return []


def _split_unreadable(contract, base):
    """A split is DECLARED but a referenced file is missing / can't be read - distinct from 'no split'
    and from 'declared and readable'. Routes a declared-but-unrunnable leakage check to CAN'T-CONFIRM
    instead of a silent 'checked'."""
    rels = _split_declared_files(contract)
    if not rels:
        return False
    for rel in rels:
        if not os.path.isfile(os.path.join(base or ".", rel)):
            return True
    return False


def _indeterminate_finding(claim_id):
    """A leakage split was DECLARED but could not be read - a declared check that cannot RUN is
    CAN'T-CONFIRM, never a silent 'checked' (clean)."""
    return {
        "id": "f-%s-leak-indeterminate" % claim_id, "claim_id": claim_id, "dimension": "leakage",
        "severity": "minor", "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": "declared train/test split could not be read (missing / unreadable file)",
        "unblock": "the leakage check was declared (split:) but its file(s) could not be read - fix "
                   "the split paths and re-verify",
        "reverify": {"kind": "artifact-recheck", "source": "split",
                     "expected": "the declared train/test split files are readable"},
        "validity_class": "indeterminate", "leakage_indeterminate": True,
    }


def run_checks(contract, base, claim_id="c1"):
    """All leakage catches against one engagement. Returns the findings that fired (possibly empty).
    A declared-but-unreadable split is INDETERMINATE (CAN'T-CONFIRM), never a silent 'checked'.
    Fail-soft: any check that errors is skipped (a check must never crash a verification)."""
    d = None
    try:
        d = _load_split(contract, base)
    except (OSError, ValueError, KeyError, TypeError):
        d = None
    out = []
    if d is None and _split_unreadable(contract, base):
        out.append(_indeterminate_finding(claim_id))
    checks = (
        lambda: check_row_overlap(d, claim_id),
        lambda: check_id_overlap(d, contract, claim_id),
        lambda: check_temporal(d, contract, claim_id),
        lambda: check_dup_inflation(d, claim_id),
        lambda: check_target_leakage(d, contract, base, claim_id),
    )
    for fn in checks:
        try:
            f = fn()
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
            f = None
        if f:
            out.append(f)
    return out


def family_status(contract, findings):
    """Honest per-family status for the ledger scope.families map."""
    applicable = bool(contract.get("split")) or bool((contract.get("keys") or {}).get("target"))
    if not applicable:
        return "not-applicable"
    # a DEFINITE leakage finding wins over "indeterminate": if we flagged real leakage, the family is
    # flagged even when an unreadable split also left one check unrun (matches apply_validity).
    if any(f.get("dimension") == "leakage" and not f.get("leakage_indeterminate") for f in findings):
        return "flagged"
    if any(f.get("leakage_indeterminate") for f in findings):
        return "indeterminate"  # declared but the split couldn't be read - not a clean scan
    return "checked"


# ---- claim-scope guard + verdict promotion ----------------------------------

def oos_status(contract, claim_text):
    """Does the claim assert an out-of-sample result? 'oos' | 'in-sample' | 'indeterminate'. Drives the
    scope-guard: INVALIDATED requires a POSITIVE oos assertion; an explicit in-sample claim degrades to
    a caveat; anything ambiguous degrades to CAN'T-CONFIRM (declare the scope) - never a manufactured
    INVALIDATED."""
    t = claim_text or ""
    if _INSAMPLE_RE.search(t):
        return "in-sample"
    if _OOS_RE.search(t):
        return "oos"
    sp = contract.get("split") or {}
    if sp.get("train") and sp.get("test"):
        head = _headline_metric(contract)
        if head and os.path.basename(str(head.get("artifact", ""))) == os.path.basename(str(sp["test"])):
            return "oos"  # the headline metric is computed on the held-out test file: a structural OOS claim
        return "indeterminate"
    return "indeterminate"


def corrected_recompute(contract, base, head):
    """The leakage RE-RUN differentiator. When a row/id overlap is CORRECTABLE from the bound artifact -
    the headline metric is computed on the test split itself, so the contaminated eval rows are
    identifiable - recompute the SAME recipe on the de-contaminated eval rows. Returns
    (corrected_value, kept, dropped) or None when correction isn't feasible (no localizable rows,
    metric not on the test file, or the recompute degenerates). No full re-execution - an artifact
    subset recompute."""
    import recipes as RCP  # lazy: avoids any import-time coupling
    sp = contract.get("split") or {}
    if not sp.get("test") or not head:
        return None
    if os.path.basename(str(head.get("artifact", ""))) != os.path.basename(str(sp.get("test", ""))):
        return None  # contamination can't be localized to the eval rows the metric is computed on
    d = _load_split(contract, base)
    if not d or not d["test"]:
        return None
    fn = RCP.get(head.get("metric_id"))
    binding = head.get("binding") or {}
    if not fn or not binding:
        return None
    excl = (d["split_col"],) if d["split_col"] else ()
    train_hashes = set(_canon_hash(d["train_h"], d["train"], excl))
    test_hashes = _canon_hash(d["test_h"], d["test"], excl)
    idcol = (contract.get("keys") or {}).get("id")
    train_ids = set(_col(d["train_h"], d["train"], idcol)) if idcol and idcol in d["train_h"] else set()
    id_i = d["test_h"].index(idcol) if (idcol and idcol in d["test_h"]) else None
    keep = []
    for i, r in enumerate(d["test"]):
        bad = test_hashes[i] in train_hashes
        if not bad and train_ids and id_i is not None:
            bad = (r[id_i] if id_i < len(r) else None) in train_ids
        if not bad:
            keep.append(i)
    dropped = len(d["test"]) - len(keep)
    if dropped == 0 or not keep:
        return None
    cols = {}
    for cname in binding.values():
        if cname in d["test_h"]:
            ci = d["test_h"].index(cname)
            vals = []
            for i in keep:
                try:
                    vals.append(float(d["test"][i][ci]))
                except (ValueError, IndexError):
                    vals.append(float("nan"))
            cols[cname] = vals
    try:
        res = fn(cols, binding, head.get("convention"))
        val = res.get("value")
    except (ValueError, KeyError, TypeError, ZeroDivisionError, OverflowError):
        return None
    if not (isinstance(val, float) and val == val and val not in (float("inf"), float("-inf"))):
        return None
    return val, len(keep), dropped


def apply_validity(claims, findings, contract, claim_text, base=None):
    """Promote the headline claim's verdict per the leakage findings + the claim scope. Mutates the
    headline claim's verdict_inputs (and re-derives the label) and, for the in-sample path, demotes the
    authoritative findings to a caveat severity. Conservative: only a REPRODUCED number (CONFIRMED/
    CAVEATS) is ever promoted. On an out-of-sample claim with a CORRECTABLE overlap, the leakage-
    corrected recompute is attempted: if the de-contaminated number falls outside budget the claim is
    REFUTED via the ordinary gap-gated path (driving_dimension=leakage); otherwise it degrades to
    INVALIDATED, reporting that the held-out number survives correction but the split was contaminated."""
    leak = [f for f in findings if f.get("dimension") == "leakage"]
    if not leak or not claims:
        return
    head = next((c for c in claims if c.get("headline")), claims[0])
    if head.get("verdict") not in (V.CONFIRMED, V.CAVEATS):
        return  # the number didn't reproduce; leakage findings stay additive, no promotion
    vi = head.get("verdict_inputs") or {}
    auth = [f for f in leak if f.get("validity_class") == "authoritative"]
    soft = [f for f in leak if f.get("validity_class") == "soft"]
    correctable = [f for f in auth if f.get("leakage_kind") in ("row-overlap", "id-overlap")]
    # declared-but-unreadable split: the check could not run -> CAN'T-CONFIRM, never a silent pass.
    # UNLESS we ALSO detected DEFINITE leakage from the readable data (target==feature / row overlap):
    # an authoritative finding is the stronger, more actionable verdict (INVALIDATED), so it WINS over
    # "couldn't read the split". Must RE-DERIVE the headline verdict (mirror the tail) - the flag alone
    # leaves the stale CONFIRMED label on the claim while verdict_inputs says otherwise.
    if not auth and any(f.get("leakage_indeterminate") for f in leak):
        vi["validity_unresolved"] = True
        head["driving_dimension"] = "leakage"
        head["verdict_inputs"] = vi
        head["verdict"] = V.verdict(vi)
        head["headline_confidence"] = V.confidence(vi, head["verdict"])
        return
    if auth:
        status = oos_status(contract, claim_text)
        if status == "oos":
            # the leakage RE-RUN: try the de-contaminated recompute before settling on a verdict.
            corrected = corrected_recompute(contract, base, _headline_metric(contract)) \
                if (base and correctable) else None
            claimed = head.get("claimed_value")
            budget = vi.get("effective_budget") or 0.0
            if corrected is not None and claimed is not None:
                cval, kept, dropped = corrected
                tag = (" - claimed %s -> leakage-corrected %s (dropped %d contaminated of %d eval rows)"
                       % (claimed, round(cval, 6), dropped, kept + dropped))
                for f in correctable:
                    f["claim_id"] = head["id"]
                    f["locator"] = f.get("locator", "") + tag
                if abs(cval - claimed) > budget:
                    # the held-out number, de-contaminated, no longer holds -> REFUTED (gap-gated path)
                    vi["gap"] = abs(cval - claimed)
                    vi["claim_outside_ci"] = True
                    head["recomputed_value"] = cval
                    head["driving_dimension"] = "leakage"
                    head["reproduction_or_reverify"] = {
                        "kind": "artifact-recheck", "source": "rows",
                        "expected": "recompute on the de-contaminated eval set differs from the claim beyond budget"}
                    head["verdict_inputs"] = vi
                    head["verdict"] = V.verdict(vi)
                    head["headline_confidence"] = V.confidence(vi, head["verdict"])
                    return
                # survives correction: still an invalid OOS claim (the held-out set was contaminated)
            vi["validity_invalidated"] = True
            vi["oos_claim_asserted"] = True
            head["driving_dimension"] = "leakage"
            for f in auth:
                f["claim_id"] = head["id"]  # the INVALIDATED link must point at the headline claim
        elif status == "in-sample":
            for f in auth:  # not an OOS claim -> contamination is a noted caveat, not invalidating
                f["severity"] = "minor"
                f["unblock"] = f.get("unblock", "") + " (or confirm the claim is in-sample, where overlap is expected)"
            vi["soft_validity_caveat"] = True
        else:  # indeterminate -> CAN'T-CONFIRM: declare the scope, don't guess
            vi["validity_unresolved"] = True
            for f in auth:
                f["unblock"] = ("declare whether the claim is out-of-sample (a held-out split) - then "
                                "re-verify; " + f.get("unblock", ""))
    elif soft:
        vi["soft_validity_caveat"] = True
    else:
        return
    head["verdict_inputs"] = vi
    head["verdict"] = V.verdict(vi)
    head["headline_confidence"] = V.confidence(vi, head["verdict"])
