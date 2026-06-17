"""P4.3 acceptance tests -- the reviewer panel + the anti-test-hacking gate.

Pure (no LLM): the gate reads the new ledger/diff/run.json as DATA and inspects the applied patch text.
A fix is legitimate ONLY if it closed the gap because the CODE changed -- not because a goalpost moved.
Develops against the btc asset. The genuine-fix case re-verifies a real code-only patch through the
engine (subprocess, system python3); the gamed cases are rejected at reviewer #0.
"""
import hashlib
import json
import os

from edges.common import engine
from edges.repair import checkpoints as CK
from edges.repair import review as RV
from edges.repair.types import Diagnosis, Goalposts

BTC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                   ".claude", "skills", "calma", "assets", "btc"))
CLAIM = 146.97697947938846


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _goalposts():
    return Goalposts(
        claim_value=CLAIM, metric_id="total_return",
        contract_sha256=_sha(os.path.join(BTC, "verify.yaml")),
        artifact_paths=("runs/oos/returns.csv", "runs/oos/baseline.csv"),
        artifact_sha256={}, isolation_tier="seatbelt-verified",
        determinism_mode="controlled-to-bit")


def _clean_ledger():
    return {"claims": [{"metric": "total_return", "claimed_value": CLAIM,
                        "input_binding_status": "independently-bound"}],
            "scope": {"isolation_tier": "seatbelt-verified", "determinism_mode": "controlled-to-bit"}}


def _diag(dimension="metric-mismatch", files=("gen_fixture.py",)):
    return Diagnosis(cause="c", locator="claimed 147.0x but the code recomputes -32.4%",
                     dimension=dimension, unified_diff="", target_files=tuple(files), rationale="r")


# === reviewer #0 (anti-test-hacking) rejects every goalpost move ===============================
def test_rejects_patch_that_edits_the_contract():
    ok, reasons = RV.anti_test_hacking(BTC, _diag(), _goalposts(), _clean_ledger(), {},
                                       "--- a/verify.yaml\n+++ b/verify.yaml\n@@\n-x\n+y\n")
    assert not ok and any("verify.yaml" in r for r in reasons)


def test_rejects_patch_that_swaps_the_recompute_artifact():
    diff = "--- a/runs/oos/returns.csv\n+++ b/runs/oos/returns.csv\n@@\n-0.1\n+999\n"
    ok, reasons = RV.anti_test_hacking(BTC, _diag(), _goalposts(), _clean_ledger(), {}, diff)
    assert not ok and any("artifact" in r for r in reasons)


def test_rejects_downgraded_isolation_tier():
    led = _clean_ledger()
    led["scope"]["isolation_tier"] = "host-not-isolated"          # downgraded from seatbelt-verified
    ok, reasons = RV.anti_test_hacking(BTC, _diag(), _goalposts(), led, {}, "code change\n")
    assert not ok and any("isolation" in r for r in reasons)


def test_rejects_changed_claim_value_or_weakened_binding():
    led = _clean_ledger()
    led["claims"][0]["claimed_value"] = 0.5                       # the claim under test was changed
    ok, reasons = RV.anti_test_hacking(BTC, _diag(), _goalposts(), led, {}, "code change\n")
    assert not ok and any("claimed_value" in r for r in reasons)

    led2 = _clean_ledger()
    led2["claims"][0]["input_binding_status"] = "plausibly-bound"  # binding weakened
    ok2, reasons2 = RV.anti_test_hacking(BTC, _diag(), _goalposts(), led2, {}, "code change\n")
    assert not ok2 and any("binding" in r for r in reasons2)


# === smell_review catches the obvious games ====================================================
def test_smell_rejects_hardcoded_claimed_value():
    diff = "--- a/gen_fixture.py\n+++ b/gen_fixture.py\n@@\n+    print(146.97697947938846)\n"
    ok, reasons = RV.smell_review(diff, _goalposts(), _clean_ledger())
    assert not ok and any("hard-codes" in r for r in reasons)


def test_smell_rejects_non_minimal_patch():
    big = "--- a/gen_fixture.py\n+++ b/gen_fixture.py\n" + "".join("+line %d\n" % i for i in range(80))
    ok, reasons = RV.smell_review(big, _goalposts(), _clean_ledger())
    assert not ok and any("not minimal" in r for r in reasons)


def test_recompute_column_degeneracy_flags_a_generated_constant_series(tmp_path):
    # the fabrication that the literal-line smell can't see: a GENERATED constant series ([r]*n) written
    # to the recompute artifact. The OUTPUT degeneracy check catches it; a varying series passes.
    import csv as _csv
    scratch = str(tmp_path)
    json.dump({"metrics": [{"metric_id": "total_return", "artifact": "returns.csv",
                            "binding": {"return": "strat_return"}}]},
              open(os.path.join(scratch, "verify.yaml"), "w"))
    with open(os.path.join(scratch, "returns.csv"), "w", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["strat_return"])
        for _ in range(50):
            w.writerow([0.0055739382186204])                  # a constant series (forged)
    gp = Goalposts(claim_value=CLAIM, metric_id="total_return", contract_sha256="x",
                   artifact_paths=("returns.csv",), artifact_sha256={},
                   isolation_tier="seatbelt-verified", determinism_mode="controlled-to-bit")
    reason = RV._recompute_column_degenerate(scratch, gp)
    assert reason is not None and "CONSTANT" in reason

    # a varying series (a real computation) is NOT flagged
    with open(os.path.join(scratch, "returns.csv"), "w", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["strat_return"])
        for i in range(50):
            w.writerow([0.001 * ((i % 7) - 3)])
    assert RV._recompute_column_degenerate(scratch, gp) is None


def test_smell_rejects_a_fabricated_constant_series():
    # the "feed the check a constant" attack: replace a computed emission with a hard-coded series that
    # recomputes to the claim. The headline scalar never appears, so the literal check misses it.
    fab = ("--- a/gen_fixture.py\n+++ b/gen_fixture.py\n@@ -1,1 +1,20 @@\n"
           + "".join("+    0.0253000316757519,\n" for _ in range(15)))
    ok, reasons = RV.smell_review(fab, _goalposts(), _clean_ledger())
    assert not ok and any("fabricated" in r or "constant" in r for r in reasons)


def test_anti_test_hacking_fails_closed_on_dropped_goalpost_fields():
    # a gamed re-verify that simply DROPS a goalpost field must be REJECTED, not treated as "unchanged"
    led_no_claim = {"claims": [{"metric": "total_return", "input_binding_status": "independently-bound"}],
                    "scope": {"isolation_tier": "seatbelt-verified",
                              "determinism_mode": "controlled-to-bit"}}
    ok, reasons = RV.anti_test_hacking(BTC, _diag(dimension="metric-mismatch"), _goalposts(),
                                       led_no_claim, {}, "code change\n")
    assert not ok and any("claimed_value" in r for r in reasons)

    led_no_scope = {"claims": [{"metric": "total_return", "claimed_value": CLAIM,
                                "input_binding_status": "independently-bound"}], "scope": {}}
    ok2, reasons2 = RV.anti_test_hacking(BTC, _diag(dimension="metric-mismatch"), _goalposts(),
                                         led_no_scope, {}, "code change\n")
    assert not ok2 and any("isolation" in r or "determinism" in r for r in reasons2)


def test_anti_test_hacking_fails_closed_on_empty_artifact_goalposts():
    gp = Goalposts(claim_value=CLAIM, metric_id="total_return",
                   contract_sha256=_sha(os.path.join(BTC, "verify.yaml")),
                   artifact_paths=(), artifact_sha256={}, isolation_tier="seatbelt-verified",
                   determinism_mode="controlled-to-bit")                      # capture FAILED -> empty
    ok, reasons = RV.anti_test_hacking(BTC, _diag(dimension="metric-mismatch"), gp, _clean_ledger(),
                                       {}, "code change\n")
    assert not ok and any("artifact" in r and "empty" in r for r in reasons)


def test_anti_test_hacking_ignores_contract_mention_in_a_comment():
    # the file-header check (not a substring scan) must NOT reject an honest patch whose COMMENT mentions
    # verify.yaml -- only an actual modification of verify.yaml counts
    diff = ("--- a/gen_fixture.py\n+++ b/gen_fixture.py\n@@\n"
            "+    # paths are read from verify.yaml; this only changes the producing code\n")
    ok, reasons = RV.anti_test_hacking(BTC, _diag(dimension="metric-mismatch"), _goalposts(),
                                       _clean_ledger(), {}, diff)
    assert all("modifies verify.yaml" not in r for r in reasons)


def test_smell_passes_a_minimal_code_change():
    diff = ("--- a/gen_fixture.py\n+++ b/gen_fixture.py\n@@\n"
            "-    _, oos_rets = backtest(OOS, bf, bs, bl, fee=fee)\n"
            "+    _, oos_rets = backtest(IS, bf, bs, bl, fee=0.0)\n")
    ok, _ = RV.smell_review(diff, _goalposts(), _clean_ledger())
    assert ok


# === spec_review ties the patch to the finding =================================================
def test_spec_review_requires_matching_dimension_and_target_files():
    finding = {"dimension": "metric-mismatch"}
    ok, _ = RV.spec_review(_diag(dimension="metric-mismatch"), finding)
    assert ok
    bad, reasons = RV.spec_review(_diag(dimension="baseline"), finding)
    assert not bad and any("dimension" in r for r in reasons)
    none, reasons2 = RV.spec_review(_diag(files=()), finding)
    assert not none and any("target files" in r for r in reasons2)


# === review() end-to-end: a genuine minimal code fix passes ALL reviewers ======================
def test_genuine_code_fix_passes_review_end_to_end():
    scratch = CK.make_scratch(BTC)
    try:
        base = CK.checkpoint(scratch)
        gp = os.path.join(scratch, "gen_fixture.py")
        src = open(gp).read()
        open(gp, "w").write(src.replace("backtest(OOS, bf, bs, bl, fee=fee)",
                                        "backtest(IS, bf, bs, bl, fee=0.0)"))
        # the TRUE patch, captured BEFORE the re-verify re-emits artifacts (mirrors the orchestrator)
        patch_diff = CK.diff_since(scratch, base)
        assert "gen_fixture.py" in patch_diff and "runs/oos/returns.csv" not in patch_diff

        res = engine.verify(scratch, claim=CLAIM, metric="total_return", extra_args=("--force",))
        assert res["verdict"] in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS")
        new_ledger = engine.read_ledger(res["run_dir"])
        new_diff = engine.read_diff(res["run_dir"])
        finding = {"dimension": "metric-mismatch",
                   "locator": "claimed 147.0x but the code recomputes -32.4%"}

        ok, reasons = RV.review(scratch, _diag(), _goalposts(), new_ledger, new_diff, res, finding,
                                base_ckpt=base, applied_diff=patch_diff)
        assert ok, reasons
    finally:
        CK.cleanup_scratch(scratch)
