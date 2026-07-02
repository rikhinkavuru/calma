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
  stochastic_fabricated  an unstable metric (varies across k>=5 runs), claim outside the observed range
  static_target_coincidence  a NAME-matched (not library/human/AI-verified) hand-rolled capture target;
                      even a clean coincidental match must not confirm (Cycle-2, runner/target_discovery.py)
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from core import diff as D  # noqa: E402
from core import redteam_gate as RTG  # noqa: E402
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

    # 9. stochastic fabrication: an UNSTABLE metric (varies across k≥5 runs) with a claim OUTSIDE the observed
    # range must NOT reach an affirmative verdict — CONFIRMED-STOCHASTIC included (feature 6 guard).
    sruns = [[call("accuracy", (160 + i) / 200, acc_inputs(200, 160 + i), n=200)] for i in range(6)]
    out.append(("stochastic_fabricated", {"metric": "accuracy", "value": "0.95"}, sruns))

    # 10. static-target coincidence: a hand-rolled function was auto-discovered by NAME MATCH alone
    # (runner/target_discovery.py, Cycle-2) — not a real library call, not a human/AI's judgment. Even when
    # everything lines up (claim == produced == independent recompute, deterministic), a NAME-matched guess
    # must never reach CONFIRMED on its own — same discipline as attack #1's size-matched guess.
    c = call("accuracy", 0.90, acc_inputs(100, 90), n=100, sink="static:target:accuracy")
    out.append(("static_target_coincidence", {"metric": "accuracy", "value": "0.90"}, [[c], [dict(c)]]))
    return out


def honest_confirms():
    """Honest computations that legitimately reach CONFIRMED — the precision guard for feature 8's inline
    gate: it must downgrade ZERO of these (a downgrade here would be a false-REFUTE, not an FCR breach, but
    still a trust cost). Balanced labels, a score well above the trivial baseline, clean equal-length inputs."""
    out = []
    out.append(("honest_accuracy", {"metric": "accuracy", "value": "0.9"},
                [[call("accuracy", 0.9, acc_inputs(20, 18))], [call("accuracy", 0.9, acc_inputs(20, 18))]]))
    out.append(("honest_auc", {"metric": "roc_auc", "value": "0.83"},
                [[call("roc_auc", 0.8333333333, {"y_true": [0, 0, 1, 1, 1, 0], "y_score": [0.1, 0.2, 0.9, 0.7, 0.6, 0.3]}, n=6)],
                 [call("roc_auc", 0.8333333333, {"y_true": [0, 0, 1, 1, 1, 0], "y_score": [0.1, 0.2, 0.9, 0.7, 0.6, 0.3]}, n=6)]]))
    return out


def main():
    rows, breaches = [], []
    gate_breaches, honest_downgrades = [], []
    for name, claim, runs in attacks():
        rec = D.diff_claim(claim, runs)
        v = rec["verdict"]
        # a breach is ANY affirmative verdict on a wrong number — CONFIRMED or the weaker CONFIRMED-STOCHASTIC
        # (feature 6). The gate must guard both; POSITIVE alone would let a stochastic false-affirm slip.
        confirmed = (v in VD.AFFIRMATIVE)
        # inline-gate FCR: re-screen the bound computation and fold through monotone (downgrade-only). The
        # gate can only ever LOWER v, so gated_confirmed ⊆ confirmed — but we assert it explicitly.
        gv = v
        if confirmed:
            base = runs[0] if runs else []
            bc, st, _ = D._bound_call(claim, base)
            if st == "bound" and bc:
                proposed, _reason = RTG.screen(claim.get("metric"), bc, base)
                gv = VD.monotone(v, proposed)
        if gv in VD.AFFIRMATIVE:
            gate_breaches.append(name)
        rows.append({"attack": name, "verdict": v, "gated": gv, "confirmed": confirmed,
                     "reason": rec.get("reason", "")[:120]})
        if confirmed:
            breaches.append(name)
    # precision guard: the gate must NOT downgrade a legitimately-CONFIRMED claim.
    for name, claim, runs in honest_confirms():
        rec = D.diff_claim(claim, runs)
        if rec["verdict"] not in VD.POSITIVE:
            continue  # not a CONFIRMED baseline this env — skip (the gate can't downgrade what didn't confirm)
        base = runs[0]
        bc, st, _ = D._bound_call(claim, base)
        proposed, _r = RTG.screen(claim.get("metric"), bc, base) if (st == "bound" and bc) else (None, None)
        if VD.monotone(rec["verdict"], proposed) != rec["verdict"]:
            honest_downgrades.append(name)
    n = len(rows)
    m = {"n_attacks": n, "breaches": breaches, "adversarial_fcr": round(len(breaches) / n, 4) if n else None,
         "inline_gate_fcr": round(len(gate_breaches) / n, 4) if n else None,
         "gate_breaches": gate_breaches, "honest_downgrades": honest_downgrades}
    with open(os.path.join(HERE, "redteam_metrics.json"), "w") as fh:
        json.dump({**m, "rows": rows}, fh, indent=2)
    print("=== ADVERSARIAL FALSE-CONFIRM gate (#13 — the franchise) ===")
    print("attacks=%d   adversarial-FCR=%s   inline-gate-FCR=%s   [target 0 — ANY breach is a franchise bug]"
          % (n, m["adversarial_fcr"], m["inline_gate_fcr"]))
    for r in rows:
        flag = "  ‼️ BREACH" if r["confirmed"] else ""
        print("  %-18s → %-15s %s%s" % (r["attack"], r["verdict"], r["reason"][:60], flag))
    print("HELD (no attack confirmed):", not breaches)
    print("inline gate held (no honest CONFIRMED downgraded):", not honest_downgrades)
    return 1 if (breaches or gate_breaches or honest_downgrades) else 0


if __name__ == "__main__":
    sys.exit(main())
