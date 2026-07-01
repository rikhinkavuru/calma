#!/usr/bin/env python
"""optimize.formula_fuzz_eval — feature 2 meta-eval ("fuzz-the-formula").

Two adversary classes over the fixture callables:
  (a) HONEST + CONVENTION-legit formulas — must NOT be flagged (measure false-INVALIDATED rate);
  (b) CHEATING formulas (wrong denominator / off-by-scale / ignores an input) — must be caught.
And the cardinal gate: a cheat that is COINCIDENTALLY right on the real captured input must never reach
CONFIRMED once the fuzz overlay is on (false_confirm_rate == 0).
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
from core import formula_diff as FZ  # noqa: E402
from core import verdict as VD  # noqa: E402

_LABELS = {"y_true": "arg0", "y_pred": "arg1"}
_CORR = {"x": "arg0", "y": "arg1"}

HONEST = [("honest_accuracy", "accuracy", _LABELS), ("honest_sharpe", "sharpe", {"returns": "arg0"}),
          ("honest_mean", "mean", {"values": "arg0"}), ("honest_mse", "mse", _LABELS),
          ("honest_correlation", "correlation", _CORR)]
CONVENTION = [("sharpe_ddof0", "sharpe", {"returns": "arg0"})]
CHEAT = [("wrong_accuracy", "accuracy", _LABELS), ("scaled_sharpe", "sharpe", {"returns": "arg0"}),
         ("not_correlation", "correlation", _CORR), ("cheat_accuracy", "accuracy", _LABELS)]


def _cases(fn, metric, mapping, seed=7):
    r = reinvoke.fuzz_target({"target": "fuzz_metrics." + fn, "metric": metric, "inputs": mapping}, k=16, seed=seed)
    return r["cases"] if r else []


def _fcr_case():
    """A constant cheat that is COINCIDENTALLY right on the real input (true accuracy 0.95) — CONFIRMED without
    fuzz, must be INVALIDATED with fuzz. Returns the verdict WITH fuzz on."""
    yt = [0, 1] * 10
    yp = list(yt)
    yp[0] = 1 - yp[0]                       # 19/20 = 0.95
    call = {"metric": "accuracy", "result": 0.95, "inputs": {"y_true": yt, "y_pred": yp}, "kwargs": {},
            "user_site": True, "captured_full": True, "n": 20, "seq": 0,
            "sink": "target:fuzz_metrics.cheat_accuracy", "site": "r.py:1"}
    claim = {"id": "c0", "metric": "accuracy", "value": "0.95"}
    runs = [[call], [dict(call)]]
    fuzz = [reinvoke.fuzz_target({"target": "fuzz_metrics.cheat_accuracy", "metric": "accuracy",
                                  "inputs": _LABELS}, k=16, seed=7)]
    baseline = D.diff_claim(claim, runs)["verdict"]
    with_fuzz = D.diff_claim(claim, runs, fuzz=fuzz)["verdict"]
    return baseline, with_fuzz


def measure():
    false_inval = [fn for fn, m, mp in HONEST + CONVENTION if FZ.differential(m, _cases(fn, m, mp))["diverged"]]
    caught = [fn for fn, m, mp in CHEAT if FZ.differential(m, _cases(fn, m, mp))["diverged"]]
    missed = [fn for fn, m, mp in CHEAT if fn not in caught]
    baseline, with_fuzz = _fcr_case()
    n_honest, n_cheat = len(HONEST) + len(CONVENTION), len(CHEAT)
    return {
        "false_invalidated": false_inval,
        "false_invalidated_rate": round(len(false_inval) / n_honest, 4),
        "catch_rate": round(len(caught) / n_cheat, 4),
        "missed": missed,
        "fcr_baseline_verdict": baseline, "fcr_with_fuzz_verdict": with_fuzz,
        "false_confirm_rate": 0.0 if with_fuzz not in VD.POSITIVE else 1.0,
    }


def main():
    m = measure()
    with open(os.path.join(HERE, "formula_fuzz_metrics.json"), "w") as fh:
        json.dump(m, fh, indent=2)
    print("=== FORMULA FUZZ (feature 2) ===")
    print("false-INVALIDATED rate=%.2f %s   catch-rate=%.2f (missed %s)"
          % (m["false_invalidated_rate"], m["false_invalidated"], m["catch_rate"], m["missed"]))
    print("FCR case: baseline=%s  with-fuzz=%s   false-confirm-rate=%.1f [MUST be 0]"
          % (m["fcr_baseline_verdict"], m["fcr_with_fuzz_verdict"], m["false_confirm_rate"]))
    ok = (m["false_confirm_rate"] == 0.0 and m["false_invalidated_rate"] == 0.0 and m["catch_rate"] == 1.0)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
