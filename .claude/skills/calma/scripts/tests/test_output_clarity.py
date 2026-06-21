"""M6: output-clarity nits. (a) verifying a claim against a contract that commits no value of its
own no longer prints the clunky 'committed claim value (None) is not what is being verified';
(b) the batch table labels a reproduction-only row distinctly from a claim-confirmed one.
Pure stdlib, offline. Run: python3 test_output_clarity.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import calma as C  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- M6a: drafted/binding-only contract (no committed claim value) ---
contract = {"metrics": [{"metric_id": "accuracy", "headline": True,
                         "binding": {"prediction": "pred", "label": "y"},
                         "artifact": "out.csv", "claimed_value": None}]}
note, block = C._reconcile_claim(contract, "accuracy 0.9", None)
truth(block is None, "no block when the claim's metric is pinned")
truth(note and "(None)" not in note, "M6a: the clunky '(None)' phrasing is gone")
truth(note and "commits no claim value of its own" in note,
      "M6a: says plainly the contract commits no claim value")

# --- M6a': a contract that DOES commit a different value reads clearly too ---
contract2 = {"metrics": [{"metric_id": "accuracy", "headline": True,
                          "binding": {"prediction": "pred", "label": "y"},
                          "artifact": "out.csv", "claimed_value": 0.80}]}
note2, _ = C._reconcile_claim(contract2, "accuracy 0.9", None)
truth(note2 and "differs from the contract's committed value" in note2 and "0.8" in note2,
      "M6a': differing committed value is explained, YOUR claim is verified")

# --- M6b: batch table labels reproduction rows distinctly ---
rows = [
    {"target": "claimcheck", "verdict": "CONFIRMED", "metric": "total_return",
     "claimed": 0.35, "recomputed": 0.35, "clean": True},
    {"target": "repro_only", "verdict": "CONFIRMED", "metric": "column_sum",
     "claimed": None, "recomputed": 4950.0, "clean": True},
]
table = C._render_batch(rows)  # returns the rendered string
if isinstance(table, (list, tuple)):
    table = "\n".join(table)
repro_line = next(ln for ln in table.splitlines() if "repro_only" in ln)
claim_line = next(ln for ln in table.splitlines() if "claimcheck" in ln)
truth("(reproduction)" in repro_line, "M6b: reproduction-only row is labelled '(reproduction)'")
truth("(reproduction)" not in claim_line, "M6b: a claim-confirmed row is NOT labelled reproduction")

print("output-clarity (M6): %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
