"""V2 study-wide multiple-testing / HLZ haircut. Reference vectors (hand-derived from the published
Bonferroni/Holm/BHY formulas) lock the haircut math; the detector fires when the adjusted t falls below
3.0, stays silent when the edge survives, and is honest ("unverifiable") when N is undisclosed; the
promotion is scope-guarded on a significance/genuine-factor claim. Pure stdlib. Run: python3 ...
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import data_snooping_checks as DS  # noqa: E402
import ledger as LED  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def close(a, b, tol=0.01):
    return a == a and abs(a - b) <= tol


# ---- REFERENCE VECTORS: (t, N) -> expected (two-sided p, Bonferroni t_adj, Bonf haircut, BHY t_adj),
# derived from t=SR*sqrt(T); p=2(1-Phi(t)); Bonf p_adj=min(N*p,1); t_adj=Phi^-1(1-p_adj/2); BHY uses
# p_adj=p*N*c(N), c(N)=sum 1/i. Independently checkable against the HLZ papers. -----------------------
VECTORS = [
    # t,     N,   p,        bonf_t,  bonf_haircut, bhy_t,  c_n
    (3.464, 50, 0.000532, 2.217, 0.360, 1.562, 4.4992),
    (3.464, 1,  0.000532, 3.464, 0.000, 3.464, 1.0000),
    (5.000, 50, 5.73e-7,  4.178, 0.164, 3.829, 4.4992),
    (2.500, 20, 0.012419, 1.149, 0.540, 0.135, 3.5977),
]
for (t, n, p, bt, bhc, yt, cn) in VECTORS:
    h = DS.haircut(t, n)
    truth(close(h["p"], p, max(1e-7, 0.02 * p)), "vector p t=%.3f N=%d" % (t, n))
    truth(close(h["c_n"], cn, 1e-3), "vector c(N) N=%d" % n)
    truth(close(h["methods"]["bonferroni"]["t_adj"], bt), "vector bonf_t t=%.3f N=%d (got %.3f)"
          % (t, n, h["methods"]["bonferroni"]["t_adj"]))
    truth(close(h["methods"]["bonferroni"]["haircut"], bhc), "vector bonf_haircut t=%.3f N=%d" % (t, n))
    truth(close(h["methods"]["bhy"]["t_adj"], yt), "vector bhy_t t=%.3f N=%d (got %.3f)"
          % (t, n, h["methods"]["bhy"]["t_adj"]))
# the haircut is nonlinear (a lower SR is haircut MORE) and monotone in N
truth(DS.haircut(2.5, 50)["methods"]["bonferroni"]["haircut"]
      > DS.haircut(5.0, 50)["methods"]["bonferroni"]["haircut"],
      "haircut nonlinearity: a weaker edge is haircut more than a stronger one")
truth(DS.haircut(3.464, 100)["methods"]["bonferroni"]["haircut"]
      > DS.haircut(3.464, 10)["methods"]["bonferroni"]["haircut"],
      "haircut monotone in N: more trials -> bigger haircut")


def _study_contract(**study):
    return {"study": study, "metrics": [{"metric_id": "sharpe", "artifact": "r.csv", "headline": True,
                                         "binding": {"return": "ret"}, "claimed_value": study.get("sharpe")}]}


# ---- detector: fires below t>3.0, silent above, honest when N undisclosed -----
f = DS.run_checks(_study_contract(trials=50, sharpe=1.0, periods=12), ".", "c1")
truth(f and f[0]["dimension"] == "data-snooping" and "multiple-testing" in f[0]["locator"]
      and "t>3.0" in f[0]["locator"], "fires: Sharpe-1 over T=12, N=50 -> adjusted t<3.0")
truth(f and "Harvey-Liu-Zhu" in f[0]["locator"], "cites Harvey-Liu-Zhu in the reason")
# a genuinely strong edge survives the haircut -> SILENT
truth(DS.run_checks(_study_contract(trials=50, t_stat=5.0), ".", "c1") == [],
      "silent: a t=5.0 edge survives the N=50 haircut (no false alarm)")
# a genuinely single test (N<2) -> SILENT
truth(DS.run_checks(_study_contract(trials=1, sharpe=1.0, periods=12), ".", "c1") == [],
      "silent: a single test (N=1) has no multiplicity to correct")
# a study signalled but N undisclosed -> 'unverifiable' (N never guessed)
fu = DS.run_checks({"study": {"selected_from": "best"},
                    "metrics": [{"metric_id": "sharpe", "headline": True}]}, ".", "c1")
truth(fu and fu[0].get("validity_class") == "unverifiable" and "N is not countable" in fu[0]["locator"],
      "unverifiable: a study with no trials/matrix -> 'N not countable', never a guessed N")
# t missing -> unverifiable on the statistic
ft = DS.run_checks(_study_contract(trials=50), ".", "c1")
truth(ft and ft[0].get("validity_class") == "unverifiable" and "no test statistic" in ft[0]["locator"],
      "unverifiable: N declared but no t/sharpe -> needs a test statistic")
# no study block -> ABSTAIN
truth(DS.run_checks({"metrics": []}, ".", "c1") == [], "ABSTAINS without a study block")


# ---- promotion (scope-guarded on the significance assertion) ------------------
def _confirmed_claim():
    vi = {"gap": 0.0, "effective_budget": 1e-9, "binding_status": "independently-bound",
          "determinism_mode": "controlled-to-bit", "container_present": True, "band_coverage_ok": True,
          "sufficient_k": True, "exit_codes": [0], "claim_confirmed_target": True}
    return {"id": "c1", "headline": True, "metric": "sharpe", "claimed_value": 1.0,
            "recomputed_value": 1.0, "verdict": V.verdict(vi),
            "input_binding_status": "independently-bound", "headline_confidence": 0.9,
            "verdict_inputs": vi, "verdict_status": "stable", "waivable": False, "reason": "ok"}


def _promote(contract, claim_text):
    claims = [_confirmed_claim()]
    findings = DS.run_checks(contract, ".", "c1", claim_text)
    DS.apply_validity(claims, findings, contract, claim_text, base=".")
    return claims[0], findings


def _ledger_valid(claims, findings):
    led = {"schema": "calma/ledger@1", "claims": claims, "findings": findings,
           "scope": {"isolation_tier": "tier0", "determinism_mode": "controlled-to-bit",
                     "families": {}, "not_verified": []}, "repo_verdict": None}
    led["repo_verdict"] = LED.compute_repo_verdict(led)
    return LED.validate_obj(led)


sc = _study_contract(trials=50, sharpe=1.0, periods=12)
hc, hf = _promote(sc, "a statistically significant Sharpe of 1.0")
truth(hc["verdict"] == V.INVALIDATED and hc.get("driving_dimension") == "data-snooping",
      "promote: haircut t<3.0 + a significance claim -> INVALIDATED('data-snooping')")
truth(_ledger_valid([hc], hf)[0] in (0, 1), "data-snooping INVALIDATED ledger validates")
nc, _ = _promote(sc, "Sharpe 1.0")
truth(nc["verdict"] == V.CAVEATS, "scope-guard: a bare Sharpe number -> CAVEATS, not INVALIDATED")
# unverifiable N + a significance claim -> CAN'T-CONFIRM (declare N), never a guessed haircut
uc, _ = _promote({"study": {"selected_from": "best"}, "metrics": [{"metric_id": "sharpe", "headline": True}]},
                 "a genuine, statistically significant factor")
truth(uc["verdict"] == V.INCONCLUSIVE,
      "unverifiable + a significance claim -> CAN'T-CONFIRM (declare N), not a guessed correction")

# ---- family status -----------------------------------------------------------
truth(DS.family_status({}, []) == "not-applicable", "family_status: not-applicable without a study block")
truth(DS.family_status(sc, hf) == "flagged", "family_status: flagged when a finding fired")

print("data_snooping_checks: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
