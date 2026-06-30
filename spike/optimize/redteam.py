#!/usr/bin/env python
"""optimize.redteam — adversarial false-confirm gate (#13, the franchise).

FCR=0 on honest+misreport injections is necessary but not sufficient: the real test is whether a capture
ENGINEERED to fool the verifier can extract a CONFIRMED. Each attack below targets a specific way a wrong
number could sneak through; the gate is simple and absolute — **no attack may yield CONFIRMED**. A breach is
a franchise-level bug. (Construct-only; no execution.)

Attacks:
  value_coincidence  multi-candidate, claim misreports computation A to computation B's value, no hint
  cheating_formula   claimed==produced but produced != independent recompute (a wrong/hardcoded formula)
  metric_spoof       claim a metric the repo never computed (name mismatch)
  single_class       y_true one class → accuracy vacuous though it recomputes to the claim
  trivial_baseline   accuracy == majority-class baseline (no signal) though it recomputes
  degenerate_nan     a NaN in the inputs → recompute degenerate; a hardcoded result must not confirm
  nondeterministic   the produced value differs across runs; the claim matches run 0 only
  length_mismatch    malformed inputs (len mismatch) → degenerate recompute
"""
from __future__ import annotations

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from core import diff as D  # noqa: E402
from core import verdict as VD  # noqa: E402


def call(metric, result, inputs=None, *, kwargs=None, user_site=True, n=None, seq=0, sink=None):
    inputs = inputs if inputs is not None else {"y_true": [0, 1, 0, 1], "y_pred": [0, 1, 0, 1]}
    return {"metric": metric, "result": result, "inputs": inputs, "kwargs": kwargs or {},
            "user_site": user_site, "captured_full": True,
            "n": n if n is not None else len(next(iter(inputs.values()))),
            "seq": seq, "sink": sink or ("sklearn.metrics.%s_score" % metric), "site": "r.py:%d" % (1 + seq)}


def acc_inputs(n, correct):
    """2-class balanced inputs with exactly `correct`/`n` accuracy (majority baseline = 0.5)."""
    yt = [i % 2 for i in range(n)]
    yp = list(yt)
    for i in range(n - correct):
        yp[i] = 1 - yp[i]
    return {"y_true": yt, "y_pred": yp}


def attacks():
    out = []

    # 1. value-coincidence multi-candidate: claim "0.96" inflates A (true 0.90) to B's value; no hint.
    A = call("accuracy", 0.90, acc_inputs(200, 180), n=200, seq=0)
    B = call("accuracy", 0.96, acc_inputs(50, 48), n=50, seq=1)
    out.append(("value_coincidence", {"metric": "accuracy", "value": "0.96"}, [[A, B], [A, B]]))

    # 2. cheating formula: claimed==produced==0.99 but the inputs recompute to 0.90.
    c = call("accuracy", 0.99, acc_inputs(100, 90), n=100)
    out.append(("cheating_formula", {"metric": "accuracy", "value": "0.99"}, [[c], [dict(c)]]))

    # 3. metric spoof: repo computed accuracy; claim says roc_auc with that value → no candidate.
    c = call("accuracy", 0.83, acc_inputs(100, 83), n=100)
    out.append(("metric_spoof", {"metric": "roc_auc", "value": "0.83"}, [[c], [dict(c)]]))

    # 4. single-class: y_true all one class → accuracy 1.0 vacuous though it recomputes.
    c = call("accuracy", 1.0, {"y_true": [1] * 100, "y_pred": [1] * 100}, n=100)
    out.append(("single_class", {"metric": "accuracy", "value": "1.0"}, [[c], [dict(c)]]))

    # 5. trivial baseline: accuracy == majority-class fraction (no signal).
    c = call("accuracy", 0.90, {"y_true": [0] * 90 + [1] * 10, "y_pred": [0] * 100}, n=100)
    out.append(("trivial_baseline", {"metric": "accuracy", "value": "0.90"}, [[c], [dict(c)]]))

    # 6. degenerate NaN: a NaN score → recompute degenerate; a hardcoded 0.95 must not confirm.
    ys = [0.1, 0.9, 0.2, 0.8, 0.7, float("nan")]
    c = call("roc_auc", 0.95, {"y_true": [0, 1, 0, 1, 1, 0], "y_score": ys}, n=6)
    out.append(("degenerate_nan", {"metric": "roc_auc", "value": "0.95"}, [[c], [dict(c)]]))

    # 7. nondeterministic: produced differs across runs; the claim matches run 0 only.
    r0 = call("accuracy", 0.83, acc_inputs(100, 83), n=100)
    r1 = call("accuracy", 0.80, acc_inputs(100, 80), n=100)
    out.append(("nondeterministic", {"metric": "accuracy", "value": "0.83"}, [[r0], [r1]]))

    # 8. length mismatch: malformed inputs → degenerate recompute.
    c = call("accuracy", 0.90, {"y_true": [0, 1, 0, 1, 1], "y_pred": [0, 1, 0, 1]}, n=5)
    out.append(("length_mismatch", {"metric": "accuracy", "value": "0.90"}, [[c], [dict(c)]]))
    return out


def main():
    rows, breaches = [], []
    for name, claim, runs in attacks():
        rec = D.diff_claim(claim, runs)
        v = rec["verdict"]
        confirmed = (v in VD.POSITIVE)
        rows.append({"attack": name, "verdict": v, "confirmed": confirmed, "reason": rec.get("reason", "")[:120]})
        if confirmed:
            breaches.append(name)
    n = len(rows)
    m = {"n_attacks": n, "breaches": breaches, "adversarial_fcr": round(len(breaches) / n, 4) if n else None}
    with open(os.path.join(HERE, "redteam_metrics.json"), "w") as fh:
        json.dump({**m, "rows": rows}, fh, indent=2)
    print("=== ADVERSARIAL FALSE-CONFIRM gate (#13 — the franchise) ===")
    print("attacks=%d   adversarial-FCR=%s   [target 0 — ANY breach is a franchise bug]"
          % (n, m["adversarial_fcr"]))
    for r in rows:
        flag = "  ‼️ BREACH" if r["confirmed"] else ""
        print("  %-18s → %-15s %s%s" % (r["attack"], r["verdict"], r["reason"][:60], flag))
    print("HELD (no attack confirmed):", not breaches)
    return 1 if breaches else 0


if __name__ == "__main__":
    sys.exit(main())
