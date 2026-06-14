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

# --- fail-closed: an unknown repo_verdict NEVER gates clean (exit 0) ---
expect(L.gate({"repo_verdict": "ZZZ_UNKNOWN", "findings": []})[0] == 1,
       "fail-closed: unknown repo_verdict gates to exit 1 (allowlist clean)")

# --- INVALIDATED: the number reproduces, but the result is invalid (gap-free, OOS-gated) ---
_ivi = {
    "gap": 0.0, "effective_budget": 1e-9, "binding_status": "independently-bound",
    "determinism_mode": "controlled-to-bit", "container_present": True, "band_coverage_ok": True,
    "sufficient_k": True, "exit_codes": [0], "claim_outside_ci": False, "claim_confirmed_target": True,
    "validity_invalidated": True, "oos_claim_asserted": True,
}
INVAL = {
    "repo_verdict": "INVALIDATED",
    "scope": {"isolation_tier": "tier0", "determinism_mode": "controlled-to-bit"},
    "claims": [{
        "id": "c1", "headline": True, "verdict": "INVALIDATED",
        "input_binding_status": "independently-bound", "verdict_inputs": _ivi,
        "driving_dimension": "leakage", "waivable": False,
        "metric": "auc", "claimed_value": 0.94, "recomputed_value": 0.94,
    }],
    "findings": [{
        "id": "f-c1-leak", "claim_id": "c1", "dimension": "leakage", "severity": "blocker",
        "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": "held-out AUC isn't held-out: 30% exact row overlap (150/500 test rows)",
        "unblock": "evaluate on a split with no train/test overlap, then re-verify",
        "reverify": {"kind": "artifact-recheck", "source": "rows", "expected": "zero train/test overlap"},
    }],
}
expect(not L.structural_validate(INVAL), "INVALIDATED ledger structural ok")
expect(not L.semantic_validate(INVAL), "INVALIDATED ledger semantic ok")
expect(L.validate_obj(INVAL)[0] == 1, "INVALIDATED ledger valid but not clean -> exit 1")
expect(L.gate(INVAL)[1]["open_blocking"] == 1, "INVALIDATED carries an open blocker")
expect(L.compute_repo_verdict(INVAL) == "INVALIDATED", "headline INVALIDATED -> repo INVALIDATED")
expect(V.verdict(INVAL["claims"][0]["verdict_inputs"]) == "INVALIDATED", "claim re-derives INVALIDATED")

# non-headline INVALIDATED rolls up to MIXED (peer of non-headline REFUTED)
_nh = copy.deepcopy(INVAL)
_nh["claims"][0]["headline"] = False
expect(L.compute_repo_verdict(_nh) == "MIXED", "non-headline INVALIDATED -> MIXED")

# INVALIDATED needs a linked blocker finding of the driving dimension
_bad_a = copy.deepcopy(INVAL)
_bad_a["findings"] = []
expect(bool(L.semantic_validate(_bad_a)), "INVALIDATED without a linked blocker -> error")

# INVALIDATED requires an out-of-sample claim assertion (the scope-guard)
_bad_b = copy.deepcopy(INVAL)
_bad_b["claims"][0]["verdict_inputs"] = dict(_ivi, oos_claim_asserted=False)
expect(bool(L.semantic_validate(_bad_b)), "INVALIDATED without an OOS assertion -> error (re-derive + branch)")

# leakage is an EXEC dimension: its finding cannot be static-reread
_bad_c = copy.deepcopy(INVAL)
_bad_c["findings"][0]["reverify"]["kind"] = "static-reread"
expect(bool(L.semantic_validate(_bad_c)), "leakage finding cannot be static-reread")

# a non-waivable INVALIDATED cannot coexist with a clean repo_verdict
_bad_d = copy.deepcopy(INVAL)
_bad_d["repo_verdict"] = "CONFIRMED-WITH-CAVEATS"
expect(bool(L.semantic_validate(_bad_d)), "non-waivable INVALIDATED cannot be clean")

print("ledger.py: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
