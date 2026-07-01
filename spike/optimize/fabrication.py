#!/usr/bin/env python
"""optimize.fabrication — feature 10 meta-eval (perturbation-fabrication).

Three fixture classes:
  (a) a genuinely-computed metric — must NOT be flagged;
  (b) a hard-coded literal EQUAL to the true value — must be caught;
  (c) a hard-coded literal OFF the true value — must be caught.
Reports fabrication catch-rate (must catch b, c), false-fabrication-flag rate on genuine metrics (target 0),
and the cardinal false_confirm_rate (a coincidentally-right constant must not reach CONFIRMED with fuzz on).
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
from core import diff as D  # noqa: E402
from core import perturb as PB  # noqa: E402
from core import verdict as VD  # noqa: E402

_LABELS = {"y_true": "arg0", "y_pred": "arg1"}

# (a) genuine, (b/c) hard-coded constants. cheat_accuracy returns 0.95 regardless of inputs.
GENUINE = [("honest_accuracy", "accuracy", _LABELS), ("honest_sharpe", "sharpe", {"returns": "arg0"}),
           ("honest_mean", "mean", {"values": "arg0"})]
FABRICATED = [("cheat_accuracy", "accuracy", _LABELS)]     # constant 0.95


def _cases(fn, metric, mapping, seed=5):
    r = reinvoke.fuzz_target({"target": "fuzz_metrics." + fn, "metric": metric, "inputs": mapping}, k=16, seed=seed)
    return r["cases"] if r else []


def _fcr_verdict(real_acc):
    """cheat_accuracy (constant 0.95) with a real input whose true accuracy == `real_acc`. When real_acc==0.95
    the constant is coincidentally right (would-be CONFIRMED); the fabrication overlay must invalidate it."""
    yt = [0, 1] * 10
    yp = list(yt)
    n_wrong = round((1 - real_acc) * 20)
    for i in range(n_wrong):
        yp[i] = 1 - yp[i]
    call = {"metric": "accuracy", "result": 0.95, "inputs": {"y_true": yt, "y_pred": yp}, "kwargs": {},
            "user_site": True, "captured_full": True, "n": 20, "seq": 0,
            "sink": "target:fuzz_metrics.cheat_accuracy", "site": "r.py:1"}
    claim = {"id": "c0", "metric": "accuracy", "value": "0.95"}
    fuzz = [reinvoke.fuzz_target({"target": "fuzz_metrics.cheat_accuracy", "metric": "accuracy",
                                  "inputs": _LABELS}, k=16, seed=5)]
    return D.diff_claim(claim, [[call], [dict(call)]], fuzz=fuzz)["verdict"]


def measure():
    false_flag = [fn for fn, m, mp in GENUINE if PB.fabrication_from_fuzz(_cases(fn, m, mp)) is not None]
    caught = [fn for fn, m, mp in FABRICATED if PB.fabrication_from_fuzz(_cases(fn, m, mp)) is not None]
    missed = [fn for fn, m, mp in FABRICATED if fn not in caught]
    coincident = _fcr_verdict(0.95)     # constant coincidentally right on the real input
    return {"false_fabrication_flag": false_flag,
            "false_fabrication_flag_rate": round(len(false_flag) / len(GENUINE), 4),
            "catch_rate": round(len(caught) / len(FABRICATED), 4), "missed": missed,
            "coincident_verdict": coincident,
            "false_confirm_rate": 0.0 if coincident not in VD.POSITIVE else 1.0}


def main():
    m = measure()
    with open(os.path.join(HERE, "fabrication_metrics.json"), "w") as fh:
        json.dump(m, fh, indent=2)
    print("=== FABRICATION (feature 10) ===")
    print("catch-rate=%.2f (missed %s)   false-flag-rate=%.2f %s"
          % (m["catch_rate"], m["missed"], m["false_fabrication_flag_rate"], m["false_fabrication_flag"]))
    print("coincident-constant verdict=%s   false-confirm-rate=%.1f [MUST be 0]"
          % (m["coincident_verdict"], m["false_confirm_rate"]))
    ok = (m["false_confirm_rate"] == 0.0 and m["false_fabrication_flag_rate"] == 0.0 and m["catch_rate"] == 1.0)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
