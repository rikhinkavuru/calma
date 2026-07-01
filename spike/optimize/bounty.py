#!/usr/bin/env python
"""optimize.bounty — the FCR bug-bounty triage + fixture promotion (feature 9).

A valid submission is exactly a BREACH in the offline meta-eval: a wrong number that reached CONFIRMED. Triage
runs the submitted construct/repo through the verifier and checks for a CONFIRMED it should not have gotten;
a valid breach is frozen as a construct-only fixture (a redteam.attacks() tuple or a T4 repos.yaml stub) that
the standing CI gate then guards forever — so a fixed bug can never silently regress. The program
OPERATIONALIZES FCR=0: the payout condition is definitionally "the adversarial-FCR gate was breached in the
wild," and every accepted counterexample only strengthens the invariant.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from core import diff as D  # noqa: E402
from core import verdict as VD  # noqa: E402


def dedup_key(metric, capability, transform=None) -> str:
    """HackerOne-style dedupe signature: metric x capability x transform. Two submissions with the same key are
    the same class of bug (one fixture guards both)."""
    return "%s|%s|%s" % ((metric or "?"), (capability or "?"), (transform or "-"))


def triage(submission: dict, verify_fn=None) -> dict:
    """Triage a submission. `submission` is construct-only ({metric, claim, runs, capability}) — the common
    case — or carries a `verify_fn(submission)->record` for a full repo run. `is_false_confirm` is True iff the
    submitted KNOWN-WRONG number reached CONFIRMED (the only Critical). Returns {valid, verdict,
    is_false_confirm, dedup_key}."""
    if verify_fn is not None:
        rec = verify_fn(submission)
    else:
        rec = D.diff_claim(submission.get("claim", {}), submission.get("runs", []))
    verdict = rec.get("verdict")
    # any AFFIRMATIVE verdict (CONFIRMED or CONFIRMED-STOCHASTIC) on a submission asserted wrong = the breach
    is_fc = verdict in VD.AFFIRMATIVE
    return {"valid": bool(is_fc), "verdict": verdict, "is_false_confirm": bool(is_fc),
            "dedup_key": dedup_key(submission.get("metric") or (submission.get("claim") or {}).get("metric"),
                                   submission.get("capability"), submission.get("transform"))}


def promote_to_fixture(submission: dict) -> dict:
    """Emit the regression fixture for an accepted breach: a construct-only redteam.attacks() tuple stub
    (default) or a T4 repos.yaml stub for a full-repo case. This is what the CI gate then guards forever."""
    metric = submission.get("metric") or (submission.get("claim") or {}).get("metric")
    cap = submission.get("capability", "unknown")
    if submission.get("repo"):
        return {"kind": "repos_yaml_t4", "stub": {
            "repo": submission["repo"], "tier": "T4", "capability": cap,
            "expect": {"metric": metric, "not_verdict": VD.CONFIRMED}}}
    return {"kind": "redteam_attack", "stub": {
        "name": "bounty_%s_%s" % (metric or "metric", cap),
        "claim": submission.get("claim"), "runs": submission.get("runs"),
        "must_not_confirm": True}}


def main():
    # self-check: the standing attack corpus contains ZERO valid bounties (the engine holds FCR=0), so triage
    # of every construct-only attack returns is_false_confirm=False — the public "wild adversarial-FCR = 0".
    sys.path.insert(0, HERE)
    import redteam
    valid = []
    for name, claim, runs in redteam.attacks():
        t = triage({"claim": claim, "runs": runs, "metric": claim.get("metric"), "capability": name})
        if t["is_false_confirm"]:
            valid.append(name)
    ledger = {"wild_adversarial_fcr": round(len(valid) / max(1, len(redteam.attacks())), 4),
              "valid_bounties": valid}
    with open(os.path.join(HERE, "bounty_ledger.json"), "w") as fh:
        json.dump(ledger, fh, indent=2)
    print("=== FCR BUG BOUNTY (feature 9) ===")
    print("wild adversarial-FCR = %s  valid bounties = %s [target 0]" % (ledger["wild_adversarial_fcr"], valid))
    return 0 if not valid else 1


if __name__ == "__main__":
    sys.exit(main())
