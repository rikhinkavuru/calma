#!/usr/bin/env python
"""optimize.convention_fuzz — the coincidental-value fuzz test (guide §B.2 rule 8; §A.5 T4 'coincidental').

The standing FCR proof for the convention registry. Convention-search rescues a *runtime-produced* number
that is a valid metric under some STANDARD convention (annualization, ddof, downside-denom, correlation
type). The danger as the grid grows: a FABRICATED value coincidentally equalling a grid cell's output on
the captured inputs — a false CONFIRM. This harness fires many random fabricated values against random
inputs, per convention metric, and asserts the diff CONFIRMS *none* of them (beyond the tolerance base
rate, which for a 1e-6 relative match against continuous draws is effectively zero).

It is deliberately adversarial: claim == produced == the fabricated value (so the REFUTED gate passes and
the DEFAULT recompute disagrees), which is exactly the state that triggers convention-search. A CONFIRMED
here would be a franchise-level P0. Construct-only, seeded, pure-stdlib. Run in the spike venv.
"""
from __future__ import annotations

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from core import conventions as CONV  # noqa: E402
from core import diff as D  # noqa: E402
from core import verdict as VD  # noqa: E402


_VOCAB = "the a cat sat on mat dog ran fast slow big small red blue over under".split()


def _inputs_for(metric: str, rng: random.Random) -> dict:
    """Random, NON-degenerate inputs for a convention metric (real variance, some downside, non-constant)."""
    n = rng.randint(20, 260)
    if metric in ("sharpe", "sortino", "calmar"):
        return {"returns": [rng.gauss(0.0005, 0.02) for _ in range(n)]}
    if metric == "information_ratio":
        return {"returns": [rng.gauss(0.001, 0.02) for _ in range(n)],
                "benchmark": [rng.gauss(0.0008, 0.015) for _ in range(n)]}
    if metric in ("stdev", "variance"):
        return {"values": [rng.gauss(5, 3) for _ in range(n)]}
    if metric == "correlation":
        return {"x": [rng.gauss(0, 1) for _ in range(n)], "y": [rng.gauss(0, 1) for _ in range(n)]}
    if metric == "ndcg":
        return {"relevances": [rng.randint(0, 3) for _ in range(rng.randint(5, 30))]}
    if metric == "bleu":
        cand = " ".join(rng.choice(_VOCAB) for _ in range(rng.randint(6, 16)))
        ref = " ".join(rng.choice(_VOCAB) for _ in range(rng.randint(6, 16)))
        return {"candidate": cand, "references": [ref]}
    raise ValueError("no input generator for %r" % metric)


def _fabricated(metric: str, rng: random.Random) -> float:
    """A random value the metric would essentially never produce on the given inputs — drawn in the metric's
    PLAUSIBLE OUTPUT RANGE (the hardest coincidence test). BLEU spans [0,100] to cover both unit + percent
    scale cells; bounded metrics span a bit past their range; ratios span a wide band."""
    if metric == "correlation":
        return rng.uniform(-1.5, 1.5)
    if metric == "ndcg":
        return rng.uniform(-0.2, 1.2)
    if metric == "bleu":
        return rng.uniform(0.0, 100.0)
    return rng.uniform(-25.0, 25.0)


def _call(metric, result, inputs):
    return {"metric": metric, "result": float(result), "inputs": inputs, "kwargs": {},
            "user_site": True, "captured_full": True, "n": len(next(iter(inputs.values()))),
            "seq": 0, "sink": "target:" + metric, "site": "r.py:1"}


def trials(n_per_metric: int = 400):
    rng = random.Random(0xFACADE)
    for metric in CONV.CONVENTIONS:
        for _ in range(n_per_metric):
            yield metric, _fabricated(metric, rng), _inputs_for(metric, rng)


def measure(n_per_metric: int = 400) -> dict:
    n = 0
    false_confirms = []
    per_metric: dict[str, int] = {}
    for metric, val, inputs in trials(n_per_metric):
        n += 1
        per_metric.setdefault(metric, 0)
        call = _call(metric, val, inputs)
        rec = D.diff_claim({"metric": metric, "value": "%.10g" % val}, [[call], [dict(call)]])
        if rec["verdict"] in VD.POSITIVE:
            per_metric[metric] += 1
            false_confirms.append({"metric": metric, "value": val, "reason": rec.get("reason", "")[:120]})
    return {"n_trials": n, "false_confirms": len(false_confirms), "breaches": false_confirms,
            "per_metric": per_metric,
            "grids": {m: len(c.grid) for m, c in CONV.CONVENTIONS.items()}}


def main():
    m = measure()
    with open(os.path.join(HERE, "convention_fuzz.json"), "w") as fh:
        json.dump(m, fh, indent=2)
    print("=== COINCIDENTAL-VALUE FUZZ (convention registry FCR gate — guide §B.2 rule 8) ===")
    print("trials=%d across %d convention metrics; grids=%s" % (m["n_trials"], len(m["grids"]), m["grids"]))
    print("FALSE-CONFIRMS: %d   [target 0 — ANY coincidental confirm is a P0]" % m["false_confirms"])
    if m["breaches"]:
        for b in m["breaches"][:20]:
            print("  ‼️ %-16s fabricated=%.6g — %s" % (b["metric"], b["value"], b["reason"]))
    else:
        print("HELD: no fabricated value matched any standard convention (FCR=0 on the grid).")
    return 1 if m["false_confirms"] else 0


if __name__ == "__main__":
    sys.exit(main())
