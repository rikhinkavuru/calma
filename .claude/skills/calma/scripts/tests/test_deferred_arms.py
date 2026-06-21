"""T2: the three deferred arms get EXERCISED, not just claimed - to the extent possible offline.
  D2 (benchmark agent arm)   - the --mock backend runs the full plumbing + scoring offline.
  C4 (per-framework vectors)  - the contract half: every starter contract validates + binds.
  draft --ai                  - the fallback path: with no edges deps / API key it degrades to the
                                heuristic draft instead of crashing.
The REAL-agent run (needs ANTHROPIC_API_KEY) and framework-GENERATED vectors (need the frameworks
installed) remain gated CI jobs - documented, not silently skipped. Pure stdlib offline.
Run: python3 test_deferred_arms.py
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import shutil
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(SCR, "..", "..", "..", ".."))
sys.path.insert(0, SCR)
import calma as C  # noqa: E402
import draft_contract as DC  # noqa: E402
import frameworks as FW  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- D2: the mock agent arm runs the whole plumbing offline (no API key, no network) ---
agent = os.path.join(ROOT, "benchmark", "run_agent.py")
if os.path.isfile(agent):
    r = subprocess.run([sys.executable, agent, "--mock", "--limit", "2"],
                       cwd=ROOT, capture_output=True, text=True, timeout=180)
    out = r.stdout + r.stderr
    truth(r.returncode == 0, "D2: mock agent arm exits 0 (plumbing works offline)")
    truth("MOCK" in out and "wrote results/agent.json" in out,
          "D2: mock arm writes results/agent.json and flags itself MOCK (never reported as real)")
    aj = os.path.join(ROOT, "benchmark", "results", "agent.json")
    if os.path.isfile(aj):
        data = json.load(open(aj))
        truth(isinstance(data, list) and data
              and all("reruns" in rec and "unstable" in rec for rec in data),
              "D2: agent.json is per-case records carrying reruns/unstable (the instability shape)")
else:
    truth(False, "D2: benchmark/run_agent.py is missing")

# --- C4: every starter contract validates + binds its headline metric (the testable half) ---
for fw in FW.list_frameworks():
    contract = FW.starter_contract(fw)
    contract.pop("_note", None)
    errs = DC.validate_contract(contract)
    truth(not errs, "C4: %s starter contract validates (%s)" % (fw, errs))
    mids = [m.get("metric_id") for m in contract.get("metrics", [])]
    truth(any(mids), "C4: %s starter contract pins a headline metric (%s)" % (fw, mids))

# --- draft --ai: with no edges/key it must degrade to the heuristic draft, not crash ---
tmp = tempfile.mkdtemp(prefix="calma_t2_")
repo = os.path.join(tmp, "r")
os.makedirs(repo)
open(os.path.join(repo, "main.py"), "w").write(
    "import csv\nw=csv.writer(open('out.csv','w',newline=''))\n"
    "w.writerow(['value'])\n[w.writerow([float(i)]) for i in range(10)]\n")
subprocess.run([sys.executable, "main.py"], cwd=repo, check=True)  # produce the artifact
out, err = io.StringIO(), io.StringIO()
# ensure no key leaks a real call
os.environ.pop("ANTHROPIC_API_KEY", None)
with redirect_stdout(out), redirect_stderr(err):
    rc = C.draft_cmd(repo, ai=True, force=True)
combined = out.getvalue() + err.getvalue()
truth(rc == 0, "draft --ai exits 0 even with no edges deps / API key")
truth(os.path.isfile(os.path.join(repo, "verify.yaml")),
      "draft --ai falls back to the heuristic and still writes verify.yaml")
# pin the FALLBACK actually happened (not a silent AI success via a leaked key) - the round-2
# audit flagged that asserting only rc/file would pass even if AI drafting succeeded.
truth("unavailable" in combined.lower() or "heuristic" in combined.lower(),
      "draft --ai says it fell back to the heuristic (got: %r)" % combined[:160])

shutil.rmtree(tmp, ignore_errors=True)
print("deferred-arms (T2): %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
