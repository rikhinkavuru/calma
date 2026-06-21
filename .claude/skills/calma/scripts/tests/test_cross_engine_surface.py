"""M3: the cross-engine line is surfaced RIGHT UNDER the verdict (not buried below a not-verified
dump + the exit line), and a metric with NO independent kernel prints an explicit 'no kernel' note
instead of nothing (which used to read as a silent pass). Pure stdlib, offline.
Run: python3 test_cross_engine_surface.py
"""
import os
import sys
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import calma as C  # noqa: E402
import report as REP  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- unit: the three line shapes ---
agree = REP._cross_engine_line({"n_checked": 2, "any_divergence": False, "covered": ["sum"]})
truth("agree with a second independent kernel" in agree, "agree line")
div = REP._cross_engine_line({"n_checked": 1, "any_divergence": True,
                              "metrics": [{"metric": "total_return", "agree": False,
                                           "primary": 1.0, "second": 2.0}]})
truth("DIVERGENCE on total_return" in div, "divergence line")
empty = REP._cross_engine_line({"n_checked": 0, "uncovered": ["auc"],
                                "covered": ["total_return", "sum", "sharpe"]})
truth("no independent kernel for auc" in empty and "covered:" in empty
      and "stands" in empty, "empty line names the metric + the covered set")
# COR-4: a metric that HAS a kernel but was SKIPPED (unsupported convention) must NOT print the
# self-contradiction "no kernel for sharpe (covered: ...sharpe...)".
skipped = REP._cross_engine_line({"n_checked": 0, "uncovered": [], "requested": ["sharpe"],
                                  "covered": ["total_return", "sum", "sharpe"]})
truth("no independent kernel" not in skipped and "did not apply to sharpe" in skipped,
      "COR-4: kernel-skipped says 'did not apply', never 'no kernel' for a covered metric")

# --- integration fixture: a single value column ---
tmp = tempfile.mkdtemp(prefix="calma_m3_")
d = os.path.join(tmp, "proj")
os.makedirs(d)
open(os.path.join(d, "main.py"), "w").write(
    "import csv\n"
    "w=csv.writer(open('out.csv','w',newline=''))\n"
    "w.writerow(['value'])\n"
    "[w.writerow([float(i)]) for i in range(100)]\n")  # sum=4950

# (1) kernel-backed metric, WRONG claim -> REFUTED; cross-engine line must sit ABOVE the details
res = C.verify(d, claim="1000000", metric="column_sum",
               opts=C.VerifyOptions(cross_engine=True, force=True))
rep = res.get("report", "")
truth(res["repo_verdict"] == "REFUTED", "kernel-backed wrong claim REFUTES (got %s)" % res["repo_verdict"])
lines = rep.splitlines()
ce_idx = next((i for i, ln in enumerate(lines) if "cross-engine:" in ln), -1)
scope_idx = next((i for i, ln in enumerate(lines) if "scope:" in ln or "not verified" in ln), 10**6)
truth(ce_idx != -1, "cross-engine line present on a REFUTED")
truth(0 <= ce_idx <= 2, "cross-engine line is near the TOP (line %d)" % ce_idx)
truth(ce_idx < scope_idx, "cross-engine line is ABOVE the not-verified/scope dump")
truth("agree" in lines[ce_idx], "kernel-backed metric reports agreement")

# (2) NO-kernel metric (column_median) -> n_checked==0 -> explicit 'no kernel' note, never silent
res2 = C.verify(d, claim="49.5", metric="column_median",
                opts=C.VerifyOptions(cross_engine=True, force=True))
rep2 = res2.get("report", "")
truth("no independent kernel for column_median" in rep2,
      "no-kernel metric prints an explicit 'no independent kernel' note (not silence)")
truth("covered:" in rep2, "no-kernel note lists the covered metrics")
truth(res2.get("cross_engine", {}).get("n_checked") == 0,
      "n_checked is 0 for a no-kernel metric")
truth("column_median" in (res2.get("cross_engine", {}).get("uncovered") or []),
      "the uncovered metric is named in the cross_engine result")

shutil.rmtree(tmp, ignore_errors=True)
print("cross-engine-surface (M3): %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
