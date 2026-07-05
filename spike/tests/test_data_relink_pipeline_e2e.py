"""S0 (adaptive edge-case brain): the ABSOLUTE hardcoded data-path relink, end-to-end through the DEFAULT
deep pipeline — the path the make-runnable smoke actually ran (orchestrate is flag-gated off). The old wiring
called the relative-only relink_committed_data, which SILENTLY skipped an absolute read (`/Users/…/x.csv`) —
the exact ebv-ms case. The pipeline now calls make_data_available: it copies the committed file + rewrites the
hardcoded literal so the run proceeds, and the rewrite caps the verdict at REPRODUCED-ONLY (a source edit can
no longer attribute the number to the repo's own code → never a false CONFIRM). The relative case stays
uncapped (no edit → full verdict) — the no-regression guard below."""
import json

import pipeline
from core import verdict as VD


def _opts(**kw):
    return pipeline.VerifyOptions(runner="local", deep=True, entry="run.py", discover=True, k=2,
                                  timeout=60, plan=False, hooks="sklearn", **kw)


# id,y_true,y_pred over 6 rows → accuracy 5/6 = 0.8333 (one miss at row 5); balanced labels so it clears the
# majority-class baseline (0.5) and isn't INVALIDATED as trivial.
_DATA = "y_true,y_pred\n0,0\n1,1\n0,0\n1,1\n0,1\n1,1\n"


def _reader(read_path):
    # reads the CSV via a HARDCODED path, computes accuracy with the instrumented sklearn hook, and prints it.
    return (
        "import csv\n"
        "from sklearn.metrics import accuracy_score\n"
        "rows = list(csv.DictReader(open(%r)))\n"
        "yt = [int(r['y_true']) for r in rows]\n"
        "yp = [int(r['y_pred']) for r in rows]\n"
        "acc = accuracy_score(yt, yp)\n"
        "print('accuracy', round(acc, 4))\n"
    ) % read_path


def _repo(tmp_path, read_path):
    (tmp_path / "data.csv").write_text(_DATA)                 # committed at ROOT
    (tmp_path / "run.py").write_text(_reader(read_path))      # reads it from `read_path`
    (tmp_path / "results.json").write_text(json.dumps({"accuracy": 0.8333}))
    return str(tmp_path)


def test_absolute_hardcoded_path_runs_and_caps_to_reproduced_only(tmp_path):
    # code reads an ABSOLUTE path that doesn't exist; the file's basename IS committed at root. The relink must
    # copy+rewrite so the run proceeds — and BECAUSE it rewrote source, the matching number caps below CONFIRMED.
    out = pipeline.verify_repo(_repo(tmp_path, "/no/such/dir/data.csv"), _opts())
    assert out["run"]["ran"], out["run"]                      # the fix: absolute relink made a dead run runnable
    acc = [c for c in out["claims"] if c["metric"] == "accuracy"]
    assert acc, out["claims"]
    assert all(c["verdict"] != VD.CONFIRMED for c in acc), acc          # a source rewrite → never a bare CONFIRM
    assert any(c["verdict"] == VD.REPRODUCED_ONLY for c in acc), acc     # capped, not refuted (the value matches)


def test_relative_committed_relink_stays_uncapped(tmp_path):
    # no-regression: a RELATIVE read of a committed basename is placed WITHOUT a source edit → full verdict.
    # Upgrading the pipeline to make_data_available must not over-cap this (it returns modified=[] here).
    out = pipeline.verify_repo(_repo(tmp_path, "data/data.csv"), _opts())
    assert out["run"]["ran"], out["run"]
    acc = [c for c in out["claims"] if c["metric"] == "accuracy"]
    assert acc, out["claims"]
    assert any(c["verdict"] == VD.CONFIRMED for c in acc), acc          # no edit → uncapped, genuine CONFIRM
    assert not any(c["verdict"] == VD.REPRODUCED_ONLY for c in acc), acc
