"""V3 walk-forward / regime robustness. The detector fires when an in-sample edge collapses
out-of-sample (corroborated by a KS regime-shift), stays silent on a stable series and without enough
history, and is scope-guarded on a robustness/walk-forward claim. Pure stdlib, offline.
Run: python3 test_regime_checks.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import ledger as LED  # noqa: E402
import regime_checks as RGC  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF


def _repo(returns):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "returns.csv"), "w", newline="") as fh:
        fh.write("daily_return\n")
        for r in returns:
            fh.write("%.8f\n" % r)
    return d


def _contract(**extra):
    c = {"metrics": [{"metric_id": "total_return", "artifact": "returns.csv",
                      "binding": {"return": "daily_return"}, "claimed_value": 0.1, "headline": True,
                      "binding_status": "independently-bound"}]}
    c.update(extra)
    return c


# collapse series: a strong first half, a flat/negative second half (the edge holds in one regime only)
g = _lcg(5)
collapse = [round(0.012 + (next(g) - 0.5) * 0.01, 8) for _ in range(20)] + \
           [round(-0.001 + (next(g) - 0.5) * 0.01, 8) for _ in range(20)]
# stable series: a consistent edge across the whole sample
g2 = _lcg(9)
stable = [round(0.004 + (next(g2) - 0.5) * 0.01, 8) for _ in range(40)]

dc, ds = _repo(collapse), _repo(stable)

# --- detector: fires on the collapse (activated by a windows block) ---
f = RGC.check_regime(_contract(windows={"k": 2}), dc, "c1", "total return")
truth(f and f["dimension"] == "regime" and "collapses out-of-sample" in f["locator"],
      "regime: an IS edge that collapses OOS fires a regime finding")
truth(f and "KS test rejects" in f["locator"], "regime: the KS regime-shift corroborates in the reason")
# activated by a robustness CLAIM (no windows block)
truth(RGC.run_checks(_contract(), dc, "c1", "robust across regimes, walk-forward validated"),
      "regime: a robustness/walk-forward claim auto-activates the check")
# a stable result -> SILENT
truth(RGC.run_checks(_contract(windows={"k": 2}), ds, "c1", "total return") == [],
      "regime: a stable edge across the sample is SILENT (no false alarm)")
# neither a windows block nor a robustness claim -> NOT APPLICABLE (silent)
truth(RGC.run_checks(_contract(), dc, "c1", "total return 0.1") == [],
      "regime: ABSTAINS with no windows block and no robustness claim")
# insufficient history -> ABSTAIN
short = _repo(collapse[:8])
truth(RGC.run_checks(_contract(windows={"k": 2}), short, "c1", "walk-forward") == [],
      "regime: ABSTAINS without enough history to split")


# --- promotion (scope-guarded on the robustness assertion) ---
def _confirmed_claim():
    vi = {"gap": 0.0, "effective_budget": 1e-9, "binding_status": "independently-bound",
          "determinism_mode": "controlled-to-bit", "container_present": True, "band_coverage_ok": True,
          "sufficient_k": True, "exit_codes": [0], "claim_confirmed_target": True}
    return {"id": "c1", "headline": True, "metric": "total_return", "claimed_value": 0.1,
            "recomputed_value": 0.1, "verdict": V.verdict(vi),
            "input_binding_status": "independently-bound", "headline_confidence": 0.9,
            "verdict_inputs": vi, "verdict_status": "stable", "waivable": False, "reason": "ok"}


def _promote(contract, base, claim_text):
    claims = [_confirmed_claim()]
    findings = RGC.run_checks(contract, base, "c1", claim_text)
    RGC.apply_validity(claims, findings, contract, claim_text, base=base)
    return claims[0], findings


def _ledger_valid(claims, findings):
    led = {"schema": "calma/ledger@1", "claims": claims, "findings": findings,
           "scope": {"isolation_tier": "tier0", "determinism_mode": "controlled-to-bit",
                     "families": {}, "not_verified": []}, "repo_verdict": None}
    led["repo_verdict"] = LED.compute_repo_verdict(led)
    return LED.validate_obj(led)


hc, hf = _promote(_contract(windows={"k": 2}), dc, "a robust edge, consistent across every regime")
truth(hc["verdict"] == V.INVALIDATED and hc.get("driving_dimension") == "regime",
      "regime: OOS collapse + a robustness claim -> INVALIDATED('regime')")
truth(_ledger_valid([hc], hf)[0] in (0, 1), "regime INVALIDATED ledger validates")
nc, _ = _promote(_contract(windows={"k": 2}), dc, "total return 0.1")
truth(nc["verdict"] == V.CAVEATS,
      "regime scope-guard: a windows block but no robustness claim -> CAVEATS, not INVALIDATED")

truth(RGC.family_status(_contract(), []) == "not-applicable", "family_status: not-applicable by default")
truth(RGC.family_status(_contract(windows={"k": 2}), hf) == "flagged", "family_status: flagged on a finding")

print("regime_checks: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
