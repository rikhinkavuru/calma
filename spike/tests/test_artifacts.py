"""Recompute-from-committed-predictions: verify a repo's metric straight from a committed predictions.csv,
no re-run. Validated against sklearn."""
import csv
import random

from sklearn.metrics import accuracy_score, roc_auc_score

from core import artifacts as A
from synth import formula as F


def _write_csv(path, header, rows):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def test_recompute_accuracy_from_committed_csv(tmp_path):
    rng = random.Random(1)
    yt = [rng.randint(0, 1) for _ in range(200)]
    yp = [yt[i] if rng.random() < 0.8 else 1 - yt[i] for i in range(200)]
    (tmp_path / "results").mkdir()
    _write_csv(tmp_path / "results" / "predictions.csv", ["y_true", "y_pred"], zip(yt, yp))
    out = A.recompute_from_artifacts(str(tmp_path), "accuracy", F.recompute_any)
    assert out is not None
    res, fname = out
    assert fname == "predictions.csv"
    assert abs(res["value"] - accuracy_score(yt, yp)) < 1e-9


def test_roc_auc_from_committed_scores(tmp_path):
    rng = random.Random(2)
    yt = [rng.randint(0, 1) for _ in range(200)]
    ys = [rng.random() for _ in range(200)]
    _write_csv(tmp_path / "preds.csv", ["label", "score"], zip(yt, ys))   # aliased column names
    out = A.recompute_from_artifacts(str(tmp_path), "roc_auc", F.recompute_any)
    assert out is not None and abs(out[0]["value"] - roc_auc_score(yt, ys)) < 1e-9


def test_no_prediction_file(tmp_path):
    (tmp_path / "data.csv").write_text("feature_a,feature_b\n1,2\n3,4\n")
    assert A.recompute_from_artifacts(str(tmp_path), "accuracy", F.recompute_any) is None


def test_artifact_verify_scans_repo_once_not_per_claim(tmp_path, monkeypatch):
    """The prediction-file scan is a pure function of repo_dir — it must run ONCE, not once per claim. With
    hundreds of discovered claims (gb_kmer: 838) the per-claim scan was a ~15-minute stall."""
    import pipeline as PIPE

    calls = {"n": 0}
    def counting_find(_repo):
        calls["n"] += 1
        return []                                    # no prediction files → the loop body is skipped anyway
    monkeypatch.setattr(PIPE.A, "find_prediction_files", counting_find)

    claims = [{"id": "c%d" % i, "metric": "accuracy", "value": 0.9} for i in range(200)]
    PIPE._artifact_verify(str(tmp_path), claims)
    assert calls["n"] == 1                            # scanned ONCE for all 200 claims, not 200×
