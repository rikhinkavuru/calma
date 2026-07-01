#!/usr/bin/env python
"""optimize.xcheck_eval — feature 17 meta-eval (differential recompute).

Injects a deliberately BUGGY shadow oracle and asserts the cross-check catches the disagreement and DOWNGRADES
(never confirms through a divergent oracle); on an HONEST agreeing shadow, asserts agreement introduces no new
false REFUTED/INVALIDATED and the CONFIRMED count is unchanged (agreement is the common case).
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from core import catalog as C  # noqa: E402
from core import diff as D  # noqa: E402
from core import verdict as VD  # noqa: E402


def _acc_call(acc=0.9, n=100):
    correct = round(acc * n)
    yt = [i % 2 for i in range(n)]
    yp = list(yt)
    for i in range(n - correct):
        yp[i] = 1 - yp[i]
    real = sum(1 for a, b in zip(yt, yp) if a == b) / n
    return {"metric": "accuracy", "result": real, "inputs": {"y_true": yt, "y_pred": yp}, "kwargs": {},
            "user_site": True, "captured_full": True, "n": n, "seq": 0,
            "sink": "sklearn.metrics.accuracy_score", "site": "r.py:1"}


def _honest_shadow(metric, inputs, kwargs):
    return C.recompute(metric, inputs, kwargs)              # agrees with the primary


def _buggy_shadow(metric, inputs, kwargs):
    r = C.recompute(metric, inputs, kwargs)
    return {**r, "value": r["value"] + 0.1}                 # a divergent (buggy) oracle


def measure():
    call = _acc_call(0.9)
    claim = {"metric": "accuracy", "value": "%.4f" % call["result"]}
    runs = [[call], [dict(call)]]
    base = D.diff_claim(claim, runs)["verdict"]
    honest = D.diff_claim(claim, runs, shadow=_honest_shadow)["verdict"]
    buggy = D.diff_claim(claim, runs, shadow=_buggy_shadow)["verdict"]
    return {"baseline": base, "with_honest_shadow": honest, "with_buggy_shadow": buggy,
            "agreement_preserves_confirm": base == VD.CONFIRMED and honest == VD.CONFIRMED,
            "disagreement_downgrades": buggy not in VD.AFFIRMATIVE,
            "false_confirm_rate": 0.0 if buggy not in VD.AFFIRMATIVE else 1.0}


def main():
    m = measure()
    with open(os.path.join(HERE, "xcheck_metrics.json"), "w") as fh:
        json.dump(m, fh, indent=2)
    print("=== DIFFERENTIAL RECOMPUTE (feature 17) ===")
    print("baseline=%s  +honest-shadow=%s  +buggy-shadow=%s"
          % (m["baseline"], m["with_honest_shadow"], m["with_buggy_shadow"]))
    print("agreement preserves CONFIRM=%s  disagreement downgrades=%s  FCR=%.1f"
          % (m["agreement_preserves_confirm"], m["disagreement_downgrades"], m["false_confirm_rate"]))
    ok = m["agreement_preserves_confirm"] and m["disagreement_downgrades"] and m["false_confirm_rate"] == 0.0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
