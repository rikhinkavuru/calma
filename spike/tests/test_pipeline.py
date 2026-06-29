"""End-to-end pipeline orchestration tests."""
import os
import random

from core import verdict as VD
from pipeline import VerifyOptions, _error_summary, verify_repo

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


def test_error_summary_picks_the_exception_line():
    tb = ("Traceback (most recent call last):\n"
          '  File "train.py", line 3, in <module>\n'
          "    import genomic_benchmarks\n"
          "ModuleNotFoundError: No module named 'genomic_benchmarks'\n")
    assert _error_summary(tb) == "ModuleNotFoundError: No module named 'genomic_benchmarks'"
    assert _error_summary("") == ""
    assert _error_summary("just a plain message line") == "just a plain message line"


def test_failed_run_surfaces_real_error(tmp_path):
    repo = str(tmp_path / "broken")
    os.makedirs(repo)
    with open(os.path.join(repo, "eval.py"), "w") as fh:
        fh.write("import genomic_benchmarks  # not installed\n")
    with open(os.path.join(repo, "results.json"), "w") as fh:
        fh.write('{"accuracy": 0.89}\n')
    result = verify_repo(repo, VerifyOptions(deep=True, entry="eval.py", discover=True, k=1))
    assert result["run"]["ran"] is False
    assert "ModuleNotFoundError" in result["run"]["error"]
    assert "genomic_benchmarks" in result["run"]["error"]


def _seq(rng, n=60):
    return "".join(rng.choice("ACGT") for _ in range(n))


def _write_leaky_benchmark(repo, *, claimed="0.89"):
    """A repo that reports a per-dataset accuracy table whose held-out split is contaminated — the genomics
    failure: the number reproduces, but the test set leaked from train."""
    os.makedirs(repo, exist_ok=True)
    rng = random.Random(7)
    train = [_seq(rng) for _ in range(200)]
    test = train[:100] + [_seq(rng) for _ in range(20)]   # 100/120 test rows are verbatim from train
    with open(os.path.join(repo, "promoters_train.csv"), "w") as fh:
        fh.write("sequence,label\n" + "\n".join("%s,%d" % (s, i % 2) for i, s in enumerate(train)))
    with open(os.path.join(repo, "promoters_test.csv"), "w") as fh:
        fh.write("sequence,label\n" + "\n".join("%s,%d" % (s, i % 2) for i, s in enumerate(test)))
    with open(os.path.join(repo, "results.csv"), "w") as fh:
        fh.write("dataset,accuracy\npromoters,%s\n" % claimed)


def test_leakage_overlay_invalidates_attributed_claim(tmp_path):
    repo = str(tmp_path / "leaky")
    _write_leaky_benchmark(repo)
    result = verify_repo(repo, VerifyOptions(deep=False, discover=True))

    # the dataset-level leakage banner is still produced
    assert result["leakage"] and result["leakage"][0]["findings"]

    # the discovered accuracy claim, attributed to dataset=promoters, is INVALIDATED by the leak — not left
    # as an unverified DISCOVERED number, and not (it has no committed predictions) silently dropped.
    accs = [c for c in result["claims"] if c["metric"] == "accuracy"]
    assert accs, "expected the per-dataset accuracy claim to be discovered"
    assert all(c["verdict"] == VD.INVALIDATED for c in accs)
    assert all(c["validity"]["invalidating"] for c in accs)
    assert any("contaminated" in c["reason"] for c in accs)


def test_clean_benchmark_not_invalidated(tmp_path):
    """A clean split must NOT be downgraded — the overlay only fires on a real, attributed leak."""
    repo = str(tmp_path / "clean")
    os.makedirs(repo)
    rng = random.Random(8)
    train = [_seq(rng) for _ in range(200)]
    test = [_seq(rng) for _ in range(120)]                 # all novel — no leakage
    with open(os.path.join(repo, "promoters_train.csv"), "w") as fh:
        fh.write("sequence,label\n" + "\n".join("%s,%d" % (s, i % 2) for i, s in enumerate(train)))
    with open(os.path.join(repo, "promoters_test.csv"), "w") as fh:
        fh.write("sequence,label\n" + "\n".join("%s,%d" % (s, i % 2) for i, s in enumerate(test)))
    with open(os.path.join(repo, "results.csv"), "w") as fh:
        fh.write("dataset,accuracy\npromoters,0.89\n")
    result = verify_repo(repo, VerifyOptions(deep=False, discover=True))
    accs = [c for c in result["claims"] if c["metric"] == "accuracy"]
    assert accs and all(c["verdict"] != VD.INVALIDATED for c in accs)
