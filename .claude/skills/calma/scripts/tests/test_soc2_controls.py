"""Tests for soc2_controls.py - the four Calma SOC 2 controls as one auditable evidence pack (master §1.2).
Pure stdlib. Runs the real controls on this host (a few seconds — sandbox probes). Run: python3 test_soc2_controls.py"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import soc2_controls as SC  # noqa: E402

_n = _fail = 0


def expect(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- the consolidated pack ---
pack = SC.run_controls(as_of="2026-06-24")
expect(pack["control_pack"] == SC.CONTROL_PACK and pack["as_of"] == "2026-06-24", "evidence-pack shape + date")
names = {c["name"] for c in pack["controls"]}
expect(names == {"sandbox-isolation", "egress-blocked", "no-raw-data-retention", "verdict-integrity"},
       "all four §1.2 controls run")
expect(all(c["result"] in ("verified", "skipped-host-not-isolated", "skipped", "FAILED", "LEAK") for c in pack["controls"]),
       "every control reports an honest result")
expect(pack["all_pass"] is (not any(str(c["result"]) in ("FAILED", "LEAK") for c in pack["controls"])),
       "all_pass iff no control FAILED/LEAKed (a skip is not a failure)")
json.dumps(pack)
expect(True, "the evidence pack is JSON-serialisable")

# --- the always-attestable controls (no sandbox needed) MUST verify ---
nr = SC.control_no_raw_retention()
expect(nr["result"] == "verified", "no-raw-data-retention verifies (the registry whitelist is metadata-only + fails closed)")
vi = SC.control_verdict_integrity()
expect(vi["result"] == "verified" and vi.get("engine_version"), "verdict-integrity verifies on the signed BTC fixture + pins the engine version")

# --- sandbox-dependent controls: verified under a tier, else honestly skipped (never a false pass) ---
iso, eg = SC.control_isolation(), SC.control_egress()
expect(iso["result"] in ("verified", "skipped-host-not-isolated"), "sandbox-isolation: verified or honestly skipped")
expect(eg["result"] in ("verified", "skipped-host-not-isolated"), "egress: verified or honestly skipped")
if iso["result"] == "verified":
    expect(eg["result"] == "verified" and pack["all_pass"], "under a verified tier: isolation + egress both verify, pack passes")

# --- ADVERSARIAL: verdict-integrity must CATCH a tampered ledger (a stored label that doesn't re-derive) ---
import ledger as L  # noqa: E402
led = L.load_ledger(SC._BTC_LEDGER)
led["claims"][0]["verdict"] = "CONFIRMED"            # forge the REFUTED headline to CONFIRMED
led["repo_verdict"] = "CONFIRMED"
tampered = os.path.join(tempfile.mkdtemp(), "ledger.json")
json.dump(led, open(tampered, "w"))
expect(SC.control_verdict_integrity(tampered)["result"] == "FAILED",
       "verdict-integrity FAILS on a tampered ledger (the forged label doesn't re-derive — the control bites)")

# --- main() exit code: 0 when all pass ---
expect(SC.main(["--as-of", "2026-06-24"]) in (0, 1), "main runs + returns a 0/1 exit")
if pack["all_pass"]:
    expect(SC.main(["--as-of", "2026-06-24"]) == 0, "main exits 0 when all controls pass")

print("soc2_controls: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
