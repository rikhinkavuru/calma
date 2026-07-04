#!/usr/bin/env python
"""validity_scan — the GTM "validity wedge": a FAST, no-reproduction check of a repo for the three failure
modes that don't need to re-run anything — data leakage, a trivial/degenerate baseline, and a misreport
detectable from committed predictions. Produces a report card (grade + per-check findings).

This is the reliable, differentiated front door: "point Calma at your repo and it tells you if the number is
leaked / trivially-beatable / misreported" — without building an environment or executing the code. It is
also the right backend for the stop-hook guardrail: fast, local, and fail-closed (a number with nothing to
check against is INCOMPLETE, never a false verdict).

Under the hood it is `pipeline.verify_repo(deep=False)` — which already skips the sandbox and runs only the
static/committed-data checks (leakage via core.leakage.from_committed_splits, trivial-baseline via the label
distribution, and misreport via committed-prediction recompute) — reshaped into a report card. No new
detection logic; the FCR firewall is untouched (verdicts still come from the engine, never from this shaper).

    python validity_scan.py <repo_dir> [--claim VALUE --metric ID] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys

import pipeline

# keywords that mark a per-claim invalidation as a TRIVIAL-BASELINE / degenerate finding (vs a leakage one),
# so the report card can group findings by check. Matched against the engine's own validity strings.
_BASELINE_MARKS = ("baseline", "chance", "majority", "degenerate", "trivial", "single class", "single-class",
                    "constant", "no better than")


def _leakage_check(result: dict) -> dict:
    scans = result.get("leakage") or []
    findings = [f.get("detail", f.get("kind", "leakage"))
                for s in scans for f in (s.get("findings") or [])]
    if findings:
        status = "fail"
    elif scans:
        status = "pass"                 # committed splits were found and scanned clean
    else:
        status = "not-applicable"       # no committed train/test split to check
    return {"name": "leakage", "status": status, "findings": findings}


def _baseline_check(result: dict) -> dict:
    findings = []
    checkable = False
    for c in result.get("claims") or []:
        inval = (c.get("validity") or {}).get("invalidating") or []
        for note in inval:
            if any(m in note.lower() for m in _BASELINE_MARKS):
                findings.append("%s=%s: %s" % (c.get("metric"), c.get("claimed"), note))
        # a claim whose value was compared against the label distribution was baseline-checkable
        if c.get("claimed") is not None:
            checkable = True
    status = "fail" if findings else ("pass" if checkable else "not-applicable")
    return {"name": "trivial-baseline", "status": status, "findings": findings}


def _misreport_check(result: dict) -> dict:
    findings = []
    checkable = False
    for c in result.get("claims") or []:
        prov = c.get("provenance") or ""
        if str(prov).startswith("artifact"):            # recomputed from committed predictions — no run needed
            checkable = True
            if c.get("verdict") == "REFUTED":
                d = c.get("diff") or {}
                findings.append("%s: reported %s, recompute of committed predictions gives %s"
                                % (c.get("metric"), d.get("claimed"), d.get("recomputed")))
    status = "fail" if findings else ("pass" if checkable else "not-applicable")
    return {"name": "misreport", "status": status, "findings": findings}


def _grade(checks: list[dict]) -> str:
    if any(c["status"] == "fail" for c in checks):
        return "FAIL"
    if all(c["status"] == "not-applicable" for c in checks):
        return "INCOMPLETE"             # nothing to check — honest, not a false clean bill
    return "PASS"


def card_from_result(result: dict) -> dict:
    """Reshape a `verify_repo` result dict into a validity report card (grade + per-check findings). Pure —
    no run, no verdict authorship (the verdicts already came from the engine). Callable on any deep=False
    result the server already has, so the card has one source of truth and no duplicated logic in the UI."""
    checks = [_leakage_check(result), _baseline_check(result), _misreport_check(result)]
    return {
        "grade": _grade(checks),
        "checks": checks,
        "summary": result.get("summary", {}),
        "counts": result.get("counts", {}),
        "leakage": result.get("leakage", []),
        "claims": result.get("claims", []),
    }


def scan(repo_dir: str, claims: list[dict] | None = None) -> dict:
    """Run the no-reproduction validity checks on a checked-out repo and return a report card. `claims` is an
    optional list of externally-stated claims (e.g. one a stop-hook scraped from a message) to also check
    against committed predictions — a bare claim with no producing artifact stays DISCOVERED, never REFUTED."""
    opts = pipeline.VerifyOptions(deep=False, discover=True, claims=list(claims or []))
    return card_from_result(pipeline.verify_repo(repo_dir, opts))


def _fmt_text(card: dict) -> str:
    icon = {"PASS": "✅", "FAIL": "❌", "INCOMPLETE": "◻️"}.get(card["grade"], "?")
    lines = ["%s VALIDITY: %s" % (icon, card["grade"])]
    for c in card["checks"]:
        mark = {"pass": "✓", "fail": "✗", "not-applicable": "–"}.get(c["status"], "?")
        lines.append("  %s %-16s %s" % (mark, c["name"], c["status"]))
        for f in c["findings"]:
            lines.append("      • %s" % f)
    if card["summary"].get("headline"):
        lines.append("  %s" % card["summary"]["headline"])
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Fast, no-reproduction validity report card for a repo.")
    ap.add_argument("repo_dir")
    ap.add_argument("--claim", help="an externally-stated claimed value to also check")
    ap.add_argument("--metric", help="the claim's metric id (with --claim)")
    ap.add_argument("--json", action="store_true", help="emit the report card as JSON")
    args = ap.parse_args()
    claims = None
    if args.claim:
        claims = [{"metric": args.metric, "value": args.claim, "id": "hook_claim"}]
    card = scan(args.repo_dir, claims=claims)
    print(json.dumps(card) if args.json else _fmt_text(card))
    return 1 if card["grade"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
