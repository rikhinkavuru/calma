"""mcc + cohen_kappa must match sklearn to 1e-9 (they were flywheel-dependent; now native catalog metrics).

Independent ref-vectors: the catalog impl shares zero code with sklearn, so agreement is genuine
cross-implementation evidence. Binary + multiclass + imbalanced + a random larger case.
"""
import numpy as np
from sklearn.metrics import brier_score_loss, cohen_kappa_score, matthews_corrcoef

from core import catalog as C


def _cases():
    rng = np.random.default_rng(0)
    cs = [
        ([0, 1, 0, 1, 1, 0, 1, 0], [0, 1, 1, 1, 0, 0, 1, 0]),            # binary
        ([0, 0, 1, 2, 2, 1, 0, 2, 1, 0], [0, 1, 1, 2, 0, 1, 0, 2, 2, 0]),  # 3-class
        ([0, 0, 0, 0, 0, 0, 1, 1], [0, 0, 0, 1, 0, 0, 1, 0]),            # imbalanced binary
        (rng.integers(0, 4, 300).tolist(), rng.integers(0, 4, 300).tolist()),  # random 4-class
    ]
    return cs


def test_mcc_matches_sklearn():
    for yt, yp in _cases():
        exp = matthews_corrcoef(yt, yp)
        got = C.recompute("mcc", {"y_true": yt, "y_pred": yp})
        assert not got["degenerate"], got
        assert abs(got["value"] - exp) < 1e-9, (got["value"], exp)


def test_cohen_kappa_matches_sklearn():
    for yt, yp in _cases():
        exp = cohen_kappa_score(yt, yp)
        got = C.recompute("cohen_kappa", {"y_true": yt, "y_pred": yp})
        assert not got["degenerate"], got
        assert abs(got["value"] - exp) < 1e-9, (got["value"], exp)


def test_brier_matches_sklearn():
    rng = np.random.default_rng(1)
    for _ in range(4):
        yt = rng.integers(0, 2, 200).tolist()
        p = rng.random(200).tolist()
        exp = brier_score_loss(yt, p)
        got = C.recompute("brier", {"y_true": yt, "y_score": p})
        assert not got["degenerate"], got
        assert abs(got["value"] - exp) < 1e-9, (got["value"], exp)


def test_aliases_resolve():
    assert C.canonical("matthews_corrcoef") == "mcc"
    assert C.canonical("MCC") == "mcc"
    assert C.canonical("cohen_kappa_score") == "cohen_kappa"
    assert C.canonical("kappa") == "cohen_kappa"
    assert C.canonical("brier_score_loss") == "brier"
