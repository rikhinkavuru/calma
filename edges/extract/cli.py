"""A1 CLI seam -- `calma-extract <target>`: verify every number in an artifact, automatically, with
each catch tied to its source span.

This is the single user-facing command that wires the A1 pipeline end to end:

    ingest -> route(extract) -> to_contract(compile + engine.verify) -> reconcile(render)

It ORCHESTRATES the existing modules and computes NOTHING itself. Every verdict word and every
recomputed number is the engine's (reached only through to_contract.verify_graph, a subprocess);
every citation is reconcile's structural join. This module never imports the verdict core
(verdict / ledger / compare / recompute / numeric) -- enforced by edges/tests/test_firewall.py.

AI proposes, determinism disposes: route.extract_routed PROPOSES claims (the cheap-first Haiku ->
Sonnet -> Opus ladder); the deterministic engine DISPOSES (recompute + regrade owns every verdict).

<target> must be a DIRECTORY the engine can actually run: the artifact(s) that state the claims (a
notebook / PDF / CSV) PLUS the entrypoint + data the numbers were computed from (so the engine can
re-emit and recompute). A bare notebook with no produced data is not an error -- its per-claim
verdicts simply degrade to CAN'T-CONFIRM (nothing to recompute against), which is the correct,
non-crashing outcome.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from edges.extract import ingest, reconcile, route, to_contract

# the per-claim outcomes that mean "the catch fired" (mirrors reconcile.CATCH_VERDICTS + the repo
# rollup MIXED); used to drive the human ordering note and the exit code.
_CATCH_REPO = ("REFUTED", "INVALIDATED", "MIXED")
_CLEAN_REPO = ("CONFIRMED", "CONFIRMED-WITH-CAVEATS")


def run(target, *, mode="flag", model=None):
    """The whole A1 seam as one call. Returns (report, stats, handoffs) where handoffs is [] unless
    mode='fix'. No new LLM call is made beyond route.extract_routed's own cheap-first ladder; `model`
    is the caller's advisory tier preference (the router owns escalation -- see main())."""
    bundle = ingest.ingest(target)                              # 1. dir -> spans + recompute-able data
    graph, stats = route.extract_routed(bundle)                # 2. cheap-first extraction + RouteStats
    result = to_contract.verify_graph(graph, target)           # 3. compile verify.yaml + engine.verify
    rendered = reconcile.render(graph, result, mode=mode)      # 4. join verdicts to spans (catches first)
    if mode == "fix":
        report, handoffs = rendered
    else:
        report, handoffs = rendered, []
    return report, stats, handoffs


def exit_code_for(repo_verdict):
    """0 if CONFIRMED/CONFIRMED-WITH-CAVEATS, 1 if a catch (REFUTED/INVALIDATED/MIXED), 2 otherwise
    (INCONCLUSIVE / anything else). Mirrors calma.py's verify exit policy."""
    if repo_verdict in _CLEAN_REPO:
        return 0
    if repo_verdict in _CATCH_REPO:
        return 1
    return 2


def _cost_line(stats):
    """A one-line RouteStats cost breadcrumb: spans seen, the cheap (heuristic + haiku) path, the
    escalations, and the share that never escalated."""
    return ("cost: %d span%s checked  -  %d heuristic (no-LLM), %d haiku, %d->sonnet, %d->opus  -  "
            "%.0f%% cheap-path, %d pre-checked likely-ok" % (
                stats.claims, "" if stats.claims == 1 else "s", stats.heuristic, stats.haiku,
                stats.escalated_sonnet, stats.escalated_opus,
                100.0 * stats.coverage_no_escalation(), stats.likely_ok))


def _render_human(report, stats, handoffs):
    """summary line -> each ClaimReport (catch verdicts first, with their CLARIESG citation) -> the
    single most-actionable fix -> the RouteStats cost line -> (mode='fix') the RepairHandoff list."""
    lines = ["%s  [%s]" % (report.summary, report.repo_verdict)]
    if not report.claims:
        lines.append("  (no numeric claims found to verify)")
    for cr in report.claims:                                    # already sorted catches-first by render
        lines.append("  [%s] %s" % (cr.verdict, cr.citation))
        if cr.reason and cr.verdict not in _CLEAN_REPO:
            lines.append("        reason: %s" % cr.reason)
    if report.fix:
        lines.append("fix: %s" % report.fix)
    lines.append(_cost_line(stats))
    if handoffs:
        lines.append("repair handoffs (A4 input):")
        for h in handoffs:
            lines.append("  - %s  claimed=%s  run_dir=%s" % (
                h.metric_id, h.claimed_value, h.run_dir))
    return "\n".join(lines)


def _json_payload(report, stats, handoffs, mode):
    payload = report.to_json()
    payload["route_stats"] = stats.to_json()
    payload["mode"] = mode
    if mode == "fix":
        payload["handoffs"] = [h.to_json() for h in handoffs]
    return payload


def build_parser():
    ap = argparse.ArgumentParser(
        prog="calma-extract",
        description="Verify every number in an artifact directory, automatically -- each catch tied "
                    "to its source span. AI proposes the claims; the deterministic engine disposes "
                    "every verdict.")
    ap.add_argument("target", help="a directory the engine can run: the claim artifact "
                                   "(notebook/PDF/CSV) PLUS the entrypoint + data it was computed from")
    ap.add_argument("--mode", choices=["flag", "fix"], default="flag",
                    help="flag (default): surface the catches. fix: also emit the A4 RepairHandoff list.")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="print the machine-readable Report JSON (+ route_stats) instead of the human view")
    ap.add_argument("--model", choices=["haiku", "sonnet", "opus"], default=None,
                    help="advisory extractor tier. The router runs a cost-optimal Haiku->Sonnet->Opus "
                         "ladder and escalates only when needed, so this is a preference hint, not an "
                         "override (the deterministic engine owns every verdict regardless).")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    target = a.target
    if not os.path.isdir(target):
        # the engine needs a runnable dir; a bare file can't be re-emitted + recomputed.
        print("error: <target> must be a directory the engine can run (an entrypoint + the data the "
              "claim was computed from); got %r" % target, file=sys.stderr)
        return 2

    report, stats, handoffs = run(target, mode=a.mode, model=a.model)

    if a.as_json:
        print(json.dumps(_json_payload(report, stats, handoffs, a.mode), indent=2, default=str))
    else:
        print(_render_human(report, stats, handoffs))

    return exit_code_for(report.repo_verdict)


if __name__ == "__main__":
    raise SystemExit(main())
