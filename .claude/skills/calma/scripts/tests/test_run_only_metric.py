"""M2: --run-only is a no-verdict / no-gate DEBUG view, so --metric must be free to explore a
metric the committed contract does NOT pin (the "let me just see my Sharpe" iteration). The normal
verify path must STILL refuse a metric the contract doesn't pin (verdict integrity is untouched).
Pure stdlib, offline. Run: python3 test_run_only_metric.py
"""
import json
import os
import shutil
import sys
import tempfile

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


tmp = tempfile.mkdtemp(prefix="calma_m2_")
d = os.path.join(tmp, "proj")
os.makedirs(d)
with open(os.path.join(d, "main.py"), "w") as fh:
    fh.write("import csv\n"
             "w = csv.writer(open('out.csv','w',newline=''))\n"
             "w.writerow(['value'])\n"
             "[w.writerow([float(i)]) for i in range(100)]\n")  # sum=4950, mean=49.5
# a COMMITTED contract that pins column_sum on the value column
with open(os.path.join(d, "verify.yaml"), "w") as fh:
    json.dump({"run": {"entrypoint": "main.py", "network": "off", "cwd": "."},
               "env": {"ecosystem": "auto", "trust": "own-code"},
               "artifacts": [{"path": "out.csv", "columns": {"value": {"tag": "value"}}}],
               "metrics": [{"metric_id": "column_sum", "artifact": "out.csv",
                            "binding": {"value": "value"}, "claimed_value": 4950}]},
              fh)

# --- M2: run-only explores a DIFFERENT metric (column_mean) with NO verdict ---
res = C.verify(d, metric="column_mean", opts=C.VerifyOptions(run_only=True))
truth(res.get("run_only") is True, "run-only --metric returns a no-verdict debug view")
mean_row = next((m for m in res.get("metrics", []) if m.get("metric") == "column_mean"), None)
truth(mean_row is not None, "run-only explored the requested metric (column_mean)")
truth(mean_row and abs(mean_row.get("recomputed", 0) - 49.5) < 1e-9,
      "run-only recomputed the requested metric correctly (mean=49.5, got %s)"
      % (mean_row or {}).get("recomputed"))
truth("repo_verdict" not in res, "run-only emits NO verdict")

# --- integrity intact: the NORMAL path still refuses a metric the contract doesn't pin ---
res2 = C.verify(d, metric="column_mean", opts=C.VerifyOptions(force=True))
truth(res2.get("repo_verdict") not in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED"),
      "normal path does NOT silently verify an unpinned metric (got %s)" % res2.get("repo_verdict"))
findings = " ".join(f.get("locator", "") for f in (res2.get("ledger", {}).get("findings") or []))
truth("refusing to verify a claim you didn't make" in findings,
      "normal path keeps the 'refusing to verify a claim you didn't make' guard")

# --- run-only on the SAME metric the contract pins still works (no re-draft needed) ---
res3 = C.verify(d, metric="column_sum", opts=C.VerifyOptions(run_only=True))
truth(res3.get("run_only") is True and any(m.get("metric") == "column_sum"
                                           for m in res3.get("metrics", [])),
      "run-only on the pinned metric works unchanged")

# --- COR-1: run-only NEVER emits a verdict, even when there's nothing to recompute ---
# (a) no entrypoint -> MANUAL: must return a no-verdict run_only view, not an INCONCLUSIVE verdict
manual = os.path.join(tmp, "manual")
os.makedirs(manual)
with open(os.path.join(manual, "data.csv"), "w") as fh:
    fh.write("value\n1\n2\n3\n")   # data but no runnable entrypoint
res_m = C.verify(manual, metric="column_sum", opts=C.VerifyOptions(run_only=True))
truth(res_m.get("run_only") is True, "run-only on a no-entrypoint repo returns a run_only view")
truth("repo_verdict" not in res_m, "run-only on MANUAL emits NO verdict (COR-1)")
truth(res_m.get("metrics") == [] and res_m.get("note"),
      "run-only on MANUAL explains there's nothing to recompute")
# (b) a conflicting CLAIM (no --metric) on a committed contract: still no verdict
res_c = C.verify(d, "sharpe 1.2", opts=C.VerifyOptions(run_only=True))
truth(res_c.get("run_only") is True and "repo_verdict" not in res_c,
      "run-only with a conflicting claim returns a run_only view, NO verdict (COR-1)")

# --- COR-5: run-only ALSO surfaces --cross-engine (computed + returned, not silently discarded) ---
res_ce = C.verify(d, metric="column_sum",
                  opts=C.VerifyOptions(run_only=True, cross_engine=True, force=True))
truth(res_ce.get("run_only") is True
      and (res_ce.get("cross_engine") or {}).get("n_checked", 0) >= 1,
      "run-only --cross-engine returns the cross-engine block (n_checked>=1)")

shutil.rmtree(tmp, ignore_errors=True)
print("run-only-metric (M2): %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
