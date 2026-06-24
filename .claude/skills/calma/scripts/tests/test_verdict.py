"""Unit tests for verdict.py - every enum path, incl. the non-numeric INCONCLUSIVE branches.
Pure stdlib (no pytest/numpy). Run: python3 test_verdict.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import verdict as V  # noqa: E402

_n = 0
_fail = 0


def check(inputs, expected, label):
    global _n, _fail
    _n += 1
    got = V.verdict(inputs)
    ok = got == expected
    if not ok:
        _fail += 1
        why = V.verdict_with_reason(inputs)[1]
        print("  FAIL [%s] expected %s got %s :: %s" % (label, expected, got, why))


# A baseline of a clean, fully-cleared CONFIRMED then mutate one field per case.
CLEAN = dict(
    gap=0.001, effective_budget=0.01, margin=3.0, claim_outside_ci=True, sign_agrees=True,
    band_coverage_ok=True, binding_status="independently-bound", isolation_tier="tier0",
    container_present=True, untrusted=False, exit_codes=(0,), killed=False,
    determinism_mode="controlled-to-bit", sufficient_k=True, unbounded_op_present=False,
    path_dependent=False, m2_calibrated=True, recompute_degenerate=False,
    claim_confirmed_target=True,
)


def R(**kw):
    d = dict(CLEAN)
    d.update(kw)
    return d


# ---- CONFIRMED ----
check(R(), V.CONFIRMED, "clean within budget")
check(R(gap=0.01), V.CONFIRMED, "gap exactly at budget edge")

# ---- REFUTED ----
check(R(gap=147.0), V.REFUTED, "huge gap, all guards cleared")
check(R(gap=147.0, container_present=False, determinism_mode="controlled-to-bit"),
      V.REFUTED, "controlled-to-bit REFUTES without a container (BTC-fixture path)")

# ---- REFUTED blocked -> INCONCLUSIVE ----
check(R(gap=147.0, binding_status="plausibly-bound"), V.INCONCLUSIVE, "big gap but binding not independent")
check(R(gap=147.0, path_dependent=True), V.INCONCLUSIVE, "big gap but path-dependent")
check(R(gap=147.0, claim_outside_ci=False), V.INCONCLUSIVE, "big gap but not statistically distinguishable")
check(R(gap=147.0, claim_confirmed_target=False), V.INCONCLUSIVE, "big gap but claim target unconfirmed")
check(R(gap=147.0, unbounded_op_present=True), V.INCONCLUSIVE, "big gap but unbounded nondeterministic op")
check(R(gap=147.0, determinism_mode="uncontrolled", container_present=False, fraud_multiple_met=False),
      V.INCONCLUSIVE, "uncontrolled, no container, no fraud-multiple -> blocked")
check(R(gap=147.0, determinism_mode="measured-band", container_present=False, m2_calibrated=False,
        band_coverage_ok=True, sufficient_k=True, fraud_multiple_met=False),
      V.INCONCLUSIVE, "measured-band without container disabled until M2")

# ---- decoupled fraud-multiple path: uncontrolled CAN refute with a container + fraud multiple ----
check(R(gap=147.0, determinism_mode="uncontrolled", container_present=True, fraud_multiple_met=True,
        m2_calibrated=True),
      V.REFUTED, "uncontrolled but fraud-multiple met with container -> REFUTED")

# ---- cross-stack down-rank ----
check(R(gap=147.0, cross_stack_attributable=True), V.CAVEATS, "big gap explained by cross-stack -> CAVEAT")

# ---- hard INCONCLUSIVE guards ----
check(R(killed=True), V.INCONCLUSIVE, "resource kill")
check(R(exit_codes=(0, 3)), V.INCONCLUSIVE, "refused-no-isolation exit code")
check(R(exit_codes=(0, 4)), V.INCONCLUSIVE, "kill exit code")
check(R(recompute_degenerate=True), V.INCONCLUSIVE, "degenerate recompute")
check(R(untrusted=True, container_present=False), V.INCONCLUSIVE, "untrusted, no isolation")
check(R(gap=None), V.INCONCLUSIVE, "no numeric to compare")
check(R(effective_budget=None), V.INCONCLUSIVE, "no budget computable")
check({}, V.INCONCLUSIVE, "empty inputs -> conservative INCONCLUSIVE")

# ---- CONFIRMED-WITH-CAVEATS ----
check(R(binding_status="plausibly-bound"), V.CAVEATS, "within budget but plausibly-bound")
check(R(determinism_mode="uncontrolled", sufficient_k=False), V.CAVEATS, "within budget but uncontrolled")
check(R(sign_agrees=False), V.CAVEATS, "magnitude matches but sign differs")
check(R(isolation_tier="host-not-isolated"), V.CAVEATS, "within budget but host not isolated")
check(R(gap=0.02), V.CAVEATS, "ambiguous zone: between budget and budget*margin")

# ---- INVALIDATED (validity findings rail): the number reproduces, but the result is invalid ----
# These DEGRADE a would-be CONFIRMED only; REFUTED stays strictly gap-gated.
check(R(validity_invalidated=True, oos_claim_asserted=True), V.INVALIDATED,
      "authoritative contamination on an OOS claim -> INVALIDATED")
check(R(validity_invalidated=True, oos_claim_asserted=False), V.CONFIRMED,
      "scope-guard: validity_invalidated WITHOUT an OOS assertion never manufactures INVALIDATED")
check(R(validity_unresolved=True), V.INCONCLUSIVE,
      "validity concern unadjudicable as claimed (e.g. OOS indeterminate / uncountable N) -> CAN'T-CONFIRM")
check(R(soft_validity_caveat=True), V.CAVEATS,
      "heuristic / soft validity concern -> CONFIRMED-WITH-CAVEATS (never blocks)")
check(R(gap=0.02, validity_invalidated=True, oos_claim_asserted=True), V.INVALIDATED,
      "ambiguous zone + authoritative OOS contamination -> INVALIDATED")
# REFUTED stays gap-gated: the override is consulted ONLY on the within/ambiguous (reproduces) paths.
check(R(gap=147.0, validity_invalidated=True, oos_claim_asserted=True), V.REFUTED,
      "huge gap + contamination -> REFUTED (numeric path wins; INVALIDATED never overrides a real gap)")
# INVALIDATED implies the number reproduced: a failed/killed/degenerate run still goes INCONCLUSIVE.
check(R(killed=True, validity_invalidated=True, oos_claim_asserted=True), V.INCONCLUSIVE,
      "killed run + contamination -> INCONCLUSIVE (INVALIDATED requires reproduction)")
check(R(recompute_degenerate=True, validity_invalidated=True, oos_claim_asserted=True), V.INCONCLUSIVE,
      "degenerate recompute + contamination -> INCONCLUSIVE (no valid number to call invalid)")

# ---- FLAG_FOR_DECLARATION (M-8b.1): inferred invalidating structure on an UNDECLARED scope ----
# The number reproduces and the declared scope doesn't refute it, but the artifacts carry positive,
# multi-signal structure (real overlap / strong regime break / an undeclared trials matrix). Louder than
# a caveat, weaker than INVALIDATED, resolvable by declaring the block. Conservative-only (only degrades).
check(R(flag_for_declaration=True, inferred_structure="train/test split"), V.FLAG_FOR_DECLARATION,
      "reproduces + inferred invalidating structure, nothing declared -> FLAG_FOR_DECLARATION")
check(R(gap=0.02, flag_for_declaration=True), V.FLAG_FOR_DECLARATION,
      "ambiguous zone (budget<gap<=budget*margin) + inferred structure -> FLAG_FOR_DECLARATION")
# rank: an authoritative, declared-OOS INVALIDATED outranks a mere flag
check(R(flag_for_declaration=True, validity_invalidated=True, oos_claim_asserted=True), V.INVALIDATED,
      "INVALIDATED outranks FLAG_FOR_DECLARATION (authoritative > demand-for-declaration)")
# rank: the flag is LOUDER than the neutral validity_unresolved (which displays as CAN'T-CONFIRM)
check(R(flag_for_declaration=True, validity_unresolved=True), V.FLAG_FOR_DECLARATION,
      "FLAG_FOR_DECLARATION outranks validity_unresolved (a catch > a neutral can't-confirm)")
# conservative: a real over-budget gap stays the gap-gated REFUTED; the flag never overrides a gap
check(R(gap=147.0, flag_for_declaration=True), V.REFUTED,
      "huge gap + flag -> REFUTED (numeric path wins; the flag is consulted on reproduces-paths only)")
# FLAG implies the number reproduced: a killed / degenerate run still degrades to INCONCLUSIVE
check(R(killed=True, flag_for_declaration=True), V.INCONCLUSIVE,
      "killed run + flag -> INCONCLUSIVE (FLAG_FOR_DECLARATION requires reproduction)")
check(R(recompute_degenerate=True, flag_for_declaration=True), V.INCONCLUSIVE,
      "degenerate recompute + flag -> INCONCLUSIVE")
# the explanation names the EXACT block to declare (the resolvable-in-one-move contract, CANONICAL §3)
_lbl, _why = V.verdict_with_reason(R(flag_for_declaration=True, inferred_structure="windows"))
_n += 1
if not (_lbl == V.FLAG_FOR_DECLARATION and "declare the windows block to resolve" in _why):
    _fail += 1
    print("  FAIL [flag reason] %s :: %s" % (_lbl, _why))

# ---- fail-closed allowlist: only CONFIRMED/CAVEATS are clean; anything else (incl. unknown) is not ----
for v, want in ((V.CONFIRMED, True), (V.CAVEATS, True), (V.INVALIDATED, False),
                (V.REFUTED, False), (V.FLAG_FOR_DECLARATION, False), (V.INCONCLUSIVE, False),
                ("ZZZ_UNKNOWN_VERDICT", False)):
    _n += 1
    if V.is_clean(v) != want:
        _fail += 1
        print("  FAIL [is_clean] %r expected %s" % (v, want))
assert V.INVALIDATED in V.CATCH_VERDICTS and V.REFUTED in V.CATCH_VERDICTS
assert V.FLAG_FOR_DECLARATION in V.CATCH_VERDICTS and not V.is_clean(V.FLAG_FOR_DECLARATION)

# ---- totality: verdict() never raises and always returns a valid enum on garbage ----
for bad in [None, {}, {"gap": float("nan")}, {"exit_codes": None}, {"margin": -5}]:
    v = V.verdict(bad)
    assert v in V.VERDICTS, "non-enum result %r for %r" % (v, bad)
_n += 1

print("verdict.py: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
