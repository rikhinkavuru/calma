"""DX + soundness regression suite for the audit-round-4 fixes: natural-language claim parsing,
the YAML-subset contract loader, the failed-run guard (stale artifacts can never CONFIRM), humane
error paths, entrypoint fallback, `calma replay`, deterministic confidence, and report formatting.
Pure stdlib. Run: python3 test_dx.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import calma as C  # noqa: E402
import draft_contract as DC  # noqa: E402
import report as REP  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- parse_claim: free-text claims become (value, metric_hint) ---
cases = [
    ("accuracy 0.87", 0.87, "accuracy"),
    ("AUC 0.94", 0.94, "auc"),
    ("+14,698% backtest", 146.98, "total_return"),
    ("-32% return", -0.32, "total_return"),
    ("$4.2M revenue", 4.2e6, "column_sum"),
    ("processed 10,000 rows", 10000.0, "row_count"),
    ("0.87", 0.87, None),
    (0.87, 0.87, None),
    ("Sharpe 2.1", 2.1, "sharpe"),
    ("mean 50.0", 50.0, "column_mean"),
]
for text, want_v, want_h in cases:
    v, h = DC.parse_claim(text)
    truth(v is not None and abs(v - want_v) < 1e-9, "parse_claim value: %r -> %s" % (text, want_v))
    truth(h == want_h, "parse_claim hint: %r -> %s (got %s)" % (text, want_h, h))
v, h = DC.parse_claim("the tests pass")
truth(v is None, "parse_claim: no number -> None")

# --- YAML-subset loader: block maps, lists, flow maps, comments; off stays a string ---
yaml_text = """
# a hand-written contract
run:
  entrypoint: train.py
  network: off
artifacts:
  - path: predictions.csv
    columns:
      y_true: {tag: label}
      y_pred: {tag: prediction}
metrics:
  - metric_id: accuracy
    artifact: predictions.csv
    binding:
      label: y_true
      prediction: y_pred
    claimed_value: 0.87
    headline: true
baselines: []
"""
obj = DC.parse_simple_yaml(yaml_text)
truth(obj["run"]["entrypoint"] == "train.py", "yaml: nested map")
truth(obj["run"]["network"] == "off", "yaml: off stays a string (not YAML-1.1 False)")
truth(obj["artifacts"][0]["columns"]["y_true"] == {"tag": "label"}, "yaml: inline flow map")
truth(obj["metrics"][0]["claimed_value"] == 0.87 and obj["metrics"][0]["headline"] is True,
      "yaml: numbers and booleans in list items")
truth(obj["baselines"] == [], "yaml: empty flow list")
truth(DC.validate_contract(obj) == [], "yaml contract passes validate_contract")

# load_contract: JSON still wins; an unparseable file raises ValueError (not a traceback type)
tmp = tempfile.mkdtemp()
p = os.path.join(tmp, "verify.yaml")
open(p, "w").write('{"run": {"entrypoint": "x.py"}, "artifacts": [], "metrics": []}')
truth(DC.load_contract(p)["run"]["entrypoint"] == "x.py", "load_contract: JSON path")
open(p, "w").write("a line with no colon at all\nanother one\n")
try:
    DC.load_contract(p)
    truth(False, "load_contract: garbage raises ValueError")
except ValueError:
    truth(True, "load_contract: garbage raises ValueError")

# --- verdict: a non-zero exit can NEVER confirm (the stale-artifact fraud guard) ---
base_vi = {"gap": 0.0, "effective_budget": 1e-6, "binding_status": "independently-bound",
           "determinism_mode": "controlled-to-bit", "isolation_tier": "seatbelt-verified",
           "container_present": True, "claim_confirmed_target": True, "claim_outside_ci": False}
truth(V.verdict(dict(base_vi, exit_codes=[0])) == V.CONFIRMED, "exit 0 + zero gap -> CONFIRMED")
truth(V.verdict(dict(base_vi, exit_codes=[1])) == V.INCONCLUSIVE, "exit 1 -> INCONCLUSIVE, never CONFIRMED")
truth(V.verdict(dict(base_vi, exit_codes=[2])) == V.INCONCLUSIVE, "exit 2 -> INCONCLUSIVE")

# end-to-end: crashing entrypoint + pre-existing plausible CSV -> INCONCLUSIVE with the fix named
proj = os.path.join(tmp, "stale")
os.makedirs(proj)
with open(os.path.join(proj, "predictions.csv"), "w") as fh:
    fh.write("y_true,y_pred\n" + "\n".join("1,1" for _ in range(50)) + "\n")
open(os.path.join(proj, "main.py"), "w").write('raise SystemExit("boom")\n')
res = C.verify(proj, claim="accuracy 1.0")
truth(res["repo_verdict"] == V.INCONCLUSIVE, "stale-artifact fraud -> INCONCLUSIVE (got %s)" % res["repo_verdict"])
truth("exited non-zero" in res["report"], "report names the failed re-execution")
truth("fix:" in res["report"], "report carries a fix: line")
truth(res["gate_exit"] == 1, "failed re-execution gates not-clean")

# --- humane errors: nonexistent and empty targets raise ValueError (CLI exit 2), never a verdict ---
try:
    C.verify(os.path.join(tmp, "nope"))
    truth(False, "nonexistent target raises")
except ValueError as e:
    truth("does not exist" in str(e), "nonexistent target raises with a clear message")
empty = os.path.join(tmp, "empty")
os.makedirs(empty)
try:
    C.verify(empty)
    truth(False, "empty target raises")
except ValueError as e:
    truth("nothing to verify" in str(e), "empty target raises with a clear message")

# --- entrypoint fallback: a single .py that isn't on the candidate list is found ---
solo = os.path.join(tmp, "solo")
os.makedirs(solo)
open(os.path.join(solo, "my_model_eval.py"), "w").write("print('hi')\n")
truth(DC._detect_entrypoint(solo) == "my_model_eval.py", "single-script fallback detects my_model_eval.py")
# two scripts -> MANUAL, and verify() surfaces the exact unblock
open(os.path.join(solo, "other.py"), "w").write("print('hi')\n")
truth(DC._detect_entrypoint(solo) == "MANUAL", "ambiguous entrypoints -> MANUAL")
res = C.verify(solo)
truth(res["repo_verdict"] == V.INCONCLUSIVE and "entrypoint" in res["report"]
      and "fix:" in res["report"], "MANUAL entrypoint -> INCONCLUSIVE with the exact fix")

# --- claim-target confirmation: a bare-number claim on an auto-picked, non-independently-bound
# metric must NOT refute (binding ambiguity can't manufacture a REFUTED) ---
amb = os.path.join(tmp, "amb")
os.makedirs(amb)
with open(os.path.join(amb, "main.py"), "w") as fh:
    fh.write("import csv\n"
             "w = csv.writer(open('out.csv', 'w', newline=''))\n"
             "w.writerow(['value'])\n"
             "[w.writerow([float(i)]) for i in range(100)]\n")
res = C.verify(amb, claim="123456789")  # wildly wrong bare number, metric auto-picked
truth(res["repo_verdict"] != "REFUTED", "bare-number claim + auto metric never REFUTES (got %s)" % res["repo_verdict"])

# --- replay: a REFUTED run replays and reproduces ---
ml = os.path.join(tmp, "ml")
os.makedirs(ml)
with open(os.path.join(ml, "main.py"), "w") as fh:
    fh.write("import csv\n"
             "w = csv.writer(open('predictions.csv', 'w', newline=''))\n"
             "w.writerow(['y_true', 'y_pred'])\n"
             "for i in range(1000):\n"
             "    t = i % 2\n"
             "    w.writerow([t, t if i % 100 < 87 else 1 - t])\n")
res = C.verify(ml, claim="accuracy 0.99")
truth(res["repo_verdict"] == "REFUTED", "lying claim REFUTES (got %s)" % res["repo_verdict"])
ok, text = C.replay(res["run_dir"])
truth(ok, "replay reproduces the REFUTED verdict")
truth("REPRODUCED" in text, "replay says REPRODUCED")

# --- the verification cache: unchanged inputs -> instant cached verdict; any change -> re-run ---
res_c = C.verify(ml, claim="accuracy 0.99")
truth(res_c.get("cached") is True, "second identical verify is served from cache")
truth(res_c["repo_verdict"] == "REFUTED" and "cached" in res_c["report"],
      "cached result keeps the verdict and says it is cached")
res_f = C.verify(ml, claim="accuracy 0.99", force=True)
truth(res_f.get("cached") is False, "--force bypasses the cache")
# changing the claim is a different fingerprint
res_d = C.verify(ml, claim="accuracy 0.87")
truth(res_d.get("cached") is False, "a different claim re-executes")
# touching the code invalidates the cache
with open(os.path.join(ml, "main.py"), "a") as fh:
    fh.write("# changed\n")
res_e = C.verify(ml, claim="accuracy 0.99")
truth(res_e.get("cached") is False, "modified code re-executes")

# --- deterministic confidence ---
truth(V.confidence({}, V.INCONCLUSIVE) == 0.0, "INCONCLUSIVE has no confidence score")
hi = V.confidence(dict(base_vi, exit_codes=[0]), V.CONFIRMED)
lo = V.confidence({"binding_status": "author-asserted", "determinism_mode": "uncontrolled",
                   "isolation_tier": "host-not-isolated"}, V.CONFIRMED)
truth(hi > lo, "confidence rises with isolation+determinism+binding (%s > %s)" % (hi, lo))
truth(hi == V.confidence(dict(base_vi, exit_codes=[0]), V.CONFIRMED), "confidence is deterministic")

# --- report formatting ---
truth(REP.fmt_value(146.97697947938846, "total_return") == "+14,698%", "total_return formats as percent")
truth(REP.fmt_value(-0.3243140055429462, "total_return") == "-32.4%", "negative return formats")
truth(REP.fmt_value(0.87, "accuracy") == "0.87", "accuracy stays a plain number")
truth(REP.fmt_value(4200000.0, "column_sum") == "4,200,000", "sums get thousands separators")

shutil.rmtree(tmp, ignore_errors=True)
print("dx-fixes: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
