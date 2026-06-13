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
truth(f and f["dimension"] == "execution-realism" and f["severity"] == "blocker",
      "omitted-costs: fires a blocker execution-realism finding")
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
truth(fw and fw["dimension"] == "selection" and "window mismatch" in fw["locator"],
      "window: fires a selection finding when claimed periods exceed the data")
truth(fw and "252" in fw["locator"] and "20" in fw["locator"], "window: names claimed vs actual coverage")
# matching window -> SILENT
truth(BC.check_window(_contract(dw, claimed_periods=20), dw) is None,
      "window: SILENT when claimed periods match the data")
# claimed date window outside coverage -> FIRES
fw2 = BC.check_window(_contract(dw, claimed_window=["2015-01-01", "2024-12-31"]), dw)
truth(fw2 and fw2["dimension"] == "selection", "window: fires when the claimed date window exceeds coverage")

# --- survivorship: declared survivors-only universe -> FIRES (caveat) ---
ds = _repo([("2023-01-%02d" % (i + 1), 0.001) for i in range(20)])
fs = BC.check_survivorship(_contract(ds, universe="survivors-only"), ds)
truth(fs and fs["dimension"] == "data-integrity" and "survivorship" in fs["locator"].lower(),
      "survivorship: fires a data-integrity finding on a declared survivors-only universe")
truth(fs and "point-in-time" in fs["unblock"], "survivorship: unblock says rebuild point-in-time")
truth(BC.check_survivorship(_contract(ds), ds) is None, "survivorship: SILENT when no biased universe is declared")

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
