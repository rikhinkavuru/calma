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

# ---- totality: verdict() never raises and always returns a valid enum on garbage ----
for bad in [None, {}, {"gap": float("nan")}, {"exit_codes": None}, {"margin": -5}]:
    v = V.verdict(bad)
    assert v in V.VERDICTS, "non-enum result %r for %r" % (v, bad)
_n += 1

print("verdict.py: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
