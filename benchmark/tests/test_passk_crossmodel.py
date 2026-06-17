"""G3: the variance + steelman methodology. (1) pass^k matches the closed form C(c,k)/C(n,k)
(tau-bench, Yao 2024) - NOT pass@k; (2) the cross-model + naive-prompt plumbing runs offline (--mock):
two models -> agent.json + agent_cross.json, and score.py surfaces the cross-model arm + pass^k curve.
Snapshots+restores tracked result files. Run: python3 this_file.py
"""
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
RES = os.path.join(BENCH, "results")
sys.path.insert(0, BENCH)
import score as S  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def cclose(a, b):
    return a is not None and abs(a - b) < 1e-9


# (1) pass^k closed form C(c,k)/C(n,k) on synthetic rerun vectors
r = ["flawed", "flawed", "flawed", "honest", "abstain"]  # c=3 correct (flawed) of n=5
truth(cclose(S._passk(r, "flawed", 1), 3 / 5), "pass^1 = C(3,1)/C(5,1) = 3/5")
truth(cclose(S._passk(r, "flawed", 2), math.comb(3, 2) / math.comb(5, 2)), "pass^2 = C(3,2)/C(5,2)")
truth(cclose(S._passk(r, "flawed", 3), math.comb(3, 3) / math.comb(5, 3)), "pass^3 = C(3,3)/C(5,3)")
truth(cclose(S._passk(r, "flawed", 4), 0.0), "pass^4 = C(3,4)/C(5,4) = 0 (cliff)")
truth(S._passk(r, "flawed", 6) is None, "pass^k is None when k>n")
allc = ["flawed"] * 4
truth(all(cclose(S._passk(allc, "flawed", k), 1.0) for k in (1, 2, 3, 4)), "all-correct -> pass^k = 1.0 flat")
honest = ["honest", "honest", "flawed"]  # c=2 of 3 for an honest case
truth(cclose(S._passk(honest, "honest", 1), 2 / 3) and cclose(S._passk(honest, "honest", 2), math.comb(2, 2) / math.comb(3, 2)),
      "pass^k uses the honest-case success criterion too")
# curve = mean over cases, monotone non-increasing in k
rows = [{"reruns": r, "label": "flawed"}, {"reruns": allc, "label": "flawed"}]
curve = S._passk_curve(rows, 4)
truth(len(curve) == 4 and curve[0] >= curve[1] >= curve[2] >= curve[3], "pass^k curve is monotone non-increasing")

# (2) cross-model + naive plumbing, offline (--mock)
snap = {}
for f in ("summary.json", "site_data.json", "agent.json", "agent_cross.json"):
    p = os.path.join(RES, f)
    snap[f] = open(p, "rb").read() if os.path.exists(p) else None
try:
    p = subprocess.run([sys.executable, os.path.join(BENCH, "run_agent.py"), "--mock", "--prompt", "naive",
                        "--models", "claude-opus-4-8,gpt-4o", "--limit", "6", "--k", "3"],
                       capture_output=True, text=True)
    truth(p.returncode == 0, "run_agent --mock --models (cross-family) exits 0 (%s)" % p.stderr[-160:])
    truth(os.path.exists(os.path.join(RES, "agent.json")), "primary model -> agent.json")
    cross_p = os.path.join(RES, "agent_cross.json")
    truth(os.path.exists(cross_p), "second model -> agent_cross.json (cross-family plumbing)")
    cross = json.load(open(cross_p))
    truth(cross and cross[0].get("model") == "gpt-4o" and cross[0].get("rows"),
          "agent_cross.json carries the second model's rows")
    prim = json.load(open(os.path.join(RES, "agent.json")))
    truth(all(rr.get("prompt") == "naive" for rr in prim), "the naive-prompt run is recorded on each record")
    sp = subprocess.run([sys.executable, os.path.join(BENCH, "score.py")], capture_output=True, text=True)
    truth(sp.returncode == 0, "score.py exits 0 with a cross-model file present")
    truth("Cross-model" in sp.stdout and "pass^k curve" in sp.stdout, "score prints the cross-model + pass^k sections")
    site = json.load(open(os.path.join(RES, "site_data.json")))
    truth(isinstance(site.get("cross_model"), list) and site["cross_model"], "site_data carries cross_model")
    truth("passk_curve" in (site.get("overall", {}).get("agent-with-exec_extras", {})), "site_data carries the pass^k curve")
finally:
    for f, b in snap.items():
        p = os.path.join(RES, f)
        if b is None:
            if os.path.exists(p):
                os.remove(p)
        else:
            open(p, "wb").write(b)

print("passk_crossmodel(G3): %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
