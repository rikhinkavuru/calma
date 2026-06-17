"""V1 point-in-time / look-ahead checks. Each must FIRE on the planted failure and stay SILENT on a
clean fixture (no false alarms), and the INVALIDATED promotion must be scope-guarded on the claim TEXT
and produce a structurally + semantically valid ledger. Pure stdlib, offline.
Run: python3 test_pit_checks.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import ledger as LED  # noqa: E402
import pit_checks as PIT  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def _write(d, name, header, rows):
    with open(os.path.join(d, name), "w", newline="") as fh:
        fh.write(",".join(header) + "\n")
        for r in rows:
            fh.write(",".join(str(x) for x in r) + "\n")
    return d


def _lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF


def _confirmed_claim():
    vi = {"gap": 0.0, "effective_budget": 1e-9, "binding_status": "independently-bound",
          "determinism_mode": "controlled-to-bit", "container_present": True, "band_coverage_ok": True,
          "sufficient_k": True, "exit_codes": [0], "claim_confirmed_target": True}
    return {"id": "c1", "headline": True, "metric": "total_return", "claimed_value": 1.0,
            "recomputed_value": 1.0, "verdict": V.verdict(vi),
            "input_binding_status": "independently-bound", "headline_confidence": 0.9,
            "verdict_inputs": vi, "verdict_status": "stable", "waivable": False, "reason": "ok"}


def _promote(contract, base, claim_text):
    claims = [_confirmed_claim()]
    findings = PIT.run_checks(contract, base, "c1", claim_text)
    PIT.apply_validity(claims, findings, contract, claim_text, base=base)
    return claims[0], findings


def _ledger_valid(claims, findings):
    led = {"schema": "calma/ledger@1", "claims": claims, "findings": findings,
           "scope": {"isolation_tier": "tier0", "determinism_mode": "controlled-to-bit",
                     "families": {}, "not_verified": []}, "repo_verdict": None}
    led["repo_verdict"] = LED.compute_repo_verdict(led)
    return LED.validate_obj(led)


truth(_confirmed_claim()["verdict"] == V.CONFIRMED, "scaffold: the promotion claim starts CONFIRMED")

# ---- (1) point-in-time survivorship -----------------------------------------
# a membership with ZERO delistings over a multi-year window -> implausibly low attrition
dsv = tempfile.mkdtemp()
_write(dsv, "universe.csv", ["ticker", "delisted"], [("T%03d" % i, 0) for i in range(50)])
surv_contract = {"universe": {"membership": "universe.csv", "ticker_col": "ticker",
                              "delisted_col": "delisted"},
                 "metrics": [{"metric_id": "total_return", "artifact": "r.csv", "headline": True,
                              "binding": {"return": "ret"}}]}
f = PIT.check_point_in_time(surv_contract, dsv, "c1")
truth(f and f["dimension"] == "survivorship" and "attrition" in f["locator"],
      "PIT survivorship: zero-attrition membership fires a survivorship finding")
# a realistic membership (15% delisted) -> SILENT
dsv2 = tempfile.mkdtemp()
_write(dsv2, "universe.csv", ["ticker", "delisted"],
       [("T%03d" % i, 1 if i % 7 == 0 else 0) for i in range(50)])
truth(PIT.check_point_in_time({"universe": {"membership": "universe.csv"}}, dsv2, "c1") is None,
      "PIT survivorship: a realistic-attrition universe is SILENT (no false alarm)")
# explicit point_in_time=false -> fires regardless of data
truth(PIT.check_point_in_time({"universe": {"point_in_time": False}}, dsv, "c1"),
      "PIT survivorship: an explicit point_in_time=false fires")
# no universe block -> ABSTAIN
truth(PIT.check_point_in_time({}, dsv, "c1") is None, "PIT survivorship: ABSTAINS without a universe block")

# promotion: survivorship violation + a survivorship-free claim -> INVALIDATED; bare number -> CAVEAT
hc, hf = _promote(surv_contract, dsv, "point-in-time survivorship-free total return 0.12")
truth(hc["verdict"] == V.INVALIDATED and hc.get("driving_dimension") == "survivorship",
      "PIT survivorship: violation + a point-in-time claim -> INVALIDATED")
truth(_ledger_valid([hc], hf)[0] in (0, 1), "PIT survivorship INVALIDATED ledger validates")
nc, _ = _promote(surv_contract, dsv, "total return 0.12")
truth(nc["verdict"] == V.CAVEATS, "PIT survivorship scope-guard: a bare number -> CAVEATS, not INVALIDATED")

# ---- (2) look-ahead: the +1-period-lag robustness probe ----------------------
# a same-bar signal S[t]=sign(R[t]) -> perf0 = gross, perf1 collapses -> look-ahead is load-bearing
dla = tempfile.mkdtemp()
g = _lcg(7)
R = [round(0.002 + (next(g) - 0.5) * 0.02, 6) for _ in range(40)]
_write(dla, "bt.csv", ["signal", "ret"], [(1.0 if r >= 0 else -1.0, r) for r in R])
la_contract = {"availability": {"signal": "signal", "return": "ret", "artifact": "bt.csv"},
               "metrics": [{"metric_id": "total_return", "artifact": "bt.csv", "headline": True,
                            "binding": {"return": "ret"}}]}
fla = PIT.check_lookahead(la_contract, dla, "c1")
truth(fla and fla["dimension"] == "look-ahead" and "lag" in fla["locator"],
      "look-ahead: the +1-lag probe fires on a same-bar (sign-of-today) signal")
# a clean buy-and-hold signal S[t]=1 -> perf0==perf1, no collapse -> SILENT
dla2 = tempfile.mkdtemp()
_write(dla2, "bt.csv", ["signal", "ret"], [(1.0, r) for r in R])
truth(PIT.check_lookahead({"availability": {"signal": "signal", "return": "ret", "artifact": "bt.csv"}},
                          dla2, "c1") is None,
      "look-ahead: a constant (buy-and-hold) signal does not collapse -> SILENT (no false alarm)")
# no availability block -> ABSTAIN
truth(PIT.check_lookahead({}, dla, "c1") is None, "look-ahead: ABSTAINS without an availability block")
# an explicit availability_date > effective_date -> fires
av_contract = {"availability": {"columns": [{"column": "eps", "effective_date": "2020-03-31",
                                             "available_date": "2020-05-15"}]}}
truth(PIT.check_lookahead(av_contract, dla, "c1"),
      "look-ahead: availability_date > effective_date (restated fundamental) fires")

# promotion: look-ahead load-bearing + a forward/OOS claim -> INVALIDATED; bare number -> CAVEAT
lc, lf = _promote(la_contract, dla, "out-of-sample tradeable total return 0.08")
truth(lc["verdict"] == V.INVALIDATED and lc.get("driving_dimension") == "look-ahead",
      "look-ahead: load-bearing + a forward/OOS claim -> INVALIDATED")
truth(_ledger_valid([lc], lf)[0] in (0, 1), "look-ahead INVALIDATED ledger validates")
nlc, _ = _promote(la_contract, dla, "in-sample total return 0.08")
truth(nlc["verdict"] == V.CAVEATS, "look-ahead scope-guard: a bare/in-sample number -> CAVEATS, not INVALIDATED")

# ---- family status -----------------------------------------------------------
truth(PIT.family_status({}, []) == "not-applicable", "family_status: not-applicable without a block")
truth(PIT.family_status(surv_contract, hf) == "flagged", "family_status: flagged when a finding fired")

print("pit_checks: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
