"""Tests for signoff.py - W7 / M-7.5: the reviewer/IC sign-off state machine + hash-chained replayable audit.
Pure stdlib. Run: python3 test_signoff.py

Covers: the happy path (clean verdict -> IC_APPROVED), THE GATE (a non-clean verdict blocks IC auto-approval
unless explicitly waived/returned), role + state guards, the hash-chained audit (replay verifies; a tampered
event is caught), and serialisation round-trip.
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import signoff as SO  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def expect(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def raises(fn):
    try:
        fn()
        return False
    except SO.SignOffError:
        return True


# ---- the gate predicate ----
expect(not SO.blocks_ic_approval(V.CONFIRMED) and not SO.blocks_ic_approval(V.CAVEATS),
       "clean verdicts (CONFIRMED/CAVEATS) do NOT block IC approval")
for v in (V.REFUTED, V.INVALIDATED, V.FLAG_FOR_DECLARATION, "MIXED", V.INCONCLUSIVE):
    expect(SO.blocks_ic_approval(v), "non-clean %s blocks IC auto-approval" % v)

# ---- happy path: a CONFIRMED verification flows to IC_APPROVED with no waiver ----
s = SO.SignOff("v-1", V.CONFIRMED, at="2026-06-24T00:00:00Z")
expect(s.state == "SUBMITTED", "starts SUBMITTED")
s.open_review("alice")
s.reviewer_sign("alice", signature="sshsig:...", note="checklist all green")
s.ic_approve("bob")
expect(s.state == "IC_APPROVED", "clean verdict -> IC_APPROVED (no waiver needed)")
ok, final, errs = s.replay()
expect(ok and final == "IC_APPROVED", "the approved chain replays cleanly (provable)")

# ---- THE GATE: a FLAG_FOR_DECLARATION can NOT be IC-approved without an explicit waiver ----
f = SO.SignOff("v-2", V.FLAG_FOR_DECLARATION)
f.open_review("alice"); f.reviewer_sign("alice")
expect(raises(lambda: f.ic_approve("bob")), "FLAG_FOR_DECLARATION blocks ic_approve with no waiver")
expect(f.state == "REVIEWER_SIGNED", "the blocked approval did NOT change state")
# the IC must explicitly waive (recorded) OR return to the manager
f.ic_approve("bob", waive_reason="IC accepts the undeclared-split risk for this mandate (minutes #42)")
expect(f.state == "IC_APPROVED" and any(e.get("waive_reason") for e in f.events),
       "an explicit, RECORDED IC waiver lets the flag through (and is in the audit trail)")
ok2, _, _ = f.replay()
expect(ok2, "the waived-approval chain replays cleanly")

# a REFUTED / INVALIDATED is likewise gated; return_to_manager is always allowed
r = SO.SignOff("v-3", V.REFUTED)
r.open_review("alice"); r.reviewer_sign("alice")
expect(raises(lambda: r.ic_approve("bob")), "REFUTED blocks ic_approve with no waiver")
r.return_to_manager("bob", "ic", note="recompute differs from the claim")
expect(r.state == "RETURNED_TO_MANAGER", "return_to_manager works for a wrong number")

# ---- role + state guards ----
g = SO.SignOff("v-4", V.CONFIRMED)
expect(raises(lambda: g.ic_approve("bob")), "cannot ic_approve straight from SUBMITTED")
expect(raises(lambda: g.transition("reviewer_sign", "alice", "reviewer")), "cannot reviewer_sign before open_review")
g.open_review("alice")
expect(raises(lambda: g.transition("open_review", "bob", "ic")), "ic cannot open_review (reviewer-only)")
expect(raises(lambda: g.transition("ic_approve", "alice", "reviewer")), "a reviewer cannot ic_approve (ic-only role)")
g.reviewer_sign("alice"); g.ic_approve("bob")
expect(raises(lambda: g.return_to_manager("bob", "ic")), "no transitions out of a terminal state (IC_APPROVED)")

# ---- the hash-chained audit: replay catches a tampered event ----
t = SO.SignOff("v-5", V.REFUTED)
t.open_review("alice"); t.reviewer_sign("alice")
t.ic_approve("bob", waive_reason="override")
expect(t.replay()[0], "valid chain replays ok")
# tamper: flip an IC_APPROVED waiver away (try to launder a non-clean approval)
tampered = copy.deepcopy(t)
tampered.events[-1]["waive_reason"] = None
ok_t, _, errs_t = tampered.replay()
expect(not ok_t and any("entry_hash" in e or "waiver" in e for e in errs_t),
       "removing the recorded waiver from an event is caught by replay (hash + the no-waiver rule)")
# tamper the chain linkage
tampered2 = copy.deepcopy(t)
tampered2.events[1]["prev_hash"] = "deadbeef"
expect(not tampered2.replay()[0], "a broken prev_hash linkage is caught by replay")

# ---- serialisation round-trip ----
d = json.loads(json.dumps(s.to_dict()))
s2 = SO.load(d)
expect(s2.state == "IC_APPROVED" and s2.replay()[0], "to_dict/load round-trips + still replays")

print("signoff: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
