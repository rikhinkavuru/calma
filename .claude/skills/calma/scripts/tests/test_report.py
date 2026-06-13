"""WS2 deliverable: the branded HTML report + the self-contained, offline replay bundle.
Asserts the report carries the verdict / claim / measured gap / explicit scope-of-verification
/ limits / integrity hashes, and that the replay bundle re-derives the verdict OFFLINE,
byte-for-byte, with no network and no calma install (pure stdlib, bundled). Run: python3 test_report.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import attest as A  # noqa: E402
import calma as C  # noqa: E402
import report as REP  # noqa: E402

BTC = os.path.realpath(os.path.join(SCR, "..", "assets", "btc"))
_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# a throwaway signing key so the report carries a real bundle (and the replay bundle is signed)
tmp_keys = tempfile.mkdtemp()
os.environ["CALMA_KEY_DIR"] = tmp_keys
A.keygen()

# a real REFUTED run on the BTC fixture
res = C.verify(BTC, run_id="test_report", force=True)
run_dir = res["run_dir"]
truth(res["repo_verdict"] == "REFUTED", "BTC fixture is REFUTED (the report renders a break)")

led = json.load(open(os.path.join(run_dir, "ledger.json")))
diff = json.load(open(os.path.join(run_dir, "diff.json"))) if \
    os.path.exists(os.path.join(run_dir, "diff.json")) else None
bundle = json.load(open(os.path.join(run_dir, A.BUNDLE_NAME)))

# --- render_html: the deliverable's content contract ---
html = REP.render_html(led, diff, bundle, run_dir)
truth(html.startswith("<!doctype html>") and html.rstrip().endswith("</html>"), "render_html is a full HTML doc")
truth("CALMA" in html, "report is branded")
truth("REFUTED" in html, "report shows the verdict")
truth("Claim under test" in html and "total_return" in html, "report states the claim under test")
truth("claimed" in html and "recomputed by re-execution" in html, "report shows the measured gap")
truth("Scope of verification" in html and "Did NOT assess" in html,
      "report carries an EXPLICIT scope-of-verification (verified X; did NOT assess Y)")
truth("Limits" in html, "report carries a limits statement")
truth("@media print" in html, "report has print CSS (prints to a clean PDF)")
truth("ledger sha256" in html and "manifest sha256" in html and "signing keyid" in html,
      "report carries the integrity hashes + signing keyid")
ledsha = REP._sha256_file(os.path.join(run_dir, "ledger.json"))
truth(ledsha and ledsha in html, "the ledger hash in the report matches the file on disk")
# no model in the loop: the report renders the verdict, it does not compute one
truth("model" in html.lower() and "never a model" in html.lower(), "report states the verdict is not model-computed")
# html-escaped, no raw injection of the target into a tag-breaking position
truth("<script" not in html.lower().replace("<script>" * 0, ""), "no stray script tags in the render")

# --- the full report() orchestration (writes html, builds the replay bundle, attempts pdf) ---
out = C.report(run_dir, pdf=False)
truth(os.path.exists(out["html"]), "report() writes the HTML file")
truth(out["signed"] is True, "report() signs the run (key present)")
rb = out["replay_dir"]
truth(os.path.isdir(rb), "report() builds the replay bundle dir")
for f in ("replay.sh", "replay_verify.py", "README.txt", "attestation.bundle.json", "ledger.json",
          "report.html"):
    truth(os.path.exists(os.path.join(rb, f)), "replay bundle contains %s" % f)
for s in ("attest.py", "ledger.py", "verdict.py", "ed25519.py", "sshsig.py"):
    truth(os.path.exists(os.path.join(rb, "calma", s)), "replay bundle ships pure-stdlib %s" % s)
truth(os.access(os.path.join(rb, "replay.sh"), os.X_OK), "replay.sh is executable")

# --- the acceptance test: the bundle re-derives the verdict OFFLINE on a fresh machine ---
# Copy it OUT of the repo, run with a MINIMAL env (no calma on PATH, no network used) and a
# scrubbed sys.path - the driver must rely only on its own bundled calma/ dir.
fresh = tempfile.mkdtemp()
import shutil as _sh
fresh_bundle = os.path.join(fresh, "replay")
_sh.copytree(rb, fresh_bundle)
env = {"PATH": "/usr/bin:/bin", "HOME": fresh}  # nothing from the parent (no PYTHONPATH, no calma)
p = subprocess.run([sys.executable, "replay_verify.py"], cwd=fresh_bundle, env=env,
                   capture_output=True, text=True)
truth(p.returncode == 0, "replay bundle re-derives offline -> exit 0 (out: %s)" % (p.stdout or p.stderr)[-200:])
truth("ledger-rederive  OK" in p.stdout, "replay output shows the verdict labels re-derive byte-for-byte")
truth("REFUTED" in p.stdout, "replay re-derives the SAME verdict (REFUTED)")
truth("signature        OK" in p.stdout, "replay verifies the signature offline")
# tamper: flip the embedded verdict and confirm the offline re-derivation REJECTS it
btampered = json.load(open(os.path.join(fresh_bundle, "attestation.bundle.json")))
import base64 as _b64
stmt = json.loads(_b64.b64decode(btampered["envelope"]["payload"]))
stmt["predicate"]["verdict"] = "CONFIRMED"  # lie
btampered["envelope"]["payload"] = _b64.b64encode(json.dumps(stmt).encode()).decode()
json.dump(btampered, open(os.path.join(fresh_bundle, "attestation.bundle.json"), "w"))
p2 = subprocess.run([sys.executable, "replay_verify.py"], cwd=fresh_bundle, env=env,
                    capture_output=True, text=True)
truth(p2.returncode != 0, "a tampered (forged-verdict) bundle FAILS the offline replay")

_sh.rmtree(fresh, ignore_errors=True)
print("report: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
