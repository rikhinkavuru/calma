#!/usr/bin/env python
"""optimize.determinism — Calma's OWN verdict stability (#12).

A verifier that flips its verdict across independent re-captures of the same repo is self-defeating (it's
the meta-version of the determinism it checks for). Capture a deterministic fixture N independent times
(separate subprocess runs) and assert every claim gets an IDENTICAL verdict AND an identical produced value
across all N. Run under the spike venv.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SPIKE, "capture"))

from core import catalog as C  # noqa: E402
from core import diff as D  # noqa: E402
from runner import build  # noqa: E402
from runner.local_runner import run_local  # noqa: E402
import inject as INJ  # noqa: E402


def capture_n(n_captures=3, k=2):
    spec = {"name": "clean_eval", "source": {"kind": "local", "path": "fixtures/clean_eval"}, "entry": ["eval.py"]}
    repo_dir, _ = build.ensure_repo(spec, os.path.join(HERE, "captures", "repos"))
    python, _ = build.ensure_venv("clean_eval", None, os.path.join(SPIKE, "results", ".venvs"))
    return [run_local(repo_dir, spec["entry"], k=k, python=python, hooks="sklearn")["runs"]
            for _ in range(n_captures)]


def _headlines(runs):
    out = []
    for c in (runs[0] if runs else []):
        cid = C.canonical(c.get("metric") or "")
        if cid is None:
            continue
        try:
            out.append((cid, float(c["result"])))
        except (TypeError, ValueError):
            pass
    return out


def main():
    caps = capture_n()
    claims = [(m, cl["value"]) for m, true in _headlines(caps[0]) for cl in INJ.all_claims(m, true)]
    v_flips, p_flips, rows = 0, 0, []
    for metric, val in claims:
        verdicts, produced = [], []
        for runs in caps:
            rec = D.diff_claim({"metric": metric, "value": val}, runs)
            verdicts.append(rec["verdict"])
            produced.append((rec.get("diff") or {}).get("produced"))
        vs = len(set(verdicts)) == 1
        ps = len(set(produced)) == 1
        v_flips += (not vs)
        p_flips += (not ps)
        if not vs or not ps:
            rows.append({"metric": metric, "val": val, "verdicts": verdicts, "produced": produced})
    n = len(claims)
    m = {"n_captures": len(caps), "n_claims": n, "verdict_flips": v_flips, "produced_flips": p_flips,
         "verdict_stability": round((n - v_flips) / n, 4) if n else None,
         "produced_stability": round((n - p_flips) / n, 4) if n else None}
    with open(os.path.join(HERE, "determinism_metrics.json"), "w") as fh:
        json.dump({**m, "flips": rows[:20]}, fh, indent=2)
    print("=== VERDICT DETERMINISM (Calma-self · %d independent captures · %d claims) ===" % (len(caps), n))
    print("verdict stability: %s  [target 1.0]   (flips=%d)" % (m["verdict_stability"], v_flips))
    print("produced-value stability: %s  (flips=%d)" % (m["produced_stability"], p_flips))
    for r in rows[:10]:
        print("  FLIP:", r["metric"], r["val"], "→", r["verdicts"])
    if not rows:
        print("every claim got an identical verdict AND produced value across all captures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
