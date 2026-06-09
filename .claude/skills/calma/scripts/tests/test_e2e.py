"""End-to-end: `calma verify` chains the whole pipeline. The BTC fixture -> REFUTED with a valid,
gateable ledger + manifest + report; an honest matching claim -> CONFIRMED / clean gate. Pure stdlib.
Run: python3 test_e2e.py
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
import recompute as RC  # noqa: E402
import verdict as V  # noqa: E402

BTC = os.path.realpath(os.path.join(SCR, "..", "assets", "btc"))
_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- REFUTED end-to-end on BTC ---
res = C.verify(BTC, run_id="test_e2e")
truth(res["repo_verdict"] == "REFUTED", "BTC -> repo REFUTED")
truth(res["gate_exit"] == 1, "BTC gate exit 1 (valid, not clean)")
truth(res["report"].startswith("REFUTED"), "report leads with REFUTED")
truth(res.get("teardown") and "CALMA TEARDOWN" in res["teardown"] and "RECOMPUTED" in res["teardown"],
      "shareable teardown card produced on REFUTED")
truth("+14,698%" in res["report"] and "-32.4%" in res["report"],
      "report shows the numeric collapse, human-formatted")
rd = res["run_dir"]
for f in ("recompute.json", "diff.json", "ledger.json", "manifest.json", "report.txt"):
    truth(os.path.exists(os.path.join(rd, f)), "artifact written: %s" % f)
# in-toto / SLSA attestation + CycloneDX ML-BOM (the regulatory/procurement artifact)
att = json.load(open(os.path.join(rd, "attestation.json")))
truth(att["_type"] == "https://in-toto.io/Statement/v1", "attestation is an in-toto Statement v1")
truth(att["predicate"]["verdict"] == "REFUTED" and att["predicate"]["materials"], "attestation binds verdict + materials")
bom = json.load(open(os.path.join(rd, "mlbom.json")))
truth(bom["bomFormat"] == "CycloneDX" and bom["components"], "CycloneDX ML-BOM emitted with components")
man = json.load(open(os.path.join(rd, "manifest.json")))
truth(len(man.get("manifest_sha256", "")) == 64, "manifest has a sha256 root hash")
# the ledger written by the pipeline re-validates clean of schema/semantic errors (gate=1, not 2)
import ledger as LED  # noqa: E402
code, _ = LED.validate(os.path.join(rd, "ledger.json"))
truth(code == 1, "pipeline ledger validates (gate not-clean, no schema/semantic error)")

# --- CONFIRMED end-to-end on an honest claim ---
tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, "runs", "oos"))
shutil.copy(os.path.join(BTC, "runs", "oos", "returns.csv"), os.path.join(tmp, "runs", "oos", "returns.csv"))
# compute the TRUE total_return and claim exactly that
rec = RC.recompute_contract(os.path.join(BTC, "verify.yaml"), base=BTC, k=1)
true_val = rec["metrics"][0]["value"]
with open(os.path.join(tmp, "noop.py"), "w") as fh:
    fh.write("pass\n")  # artifact already committed; entrypoint is a no-op re-emit
with open(os.path.join(tmp, "verify.yaml"), "w") as fh:
    json.dump({"run": {"entrypoint": "noop.py", "network": "off"},
               "env": {"ecosystem": "python-stdlib", "trust": "own-code"},
               "artifacts": [{"path": "runs/oos/returns.csv", "re_emit": False,
                              "columns": {"strat_return": {"tag": "return", "na_policy": "error"}}}],
               "metrics": [{"metric_id": "total_return", "artifact": "runs/oos/returns.csv",
                            "binding": {"return": "strat_return"}, "claimed_value": true_val,
                            "headline": True, "binding_status": "independently-bound",
                            "claim_confirmed": True}],
               "baselines": []}, fh)
res2 = C.verify(tmp, run_id="honest")
# clean on both platforms: CONFIRMED when isolated (macOS Seatbelt), CONFIRMED-WITH-CAVEATS on a host
# without an isolation tier (e.g. Linux CI) - the invariant is that an honest claim never REFUTES.
truth(res2["repo_verdict"] in (V.CONFIRMED, V.CAVEATS),
      "honest matching claim is clean / not REFUTED (got %s)" % res2["repo_verdict"])
truth(res2["gate_exit"] == 0, "honest claim -> clean gate exit 0")
truth("CONFIRMED" in res2["report"], "report says CONFIRMED")

print("e2e: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
