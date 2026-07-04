"""The discover-before-run snapshot fix, end-to-end. A producer entrypoint (the kind the reverse map now
picks) REGENERATES its own results.json on run. Without snapshotting the committed claims first, discovery
reads the freshly-written honest file and a committed MISREPORT is silently overwritten → hidden. The fix
pins committed result-FILE claims to their pre-run value, so the misreport is still caught (REFUTED), while
an honest committed file still confirms (no false-refute)."""
import json

import pipeline


def _opts(**kw):
    return pipeline.VerifyOptions(runner="local", deep=True, entry="run_all.py", discover=True, k=2,
                                  timeout=60, plan=False, hooks="sklearn", **kw)


# a producer that computes 9/10 = 0.90 and rewrites results.json with the HONEST value every run
_PRODUCER = (
    "import json\n"
    "from sklearn.metrics import accuracy_score\n"
    "y_true = [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]\n"
    "y_pred = [0, 1, 0, 1, 0, 1, 0, 1, 1, 1]\n"      # 9/10 correct = 0.90 (one mismatch at index 8)
    "acc = accuracy_score(y_true, y_pred)\n"
    "json.dump({'accuracy': round(acc, 4)}, open('results.json', 'w'))\n"
    "print('accuracy', acc)\n"
)


def _repo(tmp_path, committed_accuracy):
    (tmp_path / "run_all.py").write_text(_PRODUCER)
    (tmp_path / "results.json").write_text(json.dumps({"accuracy": committed_accuracy}))
    return str(tmp_path)


def test_committed_misreport_survives_a_regenerating_entrypoint(tmp_path):
    # committed results.json claims 0.95; the producer recomputes 0.80 and rewrites the file on run.
    out = pipeline.verify_repo(_repo(tmp_path, 0.95), _opts())
    assert out["run"]["ran"], out["run"]
    acc = [c for c in out["claims"] if c["metric"] == "accuracy"]
    assert acc, out["claims"]
    assert any(c["verdict"] == "REFUTED" for c in acc), acc      # the misreport is NOT hidden by the rewrite


def test_honest_committed_file_still_confirms(tmp_path):
    # committed results.json honestly says 0.90 — pinning must not cause a false-refute.
    out = pipeline.verify_repo(_repo(tmp_path, 0.9), _opts())
    assert out["run"]["ran"], out["run"]
    acc = [c for c in out["claims"] if c["metric"] == "accuracy"]
    assert acc, out["claims"]
    assert not any(c["verdict"] == "REFUTED" for c in acc), acc
