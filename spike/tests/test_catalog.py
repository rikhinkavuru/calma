"""Validate the pure-stdlib trusted catalog against sklearn/numpy on random data.

This is the cross-implementation check that makes the oracle trustworthy: our independent recompute must
agree with sklearn (which the repos under test use) to ~1e-9 across many random trials. If it doesn't, the
INVALIDATED verdict (produced ≠ recomputed) would be untrustworthy. We deliberately share no code with
sklearn — agreement here is real evidence, not a tautology.
"""
import random

import numpy as np
import pytest
from sklearn import metrics as skm

from core import catalog as C

R = random.Random(20260627)


def _labels(n, k=2):
    return [R.randint(0, k - 1) for _ in range(n)]


def _scores(n):
    return [R.random() for _ in range(n)]


def _reals(n):
    return [R.gauss(0, 3) for _ in range(n)]


@pytest.mark.parametrize("trial", range(40))
def test_accuracy(trial):
    n = R.randint(5, 200)
    yt, yp = _labels(n, R.randint(2, 4)), _labels(n, R.randint(2, 4))
    got = C.recompute("accuracy", {"y_true": yt, "y_pred": yp}, {})
    assert abs(got["value"] - skm.accuracy_score(yt, yp)) < 1e-12


@pytest.mark.parametrize("trial", range(40))
def test_balanced_accuracy(trial):
    n = R.randint(10, 200)
    yt, yp = _labels(n, 3), _labels(n, 3)
    got = C.recompute("balanced_accuracy", {"y_true": yt, "y_pred": yp}, {})
    assert abs(got["value"] - skm.balanced_accuracy_score(yt, yp)) < 1e-12


@pytest.mark.parametrize("trial", range(40))
def test_prf_binary(trial):
    n = R.randint(10, 200)
    yt, yp = _labels(n, 2), _labels(n, 2)
    if sum(yt) == 0 or sum(yp) == 0:
        return
    for name, sk in (("precision", skm.precision_score), ("recall", skm.recall_score), ("f1", skm.f1_score)):
        got = C.recompute(name, {"y_true": yt, "y_pred": yp}, {"pos_label": 1, "average": "binary"})
        assert abs(got["value"] - sk(yt, yp, pos_label=1, zero_division=0)) < 1e-12, name


@pytest.mark.parametrize("trial", range(40))
def test_prf_macro(trial):
    n = R.randint(10, 200)
    yt, yp = _labels(n, 4), _labels(n, 4)
    for name, sk in (("precision", skm.precision_score), ("recall", skm.recall_score), ("f1", skm.f1_score)):
        got = C.recompute(name, {"y_true": yt, "y_pred": yp}, {"average": "macro"})
        assert abs(got["value"] - sk(yt, yp, average="macro", zero_division=0)) < 1e-9, name


@pytest.mark.parametrize("trial", range(50))
def test_roc_auc(trial):
    n = R.randint(10, 300)
    yt = _labels(n, 2)
    if len(set(yt)) != 2:
        return
    ys = _scores(n)
    # inject ties sometimes to exercise average-rank handling
    if trial % 3 == 0:
        ys = [round(s, 1) for s in ys]
    got = C.recompute("roc_auc", {"y_true": yt, "y_score": ys}, {})
    assert abs(got["value"] - skm.roc_auc_score(yt, ys)) < 1e-9


@pytest.mark.parametrize("trial", range(40))
def test_regression(trial):
    n = R.randint(5, 200)
    yt, yp = _reals(n), _reals(n)
    assert abs(C.recompute("mse", {"y_true": yt, "y_pred": yp}, {})["value"]
               - skm.mean_squared_error(yt, yp)) < 1e-9
    assert abs(C.recompute("rmse", {"y_true": yt, "y_pred": yp}, {})["value"]
               - skm.mean_squared_error(yt, yp) ** 0.5) < 1e-9
    assert abs(C.recompute("mae", {"y_true": yt, "y_pred": yp}, {})["value"]
               - skm.mean_absolute_error(yt, yp)) < 1e-9
    assert abs(C.recompute("r2", {"y_true": yt, "y_pred": yp}, {})["value"]
               - skm.r2_score(yt, yp)) < 1e-9


@pytest.mark.parametrize("trial", range(30))
def test_reductions_and_sharpe(trial):
    n = R.randint(5, 300)
    v = _reals(n)
    assert abs(C.recompute("mean", {"values": v}, {})["value"] - float(np.mean(v))) < 1e-9
    assert abs(C.recompute("sum", {"values": v}, {})["value"] - float(np.sum(v))) < 1e-6
    # sharpe vs numpy sample-std definition
    arr = np.array(v)
    exp = float(np.mean(arr) / np.std(arr, ddof=1)) if np.std(arr, ddof=1) > 1e-12 else None
    got = C.recompute("sharpe", {"returns": v}, {"ddof": 1})
    if exp is not None:
        assert abs(got["value"] - exp) < 1e-9


def test_fail_closed_paths():
    # length mismatch -> degenerate
    assert C.recompute("accuracy", {"y_true": [1, 0], "y_pred": [1]}, {})["degenerate"]
    # single-class AUC -> degenerate
    assert C.recompute("roc_auc", {"y_true": [1, 1, 1], "y_score": [0.1, 0.2, 0.3]}, {})["degenerate"]
    # near-zero vol sharpe -> degenerate
    assert C.recompute("sharpe", {"returns": [0.01, 0.01, 0.01]}, {})["degenerate"]
    # unknown metric -> degenerate (fail closed)
    assert C.recompute("bleu", {"values": [1, 2]}, {})["degenerate"]
    # non-numeric regression cell -> degenerate
    assert C.recompute("rmse", {"y_true": ["a", "b"], "y_pred": [1, 2]}, {})["degenerate"]
