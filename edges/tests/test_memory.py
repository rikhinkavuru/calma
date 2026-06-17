"""P4.4 acceptance tests -- episodic repair memory (failure-signature -> patch-that-passed).

Pure (no LLM). Memory only ACCELERATES the proposer (it seeds the diagnosis prompt); Calma still
re-verifies every patched result and owns the verdict, so a bad memory can waste a hypothesis but never
CONFIRM a bad fix. These tests cover the store/retrieve contract, the signature normalization, and the
one-shot-fix-rate KPI.
"""
import os
from types import SimpleNamespace

from edges.repair import memory as MEM
from edges.repair.types import Goalposts


def _gp():
    return Goalposts(claim_value=146.977, metric_id="total_return", contract_sha256="x",
                     artifact_paths=("runs/oos/returns.csv",), artifact_sha256={},
                     isolation_tier="seatbelt-verified", determinism_mode="controlled-to-bit")


def _accepted(unified_diff, index=0):
    return SimpleNamespace(diagnosis=SimpleNamespace(unified_diff=unified_diff), index=index)


PATCH = ("--- a/gen_fixture.py\n+++ b/gen_fixture.py\n@@\n"
         "-    _, oos_rets = backtest(OOS, bf, bs, bl, fee=fee)\n"
         "+    _, oos_rets = backtest(IS, bf, bs, bl, fee=0.0)\n")


def test_record_then_retrieve_same_class_returns_patch_shape(tmp_path):
    path = os.path.join(str(tmp_path), "episodes.jsonl")
    claim = {"driving_dimension": "baseline"}
    finding = {"locator": "OOS strategy return -32.4% < buy-and-hold +41.8%"}
    MEM.record(path, claim, finding, _gp(), _accepted(PATCH), ts=1700000000)

    # a later catch of the SAME dimension + a numerically-different but structurally-equal locator
    shape = MEM.retrieve(path, dimension="baseline",
                         locator="OOS strategy return -28.1% < buy-and-hold +37.0%")
    assert shape is not None
    assert "gen_fixture.py" in shape["files"]
    assert "backtest" in shape["skeleton"]

    # a DIFFERENT dimension retrieves nothing (dimension is an exact-match gate)
    assert MEM.retrieve(path, dimension="leakage",
                        locator="OOS strategy return -28.1% < buy-and-hold +37.0%") is None


def test_locator_signature_collapses_numbers_to_one_signature():
    a = MEM.locator_signature("OOS strategy return -32.4% < buy-and-hold +41.8%")
    b = MEM.locator_signature("OOS strategy return -28.1% < buy-and-hold +37.0%")
    assert a == b                                              # differ only in the numbers
    assert "<num>" in a and "buy-and-hold" in a

    # a path-bearing locator collapses the path too
    c = MEM.locator_signature("recompute of runs/oos/returns.csv disagrees by 0.9")
    assert "<path>" in c and "<num>" in c


def test_patch_shape_masks_literals_but_keeps_structure():
    shape = MEM._patch_shape(PATCH)
    assert shape["files"] == ["gen_fixture.py"]
    assert "backtest(OOS, bf, bs, bl, fee=fee)" in shape["skeleton"]      # the - line, masked of digits
    assert "146" not in shape["skeleton"]                                # any literal numbers are masked


def test_one_shot_fix_rate_over_synthetic_episodes(tmp_path):
    path = os.path.join(str(tmp_path), "episodes.jsonl")
    claim = {"driving_dimension": "baseline"}
    finding = {"locator": "x"}
    MEM.record(path, claim, finding, _gp(), _accepted(PATCH, index=0), ts=1)   # one-shot
    MEM.record(path, claim, finding, _gp(), _accepted(PATCH, index=2), ts=2)   # 3 iterations
    MEM.record(path, claim, finding, _gp(), _accepted(PATCH, index=0), ts=3)   # one-shot

    kpi = MEM.one_shot_fix_rate(path)
    assert kpi["episodes"] == 3
    assert kpi["one_shot"] == 2
    assert abs(kpi["rate"] - 2 / 3) < 1e-9


def test_retrieve_below_similarity_threshold_returns_none(tmp_path):
    path = os.path.join(str(tmp_path), "episodes.jsonl")
    MEM.record(path, {"driving_dimension": "baseline"},
               {"locator": "OOS strategy return -32.4% < buy-and-hold +41.8%"},
               _gp(), _accepted(PATCH), ts=1)
    # same dimension but a totally unrelated locator -> Jaccard below 0.34 -> no prior
    assert MEM.retrieve(path, dimension="baseline",
                        locator="duplicate rows detected in the customer table") is None
