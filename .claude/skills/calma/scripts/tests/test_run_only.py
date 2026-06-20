"""C3: `calma verify --run-only` - the no-verdict / no-gate debug path the calma_debug MCP tool wraps.
It re-runs + recomputes + diffs and emits the binding + recomputed value + gap, but NEVER assembles a
verdict or gates (always usable mid-task to iterate). On a host that can't verify a sandbox the run is
gracefully inconclusive and the recompute asserts are skipped (never faked). Pure stdlib, offline (the
bundled btc fixture). Run: python3 test_run_only.py
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, SCR)
import calma as C  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


BTC = os.path.realpath(os.path.join(SCR, "..", "assets", "btc"))
tmp = tempfile.mkdtemp()
tgt = os.path.join(tmp, "btc")
shutil.copytree(BTC, tgt, ignore=shutil.ignore_patterns(".calma"))

res = C.verify(tgt, "+14,698%", "total_return", run_id="ro", run_only=True)

if res.get("run_only") is True:
    truth("repo_verdict" not in res and "gate_exit" not in res,
          "run-only: NO verdict and NO gate in the result (pure recompute view)")
    mets = res.get("metrics") or []
    truth(len(mets) == 1 and mets[0]["metric"] == "total_return",
          "run-only: the headline metric is reported")
    m = mets[0]
    truth(m.get("binding") == {"return": "strat_return"}, "run-only: the binding is surfaced")
    truth(isinstance(m.get("recomputed"), float) and m["recomputed"] < 0,
          "run-only: the metric is RECOMPUTED from the raw outputs (btc strategy recomputes negative)")
    truth(isinstance(m.get("gap"), float) and m["gap"] > 100,
          "run-only: the gap vs the claimed +14,698% is reported and large")
    truth(bool(res.get("isolation_tier")) and bool(res.get("run_dir")),
          "run-only: carries the isolation tier + run_dir (proof / raw outputs live there)")
    truth(os.path.exists(os.path.join(res["run_dir"], "diff.json")),
          "run-only: diff.json written (the recompute is real)")
    truth(not os.path.exists(os.path.join(res["run_dir"], "ledger.json")),
          "run-only: NO ledger.json - the verdict path was short-circuited")
else:
    truth(res.get("repo_verdict") == "INCONCLUSIVE" or res.get("refused") or res.get("killed"),
          "run-only: on a non-isolating host the run is gracefully inconclusive (recompute asserts skipped)")
    print("  (run-only: host could not verify a sandbox; recompute asserts skipped)")

shutil.rmtree(tmp, ignore_errors=True)
print("run_only: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
