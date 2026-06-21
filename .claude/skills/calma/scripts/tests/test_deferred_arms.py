"""T2: the deferred arms get MEASURED offline, not just claimed - to the strongest extent possible
without secrets or heavy deps.
  D2  (benchmark agent arm)   - the --mock backend runs the full plumbing + scoring offline; AND the
                                recompute-only baseline (recompute_only.py) MEASURES the arm's thesis:
                                a recompute-only verifier false-confirms the ENTIRE validity cut - the
                                gap Calma's validity layer closes.
  C4  (per-framework vectors) - every starter contract validates + binds; AND gen_framework_vectors.py
                                proves Calma reproduces each framework's documented number to <=1e-9
                                (a frozen golden-vector oracle; the gated job confirms golden==live).
  draft --ai                  - the fallback path degrades to the heuristic draft instead of crashing.
The REAL agent run (needs ANTHROPIC_API_KEY) and the LIVE-framework confirmation (--check-live, needs the
frameworks installed) stay gated CI jobs - now backed by offline EVIDENCE, not just documented. Pure
stdlib offline. Run: python3 test_deferred_arms.py
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

# --- D2b: the RECOMPUTE-ONLY baseline MEASURES the agent arm's thesis offline (no key, deterministic) ---
# A verifier that recomputes the headline but skips validity reasoning false-confirms the whole validity
# cut - the number reproduces, the result is still invalid. That's the gap the real agent arm quantifies;
# here it's measured with Calma's own recompute engine, no model, no network.
ro = os.path.join(ROOT, "benchmark", "recompute_only.py")
if os.path.isfile(ro):
    r = subprocess.run([sys.executable, ro], cwd=ROOT, capture_output=True, text=True, timeout=180)
    truth(r.returncode == 0, "D2b: the recompute-only baseline runs offline (no key, no sandbox)")
    roj = os.path.join(ROOT, "benchmark", "results", "recompute_only.json")
    rrows = json.load(open(roj)) if os.path.isfile(roj) else []
    vscored = [x for x in rrows if x.get("validity_family") and x["prediction"] != "abstain"]
    truth(len(vscored) >= 8, "D2b: scores the validity cut offline from committed artifacts (n=%d)" % len(vscored))
    truth(bool(vscored) and all(x["prediction"] == "honest" for x in vscored),
          "D2b: recompute-only FALSE-CONFIRMS every scored validity case (the number reproduces -> 'honest')")
    truth(all(isinstance(x.get("recomputed"), float)
              and abs(x["recomputed"] - float(x["claim"])) <= max(0.01 * abs(float(x["claim"])), 1e-9)
              for x in vscored),
          "D2b: each validity headline was RE-COMPUTED and landed on the claim (the flaw is invisible to a recompute)")
else:
    truth(False, "D2b: benchmark/recompute_only.py is missing")

# --- C4: every starter contract validates + binds its headline metric (the testable half) ---
for fw in FW.list_frameworks():
    contract = FW.starter_contract(fw)
    contract.pop("_note", None)
    errs = DC.validate_contract(contract)
    truth(not errs, "C4: %s starter contract validates (%s)" % (fw, errs))
    mids = [m.get("metric_id") for m in contract.get("metrics", [])]
    truth(any(mids), "C4: %s starter contract pins a headline metric (%s)" % (fw, mids))

# --- C4b: FRAMEWORK REFERENCE VECTORS - Calma reproduces each framework's documented number to <=1e-9 ---
# The golden-vector oracle: a frozen artifact + the value the framework computes for it (e.g.
# sklearn.metrics.roc_auc_score), cross-checked offline against an INDEPENDENT pure-python reference and,
# under --check-live in the gated job, against the real installed framework.
fv = os.path.join(ROOT, "benchmark", "gen_framework_vectors.py")
if os.path.isfile(fv):
    r = subprocess.run([sys.executable, fv], cwd=ROOT, capture_output=True, text=True, timeout=180)
    truth(r.returncode == 0, "C4b: every framework reference vector reproduces to <=1e-9 (Calma == golden)")
    fvj = os.path.join(ROOT, "benchmark", "results", "framework_vectors.json")
    vecs = json.load(open(fvj)) if os.path.isfile(fvj) else []
    truth(len(vecs) >= 8 and all(isinstance(v.get("calma"), float) and abs(v["calma"] - v["value"]) <= 1e-9
                                 for v in vecs),
          "C4b: %d frozen vectors, Calma matches the framework golden on each (<=1e-9)" % len(vecs))
else:
    truth(False, "C4b: benchmark/gen_framework_vectors.py is missing")

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
