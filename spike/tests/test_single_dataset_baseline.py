"""Trivial-baseline catch on a SINGLE committed dataset (no train/test split, no run) — the common repo
shape. Must CATCH an at/below-baseline accuracy and must NOT false-invalidate a claim that beats it."""
import os
import tempfile

import validity_scan as VS
from core import leakage as L


def _repo(labels_col, claim, label_name="income"):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "data.csv"), "w") as fh:
        fh.write(label_name + "\n" + "\n".join(labels_col))
    with open(os.path.join(d, "README.md"), "w") as fh:
        fh.write("The model reaches %s accuracy.\n" % claim)
    return d


def test_from_committed_dataset_reads_named_label():
    d = _repo(["0"] * 70 + ["1"] * 30, "90%")
    res = L.from_committed_dataset(d)
    assert res and res[0]["label_stats"]["majority_frac"] == 0.7 and res[0]["single_dataset"]


def test_at_baseline_accuracy_is_invalidated():
    card = VS.scan(_repo(["0"] * 80 + ["1"] * 20, "80%"))       # majority baseline 0.80
    assert card["grade"] == "FAIL"
    tb = next(c for c in card["checks"] if c["name"] == "trivial-baseline")
    assert tb["status"] == "fail"


def test_beating_the_baseline_passes():
    card = VS.scan(_repo(["0"] * 80 + ["1"] * 20, "95%"))       # 0.95 >> 0.80 baseline
    tb = next(c for c in card["checks"] if c["name"] == "trivial-baseline")
    assert tb["status"] != "fail"


def test_balanced_data_high_accuracy_not_invalidated():
    # balanced 50/50 -> baseline 0.5; a 0.88 claim is legit, must NOT be flagged
    card = VS.scan(_repo((["0", "1"] * 50), "88%"))
    tb = next(c for c in card["checks"] if c["name"] == "trivial-baseline")
    assert tb["status"] != "fail"


def test_results_csv_is_not_treated_as_dataset():
    # a committed model_results.csv (an OUTPUT) must not be mined for a baseline
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "model_results.csv"), "w") as fh:
        fh.write("model,accuracy,class\nlr,0.8,0\nknn,0.7,1\n")
    assert L.from_committed_dataset(d) == []


def test_negative_r2_is_degenerate_no_dataset_needed():
    # a regression R2 <= 0 is no better than predicting the mean — invalid regardless of the dataset (no
    # committed labels needed). Data-independent catch.
    import tempfile
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "README.md"), "w") as fh:
        fh.write("Our model reaches an R2 of -0.05 on the held-out set.\n")
    card = VS.scan(d)
    assert card["grade"] == "FAIL", card
    tb = next(c for c in card["checks"] if c["name"] == "trivial-baseline")
    assert tb["status"] == "fail"


def test_positive_r2_passes():
    import tempfile
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "README.md"), "w") as fh:
        fh.write("R2 of 0.84 on the test set.\n")
    tb = next(c for c in VS.scan(d)["checks"] if c["name"] == "trivial-baseline")
    assert tb["status"] != "fail"


def test_contrasted_baseline_r2_is_not_a_false_fail():
    # a ≤0 R2 that is a CONTRASTED baseline (the repo reports a better R2 as its result) must NOT be branded
    # INVALIDATED — that is a false accusation on an honest paper. Only the headline/only degenerate R2 fails.
    import tempfile
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "README.md"), "w") as fh:
        fh.write("The naive mean baseline gives an R2 of -0.03, while our model reaches an R2 of 0.87.\n")
    card = VS.scan(d)
    tb = next(c for c in card["checks"] if c["name"] == "trivial-baseline")
    assert tb["status"] != "fail", card              # the -0.03 baseline must not trigger a FAIL
    assert card["grade"] != "FAIL", card
