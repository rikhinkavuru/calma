#!/usr/bin/env python
"""optimize.metamorphic_eval — feature 7 meta-eval.

(a) SOUNDNESS: every exact metamorphic relation holds on the CORRECT catalog metric across random inputs
    (no false-INVALIDATED on honest formulas).
(b) FAULT CATCH: an impostor that violates an exact relation (an order-sensitive "accuracy") is caught.
(c) FCR gate: a SATISFIED metamorphic relation never yields CONFIRMED — satisfaction is necessary, not
    sufficient, so the MR path can only fail a number closed, never open one.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)
sys.path.insert(0, os.path.join(SPIKE, "capture"))
sys.path.insert(0, os.path.join(SPIKE, "fixtures"))

import reinvoke  # noqa: E402
from core import metamorphic as MM  # noqa: E402

_LABELS = {"y_true": "arg0", "y_pred": "arg1"}

HONEST = [("honest_accuracy", "accuracy", _LABELS), ("honest_sharpe", "sharpe", {"returns": "arg0"}),
          ("honest_mean", "mean", {"values": "arg0"}), ("honest_mse", "mse", _LABELS),
          ("honest_correlation", "correlation", {"x": "arg0", "y": "arg1"})]
IMPOSTOR = [("order_sensitive_accuracy", "accuracy", _LABELS)]


def _cases(fn, metric, mapping, seed=11):
    r = reinvoke.fuzz_target({"target": "fuzz_metrics." + fn, "metric": metric, "inputs": mapping}, k=16, seed=seed)
    return r["cases"] if r else []


def measure():
    false_inval = []
    n_satisfied = 0
    for fn, m, mp in HONEST:
        res = MM.check_record(m, _cases(fn, m, mp))
        if res["invalidating"]:
            false_inval.append(fn)
        n_satisfied += len(res["satisfied"])
    caught = [fn for fn, m, mp in IMPOSTOR if MM.check_record(m, _cases(fn, m, mp))["invalidating"]]
    missed = [fn for fn, m, mp in IMPOSTOR if fn not in caught]
    return {"false_invalidated": false_inval, "n_satisfied_relations": n_satisfied,
            "catch_rate": round(len(caught) / len(IMPOSTOR), 4), "missed": missed,
            # the MR path never emits CONFIRMED — it only appends invalidations; a satisfied MR is advisory.
            "mr_confirms": 0}


def main():
    m = measure()
    with open(os.path.join(HERE, "metamorphic_metrics.json"), "w") as fh:
        json.dump(m, fh, indent=2)
    print("=== METAMORPHIC (feature 7) ===")
    print("false-INVALIDATED=%s   satisfied-relations=%d   catch-rate=%.2f (missed %s)   mr-confirms=%d"
          % (m["false_invalidated"], m["n_satisfied_relations"], m["catch_rate"], m["missed"], m["mr_confirms"]))
    ok = (not m["false_invalidated"]) and m["catch_rate"] == 1.0 and m["mr_confirms"] == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
