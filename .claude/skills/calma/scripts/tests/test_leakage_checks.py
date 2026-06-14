"""Tests for leakage_checks.py: the five detectors (exact magnitudes), the OOS scope-guard, and the
verdict promotion (INVALIDATED / CAN'T-CONFIRM / CAVEAT) verified through real ledgers that
ledger.validate_obj + gate accept. Pure stdlib. Run: python3 test_leakage_checks.py
"""
import copy
import csv
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import leakage_checks as LC  # noqa: E402
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


def _kind(findings, k):
    return next((f for f in findings if f.get("leakage_kind") == k), None)


# ====================================================================================
# detectors - exact magnitudes
# ====================================================================================

# (1) ROW overlap: 70 fresh + 30 exact-duplicate test rows -> magnitude EXACTLY 0.30
dR = tempfile.mkdtemp()
_train = [[i * 0.1, i * 0.2, i % 2] for i in range(100)]
_testR = [[(1000 + i) * 0.1, (1000 + i) * 0.2, i % 2] for i in range(70)] + [_train[i] for i in range(30)]
_write(os.path.join(dR, "train.csv"), ["x1", "x2", "y_true"], _train)
_write(os.path.join(dR, "test.csv"), ["x1", "x2", "y_true"], _testR)
cR = {"split": {"train": "train.csv", "test": "test.csv"}, "keys": {"target": "y_true"},
      "features": ["x1", "x2"], "artifacts": [], "metrics": []}
fR = LC.run_checks(cR, dR, "c1")
_row = _kind(fR, "row-overlap")
truth(_row is not None and abs(_row["magnitude"] - 0.30) < 1e-12,
      "row overlap magnitude EXACTLY 0.30 (got %r)" % (_row and _row["magnitude"]))
truth(_row and _row["severity"] == "blocker" and _row["validity_class"] == "authoritative",
      "row overlap is an authoritative blocker")
truth(_row and _row["reverify"]["kind"] == "artifact-recheck",
      "leakage finding re-verifies by artifact-recheck (not static-reread; leakage is an EXEC dim)")
truth(_kind(fR, "id-overlap") is None and _kind(fR, "dup-inflation") is None,
      "no id key + no within-test dups -> only row-overlap fires")

# (2) ID overlap: 30 test rows reuse training ids (different feature values) -> magnitude 0.30
dI = tempfile.mkdtemp()
_trI = [[i, i * 0.1, i % 2] for i in range(100)]
_teI = [[1000 + i, (1000 + i) * 0.1, i % 2] for i in range(70)] + [[i, 999.0 + i, i % 2] for i in range(30)]
_write(os.path.join(dI, "train.csv"), ["id", "x1", "y_true"], _trI)
_write(os.path.join(dI, "test.csv"), ["id", "x1", "y_true"], _teI)
cI = {"split": {"train": "train.csv", "test": "test.csv"}, "keys": {"id": "id", "target": "y_true"},
      "features": ["x1"], "artifacts": [], "metrics": []}
fI = LC.run_checks(cI, dI, "c1")
_id = _kind(fI, "id-overlap")
truth(_id is not None and abs(_id["magnitude"] - 0.30) < 1e-12,
      "id overlap magnitude EXACTLY 0.30 (got %r)" % (_id and _id["magnitude"]))
truth(_kind(fI, "row-overlap") is None, "reused-id rows with different features -> no full-row overlap")

# (3) TEMPORAL look-ahead: 50 of 100 test rows at/before the last training time -> 0.50
dT = tempfile.mkdtemp()
_write(os.path.join(dT, "train.csv"), ["time", "y_true"], [[i, i % 2] for i in range(100)])
_write(os.path.join(dT, "test.csv"), ["time", "y_true"],
       [[100 + i, i % 2] for i in range(50)] + [[i, i % 2] for i in range(50)])
cT = {"split": {"train": "train.csv", "test": "test.csv"}, "keys": {"time": "time"}, "artifacts": [], "metrics": []}
fT = LC.run_checks(cT, dT, "c1")
_tmp = _kind(fT, "temporal")
truth(_tmp is not None and abs(_tmp["magnitude"] - 0.50) < 1e-12,
      "temporal magnitude EXACTLY 0.50 (got %r)" % (_tmp and _tmp["magnitude"]))

# (4) DUPLICATE inflation: a row repeated 21x among 100 -> 20 dups -> 0.20
dD = tempfile.mkdtemp()
_write(os.path.join(dD, "train.csv"), ["x1", "y_true"], [[i, 0] for i in range(50)])
_write(os.path.join(dD, "test.csv"), ["x1", "y_true"], [[i, 1] for i in range(79)] + [[999, 1]] * 21)
cD = {"split": {"train": "train.csv", "test": "test.csv"}, "keys": {"target": "y_true"}, "artifacts": [], "metrics": []}
fD = LC.run_checks(cD, dD, "c1")
_dup = _kind(fD, "dup-inflation")
truth(_dup is not None and abs(_dup["magnitude"] - 0.20) < 1e-12,
      "dup-inflation magnitude EXACTLY 0.20 (got %r)" % (_dup and _dup["magnitude"]))
truth(_dup and _dup["severity"] == "minor" and _dup["validity_class"] == "soft", "dup-inflation is a soft minor")

# (5a) TARGET leakage - exact: a feature identical to the target -> authoritative blocker.
# (DISJOINT train/test rows, so ONLY the target check fires - no incidental row overlap.)
dX = tempfile.mkdtemp()
_write(os.path.join(dX, "train.csv"), ["x1", "leak", "y_true"], [[i, i % 2, i % 2] for i in range(40)])
_write(os.path.join(dX, "test.csv"), ["x1", "leak", "y_true"], [[i, i % 2, i % 2] for i in range(40, 80)])
cX = {"split": {"train": "train.csv", "test": "test.csv"}, "keys": {"target": "y_true"},
      "features": ["x1", "leak"], "artifacts": [], "metrics": []}
fX = LC.run_checks(cX, dX, "c1")
_tgt = _kind(fX, "target")
truth(_tgt is not None and _tgt["severity"] == "blocker" and _tgt["validity_class"] == "authoritative",
      "feature == target -> authoritative blocker")
truth(_kind(fX, "row-overlap") is None, "exact-target fixture has a clean split (only target fires)")

# (5b) TARGET leakage - heuristic: |pearson_r| >= 0.999 but not identical -> soft minor (LABELED HEURISTIC).
# DISJOINT rows; `near` ~= target with tiny per-row noise (nonzero everywhere -> not exact, |r|~1).
dXH = tempfile.mkdtemp()


def _nearrows(lo, hi):
    return [[float(i) + 0.001 * (1 if i % 2 else -1), float(i)] for i in range(lo, hi)]


_write(os.path.join(dXH, "train.csv"), ["near", "y_true"], _nearrows(0, 60))
_write(os.path.join(dXH, "test.csv"), ["near", "y_true"], _nearrows(60, 120))
cXH = {"split": {"train": "train.csv", "test": "test.csv"}, "keys": {"target": "y_true"},
       "features": ["near"], "artifacts": [], "metrics": []}
fXH = LC.run_checks(cXH, dXH, "c1")
_tc = _kind(fXH, "target-corr")
truth(_tc is not None and _tc["severity"] == "minor" and _tc["validity_class"] == "soft",
      "near-perfect feature/target correlation -> heuristic soft minor (got %r)" % (fXH))
truth(_kind(fXH, "target") is None and _kind(fXH, "row-overlap") is None,
      "heuristic fixture: clean split, not an exact match")

# (6) CLEAN split: disjoint rows/ids/times, no dup, no target leak -> NO findings
dC = tempfile.mkdtemp()
_write(os.path.join(dC, "train.csv"), ["id", "x1", "y_true"], [[i, i * 0.1, i % 2] for i in range(100)])
_write(os.path.join(dC, "test.csv"), ["id", "x1", "y_true"], [[1000 + i, (1000 + i) * 0.7, i % 2] for i in range(50)])
cC = {"split": {"train": "train.csv", "test": "test.csv"}, "keys": {"id": "id", "target": "y_true"},
      "features": ["x1"], "artifacts": [], "metrics": []}
fC = LC.run_checks(cC, dC, "c1")
truth(fC == [], "a clean split fires no leakage findings")
truth(LC.family_status(cC, fC) == "checked", "clean + applicable -> family 'checked'")
truth(LC.family_status({"metrics": []}, []) == "not-applicable", "no split/target -> family 'not-applicable'")
truth(LC.family_status(cR, fR) == "flagged", "contaminated -> family 'flagged'")

# ====================================================================================
# OOS scope-guard
# ====================================================================================
truth(LC.oos_status(cR, "auc 0.94 on held-out test") == "oos", "claim text 'held-out' -> oos")
truth(LC.oos_status(cR, "out-of-sample AUC 0.94") == "oos", "claim text 'out-of-sample' -> oos")
truth(LC.oos_status(cR, "training accuracy 0.99") == "in-sample", "claim text 'training accuracy' -> in-sample")
truth(LC.oos_status(cR, "in-sample fit 0.99") == "in-sample", "claim text 'in-sample' -> in-sample")
_cR_test = dict(cR, metrics=[{"headline": True, "artifact": "test.csv", "claimed_value": 0.9}])
truth(LC.oos_status(_cR_test, "") == "oos", "structural: headline metric on the test file -> oos")
_cR_train = dict(cR, metrics=[{"headline": True, "artifact": "train.csv", "claimed_value": 0.9}])
truth(LC.oos_status(_cR_train, "") == "indeterminate", "split but metric not on test, no OOS text -> indeterminate")
truth(LC.oos_status({"split": {"file": "d.csv", "column": "fold"}}, "auc 0.9") == "indeterminate",
      "single-file split + bare claim -> indeterminate")


# ====================================================================================
# apply_validity: the verdict lattice, verified through real ledgers
# ====================================================================================
def _confirmed_claim():
    vi = {"gap": 0.0, "effective_budget": 1e-9, "binding_status": "independently-bound",
          "determinism_mode": "controlled-to-bit", "container_present": True, "band_coverage_ok": True,
          "sufficient_k": True, "exit_codes": [0], "claim_outside_ci": False, "claim_confirmed_target": True}
    c = {"id": "c1", "headline": True, "verdict": V.verdict(vi), "input_binding_status": "independently-bound",
         "verdict_inputs": vi, "waivable": False, "metric": "auc", "claimed_value": 0.94, "recomputed_value": 0.94}
    assert c["verdict"] == V.CONFIRMED
    return c


def _ledger(claims, findings):
    led = {"schema": "calma/ledger@1", "claims": claims, "findings": findings,
           "scope": {"isolation_tier": "tier0", "determinism_mode": "controlled-to-bit"}, "repo_verdict": None}
    led["repo_verdict"] = L.compute_repo_verdict(led)
    return led


# (A) authoritative row-overlap + OOS claim -> INVALIDATED, exit 1, valid ledger
clA, fdA = [_confirmed_claim()], copy.deepcopy(fR)
LC.apply_validity(clA, fdA, cR, "auc 0.94 on held-out test")
truth(clA[0]["verdict"] == V.INVALIDATED, "OOS + authoritative contamination -> INVALIDATED (got %s)" % clA[0]["verdict"])
truth(clA[0].get("driving_dimension") == "leakage", "INVALIDATED driving_dimension = leakage")
ledA = _ledger(clA, fdA)
truth(L.validate_obj(ledA)[0] == 1 and ledA["repo_verdict"] == V.INVALIDATED, "INVALIDATED ledger valid + not clean")
truth(L.gate(ledA)[0] == 1, "INVALIDATED gates to exit 1")

# (B) same contamination, IN-SAMPLE claim -> CAVEAT, exit 0 (authoritative finding demoted to minor)
clB, fdB = [_confirmed_claim()], copy.deepcopy(fR)
LC.apply_validity(clB, fdB, cR, "in-sample training accuracy 0.94")
truth(clB[0]["verdict"] == V.CAVEATS, "in-sample contamination -> CONFIRMED-WITH-CAVEATS (got %s)" % clB[0]["verdict"])
truth(all(f["severity"] == "minor" for f in fdB if f["dimension"] == "leakage"),
      "in-sample: authoritative findings demoted to minor (so the gate stays exit 0)")
ledB = _ledger(clB, fdB)
truth(L.validate_obj(ledB)[0] == 0 and L.gate(ledB)[0] == 0, "in-sample CAVEAT ledger is CLEAN (exit 0)")

# (C) authoritative contamination, INDETERMINATE scope -> CAN'T-CONFIRM, exit 1, 'declare OOS' fix
dInd = tempfile.mkdtemp()
_write(os.path.join(dInd, "data.csv"), ["fold", "x1", "y_true"],
       [["train", i, i % 2] for i in range(50)] + [["test", i, i % 2] for i in range(15)]
       + [["test", 1000 + i, i % 2] for i in range(35)])  # 15 of 50 test rows duplicate train rows
cInd = {"split": {"file": "data.csv", "column": "fold"}, "keys": {"target": "y_true"},
        "features": ["x1"], "artifacts": [], "metrics": []}
fInd = LC.run_checks(cInd, dInd, "c1")
truth(_kind(fInd, "row-overlap") is not None, "single-file split: row overlap across folds detected")
clC = [_confirmed_claim()]
LC.apply_validity(clC, fInd, cInd, "auc 0.94")  # bare claim + single-file split -> indeterminate
truth(clC[0]["verdict"] == V.INCONCLUSIVE, "indeterminate scope -> CAN'T-CONFIRM (got %s)" % clC[0]["verdict"])
truth(any("out-of-sample" in (f.get("unblock") or "") for f in fInd), "the fix tells the author to declare the scope")
ledC = _ledger(clC, fInd)
truth(L.gate(ledC)[0] == 1, "CAN'T-CONFIRM gates to exit 1")

# (D) heuristic (soft) target-corr -> CAVEAT, exit 0 (never INVALIDATED)
clD, fdD = [_confirmed_claim()], copy.deepcopy(fXH)
LC.apply_validity(clD, fdD, cXH, "auc 0.94 held-out")
truth(clD[0]["verdict"] == V.CAVEATS, "heuristic target-corr -> CAVEAT, never INVALIDATED (got %s)" % clD[0]["verdict"])
truth(L.gate(_ledger(clD, fdD))[0] == 0, "soft caveat is exit 0")

# (E) a reproduced number that is NOT the headline's concern: no leakage -> verdict untouched
clE = [_confirmed_claim()]
LC.apply_validity(clE, [], cC, "auc 0.94 held-out")
truth(clE[0]["verdict"] == V.CONFIRMED, "no leakage findings -> headline verdict unchanged")

# ====================================================================================
# end-to-end through calma._assemble_ledger (the real wiring: LC.run_checks + apply_validity +
# families + _not_verified), reusing the 30%-row-overlap fixture dir (dR).
# ====================================================================================
import calma as C  # noqa: E402

_diff = {"metrics": [{"metric_id": "auc", "headline": True, "claimed": 0.94, "recomputed": 0.94,
                      "verdict": V.CONFIRMED, "verdict_inputs": _confirmed_claim()["verdict_inputs"],
                      "reason": "matches within budget", "recompute_error": None}],
         "baseline": None}
_run_res = {"exit_code": 0, "run_dir": os.path.join(dR, ".calma", "r"), "base": dR,
            "isolation_tier": "tier0", "determinism_mode": "controlled-to-bit"}
_contract_e2e = dict(cR, metrics=[{"metric_id": "auc", "artifact": "test.csv", "headline": True,
                                   "claimed_value": 0.94, "binding_status": "independently-bound",
                                   "binding": {"score": "score", "label": "y_true"}}])
_led = C._assemble_ledger(_contract_e2e, _diff, _run_res, claim_text="auc 0.94 on the held-out test set")
truth(_led["repo_verdict"] == V.INVALIDATED, "e2e: _assemble_ledger wires leakage -> repo INVALIDATED (got %s)"
      % _led["repo_verdict"])
truth(L.validate_obj(_led)[0] == 1, "e2e: the assembled INVALIDATED ledger validates (valid, not clean)")
truth(_led["scope"]["families"].get("leakage") == "flagged", "e2e: scope.families.leakage = flagged")
truth(not any("leakage" in s and "roadmap" in s for s in _led["scope"]["not_verified"]),
      "e2e: _not_verified no longer calls leakage a roadmap gap once it ran")

# e2e clean: a clean split assembles to a normal CONFIRMED with leakage marked 'checked'
_run_clean = dict(_run_res, base=dC)
_led_clean = C._assemble_ledger(dict(cC, metrics=_contract_e2e["metrics"]), _diff, _run_clean,
                                claim_text="auc 0.94 held-out")
truth(_led_clean["repo_verdict"] == V.CONFIRMED and _led_clean["scope"]["families"].get("leakage") == "checked",
      "e2e: a clean split -> CONFIRMED with leakage 'checked' (got %s)" % _led_clean["repo_verdict"])

print("leakage_checks: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
