"""Tests for ledger.py: gate authority, _validate re-derivation, REFUTED structural rules.
Pure stdlib. Run: python3 test_ledger.py
"""
import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import ledger as L  # noqa: E402
import verdict as V  # noqa: E402

BTC = os.path.join(HERE, "..", "..", "assets", "btc", "ledger.json")
_n = _fail = 0


def expect(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- the real BTC fixture validates and gates to NOT-CLEAN (exit 1) ---
code, info = L.validate(BTC)
expect(code == 1, "BTC ledger valid but not clean -> exit 1 (got %s: %s)" % (code, info))
expect(info.get("repo_verdict") == "REFUTED", "BTC repo_verdict REFUTED")

btc = L.load_ledger(BTC)
expect(not L.structural_validate(btc), "BTC structural ok")
expect(not L.semantic_validate(btc), "BTC semantic ok")
expect(V.verdict(btc["claims"][0]["verdict_inputs"]) == "REFUTED", "BTC claim re-derives REFUTED")

# --- a REFUTED claim with NO linked blocker finding -> semantic error ---
bad = copy.deepcopy(btc)
bad["findings"] = [f for f in bad["findings"] if f["dimension"] != "baseline"]
expect(bool(L.semantic_validate(bad)), "REFUTED without linked blocker -> error")

# --- a tampered label that doesn't re-derive -> semantic error ---
bad2 = copy.deepcopy(btc)
bad2["claims"][0]["verdict"] = "CONFIRMED"
bad2["repo_verdict"] = "CONFIRMED"
expect(bool(L.semantic_validate(bad2)), "non-re-deriving label -> error")

# --- non-waivable REFUTED + clean repo_verdict -> error ---
bad3 = copy.deepcopy(btc)
bad3["repo_verdict"] = "CONFIRMED-WITH-CAVEATS"
expect(bool(L.semantic_validate(bad3)), "non-waivable REFUTED cannot be clean")

# --- REFUTED on a non-independently-bound input -> error ---
bad4 = copy.deepcopy(btc)
bad4["claims"][0]["input_binding_status"] = "plausibly-bound"
expect(bool(L.semantic_validate(bad4)), "REFUTED needs independently-bound input")

# --- execution-derived finding marked static-reread -> error ---
bad5 = copy.deepcopy(btc)
bad5["findings"][0]["reverify"]["kind"] = "static-reread"
expect(bool(L.semantic_validate(bad5)), "exec-derived finding cannot be static-reread")

# --- a clean all-CONFIRMED ledger gates to exit 0 ---
clean = {
    "repo_verdict": "CONFIRMED", "scope": {},
    "claims": [{
        "id": "c1", "headline": True, "verdict": "CONFIRMED",
        "input_binding_status": "independently-bound",
        "verdict_inputs": {
            "gap": 0.001, "effective_budget": 0.01, "binding_status": "independently-bound",
            "container_present": True, "determinism_mode": "controlled-to-bit",
            "band_coverage_ok": True, "sufficient_k": True, "claim_confirmed_target": True,
            "claim_outside_ci": True,
        },
    }],
    "findings": [],
}
expect(not L.structural_validate(clean) and not L.semantic_validate(clean), "clean ledger valid")
expect(L.gate(clean)[0] == 0, "clean ledger gates to exit 0")

print("ledger.py: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
