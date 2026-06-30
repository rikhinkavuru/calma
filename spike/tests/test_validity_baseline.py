"""Regression: the trivial-baseline validity check must use the RIGHT baseline per metric.

A constant majority-class predictor scores `majority_fraction` on raw accuracy but only `1/n_classes` on
balanced_accuracy. Comparing balanced_accuracy against the majority fraction false-INVALIDATES honest
results (found by optimize/recompute_stress.py). These pin the corrected behavior.
"""
from core import validity as V

# 6 zeros + 2 ones: majority fraction = 0.75, n_classes = 2 → balanced-accuracy trivial baseline = 0.5
_YT = [0, 0, 0, 0, 0, 0, 1, 1]


def test_balanced_accuracy_uses_inv_nclasses_baseline_not_majority():
    # 0.667 beats the 0.5 constant-predictor baseline → has signal → NOT invalidating
    assert not V.check("balanced_accuracy", {"y_true": _YT}, 0.6667)["invalidating"]
    # at/below 1/n_classes (0.5) → genuinely trivial → invalidating
    assert V.check("balanced_accuracy", {"y_true": _YT}, 0.5)["invalidating"]
    assert V.check("balanced_accuracy", {"y_true": _YT}, 0.49)["invalidating"]


def test_raw_accuracy_still_uses_majority_fraction():
    # raw accuracy at/below the majority fraction (0.75) → trivial → invalidating
    assert V.check("accuracy", {"y_true": _YT}, 0.75)["invalidating"]
    assert V.check("accuracy", {"y_true": _YT}, 0.70)["invalidating"]
    # comfortably above majority → has signal
    assert not V.check("accuracy", {"y_true": _YT}, 0.90)["invalidating"]
