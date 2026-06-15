"""Tests for overfitting_checks.py: the engagement lattice (silent NOT-APPLICABLE / valid-N verdict /
uncountable-N CAN'T-CONFIRM / bare-number CAVEAT), num-trials integrity (N never guessed), the
per-period-SR wiring, and the verdict promotion through real ledgers. Pure stdlib.
Run: python3 test_overfitting_checks.py
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import overfitting_checks as OC  # noqa: E402
import ledger as L  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def _write(path, header, rows):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def _returns_dir(sr_target, n=120):
    """A dir with returns.csv whose per-period Sharpe ~= sr_target (mean/std of raw returns)."""
    d = __import__("tempfile").mkdtemp()
    pat = [((i % 5) - 2) for i in range(n)]  # mean 0, std ~1.414
    std_unit = (sum(p * p for p in pat) / (n - 1)) ** 0.5
    rets = [0.02 * (sr_target + pat[i] / std_unit) for i in range(n)]  # mean/std -> ~sr_target
    _write(os.path.join(d, "returns.csv"), ["ret"], [[r] for r in rets])
    return d


def _con(d, **extra):
    c = {"metrics": [{"metric_id": "sharpe", "artifact": "returns.csv", "binding": {"return": "ret"},
                      "headline": True, "claimed_value": 1.0}], "artifacts": []}
    c.update(extra)
    return c


def _kind(findings, k):
    return next((f for f in findings if f.get("overfit_kind") == k), None)


def _confirmed_claim():
    vi = {"gap": 0.0, "effective_budget": 1e-9, "binding_status": "independently-bound",
          "determinism_mode": "controlled-to-bit", "container_present": True, "band_coverage_ok": True,
          "sufficient_k": True, "exit_codes": [0], "claim_outside_ci": False, "claim_confirmed_target": True}
    return {"id": "c1", "headline": True, "verdict": V.verdict(vi), "input_binding_status": "independently-bound",
            "verdict_inputs": vi, "waivable": False, "metric": "sharpe", "claimed_value": 1.0, "recomputed_value": 1.0}


def _ledger(claims, findings):
    led = {"schema": "calma/ledger@1", "claims": claims, "findings": findings,
           "scope": {"isolation_tier": "tier0", "determinism_mode": "controlled-to-bit"}, "repo_verdict": None}
    led["repo_verdict"] = L.compute_repo_verdict(led)
    return led


# ---- (a) NO search signal -> NOT-APPLICABLE, SILENT ----
dA = _returns_dir(0.20)
cA = _con(dA)
fA = OC.run_checks(cA, dA, "c1", claim_text="sharpe 1.0")
truth(fA == [], "no trials / no selection language -> SILENT (zero findings)")
truth(OC.search_signal(cA, dA, "sharpe 1.0") is None, "no search signal detected")
truth(OC.family_status(cA, dA, fA, "sharpe 1.0") == "not-applicable", "family NOT-APPLICABLE")

# ---- (b) valid N (declared) + edge FAILS DSR + survival claim -> INVALIDATED ----
dB = _returns_dir(0.05)  # a weak per-period edge
cB = _con(dB, trials=1000, var_sr=0.002)
fB = OC.run_checks(cB, dB, "c1", claim_text="the best Sharpe of 1000 backtested configs")
_auth = _kind(fB, "multiple-testing")
truth(_auth is not None and _auth["validity_class"] == "authoritative",
      "weak edge vs a 1000-trial deflated benchmark -> authoritative overfitting finding")
clB = [_confirmed_claim()]
OC.apply_validity(clB, fB, cB, "the best Sharpe of 1000 backtested configs")
truth(clB[0]["verdict"] == V.INVALIDATED, "fails + survival claim -> INVALIDATED (got %s)" % clB[0]["verdict"])
truth(clB[0].get("driving_dimension") == "overfitting", "driving_dimension = overfitting")
ledB = _ledger(clB, fB)
truth(L.validate_obj(ledB)[0] == 1 and ledB["repo_verdict"] == V.INVALIDATED, "INVALIDATED ledger validates")

# ---- (c) valid N + edge SURVIVES DSR -> clean (no finding) ----
dC = _returns_dir(0.30)  # a strong per-period edge
cC = _con(dC, trials=10, var_sr=0.002)
fC = OC.run_checks(cC, dC, "c1", claim_text="sharpe, best of 10")
truth(fC == [], "a strong edge clears the deflated benchmark -> clean (no finding)")
truth(OC.family_status(cC, dC, fC, "sharpe, best of 10") == "checked", "family 'checked' (assessed, survived)")

# ---- (d) search signal (selection language) + UNCOUNTABLE N -> CAN'T-CONFIRM + declare-N fix ----
dD = _returns_dir(0.20)
cD = _con(dD)  # no trials, no artifact
fD = OC.run_checks(cD, dD, "c1", claim_text="the best Sharpe of 200 configurations we tried")
_unc = _kind(fD, "uncountable")
truth(_unc is not None, "selection language but no countable N -> an 'uncountable' finding (not silent)")
truth(any("trials:N" in (f.get("unblock") or "") for f in fD), "the fix tells the author to declare trials:N")
clD = [_confirmed_claim()]
OC.apply_validity(clD, fD, cD, "the best Sharpe of 200 configurations we tried")
truth(clD[0]["verdict"] == V.INCONCLUSIVE, "uncountable + survival claim -> CAN'T-CONFIRM (got %s)" % clD[0]["verdict"])
truth(L.gate(_ledger(clD, fD))[0] == 1, "CAN'T-CONFIRM gates to exit 1")

# ---- (e) edge FAILS but the claim is a BARE number (sweep only detected) -> CAVEAT, never INVALIDATED ----
dE = _returns_dir(0.05)
cE = _con(dE, trials=1000, var_sr=0.002)
fE = OC.run_checks(cE, dE, "c1", claim_text="sharpe 0.05")  # no selection language
truth(_kind(fE, "multiple-testing") is not None, "the overfitting finding still fires (sweep detected)")
clE = [_confirmed_claim()]
OC.apply_validity(clE, fE, cE, "sharpe 0.05")
truth(clE[0]["verdict"] == V.CAVEATS, "fails + bare reproduced number -> CONFIRMED-WITH-CAVEATS (got %s)" % clE[0]["verdict"])
truth(L.gate(_ledger(clE, fE))[0] == 0, "the bare-number caveat is exit 0 (never block a literally-true number)")

# ---- num-trials integrity: N is NEVER guessed (declared trials but no var_sr/matrix -> uncountable) ----
dF = _returns_dir(0.05)
cF = _con(dF, trials=1000)  # N declared but no var_sr and no matrix -> DSR not computable
fF = OC.run_checks(cF, dF, "c1", claim_text="best of 1000")
truth(_kind(fF, "uncountable") is not None and _kind(fF, "multiple-testing") is None,
      "declared N but no var_sr/matrix -> uncountable (N never guessed into a DSR)")

# ---- per-period-SR wiring: the SR fed to DSR is mean/std of RAW returns, not annualised ----
_rd = _returns_dir(0.05)
_rets = OC._returns(_con(_rd), _rd)
truth(_rets and abs(OC._per_period_sharpe(_rets) - 0.05) < 0.02,
      "the rail computes a PER-PERIOD Sharpe (~0.05) from raw returns, not an annualised SR")

# ---- end-to-end through calma._assemble_ledger (real wiring: OC.run_checks + apply_validity + families) ----
import calma as C  # noqa: E402

_diff = {"metrics": [{"metric_id": "sharpe", "headline": True, "claimed": 1.0, "recomputed": 1.0,
                      "verdict": V.CONFIRMED, "verdict_inputs": _confirmed_claim()["verdict_inputs"],
                      "reason": "matches", "recompute_error": None}], "baseline": None}
_rr = {"exit_code": 0, "run_dir": os.path.join(dB, ".calma", "r"), "base": dB,
       "isolation_tier": "tier0", "determinism_mode": "controlled-to-bit"}
_led = C._assemble_ledger(cB, _diff, _rr, claim_text="the best Sharpe of 1000 backtested configs")
truth(_led["repo_verdict"] == V.INVALIDATED, "e2e: _assemble_ledger wires overfitting -> repo INVALIDATED (got %s)"
      % _led["repo_verdict"])
truth(_led["scope"]["families"].get("overfitting") == "flagged", "e2e: scope.families.overfitting = flagged")
truth(not any("roadmap" in s and ("overfit" in s.lower() or "deflated" in s.lower() or "PBO" in s
              or "leakage" in s.lower()) for s in _led["scope"]["not_verified"]),
      "e2e: leakage/overfitting are no longer called 'roadmap' in _not_verified once they run")

# e2e NOT-APPLICABLE: an ordinary single backtest assembles to CONFIRMED, overfitting stays silent
_ledA = C._assemble_ledger(_con(dA), _diff, dict(_rr, base=dA), claim_text="sharpe 1.0")
truth(_ledA["repo_verdict"] == V.CONFIRMED and _ledA["scope"]["families"].get("overfitting") in (None, "not-applicable"),
      "e2e: ordinary single backtest -> CONFIRMED, overfitting NOT-APPLICABLE (silent)")

print("overfitting_checks: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
