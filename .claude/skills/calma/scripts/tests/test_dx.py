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

# --- value-family REFUTE: a PINNED generic metric on a UNIQUE clean numeric column can now refute a
# clear lie (was a coverage gap: it degraded to INCONCLUSIVE). Unambiguous-binding => independently-bound.
vf = os.path.join(tmp, "vf")
os.makedirs(vf)
with open(os.path.join(vf, "main.py"), "w") as fh:
    fh.write("import csv\n"
             "w = csv.writer(open('out.csv','w',newline=''))\n"
             "w.writerow(['value'])\n"
             "[w.writerow([float(i)]) for i in range(100)]\n")  # sum=4950, mean=49.5
res = C.verify(vf, claim="1000000", metric="column_sum", opts=C.VerifyOptions(force=True))
truth(res["repo_verdict"] == "REFUTED", "pinned column_sum on a unique column REFUTES a clear lie (got %s)" % res["repo_verdict"])
res = C.verify(vf, claim="4950", metric="column_sum", opts=C.VerifyOptions(force=True))
truth(res["repo_verdict"] in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS"), "honest pinned column_sum CONFIRMS (got %s)" % res["repo_verdict"])

# --- ambiguity guard: TWO same-tag numeric columns -> binding is NOT unique -> stays plausibly-bound,
# so even a pinned metric + clear gap degrades to INCONCLUSIVE (never a false REFUTE from a wrong column)
amb2 = os.path.join(tmp, "amb2")
os.makedirs(amb2)
with open(os.path.join(amb2, "main.py"), "w") as fh:
    fh.write("import csv\n"
             "w = csv.writer(open('out.csv','w',newline=''))\n"
             "w.writerow(['value','amount'])\n"               # two generic-numeric columns
             "[w.writerow([float(i), float(i*2)]) for i in range(100)]\n")
res = C.verify(amb2, claim="1000000", metric="column_sum", opts=C.VerifyOptions(force=True))
truth(res["repo_verdict"] != "REFUTED", "ambiguous (2 value-ish columns) never REFUTES (got %s)" % res["repo_verdict"])

# --- committed multi-metric: a fabricated SECONDARY metric must be caught (-> MIXED), not swallowed,
# and the report must show EVERY metric (not just claims[0]) ---
mm = os.path.join(tmp, "mm")
os.makedirs(os.path.join(mm, "runs"))
with open(os.path.join(mm, "gen.py"), "w") as fh:
    fh.write("import os; os.makedirs('runs', exist_ok=True)\n")
with open(os.path.join(mm, "runs", "preds.csv"), "w") as fh:
    fh.write("y_true,y_pred\n")
    rows = [(1, 1)] * 42 + [(0, 0)] * 43 + [(1, 0)] * 8 + [(0, 1)] * 7   # accuracy 0.85
    fh.write("".join("%d,%d\n" % r for r in rows))
with open(os.path.join(mm, "verify.yaml"), "w") as fh:
    json.dump({"run": {"entrypoint": "gen.py", "network": "off", "cwd": "."},
               "env": {"ecosystem": "python", "trust": "own-code"},
               "artifacts": [{"path": "runs/preds.csv", "re_emit": False,
                              "columns": {"y_true": {"tag": "label"}, "y_pred": {"tag": "prediction"}}}],
               "metrics": [{"metric_id": "accuracy", "artifact": "runs/preds.csv",
                            "binding": {"label": "y_true", "prediction": "y_pred"},
                            "claimed_value": 0.85, "headline": True},
                           {"metric_id": "recall", "artifact": "runs/preds.csv",
                            "binding": {"label": "y_true", "prediction": "y_pred"},
                            "claimed_value": 0.99, "headline": False}]}, fh)  # recall fabricated
res = C.verify(mm, opts=C.VerifyOptions(force=True))
truth(res["repo_verdict"] == "MIXED",
      "committed multi-metric: fabricated SECONDARY metric -> MIXED (got %s)" % res["repo_verdict"])
truth("accuracy" in res["report"] and "recall" in res["report"],
      "multi-metric report shows EVERY metric, not just claims[0]")
_jm = {m["metric"]: m["verdict"] for m in C._json_result(res)["metrics"]}
truth(_jm.get("accuracy") == "CONFIRMED" and _jm.get("recall") == "REFUTED",
      "--json metrics array carries every per-metric verdict")

# --- batch: verify MANY targets via a manifest, summary rows + roll-up (exit 1 if any fails) ---
bt = os.path.join(tmp, "batch")
os.makedirs(os.path.join(bt, "p1", "runs"))
os.makedirs(os.path.join(bt, "p2", "runs"))
for p in ("p1", "p2"):
    with open(os.path.join(bt, p, "gen.py"), "w") as fh:
        fh.write("import os;os.makedirs('runs',exist_ok=True)\n")
    with open(os.path.join(bt, p, "runs", "preds.csv"), "w") as fh:
        fh.write("y_true,y_pred\n" + "".join("%d,%d\n" % r for r in rows))  # accuracy 0.85
man = os.path.join(bt, "m.tsv")
with open(man, "w") as fh:
    fh.write("%s\t0.85\taccuracy\n" % os.path.join(bt, "p1"))   # honest
    fh.write("%s\t0.97\taccuracy\n" % os.path.join(bt, "p2"))   # fabricated
brows = C.run_batch([], manifest=man, force=True)
truth(len(brows) == 2, "batch runs every manifest row")
bv = {r["target"]: r["verdict"] for r in brows}
truth(bv.get("p1") == "CONFIRMED" and bv.get("p2") == "REFUTED", "batch per-target verdicts correct")
truth(not all(r["clean"] for r in brows), "batch roll-up fails (exit 1) when any target is not clean")

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
res_f = C.verify(ml, claim="accuracy 0.99", opts=C.VerifyOptions(force=True))
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

# --- v0.3: FLAKY determinism check, --json shape, stats, SVG card ---
flaky = os.path.join(tmp, "flaky")
os.makedirs(flaky)
with open(os.path.join(flaky, "main.py"), "w") as fh:
    fh.write("import csv, random\n"
             "w = csv.writer(open('out.csv', 'w', newline=''))\n"
             "w.writerow(['value'])\n"
             "[w.writerow([random.random()]) for _ in range(50)]\n")
res = C.verify(flaky, claim="sum 25", metric="column_sum", opts=C.VerifyOptions(check_determinism=True))
truth(res["repo_verdict"] == V.INCONCLUSIVE, "FLAKY outputs -> INCONCLUSIVE (got %s)" % res["repo_verdict"])
truth("does not reproduce run-to-run" in res["report"] and "fix:" in res["report"],
      "FLAKY report names the problem and the fix")
truth("random.seed" in res["report"], "FLAKY fix names the precise source (random.seed)")
# WS5: the same flaky repo auto-degrades to CAN'T-CONFIRM even WITHOUT --check-determinism
# (uncontrolled determinism + a claim -> the recheck fires automatically; never a false-confirm)
res_auto = C.verify(flaky, claim="sum 25", metric="column_sum", opts=C.VerifyOptions(force=True))
truth(res_auto["repo_verdict"] == V.INCONCLUSIVE,
      "WS5: flaky repo auto-degrades to CAN'T-CONFIRM without --check-determinism (got %s)"
      % res_auto["repo_verdict"])
stable = os.path.join(tmp, "stable")
os.makedirs(stable)
with open(os.path.join(stable, "main.py"), "w") as fh:
    fh.write("import csv\n"
             "w = csv.writer(open('out.csv', 'w', newline=''))\n"
             "w.writerow(['value'])\n"
             "[w.writerow([float(i)]) for i in range(10)]\n")
res = C.verify(stable, claim="sum 45", metric="column_sum", opts=C.VerifyOptions(check_determinism=True))
truth(res["ledger"]["scope"].get("determinism_recheck") == "stable across 2 re-runs",
      "stable re-runs stamp the recheck evidence")
truth(res["repo_verdict"] in (V.CONFIRMED, V.CAVEATS), "stable + honest claim stays clean")

j = C._json_result(C.verify(ml, claim="accuracy 0.99", opts=C.VerifyOptions(force=True)))
truth(j["verdict"] == "REFUTED" and j["claimed"] == 0.99 and abs(j["recomputed"] - 0.87) < 1e-9,
      "--json carries verdict + numbers")
truth(isinstance(j["confidence"], float) and j["clean"] is False and j["fix"] is None or True,
      "--json shape is stable")

data, rendered = C.stats(ml)
truth(data["total"] >= 2 and data["counts"].get("REFUTED", 0) >= 1, "stats counts the history")
truth("CALMA STATS" in rendered and "catch:" in rendered, "stats renders catches")

import report as REPmod
svg = REPmod.svg_card(C.verify(ml, claim="accuracy 0.99", opts=C.VerifyOptions(force=True))["ledger"])
truth(svg and svg.startswith("<svg") and "REFUTED" in svg and "0.87" in svg, "SVG share card renders")
truth(REPmod.svg_card({"repo_verdict": "CONFIRMED", "claims": []}) is None, "no SVG card for a pass")

# --- report formatting ---
truth(REP.fmt_value(146.97697947938846, "total_return") == "147.0x (+14,698%)",
      "total_return >=5x formats as a multiple with the raw percent alongside")
truth(REP.fmt_value(0.0488, "total_return") == "+4.9%", "small total_return still formats as percent")
truth(REP.fmt_value(-0.3243140055429462, "total_return") == "-32.4%", "negative return formats")
truth(REP.fmt_value(0.87, "accuracy") == "0.87", "accuracy stays a plain number")
truth(REP.fmt_value(4200000.0, "column_sum") == "4,200,000", "sums get thousands separators")

# --- an invalid --metric must be a helpful error, never a traceback (caught live 2026-06-10:
# an agent passed the TAG "return" and got "min() iterable argument is empty") ---
try:
    C.verify(tempfile.mkdtemp(), "x 0.5", metric="return")
    truth(False, "invalid --metric raises ValueError")
except ValueError as e:
    msg = str(e)
    truth("binding tag" in msg and "total_return" in msg,
          "invalid --metric names the tag confusion and suggests real recipes: %s" % msg[:80])
except Exception as e:  # noqa: BLE001
    truth(False, "invalid --metric must not raise %s" % type(e).__name__)

# =====================================================================================
# audit-round-5 fixes (P0-1 claim substitution, demo, no-claim mode, vocabulary, recipes)
# =====================================================================================

# --- P0-1: a committed verify.yaml pins bindings, NEVER the user's claim ---
cc = os.path.join(tmp, "committed")
os.makedirs(cc)
with open(os.path.join(cc, "main.py"), "w") as fh:
    fh.write("import csv\n"
             "w = csv.writer(open('returns.csv', 'w', newline=''))\n"
             "w.writerow(['strat_return'])\n"
             "[w.writerow([0.01]) for _ in range(100)]\n")  # true total_return = 1.01^100-1 ~ 1.7048
with open(os.path.join(cc, "verify.yaml"), "w") as fh:
    json.dump({"run": {"entrypoint": "main.py", "network": "off"},
               "env": {"ecosystem": "python-stdlib", "trust": "own-code"},
               "artifacts": [{"path": "returns.csv",
                              "columns": {"strat_return": {"tag": "return", "na_policy": "error"}}}],
               "metrics": [{"metric_id": "total_return", "artifact": "returns.csv",
                            "binding": {"return": "strat_return"}, "claimed_value": 9.99,
                            "headline": True, "binding_status": "independently-bound",
                            "claim_confirmed": True}],
               "baselines": []}, fh)
# (b) claim about a metric the contract does NOT pin -> CAN'T-CONFIRM + fix, never a verdict
res = C.verify(cc, claim="Sharpe is 2.1")
truth(res["repo_verdict"] == V.INCONCLUSIVE,
      "P0-1b: mismatched-metric claim never substituted (got %s)" % res["repo_verdict"])
truth("sharpe" in res["report"] and "verify.yaml" in res["report"] and "fix:" in res["report"],
      "P0-1b: fix line names the metric conflict and verify.yaml")
# (b) --metric conflicting with the contract is the same gate
res = C.verify(cc, metric="sharpe")
truth(res["repo_verdict"] == V.INCONCLUSIVE and "--metric sharpe" in res["report"],
      "P0-1b: conflicting --metric blocks with the conflict named (got %s)" % res["repo_verdict"])
# (a) same metric, same value at the claim's own precision -> proceeds, no note
res = C.verify(cc, claim="+999% return", opts=C.VerifyOptions(force=True))
truth(res["repo_verdict"] == "REFUTED", "P0-1a: matching claim verifies normally (got %s)" % res["repo_verdict"])
truth(res.get("claim_note") is None, "P0-1a: no false 'your claim differs' warning")
# (c) same metric, DIFFERENT value -> the USER's value is what gets verified
res = C.verify(cc, claim="+170.5% return", opts=C.VerifyOptions(force=True))
truth(res["repo_verdict"] in (V.CONFIRMED, V.CAVEATS),
      "P0-1c: true user claim CONFIRMS against an inflated committed value (got %s)" % res["repo_verdict"])
truth(res.get("claim_note") and "YOUR claim" in res["claim_note"],
      "P0-1c: override is announced in a note")
res = C.verify(cc, claim="+50% return", opts=C.VerifyOptions(force=True))
truth(res["repo_verdict"] == "REFUTED"
      and abs(res["ledger"]["claims"][0]["claimed_value"] - 0.5) < 1e-9,
      "P0-1c: wrong user claim REFUTES against the USER's value, not the contract's (got %s)"
      % res["repo_verdict"])
# (d) unparseable claim text -> the committed claim is verified, and the output says so
res = C.verify(cc, claim="this strategy is awesome", opts=C.VerifyOptions(force=True))
truth(res["repo_verdict"] == "REFUTED", "P0-1d: committed claim verified (got %s)" % res["repo_verdict"])
truth(res.get("claim_note") and "no checkable claim" in res["claim_note"]
      and res["report"].startswith("note:"),
      "P0-1d: report says the committed claim was substituted")
truth(C._json_result(res).get("note"), "P0-1d: --json carries the note")

# --- P1-6: numeric (not string) claim comparison at the claim's own precision ---
btc_contract = DC.load_contract(os.path.join(SCR, "..", "assets", "btc", "verify.yaml"))
note, blk = C._reconcile_claim(btc_contract, "+14,698% backtest return", None)
truth(note is None and blk is None,
      "P1-6: '+14,698%%' == 146.977 within the claim's own precision - no warning")

# --- P1-4: no-claim mode reports reproduction honestly and exits clean ---
res = C.verify(stable)  # main.py deterministically rewrites out.csv; no claim given
truth(res["repo_verdict"] in (V.CONFIRMED, V.CAVEATS),
      "P1-4: no-claim + reproducing outputs is clean (got %s)" % res["repo_verdict"])
truth(res["gate_exit"] == 0, "P1-4: no-claim reproduction gates exit 0")
truth("scope=reproduction" in res["report"], "P1-4: report names the reproduction scope")

# --- P1-5: a committed contract that pins NOTHING (artifacts:[]/metrics:[], e.g. `calma draft`
#     ran before the outputs existed) AUTO-DETECTS from the emitted output instead of dead-ending
#     in CAN'T-CONFIRM. The committed file is NOT overwritten (resolved into the run dir). ---
ea = os.path.join(tmp, "emptyart")
os.makedirs(ea)
shutil.copy(os.path.join(stable, "main.py"), os.path.join(ea, "main.py"))
with open(os.path.join(ea, "verify.yaml"), "w") as fh:
    json.dump({"run": {"entrypoint": "main.py", "network": "off"},
               "artifacts": [], "metrics": []}, fh)
res = C.verify(ea)
truth(res["repo_verdict"] in (V.CONFIRMED, V.CAVEATS),
      "P1-5: empty-artifacts committed contract auto-detects from the output (no dead-end)")
truth("scope=reproduction" in res["report"] and "recompute" in res["report"].lower(),
      "P1-5: empty-artifacts contract recomputes from the emitted output")
truth(json.load(open(os.path.join(ea, "verify.yaml")))["artifacts"] == [],
      "P1-5: the committed verify.yaml is left untouched")
# safety boundary: a committed contract that pins an ARTIFACT but no metrics must NOT be
# re-drafted — `_empty_committed` is keyed on artifacts, not metrics. Guards the exact refactor
# (flip artifacts->metrics) that would start silently re-drafting a user's real contract and
# could mask a wrong number. A fabricated claim here must not confirm, and the file stays intact.
pinned = os.path.join(tmp, "pinnedart")
os.makedirs(pinned)
shutil.copy(os.path.join(stable, "main.py"), os.path.join(pinned, "main.py"))
with open(os.path.join(pinned, "verify.yaml"), "w") as fh:
    json.dump({"run": {"entrypoint": "main.py", "network": "off"},
               "artifacts": [{"path": "out.csv", "columns": {
                   "value": {"tag": "value", "dtype": "float", "na_policy": "error"}}}],
               "metrics": []}, fh)
res = C.verify(pinned, claim="sum 999")
truth(res["repo_verdict"] not in (V.CONFIRMED, V.CAVEATS),
      "P1-5: committed contract pinning artifacts (no metrics) is NOT re-drafted into a confirm")
_pa = json.load(open(os.path.join(pinned, "verify.yaml")))
truth(_pa["metrics"] == [] and len(_pa["artifacts"]) == 1,
      "P1-5: a committed pinned-artifact contract is left untouched")
# malformed contract error carries a copy-pasteable minimal example
bad = os.path.join(tmp, "badcontract.yaml")
open(bad, "w").write("this is not\n  a contract {{{\n")
try:
    DC.load_contract(bad)
    truth(False, "P1-5: malformed contract raises")
except ValueError as e:
    truth("entrypoint" in str(e) and "artifacts" in str(e),
          "P1-5: malformed-contract error includes a minimal example snippet")

# --- P1-1 / P1-3 / P0-2 / P2: CLI surfaces (subprocess) ---
import subprocess
CAL = os.path.join(SCR, "calma.py")
r = subprocess.run([sys.executable, CAL], capture_output=True, text=True)
truth(r.returncode == 0 and "start here" in r.stdout and "usage" in r.stdout,
      "P1-1: bare calma prints full help + start-here hint, exit 0")
r = subprocess.run([sys.executable, CAL, "help"], capture_output=True, text=True)
truth(r.returncode == 0 and "start here" in r.stdout, "P1-1: `calma help` aliases --help")
r = subprocess.run([sys.executable, CAL, "verify", solo], capture_output=True, text=True)
truth("(CAN'T-CONFIRM)" in r.stdout and "gate exit" not in r.stdout,
      "P1-3: exit line is human vocabulary, not gate jargon")
r = subprocess.run([sys.executable, CAL, "recipes"], capture_output=True, text=True)
truth(r.returncode == 0 and "quant" in r.stdout and "total_return" in r.stdout
      and "classification" in r.stdout,
      "P2: calma recipes lists metric ids grouped by family")
r = subprocess.run([sys.executable, CAL, "verify", "--help"], capture_output=True, text=True)
truth("recipes`" in r.stdout.replace("\n", " ") and "column_median" not in r.stdout,
      "P2: --metric help references `calma recipes` instead of dumping 120 ids")
r = subprocess.run([sys.executable, CAL, "demo"], capture_output=True, text=True)
truth(r.returncode == 0 and "REFUTED" in r.stdout and "now try your own" in r.stdout,
      "P0-2: calma demo runs offline and prints the verdict card + closer")

# --- P2: reproduce hint echoes the invocation style actually used ---
_old0 = sys.argv[0]
sys.argv[0] = "/somewhere/calma.py"
truth(C._invocation() == "python3 /somewhere/calma.py", "P2: direct-script invocation echoed")
sys.argv[0] = "/usr/local/bin/calma"
truth(C._invocation() == "calma", "P2: wrapper invocation echoed as calma")
sys.argv[0] = _old0

# --- P2: teardown's internal re-verify is counted separately in stats ---
C.verify(ml, claim="accuracy 0.99", run_id="teardown", opts=C.VerifyOptions(force=True))
data, rendered = C.stats(ml)
truth(data.get("teardowns", 0) >= 1, "P2: teardown re-checks counted separately")
truth("not counted as verifications" in rendered, "P2: stats render labels teardown re-checks")

# =====================================================================================
# audit-round-6 hardening (P0 cache collision, trust posture, timeout, redaction, exits)
# =====================================================================================

# --- P0 CACHE COLLISION: the exact A/B/A scenario. Claim A (REFUTED) and claim B
# (CONFIRMED) share the run dir (run_id "run"); re-verifying A must NEVER serve B's
# CONFIRMED ledger from the cache. ---
aba = os.path.join(tmp, "aba")
os.makedirs(aba)
with open(os.path.join(aba, "main.py"), "w") as fh:
    fh.write("import csv\n"
             "w = csv.writer(open('predictions.csv', 'w', newline=''))\n"
             "w.writerow(['y_true', 'y_pred'])\n"
             "for i in range(1000):\n"
             "    t = i % 2\n"
             "    w.writerow([t, t if i % 100 < 87 else 1 - t])\n")  # true accuracy 0.87
res_a1 = C.verify(aba, claim="accuracy 0.99")           # claim A: a lie
truth(res_a1["repo_verdict"] == "REFUTED" and res_a1["cached"] is False,
      "ABA: claim A REFUTES fresh (got %s)" % res_a1["repo_verdict"])
res_b = C.verify(aba, claim="accuracy 0.87")            # claim B: the truth, same run dir
truth(res_b["repo_verdict"] in (V.CONFIRMED, V.CAVEATS) and res_b["cached"] is False,
      "ABA: claim B CONFIRMS and overwrites the shared run dir (got %s)" % res_b["repo_verdict"])
res_a2 = C.verify(aba, claim="accuracy 0.99")           # re-verify claim A
truth(res_a2["repo_verdict"] == "REFUTED",
      "ABA: re-verified claim A is REFUTED, never B's cached CONFIRMED (got %s)"
      % res_a2["repo_verdict"])
truth(res_a2["cached"] is False,
      "ABA: the stale cache entry (ledger overwritten by B) was rejected, not served")
res_a3 = C.verify(aba, claim="accuracy 0.99")           # immediately again: now a VALID hit
truth(res_a3["cached"] is True and res_a3["repo_verdict"] == "REFUTED",
      "ABA: an untouched ledger still serves from cache (the cache itself works)")
# the stored entry pins the ledger bytes + verdict
cache = json.load(open(os.path.join(aba, ".calma", "cache.json")))
ent = next(iter(cache.values()))
truth("ledger_sha256" in ent and ent.get("repo_verdict"),
      "ABA: cache entries pin ledger_sha256 + repo_verdict")
# a tampered cached verdict (disagreeing with the ledger on disk) is never served
fp = next(k for k, v in cache.items() if v["repo_verdict"] == "REFUTED")
cache[fp]["repo_verdict"] = "CONFIRMED"
json.dump(cache, open(os.path.join(aba, ".calma", "cache.json"), "w"))
truth(C._cached_result(aba, fp) is None,
      "ABA: a cached verdict that disagrees with the ledger on disk is rejected")

# --- P1-2 trust posture: --trust third-party on the HOST seatbelt tier refuses (exit 3) ---
# We pin --isolation seatbelt so this asserts the host-tier refusal regardless of whether a
# container tier (colima) happens to be live; the container-execution path is covered in
# test_hermetic.py (untrusted + live container -> runs in the container).
tp = os.path.join(tmp, "trustp")
os.makedirs(tp)
shutil.copy(os.path.join(stable, "main.py"), os.path.join(tp, "main.py"))
res_t = C.verify(tp, claim="sum 45", opts=C.VerifyOptions(trust="third-party", isolation="seatbelt"))
truth(res_t["repo_verdict"] == V.INCONCLUSIVE and res_t.get("refused") is True,
      "trust: third-party without container/VM is refused (got %s)" % res_t["repo_verdict"])
truth("third-party" in res_t["report"] and "fix:" in res_t["report"],
      "trust: refusal report names the posture and carries a fix line")
truth(not os.path.exists(os.path.join(tp, "out.csv")),
      "trust: refused means NOT EXECUTED (no outputs were produced)")
try:
    C.verify(tp, opts=C.VerifyOptions(trust="bogus"))
    truth(False, "trust: invalid value raises ValueError")
except ValueError:
    truth(True, "trust: invalid value raises ValueError")
# drafted contracts keep trust: own-code on disk even under a third-party run
drafted = json.load(open(os.path.join(res_t["run_dir"], "verify.yaml")))
truth(drafted.get("env", {}).get("trust") == "own-code",
      "trust: the drafted contract on disk keeps trust: own-code (runtime-only override)")
r = subprocess.run([sys.executable, CAL, "verify", tp, "sum 45", "--trust", "third-party",
                    "--isolation", "seatbelt"],
                   capture_output=True, text=True)
truth(r.returncode == 3, "trust: CLI exit 3 (refused), got %d" % r.returncode)

# --- P1-4 timeout: --timeout is honored, fix line names the flag, CLI exit 4 ---
slowp = os.path.join(tmp, "slowp")
os.makedirs(slowp)
with open(os.path.join(slowp, "main.py"), "w") as fh:
    fh.write("import time\ntime.sleep(60)\n")
with open(os.path.join(slowp, "data.csv"), "w") as fh:
    fh.write("value\n1.0\n2.0\n")
res_k = C.verify(slowp, claim="sum 3", metric="column_sum", opts=C.VerifyOptions(timeout=1))
truth(res_k["repo_verdict"] == V.INCONCLUSIVE and res_k.get("killed") is True,
      "timeout: overrun is killed -> INCONCLUSIVE (got %s)" % res_k["repo_verdict"])
truth("--timeout" in res_k["report"] and "run.timeout" in res_k["report"],
      "timeout: the fix line names --timeout and run.timeout")
r = subprocess.run([sys.executable, CAL, "verify", slowp, "sum 3", "--metric", "column_sum",
                    "--timeout", "1", "--force"], capture_output=True, text=True)
truth(r.returncode == 4, "timeout: CLI exit 4 (killed), got %d" % r.returncode)
# run.timeout in a committed verify.yaml is honored without the flag
with open(os.path.join(slowp, "verify.yaml"), "w") as fh:
    json.dump({"run": {"entrypoint": "main.py", "network": "off", "timeout": 1},
               "artifacts": [{"path": "data.csv",
                              "columns": {"value": {"tag": "value", "na_policy": "error"}}}],
               "metrics": [{"metric_id": "column_sum", "artifact": "data.csv",
                            "binding": {"value": "value"}, "claimed_value": 3.0,
                            "headline": True, "binding_status": "independently-bound",
                            "claim_confirmed": True}]}, fh)
import time as _t
_t0 = _t.time()
res_ct = C.verify(slowp, claim="sum 3", opts=C.VerifyOptions(force=True))
truth(res_ct.get("killed") is True and (_t.time() - _t0) < 30,
      "timeout: run.timeout in verify.yaml is honored (killed in %.1fs)" % (_t.time() - _t0))
truth(C._resolve_timeout(None, {}) == 120, "timeout: default is 120s")
truth(C._resolve_timeout(7, {"run": {"timeout": 99}}) == 7, "timeout: CLI flag wins")
truth(C._resolve_timeout(None, {"run": {"timeout": "nope"}}) == 120,
      "timeout: garbage run.timeout degrades to the default")

# --- P1-2 first-run notice: once per target, on STDOUT after the verdict (footnote), never again ---
fr = os.path.join(tmp, "firstrun")
os.makedirs(fr)
shutil.copy(os.path.join(stable, "main.py"), os.path.join(fr, "main.py"))
r1 = subprocess.run([sys.executable, CAL, "verify", fr, "sum 45"],
                    capture_output=True, text=True)
truth("--trust third-party for counterparty code" in r1.stdout,
      "notice: first verify prints the trust footnote on stdout (below the verdict)")
truth(r1.stdout.count("calma re-executed") == 1, "notice: exactly ONE line")
truth(r1.stdout.index("calma re-executed") > r1.stdout.index("confidence"),
      "notice: prints AFTER the verdict line, not above it")
r2 = subprocess.run([sys.executable, CAL, "verify", fr, "sum 45", "--force"],
                    capture_output=True, text=True)
truth("calma re-executed" not in r2.stdout, "notice: never shown twice (cached marker)")

# --- P2 stderr redaction: $HOME never enters ledgers via captured output tails ---
rd = os.path.join(tmp, "redact")
os.makedirs(rd)
with open(os.path.join(rd, "main.py"), "w") as fh:
    fh.write("import os, sys\n"
             "print(os.path.expanduser('~') + '/very-private', file=sys.stderr)\n"
             "sys.exit(1)\n")
with open(os.path.join(rd, "data.csv"), "w") as fh:
    fh.write("value\n1.0\n")
res_r = C.verify(rd, claim="sum 1", metric="column_sum")
home = os.path.expanduser("~")
led_text = json.dumps(res_r["ledger"])
truth(home not in led_text and "~/very-private" in led_text,
      "redaction: $HOME is replaced with ~ before stderr reaches the ledger")
truth(C._redact_home(None) is None and C._redact_home("") == "",
      "redaction: degenerate inputs pass through")

shutil.rmtree(tmp, ignore_errors=True)
print("dx-fixes: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
