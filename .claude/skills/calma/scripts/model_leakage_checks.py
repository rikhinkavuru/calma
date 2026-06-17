"""calma.model_leakage_checks - V4: ML-process leakage beyond row/id/temporal (that is leakage_checks).
On the findings rail, called from calma._assemble_ledger like the other validity families. Pure stdlib.

Two ML-process leakages the row/id/temporal family does not catch:
  (1) FEATURIZATION-TIME leakage (dimension "model-leakage"): a transform (scaler / encoder / target-
      encoding / imputer / feature-selector) fit on the UNION of train+test, so test statistics leak
      into training. Signalled by a `pipeline` block declaring fit_on in {train+test, all, full, both}.
      The bias is bounded by the scoped re-run gap: refitting the transform on train ONLY should not
      LOSE performance - if the reported (leaked) metric materially exceeds the train-only-fit metric,
      the improvement was leakage.
  (2) VALIDATION REUSE / SELECTION-ON-TEST (dimension "model-leakage"): K configs (hyperparameters /
      architectures) all tuned and the best SELECTED on the SAME held-out/test set. The held-out set is
      reused K times, so the selected score is optimistically biased - the V2 multiple-testing
      correction applies to the selected config's reported statistic (reused here, when a t-stat is
      declared). Signalled by a `sweep`/`selection` block declaring configs:K on a held-out set.

Scope (mirrors leakage_checks): INVALIDATED under a "no leakage / held-out / out-of-sample" claim that
the pipeline/sweep violates; the same finding next to a bare reproduced number -> a CAVEAT. ABSTAINS
without a `pipeline`/`sweep` block (never guesses). REFUTED is never manufactured here.

Library: run_checks(contract, base, claim_id, claim_text) -> [finding,...];
apply_validity(claims, findings, contract, claim_text, base=None); family_status(contract, findings).
"""
import re

import data_snooping_checks as DSC
import verdict as V

_LEAKY_FIT = {"train+test", "train_test", "traintest", "all", "full", "both", "everything",
              "train+val+test", "entire", "whole"}
_MATERIAL = 0.01  # a leaked-vs-train-only metric gap above this (in metric units) is material

_CLEAN_RE = re.compile(
    r"no (data )?leakage|leak.?free|leakage.?free|held.?out|out.?of.?sample|\boos\b|"
    r"properly (held|split|separated)|clean (split|holdout|hold.?out|test|eval)|no (train.?test )?"
    r"contamination|test set (never|not|wasn't|was not) (seen|used|touched)|strict (holdout|hold.?out|"
    r"split)|never (saw|seen|trained on) (the )?test|generaliz", re.I)


def _pipeline(contract):
    p = contract.get("pipeline")
    return p if isinstance(p, dict) else None


def _sweep(contract):
    s = contract.get("sweep") or contract.get("selection")
    return s if isinstance(s, dict) else None


def _finding(claim_id, kind, locator, unblock):
    return {
        "id": "f-%s-modelleak-%s" % (claim_id, kind), "claim_id": claim_id, "dimension": "model-leakage",
        "severity": "blocker", "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": locator, "unblock": unblock,
        "reverify": {"kind": "requires-reexecution", "source": "pipeline",
                     "expected": "every transform is fit on train only; held-out is used once, not for selection"},
        "validity_class": "authoritative", "modelleak_kind": kind,
    }


def check_featurization(contract, base, claim_id="c1"):
    """A transform fit on train+test (its statistics include test rows) - featurization-time leakage."""
    p = _pipeline(contract)
    if not p:
        return None
    fit_on = str(p.get("fit_on", "")).strip().lower().replace(" ", "")
    if fit_on not in _LEAKY_FIT:
        return None
    transform = p.get("transform") or "a transform"
    leaked, train_only = p.get("leaked_metric"), p.get("train_only_metric")
    gap_txt = ""
    if isinstance(leaked, (int, float)) and isinstance(train_only, (int, float)):
        gap = leaked - train_only
        if not (gap > _MATERIAL):
            return None  # refitting on train-only does NOT improve -> the leak was not load-bearing
        gap_txt = (" - refitting it on train ONLY drops the metric from %.4f to %.4f (a %.4f "
                   "improvement that was leakage)" % (leaked, train_only, gap))
    return _finding(
        claim_id, "featurization",
        "featurization leakage: %s was fit on '%s' (statistics computed over the test rows leak into "
        "training)%s" % (transform, p.get("fit_on"), gap_txt),
        "fit every transform (scaler / encoder / imputer / feature selector) on the TRAIN split only, "
        "then apply it to test; recompute the metric")


def check_selection(contract, base, claim_id="c1"):
    """K configs selected on the SAME held-out/test set - validation reuse / selection-on-test."""
    s = _sweep(contract)
    if not s:
        return None
    k = s.get("configs") or s.get("k") or s.get("n_configs")
    if not (isinstance(k, (int, float)) and k >= 2):
        return None
    k = int(k)
    held = s.get("held_out") or s.get("on") or "the held-out set"
    extra = ""
    t = s.get("t_stat")
    if isinstance(t, (int, float)):
        adj = DSC.haircut(float(t), k)["methods"]["holm"]["t_adj"]
        extra = (" - applying the multiple-testing correction over %d configs haircuts the selected "
                 "t=%.2f to t=%.2f" % (k, float(t), adj))
    return _finding(
        claim_id, "selection",
        "validation reuse / selection-on-test: the reported config is the best of %d tuned on '%s' - the "
        "held-out set was reused %d times for selection, so its score is optimistically biased%s"
        % (k, held, k, extra),
        "select hyperparameters/architecture on a SEPARATE validation split and report the metric on a "
        "test set used exactly once (nested CV), then recompute")


def run_checks(contract, base, claim_id="c1", claim_text=None):
    """Model-process leakage findings. SILENT unless a `pipeline` or `sweep`/`selection` block is
    declared. Fail-soft: any check that errors is skipped."""
    out = []
    for fn in (check_featurization, check_selection):
        try:
            f = fn(contract, base, claim_id)
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
            f = None
        if f:
            out.append(f)
    return out


def _applicable(contract):
    return bool(_pipeline(contract) or _sweep(contract))


def family_status(contract, findings):
    if not _applicable(contract):
        return "not-applicable"
    return "flagged" if any(f.get("dimension") == "model-leakage" and f.get("modelleak_kind")
                            for f in findings) else "checked"


def _asserts_clean(claim_text):
    return bool(isinstance(claim_text, str) and _CLEAN_RE.search(claim_text))


def apply_validity(claims, findings, contract, claim_text, base=None):
    """Promote the headline per the model-leakage findings + claim scope. Conservative: only a REPRODUCED
    number is promoted, and only DOWN. Featurization/selection leakage under a "no leakage / held-out"
    claim -> INVALIDATED("model-leakage"); the same finding next to a bare reproduced number -> CAVEAT."""
    ml = [f for f in findings if f.get("dimension") == "model-leakage" and f.get("modelleak_kind")]
    if not ml or not claims:
        return
    head = next((c for c in claims if c.get("headline")), claims[0])
    if head.get("verdict") not in (V.CONFIRMED, V.CAVEATS):
        return
    vi = head.get("verdict_inputs") or {}
    if _asserts_clean(claim_text):
        for f in ml:
            f["claim_id"] = head["id"]
        vi["validity_invalidated"] = True
        vi["oos_claim_asserted"] = True
        head["driving_dimension"] = "model-leakage"
    else:
        for f in ml:
            f["severity"] = "minor"
        vi["soft_validity_caveat"] = True
    head["verdict_inputs"] = vi
    head["verdict"] = V.verdict(vi)
    head["headline_confidence"] = V.confidence(vi, head["verdict"])
