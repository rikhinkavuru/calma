"""D1: the credibility flywheel. (1) registry_site.build_site renders a self-contained, deployable
static site from a hash-chained registry, ships the raw re-verifiable registry beside it, and the
copy still passes the offline chain audit. (2) the auto-mode LOCAL catch-record helpers: enabled by
default, opt-out via config, local-only (never the gated outward push). Renders only the redaction
whitelist - no code/data leaks into the HTML. Pure stdlib, offline. Run: python3 test_registry_site.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import attest as A  # noqa: E402
import calma as C  # noqa: E402
import registry as R  # noqa: E402
import registry_site as RS  # noqa: E402

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

# build a small real registry: a REFUTED entry built from the redaction-whitelist fields (the same
# shape derive_entry emits), then appended (signed + hash-chained) via the real append_entry path.
reg = tempfile.mkdtemp()
entry = {
    "schema": R.ENTRY_SCHEMA, "kind": "verification", "date": "2026-06-20", "target": "btc",
    "claim": "claimed total_return 146.98", "metric": "total_return",
    "claimed": 146.98, "recomputed": -0.324, "verdict": "REFUTED", "note": "genesis",
    "manifest_sha256": "a" * 64, "ledger_sha256": "c" * 64, "contract_sha256": "b" * 64,
    "keyid": "deadbeef", "time_verified": "2026-06-20T00:00:00Z",
}
truth(set(entry) <= R.ALLOWED_FIELDS, "precondition: the test entry only uses whitelisted fields")
fname, wrapper = R.append_entry(reg, entry, seed)
truth(wrapper["entry"]["verdict"] == "REFUTED", "precondition: a REFUTED entry is in the registry")

# --- build_site renders index.html + a re-verifiable raw copy ---
out = tempfile.mkdtemp()
site = RS.build_site(reg, out)
idx = os.path.join(site, "index.html")
truth(os.path.isfile(idx), "build_site writes index.html")
html = open(idx).read()
truth(html.startswith("<!doctype html>") and "CALMA" in html, "site is a full, branded HTML doc")
truth("CHAIN VERIFIED" in html, "site leads with the offline-re-derived chain status")
truth("REFUTED" in html and "146.98" in html and "-0.324" in html,
      "site shows the claimed -> recomputed gap + verdict")
truth("calma registry verify" in html and "ssh-keygen -Y verify" in html,
      "site tells the visitor to verify the BYTES (don't trust the HTML)")
# no leakage: only whitelisted fields can appear (derive_entry already enforced it; the render re-escapes)
truth("backtest.py" not in html and "returns.csv" not in html,
      "no code/data names leak into the rendered site")

# the raw registry ships beside the page AND still passes the offline audit from the copy
raw = os.path.join(site, "registry")
truth(os.path.isfile(os.path.join(raw, "HEAD.json"))
      and os.path.isdir(os.path.join(raw, "entries")), "the raw re-verifiable registry is copied in")
ok, _checks, summary = R.verify_chain(raw)
truth(ok and summary.get("entries") == 1, "the COPIED registry re-verifies offline (chain intact)")

# guards
try:
    RS.build_site(tempfile.mkdtemp())   # a dir with no HEAD.json is not a registry
    truth(False, "build_site rejects a non-registry dir")
except ValueError:
    truth(True, "build_site rejects a non-registry dir (no HEAD.json)")
try:
    RS.build_site(reg, reg)             # out == registry dir would clobber the source
    truth(False, "build_site refuses --out == the registry dir")
except ValueError:
    truth(True, "build_site refuses --out == the registry dir")

# --- the auto-mode LOCAL catch-record helpers ---
truth(C._local_catch_record_enabled(tempfile.mkdtemp()) is True,
      "local catch-record is ON by default (no config)")
off = tempfile.mkdtemp()
os.makedirs(os.path.join(off, ".calma"))
json.dump({"autonomy": {"local_catch_record": False}},
          open(os.path.join(off, ".calma", "config.json"), "w"))
truth(C._local_catch_record_enabled(off) is False,
      "local catch-record opt-out is honored (config local_catch_record:false)")
_saved = os.environ.pop("CALMA_REGISTRY_DIR", None)
truth(C._local_catch_record_dir().endswith(os.path.join(".calma", "registry")),
      "the default local catch-record lives under ~/.calma/registry (local-only)")
os.environ["CALMA_REGISTRY_DIR"] = "/tmp/explicit_reg"
truth(C._local_catch_record_dir() == "/tmp/explicit_reg",
      "CALMA_REGISTRY_DIR overrides the local catch-record location")
if _saved is None:
    os.environ.pop("CALMA_REGISTRY_DIR", None)
else:
    os.environ["CALMA_REGISTRY_DIR"] = _saved

print("registry_site: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
