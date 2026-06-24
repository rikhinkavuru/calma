"""calma.tiers - the SINGLE source of truth for which isolation_tier stamps count as VERIFIED.

This tuple is a SECURITY GATE: it decides whether an isolation tier is trusted enough to (a) run untrusted
third-party code and (b) stamp a verdict as isolation-backed. It was previously hand-duplicated in FIVE
places - run_hermetic._VERIFIED_TIERS, calma.VERIFIED_TIERS, hook_stop.VERIFIED_TIERS, and inline tuples
inside verdict.confidence() and compare.compare() - guarded only by a partial test that checked membership
of ONE stamp in THREE of the five copies (never verdict.py or compare.py, never set-equality). A tier added
to one copy but not another would silently diverge the gate. Defined ONCE here now; every consumer imports
it; test_hermetic asserts strict set-equality across all consumers (incl. verdict.VERIFIED_TIERS, the symbol
CANONICAL-DECISIONS §3 asks for).

Pure stdlib, imports NOTHING - so the lightweight verdict/compare layers can import it without pulling in the
executor (run_hermetic). `host-not-isolated` is deliberately ABSENT: it is the honest CAVEAT stamp, never a
verified tier.
"""

# macOS Seatbelt + Linux bubblewrap (no-daemon host own-code tiers); the legacy container stamps
# (tier0/container/vm); and the remote Firecracker microVM stamps (E2B cloud + self-hosted).
VERIFIED_TIERS = (
    "seatbelt-verified",
    "bwrap-verified",
    "tier0",
    "container",
    "vm",
    "e2b-firecracker",
    "e2b-firecracker (self-hosted)",
)


def is_verified(tier):
    """True iff `tier` is a stamp that counts as VERIFIED isolation (the gate). host-not-isolated -> False."""
    return tier in VERIFIED_TIERS
