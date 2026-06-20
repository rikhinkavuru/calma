"""V6 thin-input plausibility smells. The detectors fire from the bound return series ALONE (no
declared block): an implausibly-high per-period Sharpe and a too-smooth (serially-correlated) curve.
They stay silent on an ordinary series and without enough history, and they are SOFT-ONLY - a smell
degrades a reproduced number to a CAVEAT, never to INVALIDATED/REFUTED. Pure stdlib, offline.
Run: python3 test_plausibility_checks.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import ledger as LED  # noqa: E402
import plausibility_checks as PLC  # noqa: E402
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


def _contract_noreturn():
    return {"metrics": [{"metric_id": "accuracy", "artifact": "preds.csv",
                         "binding": {"pred": "p", "label": "y"}, "claimed_value": 0.9, "headline": True}]}


def _ar1(n, phi, seed, scale=0.012):
    """An AR(1) return process r[t] = phi*r[t-1] + e: positive lag-1 autocorrelation ~ phi, mean ~0 so
    the Sharpe stays modest (isolates the smoothness smell from the high-Sharpe smell)."""
    g = _lcg(seed)
    out, prev = [], 0.0
    for _ in range(n):
        prev = phi * prev + (next(g) - 0.5) * scale
        out.append(round(prev, 8))
    return out


# high-Sharpe: a strong, low-variance positive drift (iid noise -> no autocorrelation)
g = _lcg(7)
hi_sharpe = [round(0.010 + (next(g) - 0.5) * 0.004, 8) for _ in range(30)]
# too-smooth: a serially-correlated curve, ~zero mean (only the smoothness smell should fire)
smooth = _ar1(40, 0.75, 11)
# ordinary: modest mean, ordinary variance, iid -> neither smell fires
g3 = _lcg(13)
ordinary = [round(0.002 + (next(g3) - 0.5) * 0.07, 8) for _ in range(40)]

R_hi, R_sm, R_ok = _repo(hi_sharpe), _repo(smooth), _repo(ordinary)


# --- detectors fire from the return series alone (no declared block) ---
fs = PLC.run_checks(_contract(), R_hi, "c1", "total return 0.1")
truth(any(f["plausibility_kind"] == "high-sharpe" for f in fs),
      "plausibility: an implausibly-high Sharpe fires from the series alone (no block declared)")
truth(all(f["dimension"] == "plausibility" and f["validity_class"] == "heuristic" for f in fs),
      "plausibility: high-sharpe finding is dimension=plausibility, heuristic")

fsm = PLC.run_checks(_contract(), R_sm, "c1", "total return")
truth(any(f["plausibility_kind"] == "smooth-curve" for f in fsm),
      "plausibility: a too-smooth (serially-correlated) curve fires the smoothness smell")
truth(not any(f["plausibility_kind"] == "high-sharpe" for f in fsm),
      "plausibility: the ~zero-mean smooth series does NOT trip the high-Sharpe smell (isolated)")

# --- silent on an ordinary series, and without enough history ---
truth(PLC.run_checks(_contract(), R_ok, "c1", "total return") == [],
      "plausibility: an ordinary series is SILENT (no false alarm)")
truth(PLC.run_checks(_contract(), _repo(hi_sharpe[:10]), "c1", "x") == [],
      "plausibility: ABSTAINS without enough history")

# --- scope: only return-bound metrics; accuracy/AUC/etc are not-applicable ---
truth(PLC.run_checks(_contract_noreturn(), R_hi, "c1", "accuracy 0.9") == [],
      "plausibility: a non-return metric is NOT-APPLICABLE (silent)")
truth(PLC.family_status(_contract_noreturn(), []) == "not-applicable",
      "family_status: not-applicable when no return is bound")
truth(PLC.family_status(_contract(), []) == "checked",
      "family_status: checked when a return series is examined and clean")
truth(PLC.family_status(_contract(), fs) == "flagged", "family_status: flagged on a smell")


# --- promotion is SOFT-ONLY: a reproduced number -> CAVEATS, never INVALIDATED / REFUTED ---
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
    findings = PLC.run_checks(contract, base, "c1", claim_text)
    PLC.apply_validity(claims, findings, contract, claim_text, base=base)
    return claims[0], findings


truth(_confirmed_claim()["verdict"] == V.CONFIRMED, "precondition: the bare claim is CONFIRMED")
hc, hf = _promote(_contract(), R_hi, "total return 0.1 — even under a robust, out-of-sample claim")
truth(hc["verdict"] == V.CAVEATS, "plausibility: a smell degrades CONFIRMED -> CONFIRMED-WITH-CAVEATS")
truth(hc["verdict"] != V.INVALIDATED and hc.get("driving_dimension") is None,
      "plausibility: SOFT-ONLY — never INVALIDATED, never drives the dimension (even on an OOS claim)")


def _ledger_valid(claims, findings):
    led = {"schema": "calma/ledger@1", "claims": claims, "findings": findings,
           "scope": {"isolation_tier": "tier0", "determinism_mode": "controlled-to-bit",
                     "families": {"plausibility": "flagged"}, "not_verified": []}, "repo_verdict": None}
    led["repo_verdict"] = LED.compute_repo_verdict(led)
    return LED.validate_obj(led)


truth(_ledger_valid([hc], hf)[0] in (0, 1), "plausibility CAVEATS ledger validates")


# ============================================================================================
# B1 thin-input broadening: regime drift (series) + undeclared-split leakage + train/test loss gap
# ============================================================================================

# --- regime drift: the two halves are a materially different distribution (a variance regime) ---
_glo, _ghi = _lcg(101), _lcg(202)
regime = ([round(0.001 + (next(_glo) - 0.5) * 0.004, 8) for _ in range(24)]
          + [round(0.001 + (next(_ghi) - 0.5) * 0.080, 8) for _ in range(24)])  # 2nd half ~20x vol
fr = PLC.run_checks(_contract(), _repo(regime), "c1", "total return")
truth(any(f["plausibility_kind"] == "regime-drift" for f in fr),
      "regime-drift: a variance-regime shift across the halves fires from the series alone (no block)")
truth(all(f["validity_class"] == "heuristic" and f["severity"] == "minor" for f in fr),
      "regime-drift: SOFT (heuristic, minor) — never INVALIDATED")
truth(not any(f["plausibility_kind"] == "regime-drift"
              for f in PLC.run_checks(_contract(), R_ok, "c1", "total return")),
      "regime-drift: a stationary (ordinary) series does NOT fire it (no false alarm)")
_sup = PLC.run_checks(_contract(), _repo(regime), "c1", "total return",
                      findings=[{"dimension": "regime", "id": "f-c1-regime"}])
truth(not any(f["plausibility_kind"] == "regime-drift" for f in _sup),
      "regime-drift: defers to the authoritative regime family when it already flagged")


# --- undeclared-split leakage: inferred train/test split + real row overlap -> SOFT smell ---
def _split_repo(train_rows, test_rows, header="x,y"):
    d = tempfile.mkdtemp()
    for name, rows in (("train.csv", train_rows), ("test.csv", test_rows)):
        with open(os.path.join(d, name), "w", newline="") as fh:
            fh.write(header + "\n")
            for r in rows:
                fh.write(r + "\n")
    return d


def _ml_contract(**extra):
    c = {"metrics": [{"metric_id": "accuracy", "artifact": "test.csv",
                      "binding": {"pred": "p", "label": "y"}, "claimed_value": 0.9, "headline": True}],
         "artifacts": [{"path": "train.csv", "columns": {"x": {}, "y": {}}},
                       {"path": "test.csv", "columns": {"x": {}, "y": {}}}]}
    c.update(extra)
    return c


_leak_base = _split_repo(["%d,%d" % (i, i % 2) for i in range(20)],
                         ["3,1", "5,1", "100,0", "101,1"])  # "3,1"/"5,1" duplicate train rows
fl = PLC.run_checks(_ml_contract(), _leak_base, "c1", "accuracy 0.9")
_leak = next((f for f in fl if f["plausibility_kind"] == "undeclared-split-leak"), None)
truth(_leak is not None,
      "undeclared-split: an inferred train/test split + real row overlap fires a SOFT leakage smell")
truth(_leak and _leak["dimension"] == "plausibility" and _leak["validity_class"] == "heuristic"
      and _leak["severity"] == "minor",
      "undeclared-split: SOFT (CAVEAT) — never an authoritative leakage blocker")
truth(_leak and "split:" in _leak["unblock"],
      "undeclared-split: the fix names the exact split block to declare")
truth(not any(f["plausibility_kind"] == "undeclared-split-leak"
              for f in PLC.run_checks(_ml_contract(split={"train": "train.csv", "test": "test.csv"}),
                                      _leak_base, "c1", "accuracy 0.9")),
      "undeclared-split: SILENT once a split is DECLARED (the authoritative family takes over)")
_clean = _split_repo(["%d,%d" % (i, i % 2) for i in range(20)], ["100,0", "101,1", "102,0"])
truth(not any(f["plausibility_kind"] == "undeclared-split-leak"
              for f in PLC.run_checks(_ml_contract(), _clean, "c1", "accuracy 0.9")),
      "undeclared-split: a clean (non-overlapping) split does NOT fire (no false alarm)")


# --- train/test loss gap: a history artifact whose val loss far exceeds train loss ---
def _hist_repo():
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "history.csv"), "w", newline="") as fh:
        fh.write("epoch,train_loss,val_loss\n1,0.50,0.55\n2,0.30,0.48\n3,0.10,0.42\n")
    return d


_hist_contract = {"metrics": [{"metric_id": "log_loss", "artifact": "history.csv",
                               "binding": {"value": "val_loss"}, "claimed_value": 0.42, "headline": True}],
                  "artifacts": [{"path": "history.csv",
                                 "columns": {"epoch": {}, "train_loss": {}, "val_loss": {}}}]}
fg = PLC.run_checks(_hist_contract, _hist_repo(), "c1", "log loss 0.42")
truth(any(f["plausibility_kind"] == "train-test-loss-gap" for f in fg),
      "loss-gap: a large train/val loss gap fires the overfit smell from the artifact alone")
truth(all(f["validity_class"] == "heuristic" and f["severity"] == "minor" for f in fg),
      "loss-gap: SOFT (heuristic, minor)")

print("plausibility_checks: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
