"""WS4 backtest catches: omitted costs (gross-sold-as-net), cherry-picked window, survivorship
universe. Each must FIRE on the planted failure with a clear explanation AND stay SILENT when the
deck is honest (no false alarms). Pure stdlib, offline. Run: python3 test_backtest_checks.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import backtest_checks as BC  # noqa: E402
import ledger as LED  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def _repo(rows, header="date,daily_return"):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "runs"))
    with open(os.path.join(d, "runs", "returns.csv"), "w") as fh:
        fh.write(header + "\n")
        for r in rows:
            fh.write(",".join(str(x) for x in r) + "\n")
    return d


def _contract(base, **extra):
    c = {"run": {"entrypoint": "gen.py"}, "env": {"trust": "own-code"},
         "artifacts": [{"path": "runs/returns.csv",
                        "columns": {"daily_return": {"tag": "return", "na_policy": "error"}}}],
         "metrics": [{"metric_id": "total_return", "artifact": "runs/returns.csv",
                      "binding": {"return": "daily_return"}, "claimed_value": None,
                      "headline": True, "binding_status": "independently-bound"}]}
    c.update(extra)
    return c


# --- omitted costs: claim tracks GROSS, net-of-cost is materially lower -> FIRES ---
rows = [("2023-01-%02d" % (i + 1), 0.01, 1.0) for i in range(20)]  # +1%/day gross, full turnover
d = _repo(rows, header="date,gross_return,turnover")
gross = 1.01 ** 20 - 1.0
c = _contract(d, costs={"fee_bps": 50.0, "turnover_col": "turnover"})
c["metrics"][0]["binding"] = {"return": "gross_return"}
c["metrics"][0]["claimed_value"] = round(gross, 4)
f = BC.check_omitted_costs(c, d)
truth(f and f["dimension"] == "omitted-costs" and f["severity"] == "blocker",
      "omitted-costs: fires a blocker omitted-costs finding")
truth(f and "gross sold as net" in f["locator"] and "net" in f["locator"], "omitted-costs: explains gross vs net")
truth(f and "assumed" in f, "omitted-costs: states its assumption")

# honest net deck (no cost column, claim is the real number) -> SILENT
d2 = _repo([("2023-01-%02d" % (i + 1), 0.001) for i in range(20)])
c2 = _contract(d2)
c2["metrics"][0]["claimed_value"] = round(1.001 ** 20 - 1.0, 6)
truth(BC.check_omitted_costs(c2, d2) is None, "omitted-costs: SILENT when no costs are declared (no false alarm)")

# costs declared but claim already tracks NET -> SILENT (no gross-as-net)
d3 = _repo([("2023-01-%02d" % (i + 1), 0.01, 1.0) for i in range(20)], header="date,gross_return,turnover")
net = 1.0
for _ in range(20):
    net *= (1.0 + 0.01 - 50.0 / 1e4)
c3 = _contract(d3, costs={"fee_bps": 50.0, "turnover_col": "turnover"})
c3["metrics"][0]["binding"] = {"return": "gross_return"}
c3["metrics"][0]["claimed_value"] = round(net - 1.0, 4)   # claims the NET number
truth(BC.check_omitted_costs(c3, d3) is None, "omitted-costs: SILENT when the claim already tracks net")

# --- cherry-picked window: claims more periods than the data covers -> FIRES ---
dw = _repo([("2024-01-%02d" % (i + 1), 0.001) for i in range(20)])
cw = _contract(dw, claimed_periods=252)
fw = BC.check_window(cw, dw)
truth(fw and fw["dimension"] == "window" and "window mismatch" in fw["locator"],
      "window: fires a window finding when claimed periods exceed the data")
truth(fw and "252" in fw["locator"] and "20" in fw["locator"], "window: names claimed vs actual coverage")
# matching window -> SILENT
truth(BC.check_window(_contract(dw, claimed_periods=20), dw) is None,
      "window: SILENT when claimed periods match the data")
# claimed date window outside coverage -> FIRES
fw2 = BC.check_window(_contract(dw, claimed_window=["2015-01-01", "2024-12-31"]), dw)
truth(fw2 and fw2["dimension"] == "window", "window: fires when the claimed date window exceeds coverage")

# --- survivorship: declared survivors-only universe -> FIRES (caveat) ---
ds = _repo([("2023-01-%02d" % (i + 1), 0.001) for i in range(20)])
fs = BC.check_survivorship(_contract(ds, universe="survivors-only"), ds)
truth(fs and fs["dimension"] == "survivorship" and "survivorship" in fs["locator"].lower(),
      "survivorship: fires a survivorship finding on a declared survivors-only universe")
truth(fs and "point-in-time" in fs["unblock"], "survivorship: unblock says rebuild point-in-time")
truth(BC.check_survivorship(_contract(ds), ds) is None, "survivorship: SILENT when no biased universe is declared")

# --- V0: the INVALIDATED promotion (apply_validity), scope-guarded on the claim TEXT ---
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
    findings = BC.run_checks(contract, base, "c1", claim_text)
    BC.apply_validity(claims, findings, contract, claim_text, base=base)
    return claims[0], findings


def _ledger_valid(claims, findings):
    led = {"schema": "calma/ledger@1", "claims": claims, "findings": findings,
           "scope": {"isolation_tier": "tier0", "determinism_mode": "controlled-to-bit",
                     "families": {}, "not_verified": []}, "repo_verdict": None}
    led["repo_verdict"] = LED.compute_repo_verdict(led)
    return LED.validate_obj(led)


truth(_confirmed_claim()["verdict"] == V.CONFIRMED, "test scaffold: the promotion claim starts CONFIRMED")

# survivors-only universe + a survivorship-free claim -> INVALIDATED on "survivorship"
hc, hf = _promote(_contract(ds, universe="survivors-only"), ds, "point-in-time survivorship-free total return")
truth(hc["verdict"] == V.INVALIDATED and hc.get("driving_dimension") == "survivorship",
      "survivorship: survivors-only + a point-in-time claim -> INVALIDATED on 'survivorship'")
truth(_ledger_valid([hc], hf)[0] in (0, 1),
      "survivorship INVALIDATED ledger validates (linked blocker + oos assertion + byte-re-derive)")
nc, _ = _promote(_contract(ds, universe="survivors-only"), ds, "total return 0.02")
truth(nc["verdict"] == V.CAVEATS,
      "survivorship scope-guard: a bare number (no point-in-time claim) -> CAVEATS, never INVALIDATED")

# gross series sold as net + declared frictions -> INVALIDATED on "omitted-costs", net number in reason
gc, gf = _promote(c, d, "net-of-fees total return")   # c/d: gross series + costs block, claim tracks gross
truth(gc["verdict"] == V.INVALIDATED and gc.get("driving_dimension") == "omitted-costs",
      "omitted-costs: gross-as-net + a net claim -> INVALIDATED on 'omitted-costs'")
truth(any(f["dimension"] == "omitted-costs" and "net" in f["locator"] for f in gf),
      "omitted-costs: the net number is named in the finding reason")
truth(_ledger_valid([gc], gf)[0] in (0, 1), "omitted-costs INVALIDATED ledger validates")
ngc, _ = _promote(c, d, "gross total return")
truth(ngc["verdict"] == V.CAVEATS,
      "omitted-costs scope-guard: a gross claim (no net assertion) -> CAVEATS, never INVALIDATED")

# claimed-period overreach + a representative/full-period claim -> INVALIDATED on "window"
wc, wf = _promote(_contract(dw, claimed_periods=252), dw, "total return over the full 252-day period")
truth(wc["verdict"] == V.INVALIDATED and wc.get("driving_dimension") == "window",
      "window: claimed-period overreach + a full-period claim -> INVALIDATED on 'window'")
truth(_ledger_valid([wc], wf)[0] in (0, 1), "window INVALIDATED ledger validates")
nwc, _ = _promote(_contract(dw, claimed_periods=252), dw, "total return 0.05")
truth(nwc["verdict"] == V.CAVEATS,
      "window scope-guard: a bare number (no representative claim) -> CAVEATS, never INVALIDATED")

# a clean backtest (no costs/window/universe declared) -> no finding, no promotion EVEN under an
# asserting claim (the family ABSTAINS without its block - never manufactures a catch from claim text).
cc, ccf = _promote(c2, d2, "point-in-time survivorship-free net-of-fees total return over the full period")
truth(cc["verdict"] == V.CONFIRMED and not ccf,
      "clean backtest: no surface declared -> no finding, stays CONFIRMED even under an asserting claim")

# --- the findings are ledger-valid (they must not break validation) ---
findings = BC.run_checks(c, d, "c1") + BC.run_checks(cw, dw, "c1") + BC.run_checks(_contract(ds, universe="survivors-only"), ds, "c1")
# a genuinely CONFIRMED claim (verdict re-derives from these inputs) so the repo-verdict downgrade is
# attributable to the WS4 finding, not to the claim itself.
_vi = {"gap": 0.0, "effective_budget": 0.01, "margin": 1.0, "claim_outside_ci": False,
       "sign_agrees": True, "band_coverage_ok": True, "claim_confirmed_target": True,
       "binding_status": "independently-bound", "isolation_tier": "seatbelt-verified",
       "container_present": True, "untrusted": False, "exit_codes": [0], "killed": False,
       "determinism_mode": "controlled-to-bit", "sufficient_k": True, "path_dependent": False,
       "m2_calibrated": True, "recompute_degenerate": False, "fraud_multiple_met": False,
       "convention_capped": False, "outputs_unstable": False, "no_claim_reproduced": False}
truth(V.verdict(_vi) == V.CONFIRMED, "test scaffold: the claim inputs re-derive to CONFIRMED")
led = {"schema": "calma/ledger@1",
       "claims": [{"id": "c1", "headline": True, "metric": "total_return", "claimed_value": 1.0,
                   "recomputed_value": 1.0, "verdict": V.verdict(_vi), "input_binding_status": "independently-bound",
                   "headline_confidence": 0.9, "verdict_inputs": _vi,
                   "verdict_status": "stable", "waivable": False, "reason": "x"}],
       "findings": findings,
       "scope": {"isolation_tier": "seatbelt-verified", "determinism_mode": "controlled-to-bit",
                 "families": {}, "not_verified": []},
       "repo_verdict": None}
led["repo_verdict"] = LED.compute_repo_verdict(led)
truth(led["repo_verdict"] == V.CAVEATS, "compute_repo_verdict: a blocking soundness finding -> CONFIRMED-WITH-CAVEATS")
code, summary = LED.validate_obj(led)
truth(code in (0, 1), "the WS4 findings keep the ledger structurally + semantically valid (code %s)" % code)

print("backtest_checks: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
