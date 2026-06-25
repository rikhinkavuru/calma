"""A4 CLI seam -- `python -m edges.repair <run_dir>`: given a REFUTED/INVALIDATED catch, the model
diagnoses the producing code and proposes a MINIMAL patch; Calma re-verifies the PATCHED code from
scratch (in an isolated scratch clone -- the user's working tree is never touched) and owns the verdict.
A patch is only "accepted" if the recompute on the new code genuinely closes the gap to a clean verdict,
the goalposts are immutable, and the deterministic review gate (anti-test-hacking) passes.

`calma repair` shells out here; the core never imports edges (the P0 firewall), so this is reached only
as a subprocess -- exactly like `calma draft --ai` -> `python -m edges.contract` and `calma onboard` ->
`python -m edges.synth.onboard`.

AI proposes, determinism disposes: the model proposes the diff; engine.verify (a subprocess, via
edges.common.engine) disposes the verdict on the patched code. This module never imports the verdict
core (verdict / ledger / compare / recompute / numeric) -- enforced by edges/tests/test_firewall.py.

Needs the edges deps (an LLM client) + an API key to RUN.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _summary(result):
    """A JSON-safe view of the RepairResult -- the accepted patch + an honest per-hypothesis trajectory
    (what was tried, what the engine said, why it was or wasn't accepted). `calma repair` consumes this."""
    gp = result.goalposts
    return {
        "ok": True,
        "accepted": result.accepted,
        "one_shot": result.one_shot,
        "before_verdict": result.before_verdict,
        "after_verdict": result.after_verdict,
        "metric_id": gp.metric_id,
        "claim_value": gp.claim_value,
        "patch": result.patch,
        "target": result.target,
        "run_dir": result.run_dir,
        "hypotheses": [
            {
                "index": h.index,
                "cause": h.diagnosis.cause,
                "target_files": list(h.diagnosis.target_files or ()),
                "after_verdict": h.after_verdict,
                "gap_closed": h.gap_closed,
                "reviewers_passed": h.reviewers_passed,
                "accepted": h.accepted,
                "reasons": list(h.review_reasons or ()),
            }
            for h in result.trajectory
        ],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="edges.repair",
        description="LLM-diagnose a REFUTED catch and propose a re-verified, goalpost-preserving patch.")
    ap.add_argument("run_dir", help="the .calma/<run-id> dir of a REFUTED/INVALIDATED verification")
    ap.add_argument("--budget", type=int, default=4, help="max diagnosis hypotheses to try (default 4)")
    ap.add_argument("--model", default=None, help="advisory diagnosis model tier")
    ap.add_argument("--apply", action="store_true",
                    help="apply the accepted patch to the working tree (default: propose only, never mutate)")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="print the {ok, accepted, patch, hypotheses} result as JSON (calma repair consumes this)")
    a = ap.parse_args(argv)

    run_dir = os.path.abspath(a.run_dir)
    if not os.path.isdir(run_dir):
        print("not a run dir: %s" % run_dir, file=sys.stderr)
        return 2

    # Lazy import: keep `--help` working without the LLM client installed; the repair call is what
    # actually needs the edges deps + an API key.
    try:
        from edges.repair import orchestrate
    except Exception as e:  # noqa: BLE001 - any import failure is a clean "unavailable", not a crash
        print("edges repair unavailable: %s" % e, file=sys.stderr)
        return 1
    try:
        result = orchestrate.repair(run_dir, budget=a.budget, model=a.model)
    except ValueError as e:  # not a REFUTED/INVALIDATED catch -> nothing to repair
        print("nothing to repair: %s" % e, file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 - LLM/network/key errors -> clean non-zero so calma can report
        print("AI repair failed (need the edges deps + an API key?): %s" % e, file=sys.stderr)
        return 1

    summary = _summary(result)
    # --apply: write the accepted patch to the user's working tree (opt-in; default is propose-only so
    # repair never silently mutates source). Reuses the same path-safe, escalating applier the
    # orchestrator used to validate the patch in the scratch.
    if a.apply and result.accepted and result.patch:
        from edges.repair import checkpoints as CK
        summary["applied"] = bool(CK.apply_diff(result.target, result.patch))

    if a.as_json:
        print(json.dumps(summary, indent=2))
    else:
        if result.accepted:
            print("repaired: %s -> %s%s"
                  % (result.before_verdict, result.after_verdict,
                     " (one-shot)" if result.one_shot else ""))
            print(result.patch or "")
            if a.apply:
                print("\napplied to working tree: %s" % ("yes" if summary.get("applied") else
                      "FAILED (apply it manually from the diff above)"))
        else:
            print("no accepted patch after %d hypothes(es); the verdict stands at %s"
                  % (len(result.trajectory), result.before_verdict))
    return 0 if result.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
