#!/usr/bin/env python
"""optimize.stochastic — feature 6 meta-eval (statistical/distribution verification).

Synthesizes UNSTABLE runs (each run recomputes to its own produced value, so the formula check passes and only
the run-to-run spread drives the verdict) and sweeps the claim offset + k. Reports:
  * false_confirm_rate — a claim CLEARLY outside the distribution that reaches CONFIRMED-STOCHASTIC (MUST be 0);
  * honest_confirm_rate — an in-distribution claim reaching CONFIRMED-STOCHASTIC;
  * catch_rate — a far misreport driven to REFUTED/INCONCLUSIVE;
  * low_k_confirms — below k_min, CONFIRMED-STOCHASTIC must NEVER fire (power gate; MUST be 0).
"""
from __future__ import annotations

import json
import os
import random
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from core import diff as D  # noqa: E402
from core import interval as I  # noqa: E402
from core import verdict as VD  # noqa: E402


def _acc_call(acc, n=200, seq=0):
    correct = max(1, min(n - 1, round(acc * n)))
    yt = [i % 2 for i in range(n)]
    yp = list(yt)
    for i in range(n - correct):
        yp[i] = 1 - yp[i]
    real = sum(1 for a, b in zip(yt, yp) if a == b) / n
    return {"metric": "accuracy", "result": real, "inputs": {"y_true": yt, "y_pred": yp}, "kwargs": {},
            "user_site": True, "captured_full": True, "n": n, "seq": seq,
            "sink": "sklearn.metrics.accuracy_score", "site": "r.py:1"}


def _runs(accs):
    return [[_acc_call(a)] for a in accs]


def verdict_for(true, sd, k, claim_val, seed):
    r = random.Random(seed)
    accs = [min(0.999, max(0.001, r.gauss(true, sd))) for _ in range(k)]
    claim = {"metric": "accuracy", "value": "%.4f" % claim_val}
    return D.diff_claim(claim, _runs(accs))["verdict"], accs


def measure(trials=40):
    true, sd = 0.85, 0.02
    false_confirms = honest_confirms = caught = low_k_confirms = 0
    n_honest = n_far = n_lowk = 0
    for s in range(trials):
        r = random.Random(1000 + s)
        base = [min(0.999, max(0.001, r.gauss(true, sd))) for _ in range(8)]
        center = statistics.fmean(base)
        iv = I.predict_interval(base)
        width = (iv["hi"] - iv["lo"]) or 0.1
        # honest: claim at the center (in-distribution)
        v_h, _ = verdict_for(true, sd, 8, center, 1000 + s)
        n_honest += 1
        if v_h == VD.CONFIRMED_STOCHASTIC:
            honest_confirms += 1
        # far misreport: claim 2 interval-widths beyond an edge (clearly wrong)
        v_f, _ = verdict_for(true, sd, 8, iv["hi"] + 2 * width, 1000 + s)
        n_far += 1
        if v_f in VD.AFFIRMATIVE:
            false_confirms += 1                      # a clearly-wrong number confirmed → an FCR breach
        if v_f in (VD.REFUTED, VD.INCONCLUSIVE):
            caught += 1
        # low-k: only 2 runs — no power; must never CONFIRMED-STOCHASTIC even at the center
        v_l, _ = verdict_for(true, sd, 2, center, 1000 + s)
        n_lowk += 1
        if v_l == VD.CONFIRMED_STOCHASTIC:
            low_k_confirms += 1
    return {"false_confirm_rate": round(false_confirms / max(1, n_far), 4),
            "honest_confirm_rate": round(honest_confirms / max(1, n_honest), 4),
            "catch_rate": round(caught / max(1, n_far), 4),
            "low_k_confirms": low_k_confirms, "trials": trials}


def main():
    m = measure()
    with open(os.path.join(HERE, "stochastic_metrics.json"), "w") as fh:
        json.dump(m, fh, indent=2)
    print("=== STOCHASTIC / DISTRIBUTION (feature 6) ===")
    print("false-confirm-rate=%.2f [MUST be 0]   honest-confirm-rate=%.2f   catch-rate=%.2f   low-k-confirms=%d"
          % (m["false_confirm_rate"], m["honest_confirm_rate"], m["catch_rate"], m["low_k_confirms"]))
    ok = m["false_confirm_rate"] == 0.0 and m["low_k_confirms"] == 0 and m["honest_confirm_rate"] >= 0.8
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
