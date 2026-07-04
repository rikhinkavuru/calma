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
