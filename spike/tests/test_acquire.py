"""Data-acquisition (paid, gated): detect the repo's download pipeline, run it, then recompute. The detector
and orchestration are pure/unit-tested; the pipeline integration is exercised end-to-end on the LOCAL runner
(a numbered acquisition script writes the data the eval needs → the re-run confirms). FCR is preserved:
acquisition only writes inputs; a wrong/failed fetch → the eval fails again → DISCOVERED, never CONFIRM."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from core import verdict as VD  # noqa: E402
from pipeline import VerifyOptions, verify_repo  # noqa: E402
from runner import acquire as ACQ  # noqa: E402


# ── detector ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_find_acquisition_numbered_scripts_in_order(tmp_path):
    for f in ("02_features.py", "01_download.py", "03_build.py", "eval.py"):
        (tmp_path / f).write_text("print(1)\n")
    cmds = ACQ.find_acquisition(str(tmp_path))
    assert cmds == [["01_download.py"], ["02_features.py"], ["03_build.py"]]   # numeric order, eval excluded


def test_find_acquisition_name_matched(tmp_path):
    (tmp_path / "download_data.py").write_text("print(1)\n")
    (tmp_path / "eval.py").write_text("print(1)\n")
    cmds = ACQ.find_acquisition(str(tmp_path))
    assert ["download_data.py"] in cmds


def test_find_acquisition_make_target(tmp_path):
    (tmp_path / "Makefile").write_text("data:\n\techo hi\n\ntest:\n\tpytest\n")
    assert ACQ.find_acquisition(str(tmp_path)) == [["make", "data"]]


def test_find_acquisition_none(tmp_path):
    (tmp_path / "eval.py").write_text("print(1)\n")
    assert ACQ.find_acquisition(str(tmp_path)) == []


# ── orchestration ─────────────────────────────────────────────────────────────────────────────────────────────
def test_run_acquisition_stops_at_first_failure():
    calls = []

    def run_cmd(argv):
        calls.append(argv)
        return {"ok": argv != ["02_bad.py"], "tail": ""}

    res = ACQ.run_acquisition([["01_ok.py"], ["02_bad.py"], ["03_never.py"]], run_cmd)
    assert res["ok"] is False and res["failed"] == ["02_bad.py"]
    assert calls == [["01_ok.py"], ["02_bad.py"]]              # 03 never runs


def test_run_acquisition_all_ok():
    res = ACQ.run_acquisition([["01.py"], ["02.py"]], lambda a: {"ok": True, "tail": ""})
    assert res["ok"] is True and res["failed"] is None and len(res["ran"]) == 2


# ── pipeline end-to-end (local) ───────────────────────────────────────────────────────────────────────────────
def test_acquisition_materializes_data_then_confirms(tmp_path):
    repo = tmp_path / "datarepo"
    repo.mkdir()
    # a numbered acquisition step that writes the dataset the eval needs
    (repo / "01_download.py").write_text(
        "with open('data.csv','w') as f:\n"
        "    f.write('y_true,y_pred\\n1,1\\n0,0\\n1,1\\n0,1\\n')\n")
    # the eval reads that dataset and reports accuracy (0.75) via a captured sklearn call
    (repo / "eval.py").write_text(
        "import csv\n"
        "from sklearn.metrics import accuracy_score\n"
        "rows=list(csv.DictReader(open('data.csv')))\n"
        "yt=[int(r['y_true']) for r in rows]; yp=[int(r['y_pred']) for r in rows]\n"
        "print('accuracy=%.4f' % accuracy_score(yt, yp))\n")

    # WITHOUT acquisition: first run fails missing-data → DISCOVERED (the honest baseline)
    base = verify_repo(str(repo), VerifyOptions(deep=True, runner="local", entry="eval.py",
                                                discover=True, acquire_data=False, plan=False))
    assert base["run"]["ran"] is False
    assert base["counts"].get(VD.CONFIRMED, 0) == 0

    # WITH acquisition (paid): 01_download.py runs, writes data.csv, the re-run computes + CONFIRMS
    got = verify_repo(str(repo), VerifyOptions(deep=True, runner="local", entry="eval.py",
                                               discover=True, acquire_data=True, plan=False))
    assert got["run"]["ran"] is True
    accs = [c for c in got["claims"] if c["metric"] == "accuracy"]
    assert accs and any(c["verdict"] == VD.CONFIRMED for c in accs)
