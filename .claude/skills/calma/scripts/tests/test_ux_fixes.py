"""UX-audit MEDIUM regressions: (1) a degenerate-recompute fix-line must name the ROOT cause (the unreadable
artifact) ahead of a secondary validity-family unblock (the misleading-fix bug); (2) `batch` must not
double-count a target given BOTH positionally and in the --manifest (the manifest row wins). Pure stdlib.
Run: python3 test_ux_fixes.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import calma  # noqa: E402
import report as RP  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# (1) fix-line priority: recompute_error (root) beats a validity finding's unblock (secondary)
led = {"repo_verdict": "INCONCLUSIVE",
       "claims": [{"headline": True, "verdict": "INCONCLUSIVE",
                   "recompute_error": "binding failed: artifact predictions.csv is not a regular file",
                   "reason": "degenerate recompute"}],
       "findings": [{"dimension": "leakage", "unblock": "the leakage check was declared (split:) but its "
                     "file(s) could not be read - fix the split paths and re-verify"}]}
fx = RP._fix_line(led)
truth(fx and "predictions.csv" in fx and "split paths" not in fx,
      "fix-line: a missing-artifact degenerate recompute names predictions.csv, not the split red-herring")

# a REFUTED/INVALIDATED ledger has NO recompute_error -> the finding unblock still drives the fix (unchanged)
led2 = {"repo_verdict": "INVALIDATED",
        "claims": [{"headline": True, "verdict": "INVALIDATED", "reason": "validity"}],
        "findings": [{"dimension": "leakage", "unblock": "use a clean held-out split, then recompute"}]}
truth(RP._fix_line(led2) == "use a clean held-out split, then recompute",
      "fix-line: a reproduced-but-invalid verdict still leads with the validity finding's unblock (unchanged)")

# (2) batch dedup: a dir given positionally AND in the manifest -> one job, the manifest claim wins
d = tempfile.mkdtemp(prefix="calma_uxb_")
good = os.path.join(d, "good")
os.makedirs(good)
man = os.path.join(d, "m.tsv")
open(man, "w").write("%s\tf1 0.9\tf1\n" % good)
jobs = calma._batch_jobs([good], man)
truth(len(jobs) == 1, "batch: a dir given positionally + in the manifest is ONE job (no double-count)")
truth(jobs and jobs[0][1] == "f1 0.9", "batch: the manifest claim wins over the bare positional reproduction")
# a positional-only dir (not in the manifest) still runs as a no-claim reproduction
jobs2 = calma._batch_jobs([good], None)
truth(len(jobs2) == 1 and jobs2[0][1] is None, "batch: a positional-only dir is still a no-claim reproduction")

print("ux_fixes: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
