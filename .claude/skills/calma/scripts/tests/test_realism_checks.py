"""Tests for realism_checks.py: the friction-deflated recompute (exact magnitudes), the capacity /
market-impact catch, the net/gross scope-guard, and the verdict promotion (REFUTED / INVALIDATED /
CAN'T-CONFIRM / CAVEAT) verified through real ledgers that ledger.validate_obj + gate accept. Pure
stdlib. Run: python3 test_realism_checks.py
"""
import copy
import csv
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import realism_checks as RL  # noqa: E402
import ledger as L  # noqa: E402
import numeric as N  # noqa: E402
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


def _kind(findings, k):
    return next((f for f in findings if f.get("realism_kind") == k), None)


def _contract(d, frictions, metric_id, claimed, binding, conv=None):
    m = {"metric_id": metric_id, "artifact": "returns.csv", "headline": True, "claimed_value": claimed,
         "binding": binding}
    if conv is not None:
        m["convention"] = conv
    return {"frictions": frictions, "artifacts": [], "metrics": [m]}


# ====================================================================================
# the friction-deflated recompute - exact magnitudes (total_return is exact arithmetic)
# ====================================================================================
# 50 periods of +2% gross; fee 100bps + slippage 100bps = 200bps = 0.02 per (flat) turnover -> net 0.0.
dDef = tempfile.mkdtemp()
_rets = [[0.02] for _ in range(50)]
_write(os.path.join(dDef, "returns.csv"), ["ret"], _rets)
_gross_tr = N.total_return([0.02] * 50)
_net_tr = N.total_return([0.0] * 50)
truth(abs(_gross_tr - (1.02 ** 50 - 1.0)) < 1e-12, "gross total_return is (1.02^50 - 1)")
truth(abs(_net_tr - 0.0) < 1e-12, "net-of-friction total_return is exactly 0.0")
cDef = _contract(dDef, {"fee_bps": 100, "slippage_bps": 100}, "total_return", _gross_tr, {"return": "ret"})

d = RL.deflate(cDef, dDef)
truth(d is not None and abs(d["gross"] - _gross_tr) < 1e-12 and abs(d["net"] - 0.0) < 1e-12,
      "deflate(): gross reproduces, net is 0.0 after 200bps/turnover (got %r)" % (d and d["net"]))
fDef = RL.run_checks(cDef, dDef, "c1", claim_text="net total return after costs")
_dfn = _kind(fDef, "deflation")
truth(_dfn is not None and _dfn["severity"] == "blocker" and _dfn["validity_class"] == "authoritative",
      "material friction deflation -> authoritative blocker")
truth(_dfn and _dfn["reverify"]["kind"] == "artifact-recheck",
      "realism finding re-verifies by artifact-recheck (execution-realism is an EXEC dim)")

# immaterial frictions (1bps) -> no finding (the edge survives)
cTiny = _contract(dDef, {"fee_bps": 1}, "total_return", _gross_tr, {"return": "ret"})
truth(RL.run_checks(cTiny, dDef, "c1", claim_text="net total return") == [],
      "immaterial frictions fire no finding (edge survives realistic costs)")

# NOT-APPLICABLE: no frictions block
truth(RL.run_checks({"metrics": []}, dDef, "c1") == [] and RL.family_status({"metrics": []}, []) == "not-applicable",
      "no frictions block -> realism NOT-APPLICABLE, silent")
# NOT-APPLICABLE: frictions declared on a NON-trading headline (e.g. accuracy) -> silent (contract misuse)
_cAcc = {"frictions": {"fee_bps": 100, "adv": 1000, "size": 5000}, "artifacts": [],
         "metrics": [{"metric_id": "accuracy", "artifact": "returns.csv", "headline": True,
                      "claimed_value": 0.9, "binding": {"prediction": "p", "label": "y"}}]}
truth(RL.run_checks(_cAcc, dDef, "c1", claim_text="live accuracy") == []
      and RL.family_status(_cAcc, []) == "not-applicable",
      "frictions on a non-return headline -> realism NOT-APPLICABLE (never fires capacity on a non-trading claim)")
truth(RL.family_status(cDef, fDef) == "flagged", "frictions + a finding -> family 'flagged'")
truth(RL.family_status(cTiny, []) == "checked", "frictions, no finding -> family 'checked'")


# ====================================================================================
# net/gross scope-guard
# ====================================================================================
truth(RL.net_status(cDef, "net Sharpe 2.1 after costs") == "net", "claim 'net ... after costs' -> net")
truth(RL.net_status(cDef, "live tradeable return") == "net", "claim 'live tradeable' -> net")
truth(RL.net_status(cDef, "gross return before costs") == "gross", "claim 'gross ... before costs' -> gross")
truth(RL.net_status(cDef, "frictionless paper backtest") == "gross", "claim 'frictionless paper' -> gross")
truth(RL.net_status(cDef, "total return 1.7") == "indeterminate", "claim with no net/gross -> indeterminate")


# ====================================================================================
# apply_validity - the verdict lattice, verified through real ledgers
# ====================================================================================
def _confirmed_claim(claimed, recomputed=None):
    vi = {"gap": 0.0, "effective_budget": 1e-9, "binding_status": "independently-bound",
          "determinism_mode": "controlled-to-bit", "container_present": True, "band_coverage_ok": True,
          "sufficient_k": True, "exit_codes": [0], "claim_outside_ci": False, "claim_confirmed_target": True}
    c = {"id": "c1", "headline": True, "verdict": V.verdict(vi), "input_binding_status": "independently-bound",
         "verdict_inputs": vi, "waivable": False, "metric": "total_return",
         "claimed_value": claimed, "recomputed_value": recomputed if recomputed is not None else claimed}
    assert c["verdict"] == V.CONFIRMED
    return c


def _ledger(claims, findings):
    led = {"schema": "calma/ledger@1", "claims": claims, "findings": findings,
           "scope": {"isolation_tier": "tier0", "determinism_mode": "controlled-to-bit"}, "repo_verdict": None}
    led["repo_verdict"] = L.compute_repo_verdict(led)
    return led


# (A) NET claim + material deflation outside budget -> REFUTED via the friction-deflated gap path
clA, fdA = [_confirmed_claim(_gross_tr)], copy.deepcopy(fDef)
RL.apply_validity(clA, fdA, cDef, "net total return after costs", base=dDef)
truth(clA[0]["verdict"] == V.REFUTED, "net claim + friction-deflated outside budget -> REFUTED (got %s)" % clA[0]["verdict"])
truth(abs(clA[0]["recomputed_value"] - 0.0) < 1e-12, "the report's recompute IS the friction-deflated number (0.0)")
truth(clA[0].get("driving_dimension") == "execution-realism", "REFUTED driving_dimension = execution-realism")
truth(any("friction-deflated" in (f.get("locator") or "") for f in fdA), "the finding shows claimed -> friction-deflated")
ledA = _ledger(clA, fdA)
truth(L.validate_obj(ledA)[0] == 1 and ledA["repo_verdict"] == V.REFUTED, "realism-REFUTED ledger validates (not clean)")

# (A2) a SHARPE headline whose core vi carries convention_capped=True (252/365/52 annualization) must
# still REFUTE on a net claim - the friction-deflated recompute is convention-identical, so the cap
# cannot explain the gap (regression guard for the realism convention_capped clearing).
dSh = tempfile.mkdtemp()
_sh_rets = [0.03 if i % 2 == 0 else 0.01 for i in range(50)]   # mean 0.02, nonzero vol -> finite Sharpe
_write(os.path.join(dSh, "returns.csv"), ["ret", "turnover"], [[r, 1.0] for r in _sh_rets])
_gross_sh = N.sharpe(_sh_rets, 252)[0]
cSh = _contract(dSh, {"fee_bps": 100, "slippage_bps": 100, "turnover_col": "turnover"},
                "sharpe", _gross_sh, {"return": "ret"}, conv="252")
clA2 = [_confirmed_claim(_gross_sh)]
clA2[0]["metric"] = "sharpe"
clA2[0]["verdict_inputs"]["convention_capped"] = True   # the core Sharpe path sets this for annualization
fdA2 = RL.run_checks(cSh, dSh, "c1", claim_text="net Sharpe after costs")
RL.apply_validity(clA2, fdA2, cSh, "net Sharpe after costs", base=dSh)
truth(clA2[0]["verdict"] == V.REFUTED,
      "sharpe + convention_capped + net claim still REFUTES after friction deflation (got %s)" % clA2[0]["verdict"])
truth(clA2[0]["verdict_inputs"].get("convention_capped") is False,
      "the realism REFUTED clears convention_capped (the deflation is convention-identical)")

# (B) GROSS claim + same deflation -> CONFIRMED-WITH-CAVEATS (the gross number is literally true)
clB, fdB = [_confirmed_claim(_gross_tr)], copy.deepcopy(fDef)
RL.apply_validity(clB, fdB, cDef, "gross total return before costs", base=dDef)
truth(clB[0]["verdict"] == V.CAVEATS, "gross claim + deflation -> CONFIRMED-WITH-CAVEATS (got %s)" % clB[0]["verdict"])
truth(all(f["severity"] == "minor" for f in fdB if f["dimension"] == "execution-realism"),
      "gross: authoritative deflation demoted to minor (gate stays exit 0)")
truth(L.gate(_ledger(clB, fdB))[0] == 0, "gross-claim CAVEAT ledger is CLEAN (exit 0)")

# (C) INDETERMINATE claim + deflation -> CAN'T-CONFIRM, exit 1, 'declare net vs gross' fix
clC, fdC = [_confirmed_claim(_gross_tr)], copy.deepcopy(fDef)
RL.apply_validity(clC, fdC, cDef, "total return 1.7", base=dDef)
truth(clC[0]["verdict"] == V.INCONCLUSIVE, "indeterminate scope -> CAN'T-CONFIRM (got %s)" % clC[0]["verdict"])
truth(any("net-of-cost or gross" in (f.get("unblock") or "") for f in fdC), "the fix tells the author to declare net vs gross")
truth(L.gate(_ledger(clC, fdC))[0] == 1, "realism CAN'T-CONFIRM gates to exit 1")

# (D) immaterial frictions -> verdict untouched (CONFIRMED)
clD = [_confirmed_claim(_gross_tr)]
RL.apply_validity(clD, RL.run_checks(cTiny, dDef, "c1", claim_text="net total return"), cTiny, "net total return", base=dDef)
truth(clD[0]["verdict"] == V.CONFIRMED, "immaterial frictions -> headline verdict unchanged (survives realistic costs)")

# (D2) SUBSTANTIATED net claim: the friction-deflated recompute MATCHES the claim within budget (an honest
# author who already reported the net number) -> the edge survives frictions -> CONFIRMED, never INVALIDATED.
# (adversarial regression: apply_validity must not fall through to INVALIDATED when net == claim.)
clD2 = [_confirmed_claim(_net_tr)]   # claim the *net* value (0.0), not the gross
fdD2 = RL.run_checks(cDef, dDef, "c1", claim_text="net total return after costs")
RL.apply_validity(clD2, fdD2, cDef, "net total return after costs", base=dDef)
truth(clD2[0]["verdict"] == V.CONFIRMED,
      "net claim substantiated by the deflated recompute (net==claim) -> CONFIRMED, not INVALIDATED (got %s)"
      % clD2[0]["verdict"])

# (D3) DEGENERATE deflation (total_return overflow at absurd declared costs) must NOT be a false CONFIRM:
# a non-finite net fires the finding and routes the net claim to INVALIDATED, never CONFIRMED.
dOvf = tempfile.mkdtemp()
_write(os.path.join(dOvf, "returns.csv"), ["ret", "turnover"], [[0.01, 1.0] for _ in range(252)])
_gross_ovf = N.total_return([0.01] * 252)
cOvf = _contract(dOvf, {"fee_bps": 100000, "slippage_bps": 100000, "turnover_col": "turnover"},
                 "total_return", _gross_ovf, {"return": "ret"})
fdOvf = RL.run_checks(cOvf, dOvf, "c1", claim_text="net total return after costs")
truth(_kind(fdOvf, "deflation") is not None, "overflow deflation fires a finding (not swallowed as 'survives')")
clOvf = [_confirmed_claim(_gross_ovf)]
RL.apply_validity(clOvf, fdOvf, cOvf, "net total return after costs", base=dOvf)
truth(clOvf[0]["verdict"] != V.CONFIRMED,
      "a non-finite friction-deflated net is never a false CONFIRM (got %s)" % clOvf[0]["verdict"])
truth(clOvf[0]["verdict"] == V.INVALIDATED,
      "non-finite net on a net claim -> INVALIDATED (the live result is not realizable) (got %s)" % clOvf[0]["verdict"])


# ====================================================================================
# capacity / market-impact: uninvestable at size -> INVALIDATED on a live claim
# ====================================================================================
dCap = tempfile.mkdtemp()
_write(os.path.join(dCap, "returns.csv"), ["ret"], [[0.01] for _ in range(60)])
_gross_cap = N.total_return([0.01] * 60)
cCap = _contract(dCap, {"adv": 1_000_000, "size": 2_000_000}, "total_return", _gross_cap, {"return": "ret"})
fCap = RL.run_checks(cCap, dCap, "c1", claim_text="live net return at $2M/day")
_cap = _kind(fCap, "capacity")
truth(_cap is not None and _cap["validity_class"] == "authoritative" and abs(_cap["magnitude"] - 2.0) < 1e-12,
      "size 2x ADV -> authoritative capacity blocker, participation 2.0 (got %r)" % (_cap and _cap.get("magnitude")))
clCap = [_confirmed_claim(_gross_cap)]
clCap[0]["metric"] = "total_return"
RL.apply_validity(clCap, copy.deepcopy(fCap), cCap, "live net return at $2M/day", base=dCap)
truth(clCap[0]["verdict"] == V.INVALIDATED, "uninvestable-at-size + live claim -> INVALIDATED (got %s)" % clCap[0]["verdict"])
truth(clCap[0].get("driving_dimension") == "execution-realism", "capacity INVALIDATED driving_dimension = execution-realism")
fdCap2 = copy.deepcopy(fCap)
clCap2 = [_confirmed_claim(_gross_cap)]
RL.apply_validity(clCap2, fdCap2, cCap, "live net return at $2M/day", base=dCap)
ledCap = _ledger(clCap2, fdCap2)
truth(L.validate_obj(ledCap)[0] == 1 and ledCap["repo_verdict"] == V.INVALIDATED, "capacity-INVALIDATED ledger validates")

# soft capacity caution (10-100% of ADV) -> CAVEAT, never INVALIDATED
cCap2 = _contract(dCap, {"adv": 1_000_000, "size": 200_000}, "total_return", _gross_cap, {"return": "ret"})
fCap2 = RL.run_checks(cCap2, dCap, "c1", claim_text="live net return")
truth(_kind(fCap2, "capacity-soft") is not None and _kind(fCap2, "capacity") is None,
      "20%% of ADV -> a SOFT capacity caution (not authoritative)")
clS = [_confirmed_claim(_gross_cap)]
RL.apply_validity(clS, copy.deepcopy(fCap2), cCap2, "live net return", base=dCap)
truth(clS[0]["verdict"] == V.CAVEATS, "soft capacity caution -> CAVEAT, never INVALIDATED (got %s)" % clS[0]["verdict"])


# ====================================================================================
# market-impact kernel (square-root model) - exact elementary value
# ====================================================================================
truth(abs(RL.sqrt_impact(0.25, 0.02, 1.0) - 0.01) < 1e-15, "sqrt_impact(0.25, 0.02) = 1*0.02*0.5 = 0.01 exactly")
truth(abs(RL.sqrt_impact(0.04, 0.05, 2.0) - 0.02) < 1e-15, "sqrt_impact(0.04, 0.05, coef=2) = 2*0.05*0.2 = 0.02 exactly")
truth(RL.sqrt_impact(-1, 0.02) != RL.sqrt_impact(-1, 0.02) or RL.sqrt_impact(-1, 0.02) is not None,
      "negative participation -> NaN (guarded)")


# ====================================================================================
# 6a: deflation extends to sortino (ratio -> clean REFUTED) and calmar (path-dependent -> INVALIDATED)
# ====================================================================================
def _deflate_verdict(metric, rets, fr, claim, conv="252", path_dependent=False):
    dd = tempfile.mkdtemp()
    _write(os.path.join(dd, "r.csv"), ["ret", "turnover"], [[x, 1.0] for x in rets])
    import recipes as RCP
    gross = RCP.get(metric)({"ret": rets}, {"return": "ret"}, conv)["value"]
    con = {"frictions": fr, "artifacts": [],
           "metrics": [{"metric_id": metric, "artifact": "r.csv", "headline": True, "claimed_value": gross,
                        "binding": {"return": "ret"}, "convention": conv}]}
    cl = _confirmed_claim(gross)
    cl["metric"] = metric
    if path_dependent:
        cl["verdict_inputs"]["path_dependent"] = True
        cl["verdict"] = V.verdict(cl["verdict_inputs"])
    fnd = RL.run_checks(con, dd, "c1", claim_text=claim)
    RL.apply_validity([cl], fnd, con, claim, base=dd)
    return cl["verdict"], gross, fnd

# returns with REAL downside (so sortino's downside-dev and calmar's max-drawdown are finite, not inf)
_dn = [0.04, -0.02, 0.05, -0.01, 0.03, -0.03, 0.06, -0.02, 0.04, -0.01] * 6
_fr_def = {"fee_bps": 150, "slippage_bps": 150, "turnover_col": "turnover"}
_vS, _gS, _fS = _deflate_verdict("sortino", _dn, _fr_def, "net sortino after costs")
truth(_vS == V.REFUTED, "sortino (a ratio) net claim deflates to a clean REFUTED (got %s)" % _vS)
truth(any(f.get("realism_kind") == "deflation" for f in _fS), "sortino deflation finding fired")
_vC, _gC, _fC = _deflate_verdict("calmar", _dn, _fr_def, "net calmar after costs", path_dependent=True)
truth(_vC == V.INVALIDATED,
      "calmar (path-dependent) net collapse -> INVALIDATED (gap-REFUTED is blocked) (got %s)" % _vC)
truth("sortino" in RL._DEFLATABLE and "calmar" in RL._DEFLATABLE, "sortino + calmar are deflatable")


# ====================================================================================
# 6c: leverage sanity - a declared leverage > 1 is a soft caveat; financing drag folds into the recompute
# ====================================================================================
dLev = tempfile.mkdtemp()
_write(os.path.join(dLev, "returns.csv"), ["ret"], [[0.001] for _ in range(50)])
cLev = _contract(dLev, {"leverage": 3.0, "borrow_bps": 50}, "total_return", N.total_return([0.001] * 50),
                 {"return": "ret"})
fLev = RL.run_checks(cLev, dLev, "c1", claim_text="net total return")
_lev = _kind(fLev, "leverage")
truth(_lev is not None and _lev["validity_class"] == "soft" and abs(_lev["magnitude"] - 3.0) < 1e-12,
      "leverage 3x -> soft caveat, magnitude 3.0 (got %r)" % (_lev and _lev.get("magnitude")))
# financing drag (leverage-1)*borrow = 2 * 50bps = 100bps/period is folded into the deflated recompute
_dLev = RL.deflate(cLev, dLev)
truth(_dLev is not None and "financing" in _dLev["components"],
      "leverage financing drag is a named component of the deflated recompute")
truth(abs(_dLev["net"] - N.total_return([0.001 - 0.01] * 50)) < 1e-9,
      "financing folds (3-1)*50bps = 100bps/period into the net recompute")
# leverage <= 1 -> no caveat
truth(RL.check_leverage(_contract(dLev, {"leverage": 1.0}, "total_return", 0.0, {"return": "ret"})) is None,
      "leverage 1.0 (unlevered) -> no caveat")


# ====================================================================================
# end-to-end through calma._assemble_ledger (the real wiring)
# ====================================================================================
import calma as C  # noqa: E402

_diff = {"metrics": [{"metric_id": "total_return", "headline": True, "claimed": _gross_tr, "recomputed": _gross_tr,
                      "verdict": V.CONFIRMED, "verdict_inputs": _confirmed_claim(_gross_tr)["verdict_inputs"],
                      "reason": "matches within budget", "recompute_error": None}],
         "baseline": None}
_run_res = {"exit_code": 0, "run_dir": os.path.join(dDef, ".calma", "r"), "base": dDef,
            "isolation_tier": "tier0", "determinism_mode": "controlled-to-bit"}
_led = C._assemble_ledger(cDef, _diff, _run_res, claim_text="net total return after costs")
truth(_led["repo_verdict"] == V.REFUTED, "e2e: _assemble_ledger wires realism -> repo REFUTED (got %s)" % _led["repo_verdict"])
truth(L.validate_obj(_led)[0] == 1, "e2e: the assembled realism-REFUTED ledger validates")
truth(_led["scope"]["families"].get("realism") == "flagged", "e2e: scope.families.realism = flagged")
truth(not any("frictions" in s and "roadmap" in s for s in _led["scope"]["not_verified"]),
      "e2e: _not_verified no longer calls realism a roadmap gap once it ran")

# e2e clean: immaterial frictions -> CONFIRMED, realism 'checked'
_led_clean = C._assemble_ledger(cTiny, _diff, _run_res, claim_text="net total return")
truth(_led_clean["repo_verdict"] == V.CONFIRMED and _led_clean["scope"]["families"].get("realism") == "checked",
      "e2e: immaterial frictions -> CONFIRMED with realism 'checked' (got %s)" % _led_clean["repo_verdict"])

# ====================================================================================
# security + token-hygiene regressions (adversarial audit 2026-06-16)
# ====================================================================================
# (sec) path traversal: a metric artifact outside the contract base must be refused (no file read)
truth(RL.deflate({"frictions": {"fee_bps": 100}, "metrics": [{"metric_id": "total_return",
      "artifact": "/etc/hosts", "headline": True, "claimed_value": 1.0, "binding": {"return": "x"}}]},
      tempfile.mkdtemp()) is None, "deflate refuses an out-of-base (absolute) artifact path")
_esc_raised = False
try:
    RL._safe_join(tempfile.mkdtemp(), "../../etc/hosts")
except ValueError:
    _esc_raised = True
truth(_esc_raised, "realism _safe_join raises on a traversal attempt")

# (token) the REFUTED deflation locator is NOT doubled (the redundant 'claimed net X -> friction-deflated
# Y' appendix is gone); the net recompute is carried in a structured field + head.recomputed_value instead
_clTok = [_confirmed_claim(_gross_tr)]
_fdTok = RL.run_checks(cDef, dDef, "c1", claim_text="net total return after costs")
RL.apply_validity(_clTok, _fdTok, cDef, "net total return after costs", base=dDef)
_dfn_tok = _kind(_fdTok, "deflation")
truth(_dfn_tok is not None and "claimed net" not in _dfn_tok["locator"],
      "the deflation locator no longer restates the claimed->net pair (no doubled appendix)")
truth(_dfn_tok is not None and "net_recompute" in _dfn_tok,
      "the net recompute is carried in a structured field (machine consumers), not the prose")
truth("magnitude" not in _dfn_tok, "the deflation finding omits a null magnitude (token hygiene)")

# (correctness) an UNPHYSICAL net (a declared cost driving a per-period net return below -100%) makes
# total_return compound through a negative base -> a nonsensical large-positive. It must be treated as a
# degenerate deflation (net NaN) and route to INVALIDATED on a net claim, never a garbage-positive REFUTED.
dUn = tempfile.mkdtemp()
_write(os.path.join(dUn, "returns.csv"), ["ret", "turnover"], [[0.01, 1.0] for _ in range(40)])
_gross_un = N.total_return([0.01] * 40)
cUn = _contract(dUn, {"fee_bps": 100000, "slippage_bps": 100000, "turnover_col": "turnover"},
                "total_return", _gross_un, {"return": "ret"})  # 20.0/period cost -> net_r ~ -19.99 < -1
_dUn = RL.deflate(cUn, dUn)
truth(_dUn is not None and not (_dUn["net"] == _dUn["net"]),
      "an unphysical (<-100%/period) total_return net is degenerate (NaN), not a garbage-positive number")
clUn = [_confirmed_claim(_gross_un)]
RL.apply_validity(clUn, RL.run_checks(cUn, dUn, "c1", claim_text="net total return after costs"),
                  cUn, "net total return after costs", base=dUn)
truth(clUn[0]["verdict"] == V.INVALIDATED,
      "unphysical net on a net claim -> INVALIDATED (not a garbage-positive REFUTED) (got %s)" % clUn[0]["verdict"])

print("realism_checks: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
