#!/usr/bin/env python
"""optimize.binding — the binding meta-eval (#4 + #5 on the scoreboard).

Binding is the bottleneck (corpus 58%) and the lever on real catch-rate (catch is coverage-bounded). The
go/no-go harness measures binding *rate* (bound-at-all) on real repos, but two things it does NOT separate:

  bind_rate         of cases with a unique correct answer, did we bind?            (coverage; → ≥0.85)
  bind_correctness  of those we bound, did we bind to the RIGHT call?              (safety; → 1.0)
  over_bind_rate    of genuinely-ambiguous cases, did we WRONGLY bind one anyway?  (the dangerous failure;
                    a wrong binding can manufacture a false CONFIRM/REFUTE — must be 0)
  fail_closed_rate  of ambiguous cases, did we refuse (→ INCONCLUSIVE)?            (→ 1.0)

We measure on SYNTHETIC multi-candidate captures (constructed, not executed — binding reads only call
metadata: metric / n / user_site / sink / seq / hint), so we can cover the disambiguation cases exhaustively
and instantly. Each call carries an `id`; the correct one is "CORRECT", so we can read back exactly which
call the binder chose. (Real multi-candidate repos validate that these conclusions transfer — a later step.)
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from core import diff as D  # noqa: E402


def call(metric, n, *, user_site=True, sink=None, seq=0, result=0.5, cid="x"):
    """A synthetic captured-call dict with the fields the binder consumes. `cid` is an identity tag the
    binder ignores — we read it back to check WHICH call got bound."""
    return {"metric": metric, "n": n, "user_site": user_site,
            "sink": sink or ("sklearn.metrics.%s_score" % metric),
            "site": "repo.py:%d" % (10 + seq), "seq": seq, "result": result,
            "captured_full": True, "kwargs": {},
            "inputs": {"y_true": [0, 1, 0, 1], "y_pred": [0, 1, 0, 1]}, "id": cid}


def _scn(name, claim, calls, expect):
    """expect: ("bind","CORRECT") | ("ambiguous",) | ("unbound",)."""
    return {"name": name, "claim": claim, "calls": calls, "expect": expect}


def scenarios():
    A = "accuracy"
    out = [
        # ---- should bind to a unique correct call --------------------------------------------------
        _scn("unique", {"metric": A},
             [call(A, 100, seq=0, cid="CORRECT")], ("bind", "CORRECT")),
        _scn("gridsearch_collapse", {"metric": A},
             [call(A, 100, user_site=False, seq=i, cid="lib%d" % i) for i in range(31)]
             + [call(A, 100, user_site=True, seq=99, cid="CORRECT")], ("bind", "CORRECT")),
        _scn("train_test_diffsize_hint", {"metric": A, "split": "test"},
             [call(A, 400, seq=0, cid="TRAIN"), call(A, 100, seq=1, cid="CORRECT")], ("bind", "CORRECT")),
        _scn("train_split_diffsize_hint", {"metric": A, "split": "train"},
             [call(A, 400, seq=0, cid="CORRECT"), call(A, 100, seq=1, cid="TEST")], ("bind", "CORRECT")),
        _scn("samesize_occurrence_hint", {"metric": A, "bind": {"occurrence": 1}},
             [call(A, 500, seq=0, cid="TRAIN"), call(A, 500, seq=1, cid="CORRECT")], ("bind", "CORRECT")),
        _scn("multimodel_sink_hint", {"metric": A, "bind": {"sink": "modelB"}},
             [call(A, 100, sink="modelA", seq=0, cid="A"),
              call(A, 100, sink="modelB", seq=1, cid="CORRECT")], ("bind", "CORRECT")),
        # ---- should REFUSE (genuinely ambiguous — fail closed) -------------------------------------
        _scn("train_test_diffsize_nohint", {"metric": A},
             [call(A, 400, seq=0, cid="TRAIN"), call(A, 100, seq=1, cid="TEST")], ("ambiguous",)),
        _scn("samesize_nohint", {"metric": A},
             [call(A, 500, seq=0, cid="TRAIN"), call(A, 500, seq=1, cid="TEST")], ("ambiguous",)),
        _scn("kfold_5", {"metric": A},
             [call(A, 100, seq=i, cid="fold%d" % i) for i in range(5)], ("ambiguous",)),
        _scn("multimodel_nohint", {"metric": A},
             [call(A, 100, sink="modelA", seq=0, cid="A"),
              call(A, 120, sink="modelB", seq=1, cid="B")], ("ambiguous",)),
        # ---- OPEN: real corpus failures, currently (correctly) fail closed -------------------------
        # iris-codealpha: GridSearchCV emits 31 internal accuracy calls + SEVERAL user-site evals (train
        # score + held-out score, different n). No split hint → after collapsing library-internal, 2
        # user-site candidates remain → ambiguous. The Cycle-1 fix target is to bind the held-out (smallest)
        # user-site computation WITHOUT value-proximity (worst case a false REFUTE, never a false CONFIRM —
        # franchise-sensitive per memory). Until that's deliberately designed, INCONCLUSIVE is the right call.
        _scn("gridsearch_multi_usersite", {"metric": A},
             [call(A, 120, user_site=False, seq=i, cid="cv%d" % i) for i in range(31)]
             + [call(A, 120, user_site=True, seq=40, cid="TRAIN"),
                call(A, 30, user_site=True, seq=41, cid="HELDOUT")], ("ambiguous",)),
        # digits-softmax: hand-rolled numpy accuracy, no sklearn sink → nothing captured → unbound.
        # Cycle-2 fix: a value-recompute fallback from captured predictions. Until then, fail closed.
        _scn("hand_rolled_uncaptured", {"metric": A}, [], ("unbound",)),
        # ---- should be unbound (no candidate) ------------------------------------------------------
        _scn("no_candidate", {"metric": A}, [call("f1", 100, seq=0, cid="F1")], ("unbound",)),
    ]
    return out


def measure(scns):
    should_bind = [s for s in scns if s["expect"][0] == "bind"]
    should_refuse = [s for s in scns if s["expect"][0] in ("ambiguous", "unbound")]
    bound, correct, over_bound, failed_closed = 0, 0, 0, 0
    detail = []
    for s in scns:
        c, status, reason = D._bound_call(s["claim"], s["calls"])
        got_id = (c or {}).get("id")
        row = {"name": s["name"], "expect": s["expect"][0], "status": status, "bound_id": got_id}
        if s["expect"][0] == "bind":
            if status == "bound":
                bound += 1
                if got_id == "CORRECT":
                    correct += 1
                else:
                    row["BUG"] = "bound to %r, expected CORRECT" % got_id
            else:
                row["BUG"] = "should have bound (got %s)" % status
        else:  # should refuse
            if status == "bound":
                over_bound += 1
                row["DANGER"] = "bound an ambiguous case to %r" % got_id
            else:
                failed_closed += 1
        detail.append(row)

    def rate(num, den):
        return round(num / den, 4) if den else None
    m = {
        "n_scenarios": len(scns), "n_should_bind": len(should_bind), "n_should_refuse": len(should_refuse),
        "bind_rate": rate(bound, len(should_bind)),
        "bind_correctness": rate(correct, bound),
        "bind_correct_overall": rate(correct, len(should_bind)),
        "over_bind_rate": rate(over_bound, len(should_refuse)),
        "fail_closed_rate": rate(failed_closed, len(should_refuse)),
        "bugs": [d for d in detail if "BUG" in d],
        "dangers": [d for d in detail if "DANGER" in d],
        "detail": detail,
    }
    return m


def main():
    m = measure(scenarios())
    with open(os.path.join(HERE, "binding_metrics.json"), "w") as fh:
        json.dump(m, fh, indent=2)
    print("=== BINDING meta-eval (synthetic multi-candidate corpus) ===")
    print("scenarios=%d  should-bind=%d  should-refuse=%d" %
          (m["n_scenarios"], m["n_should_bind"], m["n_should_refuse"]))
    print("BIND rate         (should-bind → bound):     %s   [target ≥0.85]" % m["bind_rate"])
    print("BIND correctness  (of bound → right call):   %s   [target 1.0]" % m["bind_correctness"])
    print("OVER-BIND rate    (ambiguous → wrongly bound):%s  [target 0]" % m["over_bind_rate"])
    print("FAIL-CLOSED rate  (ambiguous → refused):     %s   [target 1.0]" % m["fail_closed_rate"])
    if m["dangers"]:
        print("!! DANGERS (over-binding — can manufacture a false verdict):")
        for d in m["dangers"]:
            print("   ", d)
    if m["bugs"]:
        print(".. bind misses / wrong-call:")
        for d in m["bugs"]:
            print("   ", d)
    if not m["dangers"] and not m["bugs"]:
        print("all scenarios resolved as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
