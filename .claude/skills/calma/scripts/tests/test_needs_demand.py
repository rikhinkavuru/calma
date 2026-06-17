"""CAN'T-CONFIRM -> a STRUCTURED demand. needs_demand(led) turns an INCONCLUSIVE outcome into "what
could not be verified + exactly what to provide", reusing a driving finding's reverify.source (precise)
and falling back to a reason->needs table for the guard paths. It returns None on any non-INCONCLUSIVE
outcome (a wrong number needs a fix, not more inputs). Pure stdlib, offline.
Run: python3 test_needs_demand.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import report as REP  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def _led(repo, claim, findings=None):
    return {"repo_verdict": repo, "claims": [claim], "findings": findings or []}


# 1) a DRIVING finding maps reverify.source -> concrete inputs
led1 = _led(V.INCONCLUSIVE,
            {"headline": True, "verdict": V.INCONCLUSIVE, "driving_dimension": "leakage",
             "reason": "a validity concern cannot be adjudicated as claimed (declare the scope - see fix)"},
            [{"dimension": "leakage", "locator": "held-out set may be contaminated",
              "unblock": "rebuild the split", "reverify": {"kind": "requires-reexecution",
              "source": "split", "expected": "no train/test contamination"}}])
nd1 = REP.needs_demand(led1)
truth(nd1 and nd1["unverifiable"] == "train/test leakage", "source=split -> 'train/test leakage'")
truth(nd1 and any("split" in p for p in nd1["provide"]), "split demand names the split to provide")
truth(nd1 and nd1["reverify"] and nd1["reverify"]["source"] == "split",
      "the structured reverify hint is passed through verbatim")
truth(nd1 and set(nd1) == {"unverifiable", "reason", "provide", "reverify", "until_then"},
      "shape: the five-key structured demand")

# 2) a guard-path INCONCLUSIVE (no finding) -> the reason->needs table
nd2 = REP.needs_demand(_led(V.INCONCLUSIVE,
      {"headline": True, "verdict": V.INCONCLUSIVE,
       "reason": "untrusted code/deps with no verified isolation tier"}))
truth(nd2 and nd2["unverifiable"] == "isolation" and any("isolation" in p for p in nd2["provide"]),
      "untrusted-code reason -> an isolation demand")
truth(nd2 and nd2["reverify"] is None, "guard-path demand carries no reverify hint")

nd3 = REP.needs_demand(_led(V.INCONCLUSIVE,
      {"headline": True, "verdict": V.INCONCLUSIVE,
       "reason": "no recomputed numeric to compare against the claim"}))
truth(nd3 and nd3["unverifiable"] == "the headline number", "no-numeric reason -> 'the headline number'")

nd4 = REP.needs_demand(_led(V.INCONCLUSIVE,
      {"headline": True, "verdict": V.INCONCLUSIVE,
       "reason": "the number reproduces, but a validity concern cannot be adjudicated as claimed "
                 "(declare the scope - see fix)"}))
truth(nd4 and nd4["unverifiable"] == "validity scope", "unresolved-scope reason -> 'validity scope'")

# 2b) a precise recompute/binding error beats the generic reason mapping
nd_rce = REP.needs_demand(_led(V.INCONCLUSIVE,
      {"headline": True, "verdict": V.INCONCLUSIVE, "recompute_error": "column 'prediction' not found in the artifact",
       "reason": "NaN/Inf/degenerate recompute - data-cleaning policy undetermined"}))
truth(nd_rce and nd_rce["unverifiable"] == "the metric binding"
      and any("prediction" in p for p in nd_rce["provide"]),
      "a recompute_error -> a binding demand naming the real blocker (not the generic na_policy)")

# 3) NOT emitted on a decided outcome - a wrong number needs a fix, not more inputs
truth(REP.needs_demand(_led(V.CONFIRMED,
      {"headline": True, "verdict": V.CONFIRMED, "reason": "matches within budget"})) is None,
      "CONFIRMED -> no demand")
truth(REP.needs_demand(_led(V.REFUTED,
      {"headline": True, "verdict": V.REFUTED, "reason": "differs beyond budget"},
      [{"dimension": "leakage", "reverify": {"source": "split"}}])) is None,
      "REFUTED -> no demand (even with a finding present)")

# 4) fallback: an INCONCLUSIVE whose reason matches no needle + no finding -> empty provide, still typed
nd5 = REP.needs_demand(_led(V.INCONCLUSIVE,
      {"headline": True, "verdict": V.INCONCLUSIVE, "reason": "an unrecognized situation"}))
truth(nd5 and nd5["provide"] == [] and nd5["unverifiable"] == "the claim",
      "unmatched INCONCLUSIVE -> typed demand with an empty provide list (never crashes)")

print("needs_demand: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
