"""calma.verdict - the single deterministic verdict() pure function.

THE central honesty invariant: no statistic and no verdict label is ever computed by a model.
verdict() is a TOTAL pure function over the full verdict_inputs vector. It is imported by BOTH
compare.py (to EMIT the label) and ledger.py (to RE-DERIVE and byte-check it). There is exactly
one implementation of the labelling logic in the whole codebase: this one.

Enum:  CONFIRMED | CONFIRMED-WITH-CAVEATS | REFUTED | INCONCLUSIVE

Design rule: defaults are CONSERVATIVE. Missing/unknown information degrades toward INCONCLUSIVE,
never toward an accidental REFUTED or CONFIRMED. A REFUTED is only ever reached when every guard
below is cleared.
"""
from __future__ import annotations

CONFIRMED = "CONFIRMED"
CAVEATS = "CONFIRMED-WITH-CAVEATS"
REFUTED = "REFUTED"
INCONCLUSIVE = "INCONCLUSIVE"
VERDICTS = (CONFIRMED, CAVEATS, REFUTED, INCONCLUSIVE)

# exit-code table (references/script-interfaces.md):
#   0 done | 1 findings | 2 invalid | 3 refused-no-isolation | 4 kill->INCONCLUSIVE
REFUSED_NO_ISOLATION = 3
KILL_INCONCLUSIVE = 4

# Conservative defaults. verdict_inputs is JSON-serialisable (persisted in the ledger as the exact
# argument vector so _validate() can re-derive the enum byte-for-byte).
DEFAULTS = {
    "gap": None,                  # |recomputed - claimed| in metric units; None => no numeric diff
    "effective_budget": None,     # recompute-agreement budget (>=0); None => not computable
    "margin": 1.0,                # fraud-grade multiplier M (>=1); >1 demanded when no container
    "claim_outside_ci": False,    # claim statistically distinguishable from the recompute's CI
    "sign_agrees": True,          # recompute agrees in sign/direction with the claim
    "band_coverage_ok": False,    # the determinism band met its (coverage, confidence) target
    "band_confidence": 0.0,
    "cross_stack_attributable": False,  # gap explained by BLAS/stack reduction-order, not a defn error
    "flip_distance": None,        # conclusion-flip distance (one-sided parameter CI); None => n/a
    "binding_status": "author-asserted",  # independently-bound | plausibly-bound | author-asserted
    "isolation_tier": "none",     # vm | container | tier0 | seatbelt-verified | host-not-isolated | none
    "container_present": False,   # ANY verified isolation tier incl. Tier-0 (NOT Docker specifically)
    "untrusted": False,           # untrusted third-party code/deps
    "exit_codes": (0,),           # per-phase exit codes
    "killed": False,              # resource kill / timeout / OOM / sandbox denial
    "determinism_mode": "uncontrolled",  # controlled-to-bit | measured-band | uncontrolled
    "sufficient_k": False,        # K met the order-statistic (coverage, confidence) requirement
    "unbounded_op_present": False,  # an unbounded-magnitude nondeterministic op with no forward bound
    "nondeterministic_ops": (),
    "path_dependent": False,      # argmax/sort/threshold/near-tie metric (max-drawdown, best-of-two)
    "m2_calibrated": False,       # the M2 band-coverage lock-gate has passed on this host
    "recompute_degenerate": False,  # NaN/Inf/sentinel/degenerate recompute
    "claim_confirmed_target": False,  # the claim number+metric+units are user-confirmed (REFUTED req.)
    "fraud_multiple_met": False,  # gap exceeds the band by the calibrated fraud-multiple M (decoupled path)
    "convention_capped": False,  # gap explainable by a declared legitimate convention -> cap at CAVEAT
}


def _norm(vi):
    d = dict(DEFAULTS)
    if vi:
        d.update(vi)
    return d


def verdict(verdict_inputs):
    """Total pure function: verdict_inputs (dict) -> one of VERDICTS."""
    return _decide(_norm(verdict_inputs))[0]


def verdict_with_reason(verdict_inputs):
    """Same decision, plus the single most-limiting reason (for the line-2 render)."""
    return _decide(_norm(verdict_inputs))


def _refute_blocked(vi):
    """Return (blocked: bool, why: str). These are the FALSE-REFUTED guards: any True forces a
    non-REFUTED outcome (the caller turns an over-budget gap into INCONCLUSIVE, never CONFIRMED)."""
    if vi["binding_status"] != "independently-bound":
        return True, "input binding is %s, not independently-bound" % vi["binding_status"]
    if vi["path_dependent"]:
        return True, "metric is path-dependent (near-tie / argmax / sort)"
    if vi["unbounded_op_present"]:
        return True, "an unbounded-magnitude nondeterministic op is present with no forward bound"

    dm = vi["determinism_mode"]
    if dm == "controlled-to-bit":
        determinism_ok = True            # structural proof; band ~= 0
    elif dm == "measured-band":
        determinism_ok = vi["band_coverage_ok"] and vi["sufficient_k"]
    else:                                # uncontrolled
        determinism_ok = False
    if not determinism_ok:
        # The decoupled path: a non-controlled band can still REFUTE iff the gap exceeds it by the
        # calibrated fraud-multiple AND no unbounded op is in play.
        if not (vi["fraud_multiple_met"] and not vi["unbounded_op_present"]):
            return True, "determinism is %s without sufficient K / band coverage" % dm

    # The M2 gate: a REFUTED on a non-controlled (measured/uncontrolled) BAND requires M2 band-
    # calibration, REGARDLESS of isolation tier - the band's coverage is what is unvalidated, and a
    # container does not make an uncalibrated band trustworthy. CONTROLLED-TO-BIT is exempt (no band).
    if dm != "controlled-to-bit" and not vi["m2_calibrated"]:
        return True, "REFUTED on a non-controlled band requires M2 band-calibration"
    return False, ""


def _caveat_reasons(vi):
    out = []
    if vi["binding_status"] == "plausibly-bound":
        out.append("input only plausibly-bound")
    elif vi["binding_status"] == "author-asserted":
        out.append("input author-asserted, not independently bound")
    if vi["cross_stack_attributable"]:
        out.append("cross-stack-attributable numeric difference")
    if vi["determinism_mode"] == "uncontrolled":
        out.append("determinism uncontrolled - same result not guaranteed cross-run")
    if vi["isolation_tier"] == "host-not-isolated":
        out.append("host tier not isolated")
    return out


def _decide(vi):
    ec = tuple(vi["exit_codes"] or ())

    # G1 - resource kill / refused isolation: NEVER a verdict.
    if vi["killed"] or REFUSED_NO_ISOLATION in ec or KILL_INCONCLUSIVE in ec:
        return INCONCLUSIVE, "execution was killed or isolation was refused"
    # G2 - degenerate recompute.
    if vi["recompute_degenerate"]:
        return INCONCLUSIVE, "NaN/Inf/degenerate recompute - data-cleaning policy undetermined"
    # G3 - untrusted code/deps with no verified isolation tier: static-only.
    if vi["untrusted"] and not vi["container_present"]:
        return INCONCLUSIVE, "untrusted code/deps with no verified isolation tier"

    gap, budg = vi["gap"], vi["effective_budget"]
    if gap is None or budg is None:
        return INCONCLUSIVE, "no recomputed numeric to compare against the claim"

    gap = abs(gap)
    budg = max(budg, 0.0)
    margin = max(vi["margin"], 1.0)
    exceeds = gap > budg * margin
    within = gap <= budg

    if exceeds:
        # A gap explained by cross-stack reduction order is a CAVEAT, never a REFUTED.
        if vi["cross_stack_attributable"]:
            return CAVEATS, "gap attributable to cross-stack numeric differences, not a definition error"
        # A gap explainable by a declared legitimate (in-set) convention is a CAVEAT, never a REFUTED.
        if vi["convention_capped"]:
            return CAVEATS, "gap is within the range of a declared legitimate convention; recompute under it to resolve"
        blocked, why = _refute_blocked(vi)
        if blocked:
            return INCONCLUSIVE, "recompute differs from the claim but REFUTED is blocked: " + why
        if not vi["claim_outside_ci"]:
            return INCONCLUSIVE, "gap exceeds budget but claim and recompute are not statistically distinguishable"
        if not vi["claim_confirmed_target"]:
            return INCONCLUSIVE, "recompute lands in REFUTED territory but the claim target is unconfirmed"
        return REFUTED, "recomputed value differs from the claim beyond the calibrated budget and is statistically distinguishable"

    if within:
        if not vi["sign_agrees"]:
            return CAVEATS, "recompute agrees in magnitude but sign/direction differs"
        reasons = _caveat_reasons(vi)
        if reasons:
            return CAVEATS, "holds but narrows: " + "; ".join(reasons)
        return CONFIRMED, "recomputed value matches the claim within the calibrated budget"

    # Ambiguous zone: budget < gap <= budget * margin (close, but outside the tight budget).
    return CAVEATS, "recompute is near the claim but outside the tight budget (within the fraud-margin)"


if __name__ == "__main__":
    import json, sys
    print(json.dumps({"verdict": verdict(json.load(sys.stdin))}))
