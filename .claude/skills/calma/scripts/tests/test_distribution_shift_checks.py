"""V5 covariate / target distributional shift. The detector fires on a KS/PSI shift between train and
test, distinguishes covariate vs target shift, stays silent on matched distributions, and is
scope-guarded on an in-distribution/generalizes claim. Pure stdlib. Run: python3 ...
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import distribution_shift_checks as DSh  # noqa: E402
import ledger as LED  # noqa: E402
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


def _write(d, name, rows, header="x,y"):
    with open(os.path.join(d, name), "w", newline="") as fh:
        fh.write(header + "\n")
        for r in rows:
            fh.write(",".join(str(v) for v in r) + "\n")


def _contract(d):
    return {"split": {"train": "train.csv", "test": "test.csv"}, "keys": {"target": "y"},
            "metrics": [{"metric_id": "accuracy", "artifact": "test.csv", "headline": True,
                         "binding": {"prediction": "x", "label": "y"}, "claimed_value": 0.9,
                         "binding_status": "independently-bound"}]}


# --- covariate shift: x shifts (0..1 -> 3..4), y matched ---
dc = tempfile.mkdtemp()
g = _lcg(3)
_write(dc, "train.csv", [(round(next(g), 4), i % 2) for i in range(40)])
g2 = _lcg(8)
_write(dc, "test.csv", [(round(3 + next(g2), 4), i % 2) for i in range(40)])
f = DSh.check_shift(_contract(dc), dc, "c1")
truth(f and f["dimension"] == "distribution-shift" and f["shift_kind"] == "covariate-shift"
      and "x" in f["locator"], "covariate shift: a shifted feature x fires a covariate-shift finding")
truth(f and "KS" in f["locator"] and "PSI" in f["locator"], "covariate shift: reports KS + PSI in the reason")

# --- target shift: y shifts (mostly 0 -> mostly 1), x matched ---
dt = tempfile.mkdtemp()
g3 = _lcg(5)
_write(dt, "train.csv", [(round(next(g3), 4), 0 if next(g3) < 0.85 else 1) for _ in range(40)])
g4 = _lcg(5)  # same x generator seed start -> matched x
_write(dt, "test.csv", [(round(next(g4), 4), 1 if next(g4) < 0.85 else 0) for _ in range(40)])
ft = DSh.check_shift(_contract(dt), dt, "c1")
truth(ft and ft["shift_kind"] == "target-shift", "target shift: a shifted label y fires a target-shift finding")

# --- matched distributions -> SILENT ---
dm = tempfile.mkdtemp()
g5 = _lcg(11)
_write(dm, "train.csv", [(round(next(g5), 4), i % 2) for i in range(40)])
g6 = _lcg(11)  # identical generation -> matched
_write(dm, "test.csv", [(round(next(g6), 4), i % 2) for i in range(40)])
truth(DSh.check_shift(_contract(dm), dm, "c1") is None,
      "matched distributions -> SILENT (no false alarm)")

# --- ABSTAIN without a split ---
truth(DSh.run_checks({"metrics": []}, dc, "c1") == [], "ABSTAINS without a train/test split")


# --- promotion (scope-guarded on a generalization assertion) ---
def _confirmed_claim():
    vi = {"gap": 0.0, "effective_budget": 1e-9, "binding_status": "independently-bound",
          "determinism_mode": "controlled-to-bit", "container_present": True, "band_coverage_ok": True,
          "sufficient_k": True, "exit_codes": [0], "claim_confirmed_target": True}
    return {"id": "c1", "headline": True, "metric": "accuracy", "claimed_value": 0.9,
            "recomputed_value": 0.9, "verdict": V.verdict(vi),
            "input_binding_status": "independently-bound", "headline_confidence": 0.9,
            "verdict_inputs": vi, "verdict_status": "stable", "waivable": False, "reason": "ok"}


def _promote(contract, base, claim_text):
    claims = [_confirmed_claim()]
    findings = DSh.run_checks(contract, base, "c1", claim_text)
    DSh.apply_validity(claims, findings, contract, claim_text, base=base)
    return claims[0], findings


def _ledger_valid(claims, findings):
    led = {"schema": "calma/ledger@1", "claims": claims, "findings": findings,
           "scope": {"isolation_tier": "tier0", "determinism_mode": "controlled-to-bit",
                     "families": {}, "not_verified": []}, "repo_verdict": None}
    led["repo_verdict"] = LED.compute_repo_verdict(led)
    return LED.validate_obj(led)


hc, hf = _promote(_contract(dc), dc, "the model generalizes in-distribution to the test set")
truth(hc["verdict"] == V.INVALIDATED and hc.get("driving_dimension") == "distribution-shift",
      "promote: a covariate shift + a generalization claim -> INVALIDATED('distribution-shift')")
truth(_ledger_valid([hc], hf)[0] in (0, 1), "distribution-shift INVALIDATED ledger validates")
# without a generalization claim the family does not ACTIVATE (a shift on a split used for some other
# purpose is not ours to flag) - the headline stays CONFIRMED.
nc, ncf = _promote(_contract(dc), dc, "accuracy 0.9")
truth(nc["verdict"] == V.CONFIRMED and ncf == [],
      "activation-gate: no generalization claim -> the shift check does not run -> stays CONFIRMED")

truth(DSh.family_status({"metrics": []}, []) == "not-applicable", "family_status: not-applicable without a split")
truth(DSh.family_status(_contract(dc), hf) == "flagged", "family_status: flagged when a finding fired")

print("distribution_shift_checks: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
