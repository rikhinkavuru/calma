"""calma.signoff - W7 / M-7.5: the reviewer/IC sign-off state machine + the immutable, hash-chained,
REPLAYABLE audit trail for an allocator Verification.

A Verification (a verdict + evidence over a manager's mandate) flows through a state machine:

    SUBMITTED -> UNDER_REVIEW -> REVIEWER_SIGNED -> IC_APPROVED | IC_REJECTED | RETURNED_TO_MANAGER

THE GATE (the whole point): a NON-CLEAN verdict blocks IC auto-approval. A CONFIRMED / CONFIRMED-WITH-CAVEATS
verification can be IC-approved; anything else — `FLAG_FOR_DECLARATION` (undeclared invalidating structure),
`REFUTED`, `INVALIDATED`, `MIXED`, or `CAN'T-CONFIRM` — requires the IC to EXPLICITLY waive (with a recorded
reason) or `return_to_manager`. So a flagged or wrong number can never be silently approved. (This is exactly
the verdict-gate from spec 04 §sign-off, made conservative: the spec names FLAG/REFUTED/INVALIDATED; we gate
on "not clean," which also catches MIXED and CAN'T-CONFIRM — you don't auto-approve what wasn't verified.)

Every action is an append-only, hash-chained event (`prev_hash` sha256 chain, RFC-6962-style, mirroring the
ledger/registry chains). `replay()` re-walks the chain, verifies every hash + linkage, and re-derives the
final state from the events alone — so an IC decision is PROVABLE after the fact: it was made on this verdict
over these events, untampered. Tamper any event and the chain breaks.

PURE CODE, no creds: the state machine + the verdict-gate + the hash-chained audit. The DSSE/SSHSIG signature
keyed to WorkOS identity (the M-7.5 signatures) + the Rekor anchoring are the W3/W2 integration — this models
the signer as `{id, role}` and carries an optional `signature` field the signing layer fills in. Ties into the
FLAG_FOR_DECLARATION verdict this session shipped: a flag blocks IC auto-approval.
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verdict as V  # noqa: E402 - pure-stdlib leaf (the clean/catch verdict sets)

ROLES = ("reviewer", "ic")
STATES = ("SUBMITTED", "UNDER_REVIEW", "REVIEWER_SIGNED", "IC_APPROVED", "IC_REJECTED", "RETURNED_TO_MANAGER")
TERMINAL = {"IC_APPROVED", "IC_REJECTED", "RETURNED_TO_MANAGER"}

# action -> (allowed from-states, to-state, required role | None for "reviewer or ic")
TRANSITIONS = {
    "open_review":       (("SUBMITTED",), "UNDER_REVIEW", "reviewer"),
    "reviewer_sign":     (("UNDER_REVIEW",), "REVIEWER_SIGNED", "reviewer"),
    "ic_approve":        (("REVIEWER_SIGNED",), "IC_APPROVED", "ic"),
    "ic_reject":         (("UNDER_REVIEW", "REVIEWER_SIGNED"), "IC_REJECTED", "ic"),
    "return_to_manager": (("UNDER_REVIEW", "REVIEWER_SIGNED"), "RETURNED_TO_MANAGER", None),
}


class SignOffError(ValueError):
    """An illegal transition: wrong from-state, wrong role, or an ungated approval of a non-clean verdict."""


def _hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def blocks_ic_approval(verdict):
    """True iff this verdict blocks IC auto-approval (anything not CONFIRMED / CONFIRMED-WITH-CAVEATS). A FLAG,
    REFUTED, INVALIDATED, MIXED, or CAN'T-CONFIRM all require an explicit IC waive (recorded) or a return."""
    return not V.is_clean(verdict)


class SignOff:
    """The sign-off chain for ONE Verification. Each action appends a hash-chained event; `state` is the last
    event's state, re-derivable from the log alone (deterministic) — so the whole thing is replayable."""

    def __init__(self, verification_id, verdict, *, at=None):
        self.verification_id = verification_id
        self.verdict = verdict
        self.events = []
        self._append("submit", actor=None, role=None, state="SUBMITTED", at=at)

    def _append(self, action, actor, role, state, **extra):
        prev = self.events[-1]["entry_hash"] if self.events else None
        ev = {"seq": len(self.events), "prev_hash": prev, "verification_id": self.verification_id,
              "verdict": self.verdict, "action": action, "actor": actor, "role": role, "state": state}
        ev.update({k: v for k, v in extra.items() if v is not None})
        ev["entry_hash"] = _hash(ev)                      # hash INCLUDES prev_hash -> a true chain
        self.events.append(ev)
        return ev

    @property
    def state(self):
        return self.events[-1]["state"]

    def transition(self, action, actor, role, *, waive_reason=None, at=None, signature=None, note=None):
        """Apply an action by `actor` (role ∈ ROLES). Raises SignOffError on an illegal move or an ungated
        approval. `waive_reason` is REQUIRED to ic_approve a non-clean verdict (and is recorded in the event)."""
        if action not in TRANSITIONS:
            raise SignOffError("unknown action %r" % action)
        froms, to, need_role = TRANSITIONS[action]
        if self.state in TERMINAL:
            raise SignOffError("%s is terminal - no further transitions" % self.state)
        if self.state not in froms:
            raise SignOffError("cannot %r from state %s" % (action, self.state))
        if role not in ROLES:
            raise SignOffError("unknown role %r" % role)
        if need_role and role != need_role:
            raise SignOffError("%r requires role %r, not %r" % (action, need_role, role))
        if action == "ic_approve" and blocks_ic_approval(self.verdict) and not waive_reason:
            raise SignOffError(
                "verdict %s blocks IC auto-approval - the IC must explicitly waive (with a recorded reason) "
                "or return_to_manager; a flagged/wrong/unverified number is never silently approved"
                % self.verdict)
        return self._append(action, actor, role, to, waive_reason=waive_reason, at=at,
                            signature=signature, note=note)

    # convenience wrappers (read at call sites like a workflow)
    def open_review(self, reviewer, **kw):
        return self.transition("open_review", reviewer, "reviewer", **kw)

    def reviewer_sign(self, reviewer, **kw):
        return self.transition("reviewer_sign", reviewer, "reviewer", **kw)

    def ic_approve(self, ic, **kw):
        return self.transition("ic_approve", ic, "ic", **kw)

    def ic_reject(self, ic, **kw):
        return self.transition("ic_reject", ic, "ic", **kw)

    def return_to_manager(self, actor, role, **kw):
        return self.transition("return_to_manager", actor, role, **kw)

    def replay(self):
        """Re-walk the chain: verify every event's seq + prev_hash linkage + entry_hash, and confirm the final
        state is reachable from the recorded actions. Returns (ok, final_state, errors). PROVES the decision was
        made on `verdict` over exactly these (untampered) events."""
        errs = []
        prev = None
        state = None
        for i, ev in enumerate(self.events):
            if ev.get("seq") != i:
                errs.append("event %d: seq mismatch" % i)
            if ev.get("prev_hash") != prev:
                errs.append("event %d: prev_hash broken (chain tampered)" % i)
            body = {k: v for k, v in ev.items() if k != "entry_hash"}
            if _hash(body) != ev.get("entry_hash"):
                errs.append("event %d: entry_hash does not recompute (event tampered)" % i)
            if i == 0:
                state = ev.get("state")
            else:
                action = ev.get("action")
                froms, to, _ = TRANSITIONS.get(action, ((), None, None))
                if state not in froms or ev.get("state") != to:
                    errs.append("event %d: illegal transition %r from %s -> %s" % (i, action, state, ev.get("state")))
                if action == "ic_approve" and blocks_ic_approval(ev.get("verdict")) and not ev.get("waive_reason"):
                    errs.append("event %d: IC_APPROVED a non-clean verdict with no recorded waiver" % i)
                state = ev.get("state")
            prev = ev.get("entry_hash")
        return (not errs, state, errs)

    def to_dict(self):
        return {"verification_id": self.verification_id, "verdict": self.verdict,
                "state": self.state, "events": self.events}


def load(obj):
    """Reconstruct a SignOff from its serialised dict (re-attaches the event log; state is the last event)."""
    so = SignOff.__new__(SignOff)
    so.verification_id = obj["verification_id"]
    so.verdict = obj["verdict"]
    so.events = list(obj["events"])
    return so
