"""Catch-history registry: redacted entry derivation, the hash chain, signed HEAD, and the
tamper matrix - edited entries, reordered/dropped entries, truncated tails, re-signed chains
under a foreign key, redaction leaks. Plus the CLI surface: publish requires attest, opened
engagements without outcomes stay visible. Pure stdlib.
Run: python3 test_registry.py
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import attest as A  # noqa: E402
import calma as C  # noqa: E402
import ed25519 as E  # noqa: E402
import registry as R  # noqa: E402

BTC = os.path.realpath(os.path.join(SCR, "..", "assets", "btc"))
CALMA = os.path.join(SCR, "calma.py")
_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


tmp_keys = tempfile.mkdtemp()
os.environ["CALMA_KEY_DIR"] = tmp_keys
info = A.keygen()
seed = bytes.fromhex(open(info["key_path"]).read().strip())

# a real attested run to derive entries from
res = C.verify(BTC, run_id="test_registry", opts=C.VerifyOptions(force=True))
bundle = json.load(open(os.path.join(res["run_dir"], A.BUNDLE_NAME)))

# --- derivation + redaction ---
entry = R.derive_entry(bundle)
truth(set(entry) <= R.ALLOWED_FIELDS, "derived entry only carries whitelisted fields")
truth(entry["verdict"] == "REFUTED" and entry["claimed"] is not None
      and entry["recomputed"] is not None, "entry carries claimed vs recomputed + verdict")
blob = json.dumps(entry)
truth("returns.csv" not in blob and "backtest.py" not in blob and "/" not in entry["target"],
      "no artifact paths, no code names, no path separators leak into the entry")
truth(len(entry.get("manifest_sha256", "")) == 64 and len(entry.get("ledger_sha256", "")) == 64,
      "content hashes (not contents) bind the entry to the evidence")

# --- chain append + verify ---
reg = tempfile.mkdtemp()
f1, w1 = R.append_entry(reg, R.opened_entry("ENG-001", note="seeded fund, Q2 diligence"), seed)
f2, w2 = R.append_entry(reg, R.derive_entry(bundle, engagement="ENG-001"), seed)
f3, w3 = R.append_entry(reg, R.derive_entry(bundle), seed)
ok, checks, summary = R.verify_chain(reg)
truth(ok, "a 3-entry chain verifies: %s" % [c for c in checks if not c[1]])
truth(summary["entries"] == 3 and summary["verdicts"].get("REFUTED") == 2,
      "summary counts entries and verdicts")
truth(w2["entry"]["prev"] == w1["id"] and w3["entry"]["prev"] == w2["id"],
      "each entry embeds the previous entry's hash")
truth(summary["open_engagements"] == [], "an outcome closes the opened engagement")

# --- INVALIDATED is first-class through attest + the registry (the load-bearing property): a bundle
# whose embedded ledger re-derives to INVALIDATED verifies, and the redacted entry records the verdict
# string VERBATIM (never serialized as a CONFIRMED-anything). No registry schema change was needed. ---
_man = json.loads(base64.b64decode(bundle["envelope"]["payload"]))["predicate"]["manifest"]
_inval_led = {
    "schema": "calma/ledger@1", "repo_verdict": "INVALIDATED", "target": "leakage-fixture",
    "scope": {"isolation_tier": "tier0", "determinism_mode": "controlled-to-bit"},
    "claims": [{
        "id": "c1", "headline": True, "verdict": "INVALIDATED",
        "input_binding_status": "independently-bound",
        "verdict_inputs": {"gap": 0.0, "effective_budget": 1e-9, "binding_status": "independently-bound",
                           "determinism_mode": "controlled-to-bit", "container_present": True,
                           "band_coverage_ok": True, "sufficient_k": True, "exit_codes": [0],
                           "claim_outside_ci": False, "claim_confirmed_target": True,
                           "validity_invalidated": True, "oos_claim_asserted": True},
        "driving_dimension": "leakage", "waivable": False,
        "metric": "auc", "claimed_value": 0.94, "recomputed_value": 0.94,
    }],
    "findings": [{
        "id": "f-c1-leak", "claim_id": "c1", "dimension": "leakage", "severity": "blocker",
        "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": "held-out AUC isn't held-out: 30% exact row overlap",
        "unblock": "evaluate on a split with no train/test overlap, then re-verify",
        "reverify": {"kind": "artifact-recheck", "source": "rows", "expected": "zero overlap"},
    }],
}
_ibundle = A.make_bundle(_inval_led, _man, seed)
_iok, _ichecks = A.verify_bundle(_ibundle)
truth(_iok, "an INVALIDATED bundle verifies (re-derives byte-for-byte): %s" % [c for c in _ichecks if not c[1]])
_ientry = R.derive_entry(_ibundle)
truth(_ientry["verdict"] == "INVALIDATED" and set(_ientry) <= R.ALLOWED_FIELDS,
      "the redacted entry records verdict=INVALIDATED verbatim, whitelisted (no CONFIRMED-anything)")
_ireg = tempfile.mkdtemp()
R.append_entry(_ireg, _ientry, seed)
_iok2, _, _isum = R.verify_chain(_ireg)
truth(_iok2 and _isum["verdicts"].get("INVALIDATED") == 1,
      "the INVALIDATED entry hash-chains and the audit counts it as first-class")

# opened-without-outcome stays visible (the clinical-trial property)
reg2 = tempfile.mkdtemp()
R.append_entry(reg2, R.opened_entry("ENG-XYZ"), seed)
ok2, _, sum2 = R.verify_chain(reg2)
truth(ok2 and sum2["open_engagements"] == ["ENG-XYZ"],
      "an opened engagement with no outcome is structurally visible")

# pinned key: the right key passes, a foreign key fails
okp, _, _ = R.verify_chain(reg, pinned_pub_hex=info["public_key"])
truth(okp, "chain verifies under the pinned lab key")
attacker = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
okp2, checksp2, _ = R.verify_chain(reg, pinned_pub_hex=E.secret_to_public(attacker).hex())
truth(not okp2, "chain under a different pinned key fails")

# --- tamper matrix ---
def fresh_copy():
    d = tempfile.mkdtemp()
    shutil.copytree(reg, d, dirs_exist_ok=True)
    return d

# (1) edit a field in place -> id mismatch
d = fresh_copy()
fn = R.list_entry_files(d)[1]
p = os.path.join(d, "entries", fn)
w = json.load(open(p))
w["entry"]["verdict"] = "CONFIRMED"
json.dump(w, open(p, "w"))
ok, checks, _ = R.verify_chain(d)
truth(not ok and any("id" in n and not o for n, o, _ in checks),
      "editing a published verdict breaks the entry's content address")

# (2) edit + re-hash (fix the id) -> signature fails
d = fresh_copy()
p = os.path.join(d, "entries", R.list_entry_files(d)[1])
w = json.load(open(p))
w["entry"]["verdict"] = "CONFIRMED"
w["id"] = R.entry_id(w["entry"])
json.dump(w, open(p, "w"))
ok, checks, _ = R.verify_chain(d)
# the id now matches but the NEXT entry's prev no longer does, or the signature fails first
truth(not ok, "editing + re-hashing still breaks (signature or the next entry's prev)")

# (3) drop a middle entry -> chain link fails
d = fresh_copy()
os.remove(os.path.join(d, "entries", R.list_entry_files(d)[1]))
ok, checks, _ = R.verify_chain(d)
truth(not ok and any("chain" in n and not o for n, o, _ in checks),
      "silently dropping a middle entry breaks the chain")

# (4) truncate the tail (drop the newest entry) -> signed HEAD catches it
d = fresh_copy()
os.remove(os.path.join(d, "entries", R.list_entry_files(d)[-1]))
ok, checks, _ = R.verify_chain(d)
truth(not ok and any(n == "HEAD" and not o for n, o, _ in checks),
      "truncating the tail breaks the signed HEAD")

# (5) reorder: swap the seq/filenames of two entries -> chain fails
d = fresh_copy()
fns = R.list_entry_files(d)
a_p, b_p = (os.path.join(d, "entries", x) for x in fns[1:3])
wa, wb = json.load(open(a_p)), json.load(open(b_p))
json.dump(wb, open(a_p, "w"))
json.dump(wa, open(b_p, "w"))
ok, checks, _ = R.verify_chain(d)
truth(not ok, "reordering entries breaks the chain")

# (6) full re-sign under the attacker's key: internally consistent, so it verifies UNPINNED -
# this is exactly why the lab key is pinned/published and commits are signed; pinned must fail
d = fresh_copy()
shutil.rmtree(d)
d = tempfile.mkdtemp()
R.append_entry(d, R.opened_entry("ENG-001", note="seeded fund, Q2 diligence"), attacker)
ok, _, _ = R.verify_chain(d, pinned_pub_hex=info["public_key"])
truth(not ok, "a chain rebuilt under a foreign key fails against the pinned lab key")

# (7) redaction guard: a leaked field is rejected at append AND at verify
try:
    R.append_entry(tempfile.mkdtemp(), dict(R.opened_entry("E"), code_path="/Users/x/secret.py"),
                   seed)
    truth(False, "append rejects non-whitelisted fields")
except ValueError:
    truth(True, "append rejects non-whitelisted fields")
d = fresh_copy()
p = os.path.join(d, "entries", R.list_entry_files(d)[0])
w = json.load(open(p))
w["entry"]["data_sample"] = "leak"
w["id"] = R.entry_id(w["entry"])
json.dump(w, open(p, "w"))
ok, checks, _ = R.verify_chain(d)
truth(not ok and any("redaction" in n and not o for n, o, _ in checks),
      "verify rejects entries carrying non-whitelisted fields")

# --- CLI surface ---
env = dict(os.environ)
# publish without a bundle -> exit 2 with the attest hint
bare = tempfile.mkdtemp()
os.makedirs(os.path.join(bare, "x"))
r = subprocess.run([sys.executable, CALMA, "publish", os.path.join(bare, "x"),
                    "--registry", tempfile.mkdtemp()], capture_output=True, text=True, env=env)
truth(r.returncode == 2 and "publish requires attest" in r.stderr,
      "publish without a bundle exits 2 and names the fix")

# end-to-end: publish the attested run, then registry verify
cli_reg = tempfile.mkdtemp()
r = subprocess.run([sys.executable, CALMA, "publish", res["run_dir"], "--registry", cli_reg],
                   capture_output=True, text=True, env=env)
truth(r.returncode == 0 and "published:" in r.stdout and "REFUTED" in r.stdout,
      "calma publish appends a redacted entry: %s" % r.stderr.strip()[:120])
r = subprocess.run([sys.executable, CALMA, "registry", "verify", cli_reg],
                   capture_output=True, text=True, env=env)
truth(r.returncode == 0 and r.stdout.startswith("REGISTRY VERIFIED"),
      "calma registry verify audits the chain: %s" % r.stdout.splitlines()[:1])
r = subprocess.run([sys.executable, CALMA, "publish", "--open", "ENG-042",
                    "--registry", cli_reg], capture_output=True, text=True, env=env)
truth(r.returncode == 0, "calma publish --open records the engagement")
r = subprocess.run([sys.executable, CALMA, "registry", "verify", cli_reg],
                   capture_output=True, text=True, env=env)
truth("ENG-042" in r.stdout, "the open engagement is visible in the audit output")

del os.environ["CALMA_KEY_DIR"]
shutil.rmtree(tmp_keys, ignore_errors=True)

print("registry: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
