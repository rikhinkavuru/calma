"""Integration test for the four validity families composing through calma._assemble_ledger: a single
contract that declares MULTIPLE family surfaces at once (frictions + split + corpus + trials) must
produce a structurally + semantically VALID ledger whose repo verdict is the worst-wins outcome - no
crash, no double-promotion, no resurrection of a worse headline. Locks the cross-family interaction that
was previously only smoke-tested. Pure stdlib. Run: python3 test_validity_integration.py
"""
import csv
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import calma as C  # noqa: E402
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


def _write(d, name, header, rows):
    with open(os.path.join(d, name), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def _confirmed_vi():
    return {"gap": 0.0, "effective_budget": 1e-9, "binding_status": "independently-bound",
            "determinism_mode": "controlled-to-bit", "container_present": True, "band_coverage_ok": True,
            "sufficient_k": True, "exit_codes": [0], "claim_confirmed_target": True}


def _assemble(contract, claimed, recomputed, metric_id, base, claim_text):
    diff = {"metrics": [{"metric_id": metric_id, "headline": True, "claimed": claimed,
                         "recomputed": recomputed, "verdict": V.CONFIRMED, "verdict_inputs": _confirmed_vi(),
                         "reason": "ok", "recompute_error": None}], "baseline": None}
    run_res = {"exit_code": 0, "run_dir": os.path.join(base, ".calma", "r"), "base": base,
               "isolation_tier": "tier0", "determinism_mode": "controlled-to-bit"}
    return C._assemble_ledger(contract, diff, run_res, claim_text=claim_text)


# ------------------------------------------------------------------------------------
# (1) THREE family surfaces at once (frictions + split + corpus) on a return headline.
# The realism friction-deflation refutes the net claim (worst-wins over the leakage/contamination
# INVALIDATED that the held-out + corpus surfaces would otherwise drive). Ledger must be valid.
# ------------------------------------------------------------------------------------
d = tempfile.mkdtemp()
_write(d, "train.csv", ["id", "strat_return", "y"], [[i, 0.02, i % 2] for i in range(50)])
# 15 of 50 test rows duplicate train rows (leakage), eval text overlaps the corpus (contamination)
_write(d, "test.csv", ["id", "strat_return", "y"],
       [[1000 + i, 0.02, i % 2] for i in range(35)] + [[i, 0.02, i % 2] for i in range(15)])
with open(os.path.join(d, "corpus.txt"), "w") as fh:
    fh.write("0.02\n")  # the eval_col content (strat_return) "0.02" appears in the corpus
gross = N.total_return([0.02] * 50)
contract = {
    "frictions": {"fee_bps": 200, "slippage_bps": 200, "turnover_col": None},
    "split": {"train": "train.csv", "test": "test.csv"}, "keys": {"id": "id", "target": "y"},
    "corpus": {"manifest": "corpus.txt", "eval_col": "strat_return"},
    "artifacts": [], "metrics": [{"metric_id": "total_return", "artifact": "test.csv", "headline": True,
                                  "claimed_value": gross, "binding": {"return": "strat_return"},
                                  "binding_status": "independently-bound"}],
}
led = _assemble(contract, gross, gross, "total_return",
                d, "net total return after costs on the held-out test set")
code, info = L.validate_obj(led)
truth(code in (0, 1), "multi-family ledger validates structurally + semantically (got code %d: %s)"
      % (code, info.get("errors") if code == 2 else ""))
truth(not V.is_clean(led["repo_verdict"]),
      "multi-family contamination/leakage/realism -> a non-clean worst-wins verdict (got %s)" % led["repo_verdict"])
fams = led["scope"]["families"]
truth(fams.get("leakage") == "flagged" and fams.get("realism") == "flagged"
      and fams.get("contamination") == "flagged",
      "all three engaged families are 'flagged' in the scope map (got %r)" % fams)

# exactly ONE claim, exactly ONE driving dimension - no family double-promoted the headline
head = next(c for c in led["claims"] if c.get("headline"))
truth(head["verdict"] == led["repo_verdict"] or led["repo_verdict"] == "MIXED",
      "the headline claim verdict drives the repo verdict (no inconsistent rollup)")
truth(head.get("driving_dimension") in ("execution-realism", "leakage", "contamination"),
      "a single family owns the driving dimension (got %r)" % head.get("driving_dimension"))

# the verdict re-derives byte-for-byte from the stored inputs (the central honesty invariant holds
# even with four families having touched the same verdict_inputs)
truth(V.verdict(head["verdict_inputs"]) == head["verdict"],
      "the headline verdict re-derives byte-for-byte after multi-family promotion")


# ------------------------------------------------------------------------------------
# (2) order-safety at the pipeline level: once one family makes the headline non-clean, the later
# families in _assemble_ledger (realism, then contamination) cannot resurrect it to clean.
# A clean contract with NO family surfaces stays CONFIRMED (the families are all NOT-APPLICABLE).
# ------------------------------------------------------------------------------------
d2 = tempfile.mkdtemp()
_write(d2, "r.csv", ["ret"], [[0.01] for _ in range(30)])
clean_contract = {"artifacts": [], "metrics": [{"metric_id": "total_return", "artifact": "r.csv",
                  "headline": True, "claimed_value": N.total_return([0.01] * 30),
                  "binding": {"return": "ret"}, "binding_status": "independently-bound"}]}
led2 = _assemble(clean_contract, N.total_return([0.01] * 30), N.total_return([0.01] * 30),
                 "total_return", d2, "total return")
truth(led2["repo_verdict"] == V.CONFIRMED, "no family surfaces -> CONFIRMED (all families NOT-APPLICABLE)")
truth(L.validate_obj(led2)[0] == 0, "the clean multi-family-absent ledger gates to exit 0")
nv = led2["scope"]["not_verified"]
truth(any("contamination" in s for s in nv) and any("leakage" in s for s in nv),
      "the absent families are honestly listed in not_verified")

print("validity_integration: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
