#!/usr/bin/env python
"""optimize.capture_fixtures — run each base fixture ONCE (k runs) and persist the raw capture.

measure.py then replays thousands of injected claims against these persisted captures with no
re-execution, so the optimization loop is fast and isolated from the (slow, sometimes flaky) run step.

    ~/.calma/spike-venv/bin/python optimize/capture_fixtures.py [--k 2] [--only clean_eval]

The base set is the clean, deterministic, catalog-recognized, uniquely-binding fixtures — the ones whose
honest verdict is CONFIRMED — so an injected misreport has an unambiguous REFUTED ground truth. Other
verdict paths (INVALIDATED / NON-DETERMINISTIC) get their own injection classes in later loop cycles.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)
sys.path.insert(0, os.path.join(SPIKE, "capture"))

from runner import build  # noqa: E402
from runner.local_runner import run_local  # noqa: E402

CAP_DIR = os.path.join(HERE, "captures")
# reuse the corpus run's cached venvs (realistic_sklearn already built there) instead of rebuilding
VENVS_DIR = os.path.join(SPIKE, "results", ".venvs")

# cycle-1 base set: clean, deterministic, recognized, unique bindings → honest verdict is CONFIRMED
BASES = [
    {"name": "clean_eval", "source": {"kind": "local", "path": "fixtures/clean_eval"},
     "entry": ["eval.py"], "pip_install": None, "hooks": "sklearn"},
    {"name": "realistic_sklearn", "source": {"kind": "local", "path": "fixtures/realistic_sklearn"},
     "entry": ["train.py"], "pip_install": ["numpy", "scikit-learn"], "hooks": "sklearn"},
]


def capture_one(spec, k=2):
    repo_dir, _ = build.ensure_repo(spec, os.path.join(CAP_DIR, "repos"))
    python, note = build.ensure_venv(spec["name"], spec.get("pip_install"), VENVS_DIR)
    r = run_local(repo_dir, spec["entry"], k=k, python=python,
                  hooks=spec.get("hooks", "sklearn"), targets=spec.get("targets"))
    return r, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=2)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    os.makedirs(CAP_DIR, exist_ok=True)
    only = set(s for s in args.only.split(",") if s)
    n_ok = 0
    for spec in BASES:
        if only and spec["name"] not in only:
            continue
        print("→ capturing %s ..." % spec["name"], flush=True)
        r, note = capture_one(spec, k=args.k)
        if not r["ran_ok"]:
            print("  !! did not run (%s): %s" % (note, r["meta"][-1].get("stderr_tail", "")[-300:]))
            continue
        out = {"name": spec["name"], "ran_ok": True, "k": len(r["runs"]),
               "n_calls": r["n_calls"], "runs": r["runs"]}
        path = os.path.join(CAP_DIR, spec["name"] + ".json")
        with open(path, "w") as fh:
            json.dump(out, fh)
        n_ok += 1
        print("  ok (%s) k=%d n_calls=%s → %s" % (note, len(r["runs"]), r["n_calls"], os.path.basename(path)))
    print("captured %d fixture(s) → %s" % (n_ok, CAP_DIR))
    return 0 if n_ok else 1


if __name__ == "__main__":
    sys.exit(main())
