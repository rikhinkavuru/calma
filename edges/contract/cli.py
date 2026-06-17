"""A2 CLI seam -- `python -m edges.contract <repo>`: draft a verify.yaml for a repo with the LLM
drafter + the counterexample REPAIR loop (draft -> write verify.yaml -> engine.verify -> disagreements
-> redraft, to a budget). `calma draft --ai` shells out here; the core never imports edges (firewall),
so this is reached only as a subprocess.

AI proposes, determinism disposes: the model only PROPOSES bindings; the deterministic engine (a
subprocess, via edges.common.engine) DISPOSES -- it re-derives every binding grade from the data, and
the repair loop feeds real counterexamples back until the model's draft agrees with the engine. This
module never imports the verdict core (verdict / ledger / compare / recompute / numeric) -- enforced by
edges/tests/test_firewall.py.

Needs the edges deps (an LLM client) + an API key to RUN; `calma draft` (no --ai) uses the pure-stdlib
heuristic draft instead, and `calma draft --ai` falls back to it when this is unavailable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="edges.contract",
        description="LLM draft + counterexample-repair a Calma verify.yaml for a repo.")
    ap.add_argument("repo", help="the repo/dir to draft a verify.yaml for")
    ap.add_argument("--budget", type=int, default=3, help="max draft+repair rounds (default 3)")
    ap.add_argument("--model", default=None, help="advisory model tier")
    ap.add_argument("--oneshot", action="store_true",
                    help="seed with the nearest known shape + mined binding rules (library.draft_oneshot)")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="print {ok, contract, trace} as JSON (calma draft --ai consumes this)")
    a = ap.parse_args(argv)

    repo = os.path.abspath(a.repo)
    if not os.path.isdir(repo):
        print("not a directory: %s" % repo, file=sys.stderr)
        return 2

    # Lazy: keep `--help` (and import) working without the LLM client installed; the draft call below
    # is what actually needs the edges deps + an API key.
    try:
        from edges.contract import library, loop
    except Exception as e:  # noqa: BLE001 - any import failure is a clean "unavailable", not a crash
        print("edges drafter unavailable: %s" % e, file=sys.stderr)
        return 1
    try:
        if a.oneshot:
            contract, trace = library.draft_oneshot(repo, budget=a.budget, model=a.model)
        else:
            contract, trace = loop.draft_with_repair(repo, budget=a.budget, model=a.model)
    except Exception as e:  # noqa: BLE001 - LLM/network/key errors -> a clean non-zero so calma falls back
        print("AI draft failed (need the edges deps + an API key?): %s" % e, file=sys.stderr)
        return 1

    summary = {
        "ok": True,
        "verify_yaml": os.path.join(repo, "verify.yaml"),
        "contract": contract,
        "trace": {"resolved": trace.get("resolved"),
                  "iterations_used": trace.get("iterations_used"),
                  "final_verdict": trace.get("final_verdict")},
    }
    if a.as_json:
        print(json.dumps(summary, indent=2))
    else:
        mets = contract.get("metrics") or []
        print("drafted %s" % summary["verify_yaml"])
        print("  entrypoint: %s" % (contract.get("run", {}) or {}).get("entrypoint", "(none)"))
        print("  metrics:    %s" % (", ".join(m.get("metric_id", "?") for m in mets) or "(none)"))
        print("  repair:     resolved=%s in %s round(s)"
              % (trace.get("resolved"), trace.get("iterations_used")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
