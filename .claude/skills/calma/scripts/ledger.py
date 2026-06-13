"""calma.ledger - schema + semantic validation and the single CLEAN gate.

`_validate()` is the auditor: it RE-INVOKES verdict.verdict() on every claim's stored verdict_inputs
and asserts byte-equality with the stored enum, so a hand-edited or model-authored label cannot pass.
It also enforces the structural honesty invariants (REFUTED => linked blocker of the driving dimension
+ a structured reproduction; no REFUTED unless the input is independently-bound; non-waivable REFUTED
=> non-clean repo verdict; claim_id referential integrity; execution-derived findings are never
static-reread).

The gate is a strict lattice with a findings-floor:
    exit 0  <=>  zero blocking findings still open  AND  repo_verdict in {CONFIRMED, CONFIRMED-WITH-CAVEATS}
    exit 1  =  valid ledger, but not clean (findings and/or a non-clean repo verdict)
    exit 2  =  invalid ledger (schema or _validate failure)

Usage: python3 ledger.py validate <ledger.json>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verdict as V  # noqa: E402

DIMENSIONS = {
    "leakage", "overfitting", "execution-realism", "data-integrity", "baseline",
    "metric-appropriateness", "selection", "reproducibility", "metric-mismatch",
    "isolation-security", "input-binding", "contract-grounding", "metric-population-coverage",
    "selective-reporting", "artifact-provenance", "environment-selected",
}
# dimensions that are derived from execution and so may NOT be re-verified by a static re-read
EXEC_DIMENSIONS = {
    "reproducibility", "execution-realism", "leakage", "overfitting", "baseline",
    "selection", "metric-population-coverage", "environment-selected", "metric-mismatch",
}
SEVERITIES = {"blocker", "major", "minor", "info"}
BLOCKING_SEVERITIES = {"blocker", "major"}
CLEARED_STATUSES = {"resolved", "waived", "accepted"}
# soundness dimensions (WS4) whose open blocking findings degrade a clean CONFIRMED to CAVEATS:
# the number reproduces, but it is gross-not-net / cherry-picked / survivorship-biased.
SOUNDNESS_CAVEAT_DIMENSIONS = {"execution-realism", "selection", "data-integrity"}
REVERIFY_KINDS = {"static-reread", "artifact-recheck", "requires-reexecution"}
FIXABLE = {"editor", "author", "operator", "none"}
BINDING_STATES = {"independently-bound", "plausibly-bound", "author-asserted"}
CLEAN_REPO = {V.CONFIRMED, V.CAVEATS}
NONCLEAN_REPO = {"REFUTED", "MIXED", "CONTESTED"}


def load_ledger(path):
    with open(path) as fh:
        return json.load(fh)


def structural_validate(led):
    e = []
    for k in ("claims", "findings", "scope", "repo_verdict"):
        if k not in led:
            e.append("missing top-level key: %s" % k)
    if e:
        return e
    ids = set()
    for i, c in enumerate(led["claims"]):
        w = "claim[%d]" % i
        for k in ("id", "verdict", "verdict_inputs", "input_binding_status"):
            if k not in c:
                e.append("%s missing %s" % (w, k))
        if c.get("id") in ids:
            e.append("%s duplicate id %r" % (w, c.get("id")))
        ids.add(c.get("id"))
        if c.get("verdict") not in V.VERDICTS:
            e.append("%s verdict %r not in enum" % (w, c.get("verdict")))
        if c.get("input_binding_status") not in BINDING_STATES:
            e.append("%s input_binding_status %r invalid" % (w, c.get("input_binding_status")))
    for i, f in enumerate(led["findings"]):
        w = "finding[%d]" % i
        if f.get("dimension") not in DIMENSIONS:
            e.append("%s dimension %r invalid" % (w, f.get("dimension")))
        if f.get("severity") not in SEVERITIES:
            e.append("%s severity %r invalid" % (w, f.get("severity")))
        if f.get("fixable_by") not in FIXABLE:
            e.append("%s fixable_by %r invalid" % (w, f.get("fixable_by")))
        rv = (f.get("reverify") or {}).get("kind")
        if rv not in REVERIFY_KINDS:
            e.append("%s reverify.kind %r invalid" % (w, rv))
    if led["repo_verdict"] not in (CLEAN_REPO | NONCLEAN_REPO | {V.INCONCLUSIVE}):
        e.append("repo_verdict %r invalid" % led["repo_verdict"])
    return e


def compute_repo_verdict(led):
    """FP-aware worst-of-claims. A deterministic REFUTED on a headline claim sets the repo REFUTED;
    a REFUTED on a non-headline claim makes it MIXED; otherwise the worst clean verdict."""
    claims = led["claims"]
    if not claims:
        return V.INCONCLUSIVE
    headline_refuted = any(c["verdict"] == V.REFUTED and c.get("headline") for c in claims)
    nonheadline_refuted = any(c["verdict"] == V.REFUTED and not c.get("headline") for c in claims)
    if headline_refuted:
        return "REFUTED"
    if nonheadline_refuted:
        return "MIXED"
    if any(c["verdict"] == V.INCONCLUSIVE for c in claims):
        # not a refutation; if nothing CONFIRMED at all, the repo is under-determined
        if all(c["verdict"] == V.INCONCLUSIVE for c in claims):
            return V.INCONCLUSIVE
    if any(c["verdict"] == V.CAVEATS for c in claims):
        return V.CAVEATS
    # WS4: an open blocking soundness finding (omitted costs / cherry-picked window / survivorship)
    # means the headline number reproduces but the result is narrower/biased than the claim implies -
    # degrade a clean CONFIRMED to CONFIRMED-WITH-CAVEATS (never up to REFUTED: that stays the verdict()
    # path on a bound metric). Conservative and honest; the finding carries the explanation + fix.
    if any(f.get("dimension") in SOUNDNESS_CAVEAT_DIMENSIONS
           and f.get("severity") in BLOCKING_SEVERITIES
           and f.get("status") not in CLEARED_STATUSES
           for f in led.get("findings", [])):
        return V.CAVEATS
    return V.CONFIRMED


def semantic_validate(led):
    e = []
    claims_by_id = {c["id"]: c for c in led["claims"]}

    for c in led["claims"]:
        cid = c["id"]
        # (1) the label must re-derive byte-for-byte from the stored verdict_inputs
        rederived = V.verdict(c["verdict_inputs"])
        if rederived != c["verdict"]:
            e.append("claim %s: stored verdict %r != re-derived %r" % (cid, c["verdict"], rederived))
        if c["verdict"] == V.REFUTED:
            # (2) no REFUTED unless the input is independently-bound
            if c["input_binding_status"] != "independently-bound":
                e.append("claim %s: REFUTED on a non-independently-bound input" % cid)
            # (3) REFUTED => a linked blocker finding of the driving dimension + structured reproduction
            axis = c.get("driving_dimension")
            if axis not in DIMENSIONS:
                e.append("claim %s: REFUTED but driving_dimension %r invalid" % (cid, axis))
            linked = [f for f in led["findings"]
                      if f.get("claim_id") == cid and f.get("severity") == "blocker"
                      and f.get("dimension") == axis]
            if not linked:
                e.append("claim %s: REFUTED needs a linked blocker finding of dimension %r" % (cid, axis))
            rep = c.get("reproduction_or_reverify") or {}
            if rep.get("kind") not in REVERIFY_KINDS or not rep.get("expected"):
                e.append("claim %s: REFUTED needs a structured reproduction with a runnable `expected`" % cid)

    # (4) referential integrity + execution-derived findings are not static-reread
    for f in led["findings"]:
        if f.get("claim_id") is not None and f["claim_id"] not in claims_by_id:
            e.append("finding %s: claim_id %r has no claim" % (f.get("id"), f["claim_id"]))
        if f.get("dimension") in EXEC_DIMENSIONS and (f.get("reverify") or {}).get("kind") == "static-reread":
            e.append("finding %s: execution-derived dimension %r cannot be static-reread"
                     % (f.get("id"), f.get("dimension")))
        if f.get("fixable_by") in ("operator", "none") and f.get("status") == "fixed-pending-verify":
            e.append("finding %s: %s finding cannot be fixed-pending-verify" % (f.get("id"), f.get("fixable_by")))

    # (5) repo_verdict must equal the computed worst-of-claims; non-waivable REFUTED => non-clean
    computed = compute_repo_verdict(led)
    if led["repo_verdict"] != computed:
        e.append("repo_verdict %r != computed worst-of-claims %r" % (led["repo_verdict"], computed))
    nonwaivable_refuted = any(
        c["verdict"] == V.REFUTED and not c.get("waivable", False) for c in led["claims"])
    if nonwaivable_refuted and led["repo_verdict"] in CLEAN_REPO:
        e.append("a non-waivable REFUTED claim cannot coexist with a clean repo_verdict")
    return e


def gate(led):
    blocking = [f for f in led["findings"]
                if f.get("severity") in BLOCKING_SEVERITIES and f.get("status") not in CLEARED_STATUSES]
    clean = (not blocking) and led["repo_verdict"] in CLEAN_REPO
    return (0 if clean else 1), {
        "clean": clean, "repo_verdict": led["repo_verdict"], "open_blocking": len(blocking),
    }


def validate_obj(led):
    errs = structural_validate(led)
    if errs:
        return 2, {"stage": "structural", "errors": errs}
    errs = semantic_validate(led)
    if errs:
        return 2, {"stage": "semantic", "errors": errs}
    return gate(led)


def validate(path):
    return validate_obj(load_ledger(path))


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "validate":
        print("usage: ledger.py validate <ledger.json>", file=sys.stderr)
        sys.exit(2)
    code, info = validate(sys.argv[2])
    print(json.dumps(info, indent=2))
    sys.exit(code)
