"""calma.embargo_checks - WS-C(i): era-embargo / purged-CV leakage (Numerai-keyed default; Lopez de Prado
general form). On the findings rail, called from calma._assemble_ledger like the other validity families.
Pure stdlib.

The leakage the row/id/temporal family does NOT catch: train and validation windows that are too close in
TIME for the target's forward horizon, so the first validation eras' target windows OVERLAP the training
window. The headline metric reproduces exactly - it is just inflated by look-ahead. This is calma's
recompute-and-diff applied to the SPLIT GEOMETRY instead of the metric.

Two detections:
  A (hard gate, deterministic - needs only the era column of train + validation):
      purge gap = min_val_era - max_train_era. A required purge must separate them. Numerai's published
      guidance: 8 eras for the 20-day target, 16 for the 60-day. The general (Lopez de Prado AFML ch.7)
      form is "purge the forward-horizon eras, then embargo a buffer": required = ceil(horizon_days / 5)
      forward eras + embargo_buffer eras. With the default 4-era buffer this reproduces Numerai exactly
      (20d -> ceil(20/5)+4 = 8; 60d -> ceil(60/5)+4 = 16). gap <= required -> the unambiguous blow-up
      -> INVALIDATED under an out-of-sample / validation / leaderboard / staking claim.
  B (severity / corroborator - when the validation predictions + targets are present):
      per-era validation CORR, then inflation = mean(CORR over all val eras)
                                              - mean(CORR after dropping the first `required` val eras)
      = the leakage premium the un-purged leading eras add to the headline. Reported as the magnitude on
      A's finding. Standalone (no declared train range) a material inflation is a SOFT caveat, never a gate.

Contract block (all optional; the family ABSTAINS entirely without `embargo`):
  embargo:
    horizon_days: 20         # the target's forward horizon in trading days (Numerai: 20 or 60)
    purge_eras: 8            # OR declare the required purge directly (wins over the horizon formula)
    embargo_buffer_eras: 4   # extra buffer eras added to the forward horizon (LdP embargo); default 4
    era_col: era             # the era / time-group column name (parsed via its trailing digits)
    train: train.csv         # a file containing era_col -> the TRAINING eras (Detection A)
    val: predictions.csv     # a file with era_col (+ prediction,target for Detection B); defaults to the
                             # headline metric's artifact + binding when omitted

Scope (mirrors leakage_checks): INVALIDATED under a "validation / out-of-sample / leaderboard / staking"
claim that the gap violates; the same finding next to a bare reproduced number -> a CAVEAT. ABSTAINS without
an `embargo` block (never guesses). REFUTED is never manufactured here.

Library: run_checks(contract, base, claim_id, claim_text) -> [finding,...];
apply_validity(claims, findings, contract, claim_text, base=None); family_status(contract, findings).
"""
import csv
import math
import os
import re

import numeric as N
import pathsafe as PS
import verdict as V

# the claim scopes an era-embargo finding invalidates: a tournament/held-out number whose validity the
# overlap breaks. "validation" is the canonical Numerai scope ("validation corr 0.026").
_OOS_RE = re.compile(
    r"validation|held.?out|out.?of.?sample|\boos\b|leaderboard|live|stak(e|ing)|generaliz|"
    r"walk.?forward|purged|unseen|test[\s-]?set", re.I)
_ERA_DIGITS = re.compile(r"(\d+)\s*$")  # trailing integer of an era label ("era0123" -> 123, "0123" -> 123)


def _embargo(contract):
    e = contract.get("embargo")
    return e if isinstance(e, dict) else None


def _read_csv(path):
    """Load a CSV into {header: [raw_str, ...]}. Unreadable / non-regular-file -> {} (fail-soft)."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            rd = csv.reader(fh)
            header = next(rd, [])
            cols = {h: [] for h in header}
            for row in rd:
                for h, v in zip(header, row):
                    cols[h].append(v)
            return cols
    except (OSError, StopIteration, csv.Error):
        return {}


def _safe_join(base, rel):
    return PS.safe_join(base, rel)


def _parse_era(s):
    """The integer era of a label: a bare integer, or the trailing digit-run ('era0123' -> 123).
    None if there is no trailing integer (a date / non-era key -> Detection A is indeterminate on it)."""
    s = str(s).strip()
    if not s:
        return None
    m = _ERA_DIGITS.search(s)
    return int(m.group(1)) if m else None


def _era_ints(raw):
    """Parse a column of era labels to ints, dropping the unparseable. Returns (ints, parse_rate)."""
    ints, seen = [], 0
    for v in raw:
        seen += 1
        p = _parse_era(v)
        if p is not None:
            ints.append(p)
    return ints, (len(ints) / seen if seen else 0.0)


def _floats(raw):
    out = []
    for v in raw:
        try:
            out.append(float(str(v).strip()))
        except (TypeError, ValueError):
            out.append(float("nan"))
    return out


def _required_purge(emb):
    """The purge required between the last train era and the first val era. `purge_eras` wins; otherwise
    ceil(horizon_days/5) forward eras + an embargo buffer (default 4 eras = Numerai's published 8/16)."""
    pe = emb.get("purge_eras")
    if isinstance(pe, (int, float)) and not isinstance(pe, bool) and pe >= 0:
        return int(math.ceil(pe))
    hd = emb.get("horizon_days")
    if not (isinstance(hd, (int, float)) and not isinstance(hd, bool) and hd > 0):
        hd = 20  # the Numerai default target horizon
    buf = emb.get("embargo_buffer_eras")
    buf = int(buf) if isinstance(buf, (int, float)) and not isinstance(buf, bool) and buf >= 0 else 4
    return int(math.ceil(float(hd) / 5.0)) + buf


def _headline_metric(contract):
    for m in contract.get("metrics", []):
        if m.get("headline"):
            return m
    ms = contract.get("metrics", [])
    return ms[0] if ms else None


def _val_cols(contract, base, emb):
    """The validation columns for Detection B: era + (optionally) prediction,target. Source = embargo.val
    if declared, else the headline metric's artifact; column NAMES come from the headline binding (era_col
    overrides the era name). Returns {era:[str], pred:[str]|None, tgt:[str]|None} or None."""
    hm = _headline_metric(contract) or {}
    bind = hm.get("binding") or {}
    era_name = emb.get("era_col") or bind.get("era") or "era"
    pred_name = bind.get("prediction")
    tgt_name = bind.get("target")
    src = emb.get("val") or hm.get("artifact")
    if not src:
        return None
    cols = _read_csv(_safe_join(base, src))
    if era_name not in cols:
        return None
    return {"era": cols[era_name],
            "pred": cols.get(pred_name) if pred_name else None,
            "tgt": cols.get(tgt_name) if tgt_name else None}


def _per_era_corr(vcols):
    """{era_int: numerai_corr} over val eras with >=2 points, in ascending era order -> (eras, corrs)."""
    pred, tgt, era = vcols.get("pred"), vcols.get("tgt"), vcols.get("era")
    if not pred or not tgt or not era:
        return None
    p, t = _floats(pred), _floats(tgt)
    groups = {}
    for pv, tv, ev in zip(p, t, era):
        k = _parse_era(ev)
        if k is None:
            continue
        groups.setdefault(k, ([], []))
        groups[k][0].append(pv)
        groups[k][1].append(tv)
    eras = sorted(groups)
    corrs = []
    for k in eras:
        xs, ys = groups[k]
        c = N.numerai_corr_series(xs, ys) if len(xs) >= 2 else float("nan")
        corrs.append(c)
    pairs = [(e, c) for e, c in zip(eras, corrs) if c == c]  # drop NaN eras
    if not pairs:
        return None
    return [e for e, _ in pairs], [c for _, c in pairs]


def _inflation(contract, base, emb, required):
    """The leakage premium: mean(all val-era CORR) - mean(CORR after dropping the first `required` eras).
    Returns dict or None when there aren't enough eras to drop meaningfully."""
    vcols = _val_cols(contract, base, emb)
    if not vcols:
        return None
    pec = _per_era_corr(vcols)
    if not pec:
        return None
    _, corrs = pec
    if len(corrs) <= required + 1:  # need >=2 eras left after dropping the leading `required`
        return None
    all_mean = N.fmean(corrs)
    dropped_mean = N.fmean(corrs[required:])
    return {"inflation": all_mean - dropped_mean, "all_mean": all_mean,
            "dropped_mean": dropped_mean, "n_eras": len(corrs), "n_dropped": required}


def _finding(claim_id, kind, severity, vclass, locator, unblock):
    return {
        "id": "f-%s-embargo-%s" % (claim_id, kind), "claim_id": claim_id, "dimension": "era-embargo",
        "severity": severity, "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": locator, "unblock": unblock,
        "reverify": {"kind": "artifact-recheck", "source": "era-split",
                     "expected": "min_val_era - max_train_era > required purge (no target-window overlap)"},
        "validity_class": vclass, "embargo_kind": kind,
    }


def check_era_gap(contract, base, claim_id="c1"):
    """Detection A: the deterministic purge-gap gate. Needs a declared train file with the era column."""
    emb = _embargo(contract)
    if not emb or not emb.get("train"):
        return None
    era_col = emb.get("era_col") or ((_headline_metric(contract) or {}).get("binding") or {}).get("era") or "era"
    tcols = _read_csv(_safe_join(base, emb["train"]))
    if era_col not in tcols:
        return None
    vcols = _val_cols(contract, base, emb)
    if not vcols:
        return None
    train_eras, train_rate = _era_ints(tcols[era_col])
    val_eras, val_rate = _era_ints(vcols["era"])
    # if the era column isn't integer-parseable on either side, Detection A is indeterminate - do NOT fire.
    if not train_eras or not val_eras or train_rate < 0.5 or val_rate < 0.5:
        return None
    required = _required_purge(emb)
    max_train, min_val = max(train_eras), min(val_eras)
    gap = min_val - max_train
    if gap > required:
        return None  # correctly purged: enough empty eras separate train from validation
    inf = _inflation(contract, base, emb, required)
    inf_txt = ""
    if inf and inf["inflation"] == inf["inflation"]:
        inf_txt = (" The first %d validation eras inflate the headline CORR by %+.4f "
                   "(mean %.4f over all %d eras vs %.4f after dropping them) - the leakage premium."
                   % (inf["n_dropped"], inf["inflation"], inf["all_mean"], inf["n_eras"], inf["dropped_mean"]))
    return _finding(
        claim_id, "purge-gap", "blocker", "authoritative",
        "era-embargo leakage: validation starts at era %d but training ends at era %d - a gap of %d, "
        "and this target needs %d purged eras (%s). The leading validation eras' forward target windows "
        "overlap the training window, so the metric is inflated by look-ahead.%s"
        % (min_val, max_train, gap, required,
           "declared purge_eras=%s" % emb.get("purge_eras") if emb.get("purge_eras") is not None
           else "ceil(%s-day horizon / 5) + %d-era embargo buffer"
                % (emb.get("horizon_days", 20), required - int(math.ceil(float(emb.get("horizon_days", 20)) / 5.0))),
           inf_txt),
        "purge the validation set so min_val_era - max_train_era > %d (drop the first %d validation eras "
        "after your last training era), then recompute the headline" % (required, required - gap + 1))


def check_inflation_standalone(contract, base, claim_id="c1"):
    """Detection B standalone (no declared train range to run the A gate): a MATERIAL leading-era CORR
    inflation is a SOFT caveat - evidence the embargo may be missing, but not a deterministic proof."""
    emb = _embargo(contract)
    if not emb or emb.get("train"):  # A handles the case where train is declared
        return None
    required = _required_purge(emb)
    inf = _inflation(contract, base, emb, required)
    if not inf or inf["inflation"] != inf["inflation"]:
        return None
    # material = the leading eras lift the headline by both an absolute and a relative margin (conservative,
    # so noise on a near-zero CORR doesn't fire).
    mag, base_mean = inf["inflation"], abs(inf["all_mean"])
    if not (mag > 0 and mag >= 0.0025 and mag >= 0.25 * base_mean):
        return None
    return _finding(
        claim_id, "leading-inflation", "minor", "soft",
        "the first %d validation eras lift the headline CORR by %+.4f (%.4f over all %d eras vs %.4f "
        "without them). If those eras were not purged, the forward target overlaps training and the "
        "headline is inflated - but with no declared training-era range this cannot be adjudicated as a "
        "hard gate." % (inf["n_dropped"], mag, inf["all_mean"], inf["n_eras"], inf["dropped_mean"]),
        "declare embargo.train (the training era range) so the purge gap can be checked deterministically, "
        "or confirm the validation set is purged of the first %d eras after the last training era"
        % inf["n_dropped"])


def run_checks(contract, base, claim_id="c1", claim_text=None):
    """Era-embargo findings. SILENT unless an `embargo` block is declared. Fail-soft: any check that
    errors is skipped (never crashes the verify)."""
    out = []
    for fn in (check_era_gap, check_inflation_standalone):
        try:
            f = fn(contract, base, claim_id)
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError, IndexError):
            f = None
        if f:
            out.append(f)
    return out


def _applicable(contract):
    return bool(_embargo(contract))


def family_status(contract, findings):
    if not _applicable(contract):
        return "not-applicable"
    return "flagged" if any(f.get("dimension") == "era-embargo" and f.get("embargo_kind")
                            for f in findings) else "checked"


def _asserts_oos(claim_text):
    return bool(isinstance(claim_text, str) and _OOS_RE.search(claim_text))


def apply_validity(claims, findings, contract, claim_text, base=None):
    """Promote the headline per the era-embargo findings + claim scope. Conservative: only a REPRODUCED
    number is promoted, and only DOWN. An authoritative purge-gap finding under a validation/OOS/leaderboard
    claim -> INVALIDATED("era-embargo"); the same finding next to a bare reproduced number, or a soft
    leading-inflation finding -> CAVEAT."""
    fam = [f for f in findings if f.get("dimension") == "era-embargo" and f.get("embargo_kind")]
    if not fam or not claims:
        return
    head = next((c for c in claims if c.get("headline")), claims[0])
    if head.get("verdict") not in (V.CONFIRMED, V.CAVEATS):
        return
    vi = head.get("verdict_inputs") or {}
    auth = [f for f in fam if f.get("validity_class") == "authoritative"]
    if auth and _asserts_oos(claim_text):
        for f in auth:
            f["claim_id"] = head["id"]
        vi["validity_invalidated"] = True
        vi["oos_claim_asserted"] = True
        head["driving_dimension"] = "era-embargo"
    else:
        # authoritative finding but the claim doesn't assert the scope it breaks -> soft; or a soft finding.
        for f in fam:
            if f.get("validity_class") == "authoritative":
                f["severity"] = "minor"
        vi["soft_validity_caveat"] = True
    head["verdict_inputs"] = vi
    head["verdict"] = V.verdict(vi)
    head["headline_confidence"] = V.confidence(vi, head["verdict"])
