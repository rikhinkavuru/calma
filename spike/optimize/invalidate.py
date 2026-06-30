#!/usr/bin/env python
"""optimize.invalidate — the wrong-formula / cheating catch (the moat's core; scoreboard #8 + #11).

The misreport path (claimed != produced -> REFUTED) is the easy catch and is saturated. The HARD, valuable
catch is the INVALIDATED path: the repo computes the metric WRONG (or cheats) and reports its own wrong
number *consistently* — so claimed == produced, but produced != an INDEPENDENT recompute from the same
inputs. This is what the trusted catalog exists for. It was never measured against deliberately-wrong
formulas; this does that.

Injection (replay-friendly, no re-execution): take an honest capture, keep the inputs honest, but PERTURB
the captured `result` (the repo's produced value) and set the claim equal to it — simulating a formula that
computes `wrong` from honest inputs. The independent recompute of the inputs still gives `true`, so:
    claimed == produced == wrong   (passes the REFUTED gate)
    produced (wrong) != recompute (true)   ->  INVALIDATED      [must never be CONFIRMED]

Measures: invalidation_catch_rate (→1), false_confirm_rate (→0, the cardinal sin on the hard path), and the
INVALIDATED-axis sensitivity (the produced-vs-recompute tolerance separation, #11) — far tighter (~1e-6 rel)
than the misreport reporting-precision floor.
"""
from __future__ import annotations

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from core import catalog as C  # noqa: E402
from core import diff as D  # noqa: E402
from core import verdict as VD  # noqa: E402

CAP_DIR = os.path.join(HERE, "captures")
RATE = {"accuracy", "roc_auc", "f1", "precision", "recall", "balanced_accuracy"}


def _clamp(metric, v):
    return min(max(v, 0.0), 1.0) if metric in RATE else v


def headline_metrics(cap):
    """[(metric, true_result)] for unique catalog metrics computed with CAPTURED INPUTS (recompute needs
    them) at a user site."""
    runs = cap.get("runs") or []
    base = runs[0] if runs else []
    by = {}
    for c in base:
        cid = C.canonical(c.get("metric") or "")
        if cid is None or not c.get("captured_full", True) or "inputs" not in c:
            continue
        try:
            f = float(c.get("result"))
        except (TypeError, ValueError):
            continue
        if f != f:
            continue
        by.setdefault(cid, []).append(c)
    out = []
    for cid, calls in by.items():
        user = [c for c in calls if c.get("user_site")]
        pick = user if user else calls
        if len(pick) == 1:
            out.append((cid, float(pick[0]["result"])))
    return out


def perturb(cap, metric, new_result):
    """Deep-copy the capture; set the (unique) metric's produced result to `new_result` in every run, leaving
    its inputs honest. The independent recompute of those inputs will disagree with `new_result`."""
    c2 = copy.deepcopy(cap)
    for run in c2["runs"]:
        for c in run:
            if C.canonical(c.get("metric") or "") == metric:
                c["result"] = new_result
    return c2


RELS = (1e-4, 3e-4, 1e-3, 3e-3, 1e-2, 3e-2, 1e-1, 2e-1)


def evaluate(caps):
    rows = []
    for cap in caps:
        for metric, true in headline_metrics(cap):
            for rel in RELS:
                for s in (1, -1):
                    wrong = _clamp(metric, true * (1 + s * rel))
                    if abs(wrong - true) < 1e-9:
                        continue
                    cap2 = perturb(cap, metric, wrong)
                    rec = D.diff_claim({"metric": metric, "value": "%.6f" % wrong}, cap2["runs"])
                    rows.append({"cap": cap["name"], "metric": metric, "true": round(true, 6),
                                 "wrong": round(wrong, 6), "rel": s * rel, "verdict": rec["verdict"]})
    return rows


def score(rows):
    n = len(rows)
    inval = sum(1 for r in rows if r["verdict"] == VD.INVALIDATED)
    fc = [r for r in rows if r["verdict"] == VD.CONFIRMED]
    other = {}
    for r in rows:
        if r["verdict"] not in (VD.INVALIDATED, VD.CONFIRMED):
            other[r["verdict"]] = other.get(r["verdict"], 0) + 1
    # INVALIDATED-axis MDE: smallest |rel| at which every wrong-formula is caught
    buckets = {}
    for r in rows:
        buckets.setdefault(abs(r["rel"]), []).append(r["verdict"] == VD.INVALIDATED)
    full = [b for b, v in sorted(buckets.items()) if all(v)]
    return {
        "n": n,
        "invalidation_catch_rate": round(inval / n, 4) if n else None,
        "false_confirm_rate": round(len(fc) / n, 4) if n else None,
        "false_confirms": [(r["cap"], r["metric"], r["wrong"], r["true"]) for r in fc],
        "other_verdicts": other,
        "invalidated_axis_mde": ("%.0e" % min(full)) if full else None,
        "catch_by_rel": {("%.0e" % b): round(sum(v) / len(v), 3) for b, v in sorted(buckets.items())},
    }


def main():
    caps = [json.load(open(os.path.join(CAP_DIR, f))) for f in sorted(os.listdir(CAP_DIR))
            if f.endswith(".json")]
    caps = [c for c in caps if c.get("ran_ok")]
    if not caps:
        print("no captures — run capture_fixtures.py first", file=sys.stderr)
        return 1
    rows = evaluate(caps)
    m = score(rows)
    with open(os.path.join(HERE, "invalidation_metrics.json"), "w") as fh:
        json.dump(m, fh, indent=2)
    print("=== WRONG-FORMULA catch (INVALIDATED path — the moat's core) ===")
    print("wrong-formula injections: %d" % m["n"])
    print("INVALIDATION catch (wrong-formula → INVALIDATED): %s   [target →1]" % m["invalidation_catch_rate"])
    print("FALSE-CONFIRM (wrong-formula → CONFIRMED):        %s   [target 0]" % m["false_confirm_rate"])
    print("INVALIDATED-axis MDE (smallest |rel| fully caught): %s" % m["invalidated_axis_mde"])
    print("catch by |rel|: %s" % m["catch_by_rel"])
    if m["other_verdicts"]:
        print("other verdicts (NOT caught as INVALIDATED — investigate):", m["other_verdicts"])
    if m["false_confirms"]:
        print("!! FALSE CONFIRMS:", m["false_confirms"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
