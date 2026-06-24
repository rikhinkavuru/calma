"""Tests for infer_validity.py - M-8b.2: the inference detectors that PROMOTE an undeclared validity signal
to FLAG_FOR_DECLARATION. Pure stdlib. Run: python3 test_infer_validity.py

Covers each detector's fire-case + its governor (no false flag when the signal is weak / not asserted /
declared), the conservative apply_validity (only a reproduced headline, never validity_invalidated), and that
the resulting FLAG claim is a VALID ledger (ledger.semantic_validate passes — the wiring the ledger requires).
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import infer_validity as INF  # noqa: E402
import ledger as L  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def expect(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        f.write(",".join(header) + "\n")
        for r in rows:
            f.write(",".join(str(x) for x in r) + "\n")


def clean_headline(metric="accuracy", artifact="data.csv", binding=None, claimed=0.94):
    """A reproduced (CONFIRMED) headline claim + a CONFIRMED-baseline verdict_inputs, ready to be promoted."""
    vi = {"gap": 0.001, "effective_budget": 0.01, "binding_status": "independently-bound",
          "determinism_mode": "controlled-to-bit", "container_present": True, "band_coverage_ok": True,
          "sufficient_k": True, "exit_codes": [0], "claim_outside_ci": False, "claim_confirmed_target": True}
    c = {"id": "c1", "headline": True, "verdict": V.verdict(vi), "input_binding_status": "independently-bound",
         "verdict_inputs": vi, "metric": metric, "artifact": artifact, "claimed_value": claimed,
         "recomputed_value": claimed, "binding": binding or {"value": "v"}, "waivable": False}
    return c


def build_ledger(claims, findings):
    led = {"schema": "calma/ledger@1", "claims": claims, "findings": findings, "scope": {},
           "repo_verdict": None}
    led["repo_verdict"] = L.compute_repo_verdict(led)
    return led


tmp = tempfile.mkdtemp()

# ================= Detector 1: inferred train/test split + real overlap + OOS claim =================
# train.csv + test.csv where two of three test rows duplicate training rows (a leakage signature).
write_csv(os.path.join(tmp, "train.csv"), ["x", "y"], [(1, 0), (2, 1), (3, 0), (4, 1), (5, 0)])
write_csv(os.path.join(tmp, "test.csv"), ["x", "y"], [(1, 0), (2, 1), (9, 1)])   # rows 1&2 overlap train
arts = [{"path": "train.csv"}, {"path": "test.csv"}]
contract1 = {"artifacts": arts, "metrics": [{"headline": True, "artifact": "test.csv",
             "binding": {"value": "y"}, "claimed_value": 0.94}]}
oos_claim = "held-out test-set accuracy is 0.94"

fnd = INF.run_checks(contract1, tmp, "c1", claim_text=oos_claim)
expect(len(fnd) == 1 and fnd[0]["dimension"] == "leakage" and fnd[0]["validity_class"] == "inferred-flag",
       "split detector fires on undeclared split + overlap + OOS claim")
expect(fnd[0]["severity"] == "major" and "split:" in fnd[0]["unblock"],
       "split flag is BLOCKING and names the split: block to declare")

# apply_validity promotes a reproduced headline to FLAG_FOR_DECLARATION (and never INVALIDATED)
claims = [clean_headline(binding={"value": "y"}, artifact="test.csv")]
findings = list(fnd)
INF.apply_validity(claims, findings, contract1, oos_claim, base=tmp)
expect(claims[0]["verdict"] == V.FLAG_FOR_DECLARATION, "split flag promotes the headline to FLAG_FOR_DECLARATION")
expect(claims[0]["verdict_inputs"].get("flag_for_declaration") is True
       and not claims[0]["verdict_inputs"].get("validity_invalidated"),
       "apply_validity sets flag_for_declaration, NEVER validity_invalidated")
expect(claims[0]["driving_dimension"] == "leakage", "driving_dimension = leakage")
# the resulting FLAG claim is a VALID ledger (the linked-blocker + scope-guard wiring the ledger requires)
led = build_ledger(claims, findings)
expect(led["repo_verdict"] == V.FLAG_FOR_DECLARATION, "repo rolls up to FLAG_FOR_DECLARATION")
expect(not L.semantic_validate(led) and not L.structural_validate(led), "the FLAG ledger validates")
expect(L.validate_obj(led)[0] == 1, "FLAG ledger gates to exit 1 (not clean)")

# --- governors / suppression: no false flag ---
# (a) no overlap -> no flag
write_csv(os.path.join(tmp, "test_clean.csv"), ["x", "y"], [(91, 0), (92, 1), (93, 1)])
c_clean = {"artifacts": [{"path": "train.csv"}, {"path": "test_clean.csv"}], "metrics": contract1["metrics"]}
# rename so _infer_split sees train.csv + test.csv pattern: use a *_train/*_test pair instead
write_csv(os.path.join(tmp, "m_train.csv"), ["x", "y"], [(1, 0), (2, 1), (3, 0)])
write_csv(os.path.join(tmp, "m_test.csv"), ["x", "y"], [(50, 0), (60, 1), (70, 1)])   # zero overlap
c_noov = {"artifacts": [{"path": "m_train.csv"}, {"path": "m_test.csv"}], "metrics": contract1["metrics"]}
expect(INF.run_checks(c_noov, tmp, "c1", claim_text=oos_claim) == [], "no row overlap -> no split flag")
# (b) not an OOS claim -> no flag (an in-sample claim with overlap is expected, not invalidating)
expect(INF.run_checks(contract1, tmp, "c1", claim_text="in-sample fit accuracy 0.94") == [],
       "non-OOS claim -> no split flag")
# (c) a DECLARED split -> suppressed (the authoritative leakage family owns it)
c_decl = dict(contract1, split={"train": "train.csv", "test": "test.csv"})
expect(INF.run_checks(c_decl, tmp, "c1", claim_text=oos_claim) == [], "declared split -> suppressed")
# (d) an authoritative leakage finding already present -> suppressed (no double jeopardy)
prior = [{"dimension": "leakage", "validity_class": "authoritative", "severity": "blocker"}]
expect(INF.run_checks(contract1, tmp, "c1", claim_text=oos_claim, findings=prior) == [],
       "authoritative leakage already fired -> suppressed")
# (e) apply_validity does NOT touch an already-REFUTED headline
ref = [{"id": "c1", "headline": True, "verdict": V.REFUTED, "verdict_inputs": {"flag_for_declaration": False}}]
INF.apply_validity(ref, list(fnd), contract1, oos_claim, base=tmp)
expect(ref[0]["verdict"] == V.REFUTED, "apply_validity leaves a REFUTED headline untouched (conservative)")

# ================= Detector 2: a STRONG regime break + a forward/robust claim =================
# first half: tiny-variance returns near 0; second half: large-variance returns -> strong KS + var shift.
first = [0.0005 * (1 if i % 2 else -1) for i in range(40)]
second = [0.06 * (1 if i % 2 else -1) + 0.01 for i in range(40)]
write_csv(os.path.join(tmp, "rets.csv"), ["ret"], [(x,) for x in first + second])
contract2 = {"artifacts": [{"path": "rets.csv"}],
             "metrics": [{"headline": True, "artifact": "rets.csv", "binding": {"return": "ret"},
                          "claimed_value": 1.5}]}
fwd_claim = "a robust Sharpe of 1.5 that holds out of sample"
f2 = INF.run_checks(contract2, tmp, "c1", claim_text=fwd_claim)
expect(len(f2) >= 1 and any(x["dimension"] == "regime" for x in f2), "regime detector fires on strong KS + forward claim")
# governor: no forward/robust assertion -> no regime flag (a bare in-window number isn't a forward claim)
expect(not any(x["dimension"] == "regime" for x in INF.run_checks(contract2, tmp, "c1", claim_text="Sharpe 1.5")),
       "no forward/robust claim -> no regime flag")
# governor: a stationary series -> no regime flag
stat = [0.01 * (1 if i % 2 else -1) for i in range(60)]
write_csv(os.path.join(tmp, "stat.csv"), ["ret"], [(x,) for x in stat])
c_stat = {"artifacts": [{"path": "stat.csv"}], "metrics": [{"headline": True, "artifact": "stat.csv",
          "binding": {"return": "ret"}, "claimed_value": 1.5}]}
expect(not any(x["dimension"] == "regime" for x in INF.run_checks(c_stat, tmp, "c1", claim_text=fwd_claim)),
       "stationary series -> no regime flag")

# ================= Detector 3: an undeclared trials matrix + an implausibly-high Sharpe =================
# headline returns with Sharpe > 1.0 per period (mean 0.02, std ~0.01) + a sibling trials matrix (>=8 cols).
hi = [0.02 + 0.008 * (1 if i % 2 else -1) for i in range(40)]
write_csv(os.path.join(tmp, "hi.csv"), ["ret"], [(x,) for x in hi])
write_csv(os.path.join(tmp, "trials.csv"), ["t%d" % j for j in range(10)],
          [[round(0.01 * ((i + j) % 7 - 3), 4) for j in range(10)] for i in range(30)])
contract3 = {"artifacts": [{"path": "hi.csv"}, {"path": "trials.csv"}],
             "metrics": [{"headline": True, "artifact": "hi.csv", "binding": {"return": "ret"},
                          "claimed_value": 2.0}]}
f3 = INF.run_checks(contract3, tmp, "c1", claim_text="Sharpe 2.0")
expect(any(x["dimension"] == "data-snooping" and x["inferred_structure"] == "trials" for x in f3),
       "trials detector fires on an undeclared matrix sibling + high Sharpe")
# governor: no matrix sibling -> no trials flag
c_nomat = {"artifacts": [{"path": "hi.csv"}], "metrics": contract3["metrics"]}
expect(not any(x["dimension"] == "data-snooping" for x in INF.run_checks(c_nomat, tmp, "c1", claim_text="Sharpe 2.0")),
       "no trials matrix -> no trials flag")
# governor: high Sharpe required -> a low-Sharpe headline with a matrix sibling does NOT flag
write_csv(os.path.join(tmp, "lo.csv"), ["ret"], [(0.001 * (1 if i % 2 else -1),) for i in range(40)])
c_lo = {"artifacts": [{"path": "lo.csv"}, {"path": "trials.csv"}],
        "metrics": [{"headline": True, "artifact": "lo.csv", "binding": {"return": "ret"}, "claimed_value": 0.1}]}
expect(not any(x["dimension"] == "data-snooping" for x in INF.run_checks(c_lo, tmp, "c1", claim_text="Sharpe 0.1")),
       "low Sharpe + matrix -> no trials flag (needs the implausible-Sharpe co-signal)")

# ---- family_status ----
expect(INF.family_status(contract1, fnd) == "flagged", "family_status flagged when a flag fired")
expect(INF.family_status(contract1, []) == "not-applicable", "family_status not-applicable with no flag")

print("infer_validity: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
