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
INVALIDATED = "INVALIDATED"   # the number reproduces, but the result is invalid (gap-free; see _decide)
INCONCLUSIVE = "INCONCLUSIVE"
VERDICTS = (CONFIRMED, CAVEATS, REFUTED, INVALIDATED, INCONCLUSIVE)

# the verified-isolation gate, defined ONCE in calma.tiers (CANONICAL-DECISIONS §3 names this symbol).
import tiers as _tiers  # noqa: E402 - sibling leaf module (imports nothing)
VERIFIED_TIERS = _tiers.VERIFIED_TIERS

# Fail-closed verdict classification. `clean` is an ALLOWLIST: only these pass the gate. Any other
# value - including an unknown/future verdict - is treated as NON-clean, so a switch-site that forgets
# to handle a new verdict degrades to over-cautious (exit 1, no clean badge), never to a false-confirm.
CLEAN_VERDICTS = (CONFIRMED, CAVEATS)
# The authoritative "the catch worked" outcomes. MIXED is a repo-level rollup string (not a claim enum),
# so it is listed as a literal here.
CATCH_VERDICTS = (REFUTED, "MIXED", INVALIDATED)


def is_clean(repo_verdict):
    """True iff `repo_verdict` is an explicitly-clean outcome. Allowlist by design (fail-closed)."""
    return repo_verdict in CLEAN_VERDICTS

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
    "isolation_tier": "none",     # vm | container | tier0 | seatbelt-verified | bwrap-verified | e2b-firecracker[ (self-hosted)] | host-not-isolated | none
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
    "outputs_unstable": False,  # two identical re-executions produced different artifacts (FLAKY)
    "no_claim_reproduced": False,  # no claimed number was given, but the run re-executed cleanly and
                                   # the metric recomputed from raw outputs (scope=reproduction)
    # WS-validity (leakage/overfitting findings rail). Set by the validity detectors via
    # _assemble_ledger, after which the claim verdict is re-derived. All conservative-default False, so
    # a ledger without them re-derives identically (back-compat). REFUTED stays strictly gap-gated;
    # these only ever DEGRADE a would-be-CONFIRMED toward INVALIDATED / INCONCLUSIVE / CAVEATS.
    "validity_invalidated": False,   # authoritative: the number reproduces but the result is invalid
    "oos_claim_asserted": False,     # the claim asserts held-out / out-of-sample (gates INVALIDATED)
    "validity_unresolved": False,    # a validity concern whose adjudication needs an undeclared scope
    "soft_validity_caveat": False,   # a heuristic / soft validity concern -> CAVEAT (never blocks)
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


def _validity_override(vi):
    """A number that reproduces but that a validity detector (leakage / overfitting) flagged. Returns
    (label, reason) or None. CONSERVATIVE-ONLY: it can degrade a would-be CONFIRMED/CAVEAT to
    INVALIDATED or INCONCLUSIVE, never the other way - and it is consulted ONLY on the within-budget
    (number-reproduces) paths, so it can never turn an over-budget gap into anything but the gap-gated
    REFUTED/INCONCLUSIVE decided above. INVALIDATED additionally requires an out-of-sample claim
    assertion (the scope-guard): contamination on an in-sample / undeclared-scope claim never gets here
    (it is routed to soft_validity_caveat / validity_unresolved by the detector)."""
    if vi["validity_invalidated"] and vi["oos_claim_asserted"]:
        return INVALIDATED, ("the number reproduces, but the held-out result is invalid - "
                             "authoritative contamination on an out-of-sample claim")
    if vi["validity_unresolved"]:
        return INCONCLUSIVE, ("the number reproduces, but a validity concern cannot be adjudicated as "
                              "claimed (declare the scope - see fix)")
    return None


def _decide(vi):
    ec = tuple(vi["exit_codes"] or ())

    # G1 - resource kill / refused isolation: NEVER a verdict.
    if vi["killed"] or REFUSED_NO_ISOLATION in ec or KILL_INCONCLUSIVE in ec:
        return INCONCLUSIVE, "execution was killed or isolation was refused"
    # G1b - the re-execution itself failed (entrypoint/compile exited non-zero): the result was NOT
    # reproduced, so no numeric comparison is trustworthy - stale on-disk artifacts must never CONFIRM.
    if any(c != 0 for c in ec):
        return INCONCLUSIVE, ("the re-execution exited non-zero (%s) - the result was not reproduced; "
                              "recompute would read stale artifacts" % ",".join(str(c) for c in ec if c != 0))
    # G1c - FLAKY: two identical re-executions produced different artifacts. The result does not
    # reproduce, so neither run's numbers can confirm or refute anything.
    if vi["outputs_unstable"]:
        return INCONCLUSIVE, ("outputs differ across identical re-runs (FLAKY) - "
                              "the result is not reproducible as-is")
    # G2 - degenerate recompute.
    if vi["recompute_degenerate"]:
        return INCONCLUSIVE, "NaN/Inf/degenerate recompute - data-cleaning policy undetermined"
    # G3 - untrusted code/deps with no verified isolation tier: static-only.
    if vi["untrusted"] and not vi["container_present"]:
        return INCONCLUSIVE, "untrusted code/deps with no verified isolation tier"

    gap, budg = vi["gap"], vi["effective_budget"]
    if gap is None or budg is None:
        # No-claim mode ("calma verify <dir>"): there is no number to diff, but the run re-executed
        # cleanly (G1/G1b/G1c passed) and the metric recomputed from raw outputs. That is exactly the
        # README promise - report reproduction honestly instead of demanding a claim.
        if vi["no_claim_reproduced"]:
            reasons = _caveat_reasons(vi)
            if reasons:
                return CAVEATS, "reproduces (no claim was given to check): " + "; ".join(reasons)
            return CONFIRMED, ("no claim was given - the result re-executes and the number "
                               "recomputes from the raw outputs (scope=reproduction)")
        return INCONCLUSIVE, "no recomputed numeric to compare against the claim"

    gap = abs(gap)
    budg = max(budg, 0.0)
    # defense in depth: a non-finite gap/budget is not comparable. Unreachable via compare() (a
    # NaN/Inf recompute sets recompute_degenerate -> G2 above, and compare only sets gap when the
    # recompute is finite), but verdict() is a public TOTAL function, so close the hole here too.
    if gap != gap or budg != budg or gap == float("inf") or budg == float("inf"):
        return INCONCLUSIVE, "non-finite gap or budget - the claim is not numerically comparable"
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
        # the number reproduces - a validity detector may still DEGRADE it (never inflate).
        ov = _validity_override(vi)
        if ov:
            return ov
        if not vi["sign_agrees"]:
            return CAVEATS, "recompute agrees in magnitude but sign/direction differs"
        reasons = _caveat_reasons(vi)
        if vi["soft_validity_caveat"]:
            reasons = reasons + ["a validity heuristic flagged the result (see findings)"]
        if reasons:
            return CAVEATS, "holds but narrows: " + "; ".join(reasons)
        return CONFIRMED, "recomputed value matches the claim within the calibrated budget"

    # Ambiguous zone: budget < gap <= budget * margin (close, but outside the tight budget).
    ov = _validity_override(vi)
    if ov:
        return ov
    return CAVEATS, "recompute is near the claim but outside the tight budget (within the fraud-margin)"


def confidence(verdict_inputs, label):
    """Deterministic 0..1 confidence in the LABEL, derived from the same vector verdict() decides on
    (never a model, never a constant). Components: verified isolation, determinism strength,
    independent binding, statistical distinguishability. INCONCLUSIVE has no confidence (returns 0.0:
    the honest statement is 'not enough to decide', not a score)."""
    vi = _norm(verdict_inputs)
    if label == INCONCLUSIVE:
        return 0.0
    score = 0.50
    if vi["isolation_tier"] in VERIFIED_TIERS:
        score += 0.15
    dm = vi["determinism_mode"]
    if dm == "controlled-to-bit":
        score += 0.20
    elif dm == "measured-band" and vi["band_coverage_ok"] and vi["sufficient_k"]:
        score += 0.10
    if vi["binding_status"] == "independently-bound":
        score += 0.10
    elif vi["binding_status"] == "plausibly-bound":
        score += 0.05
    if label == REFUTED and vi["claim_outside_ci"]:
        score += 0.03
    return round(min(score, 0.98), 2)


if __name__ == "__main__":
    import json, sys
    print(json.dumps({"verdict": verdict(json.load(sys.stdin))}))
