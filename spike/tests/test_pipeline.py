"""End-to-end pipeline orchestration tests."""
import os

from core import verdict as VD
from pipeline import VerifyOptions, verify_repo

FIX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def test_pipeline_artifact_first_without_rerun():
    repo = os.path.join(FIX, "committed_preds")
    result = verify_repo(repo, VerifyOptions(deep=False, discover=True))
    assert result["run"] is None
    assert result["counts"][VD.CONFIRMED] >= 1
    assert any((c.get("provenance") or "").startswith("artifact:") for c in result["claims"])
    assert [e["stage"] for e in result["trace"] if e["stage"] != "note"] == [
        "initializing",
        "discovering",
        "checking data",
        "diffing",
        "done",
    ]


def test_pipeline_deep_verify_clean_fixture():
    repo = os.path.join(FIX, "clean_eval")
    result = verify_repo(
        repo,
        VerifyOptions(
            deep=True,
            entry="eval.py",
            discover=False,
            claims=[
                {"id": "acc", "metric": "accuracy", "value": "0.831"},
                {"id": "auc", "metric": "roc_auc", "value": "0.942"},
            ],
        ),
    )
    assert result["run"]["ran"]
    assert result["run"]["calls"] >= 2
    assert result["counts"] == {VD.CONFIRMED: 2}
