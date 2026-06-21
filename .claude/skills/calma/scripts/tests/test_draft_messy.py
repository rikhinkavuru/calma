"""M5: the heuristic draft is low-touch on a MESSY repo - non-standard column names (strat_return,
y_hat/y_true) and a non-main entrypoint (backtest.py) bind with ZERO hand-edits, and the drafted
contract verifies green. This is the M5 bar: `calma draft` then `calma verify`, no human tuning.
Pure stdlib, offline. Run: python3 test_draft_messy.py
"""
import os
import subprocess
import sys
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import calma as C  # noqa: E402
import draft_contract as DC  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- tag inference on messy quant column names ---
for col, tag in [("strat_return", "return"), ("total_return", "return"),
                 ("cum_return", "return"), ("log_return", "return"), ("pnl", "return")]:
    truth(DC._infer_tag(col) == tag, "tag: %s -> %s" % (col, tag))
for decoy in ["return_code", "returned_items", "net_secret", "asset_retirement",
              "excess_caret", "log_pretty", "fund_retention"]:
    truth(DC._infer_tag(decoy) != "return", "tag: %s is NOT a false return (COR-2)" % decoy)

tmp = tempfile.mkdtemp(prefix="calma_m5_")

# --- a messy backtest repo: entrypoint backtest.py, output results/perf.csv col 'strat_return' ---
repo = os.path.join(tmp, "messy")
os.makedirs(os.path.join(repo, "results"))
with open(os.path.join(repo, "backtest.py"), "w") as fh:
    fh.write("import csv, os\n"
             "os.makedirs('results', exist_ok=True)\n"
             "w = csv.writer(open('results/perf.csv','w',newline=''))\n"
             "w.writerow(['date','strat_return'])\n"
             "[w.writerow([2000+i, r]) for i, r in enumerate([0.01,0.02,-0.01,0.03,0.00])]\n")
# the user has already run it once (artifacts on disk), then points calma at the repo
subprocess.run([sys.executable, "backtest.py"], cwd=repo, check=True)

# draft with NO hand-edits
contract = DC.draft(repo)
truth(contract.get("run", {}).get("entrypoint") == "backtest.py",
      "draft detects the non-main entrypoint (backtest.py)")
mids = [m.get("metric_id") for m in contract.get("metrics", [])]
truth(any(m == "total_return" for m in mids),
      "draft binds total_return off the strat_return column (no hand-edit). got %s" % mids)

# write it like `calma draft` would, then verify - must NOT fail on a missing path/binding
import json  # noqa: E402
with open(os.path.join(repo, "verify.yaml"), "w") as fh:
    json.dump(contract, fh, indent=2)
res = C.verify(repo, opts=C.VerifyOptions(force=True))
truth(res["repo_verdict"] in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS"),
      "drafted contract VERIFIES green with no hand-edits (got %s)" % res["repo_verdict"])

shutil.rmtree(tmp, ignore_errors=True)
print("draft-messy (M5): %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
