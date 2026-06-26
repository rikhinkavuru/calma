"""calma.verdict - the single deterministic verdict() pure function.

THE central honesty invariant: no statistic and no verdict label is ever computed by a model.
verdict() is a TOTAL pure function over the full verdict_inputs vector. It is imported by BOTH
compare.py (to EMIT the label) and ledger.py (to RE-DERIVE and byte-check it). There is exactly
one implementation of the labelling logic in the whole codebase: this one.

Enum:  CONFIRMED | CONFIRMED-WITH-CAVEATS | REFUTED | INVALIDATED | FLAG_FOR_DECLARATION | INCONCLUSIVE

Design rule: defaults are CONSERVATIVE. Missing/unknown information degrades toward INCONCLUSIVE,
never toward an accidental REFUTED or CONFIRMED. A REFUTED is only ever reached when every guard
below is cleared.
"""
from __future__ import annotations

CONFIRMED = "CONFIRMED"
CAVEATS = "CONFIRMED-WITH-CAVEATS"
REFUTED = "REFUTED"
INVALIDATED = "INVALIDATED"   # the number reproduces, but the result is invalid (gap-free; see _decide)
# the number reproduces and nothing in the declared scope refutes it, but the ARTIFACTS carry positive,
# multi-signal structure that would make the headline invalid if it is what it looks like (an inferred
# train/test split with real row-overlap; a strong regime break; an undeclared trials matrix) and the
# producer declared nothing that lets us confirm or rule it out. Louder than a caveat, weaker than
# INVALIDATED, and RESOLVABLE in one move (declare the block). NOT an assertion of wrongdoing - it is a
# demand for declaration. It never flips to INVALIDATED on its own (that stays declaration-gated).
FLAG_FOR_DECLARATION = "FLAG_FOR_DECLARATION"
INCONCLUSIVE = "INCONCLUSIVE"
VERDICTS = (CONFIRMED, CAVEATS, REFUTED, INVALIDATED, FLAG_FOR_DECLARATION, INCONCLUSIVE)

# the verified-isolation gate, defined ONCE in calma.tiers (CANONICAL-DECISIONS §3 names this symbol).
import tiers as _tiers  # noqa: E402 - sibling leaf module (imports nothing)
VERIFIED_TIERS = _tiers.VERIFIED_TIERS

# Fail-closed verdict classification. `clean` is an ALLOWLIST: only these pass the gate. Any other
# value - including an unknown/future verdict - is treated as NON-clean, so a switch-site that forgets
# to handle a new verdict degrades to over-cautious (exit 1, no clean badge), never to a false-confirm.
CLEAN_VERDICTS = (CONFIRMED, CAVEATS)
# The authoritative "the catch worked" outcomes. MIXED is a repo-level rollup string (not a claim enum),
# so it is listed as a literal here. FLAG_FOR_DECLARATION is a catch (it blocks the gate / IC auto-
# approval and carries a replay command) even though it is resolvable, not an assertion of wrongdoing.
# Catch-loudness rank (CANONICAL §3): REFUTED >= INVALIDATED > FLAG_FOR_DECLARATION > MIXED > CAVEATS.
CATCH_VERDICTS = (REFUTED, "MIXED", INVALIDATED, FLAG_FOR_DECLARATION)

# DEFINITE verdicts: a settled outcome that is safe to cache / publish (clean OR a catch). INCONCLUSIVE
# is deliberately EXCLUDED - it may have been environmental (a missing dep, a timeout), so it always
# re-runs and is never cached. Single source for the cache guards that used to hand-write this tuple.
DEFINITE_VERDICTS = CLEAN_VERDICTS + CATCH_VERDICTS


def is_clean(repo_verdict):
    """True iff `repo_verdict` is an explicitly-clean outcome. Allowlist by design (fail-closed)."""
    return repo_verdict in CLEAN_VERDICTS

# exit-code table (references/script-interfaces.md):
#   0 done | 1 findings | 2 invalid | 3 refused-no-isolation | 4 kill->INCONCLUSIVE
REFUSED_NO_ISOLATION = 3
KILL_INCONCLUSIVE = 4

# ── WS3: the 3-outcome user-facing roll-up ───────────────────────────────────────────────────────
# The six internal verdicts above remain the SOURCE OF TRUTH: persisted in the ledger, re-derived,
# and byte-checked. outcome() is a PURE PRESENTATION roll-up over the (verdict, effective exit code)
# pair. It adds NOTHING to the decision, changes NO exit code, and discards NO nuance - the full
# verdict + its single-most-limiting reason stay in the ledger, in --why, and in --json. The roll-up
# is published here, deterministically, so the terminal headline can read in <2s without exposing the
# six-way internal vocabulary by default.
#
# It keys on the exit code (not the verdict alone) so a green "Confirmed" can NEVER print over a
# non-zero exit - a clean-verdict run that still carries an open blocking finding (exit 1) reads as
# "Caught", never as a green pass painted over a real finding (the gitsafehub "incomplete is not safe"
# rule, applied to "never paint Confirmed over a blocking finding"). Total + fail-closed: an unknown
# verdict or exit degrades to CAN'T-TELL, never to CONFIRMED.
CONFIRMED_OUTCOME = "Confirmed"
CAUGHT_OUTCOME = "Caught"
CANT_TELL_OUTCOME = "Can't tell"
OUTCOMES = (CONFIRMED_OUTCOME, CAUGHT_OUTCOME, CANT_TELL_OUTCOME)

# outcome -> (ascii glyph, unicode glyph). The WORD is ALWAYS printed next to the glyph, so the output
# is unambiguous under NO_COLOR, on a colour-blind terminal, and through a pipe (clig.dev).
_OUTCOME_GLYPH = {
    CONFIRMED_OUTCOME: ("v", "✓"),   # ✓
    CAUGHT_OUTCOME:    ("x", "✗"),   # ✗
    CANT_TELL_OUTCOME: ("?", "?"),
}
# outcome -> ANSI colour (green / red / dim-yellow). Caught is rendered amber for the soft sub-case by
# the caller (a FLAG_FOR_DECLARATION is a resolvable demand, not a hard break).
_OUTCOME_ANSI = {CONFIRMED_OUTCOME: "32", CAUGHT_OUTCOME: "31", CANT_TELL_OUTCOME: "33"}


def outcome(repo_verdict, exit_code):
    """Map an internal verdict + its effective process exit code -> one of the three user-facing
    OUTCOMES. Deterministic, total, fail-closed. Never influences the exit code (display only).

    Keyed on the VERDICT first, then the exit code - because a plain INCONCLUSIVE is "not clean" and so
    exits 1 (same code as a REFUTED), yet it must read as CAN'T-TELL, never CAUGHT. The exit code is
    only consulted to catch the one case the verdict alone misses: a clean CONFIRMED / CAVEATS that
    still failed the gate on an OPEN blocking finding (exit 1) - that reads CAUGHT, never a green pass."""
    if repo_verdict == INCONCLUSIVE or exit_code in (REFUSED_NO_ISOLATION, KILL_INCONCLUSIVE, 2):
        return CANT_TELL_OUTCOME           # can't-confirm / refused / killed / invalid ledger
    if repo_verdict in CATCH_VERDICTS or exit_code == 1:
        return CAUGHT_OUTCOME              # a catch, or a blocking finding on an otherwise-clean verdict
    if repo_verdict in CLEAN_VERDICTS and exit_code == 0:
        return CONFIRMED_OUTCOME
    return CANT_TELL_OUTCOME               # unknown verdict/exit -> fail-closed (never CONFIRMED)


def outcome_glyph(oc, unicode_ok=True):
    """The glyph for an outcome; ascii fallback when the terminal can't render unicode."""
    return _OUTCOME_GLYPH.get(oc, ("·", "·"))[1 if unicode_ok else 0]


def outcome_ansi(oc):
    """The ANSI colour code for an outcome (caller wraps; empty string if unknown)."""
    return _OUTCOME_ANSI.get(oc, "")

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
    "flag_for_declaration": False,   # inferred invalidating structure (real overlap/regime/trials shape)
                                     # on an UNDECLARED scope -> FLAG_FOR_DECLARATION. Set by the M-8b.2
                                     # infer_validity detectors on strong multi-signal evidence; NEVER
                                     # co-set with validity_invalidated (the verdict-flip stays
                                     # declaration-gated). Conservative: only ever degrades a would-be
                                     # CONFIRMED/CAVEAT - reached solely on the within-budget paths.
    "inferred_structure": None,      # which block to declare (e.g. "train/test split", "windows",
                                     # "trials") - carried into the FLAG explanation string.
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
    # FLAG_FOR_DECLARATION ranks BELOW INVALIDATED, ABOVE the neutral validity_unresolved (CANONICAL §3).
    # Reached only when the M-8b.2 detectors found positive, multi-signal invalidating structure on an
    # undeclared scope. It is a louder, resolvable cousin of validity_unresolved: a DEMAND to declare the
    # block (then the authoritative family runs), never a guessed verdict flip. Defense-in-depth: it can
    # only DEGRADE here (consulted on the reproduces / ambiguous paths), so a producer who declares
    # nothing while the data screams "leak" gets an IC-visible flag instead of sailing through on a caveat.
    if vi["flag_for_declaration"]:
        which = vi.get("inferred_structure") or "the undeclared"
        return FLAG_FOR_DECLARATION, (
            "the number reproduces, but the artifacts carry %s structure that would invalidate the "
            "headline if it is what it looks like, and nothing was declared - declare the %s block to "
            "resolve" % (which, which))
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
        # A gap of convention-scale earns the producer the benefit of the doubt over a hard REFUTED -
        # but it is NOT a clean pass. Calma did not recompute the number under the declared convention,
        # so it cannot CONFIRM it, and a producer must not be able to launder a same-magnitude overclaim
        # into a clean CONFIRMED-WITH-CAVEATS by naming an in-set convention (the legitimate
        # cross-annualization ratios span [1x,3x], so an overclaim is indistinguishable BY RATIO from a
        # real cross-convention claim). Surface it as INCONCLUSIVE (can't-confirm, not-clean): the number
        # may be right under that convention, but Calma can't verify it without recomputing under it.
        # The sound upgrade is convention-AWARE recompute (recompute under the declared convention and
        # match the specific value), which would let this CONFIRM legitimately.
        if vi["convention_capped"]:
            return INCONCLUSIVE, ("recompute differs from the claim by a declared-convention-scale factor; "
                                  "Calma did not recompute under that convention, so it can't confirm the "
                                  "number - recompute under the declared convention to resolve")
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
