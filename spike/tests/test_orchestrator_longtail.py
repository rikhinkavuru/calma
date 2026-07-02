"""Phase 5 — long-tail tools: R/Julia/shell interpreters (run_lang) with honest degradation + capture
propagation through a shell wrapper, and monorepo sub-project selection."""
import os
import shutil
import sys

import pytest

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from orchestrator import assess as A  # noqa: E402
from orchestrator import tools_exec as X  # noqa: E402


@pytest.mark.skipif(not shutil.which("bash"), reason="bash not available")
def test_run_lang_shell_propagates_capture(tmp_path):
    # a shell wrapper that shells out to python — the python child inherits the capture env and arms the shim,
    # so a metric call inside it is recorded even though the entrypoint is a .sh (the polyglot shape).
    (tmp_path / "compute.py").write_text(
        "from sklearn.metrics import accuracy_score\nprint(accuracy_score([0,1,1,0],[0,1,1,1]))\n")
    (tmp_path / "run.sh").write_text("#!/bin/bash\n%s compute.py\n" % sys.executable)
    res = X.run_lang(str(tmp_path), "shell", ["run.sh"], k=1)
    assert res["ran_ok"] is True
    assert res["n_calls"] and res["n_calls"][0] >= 1


def test_run_lang_degrades_without_interpreter(tmp_path):
    (tmp_path / "x.R").write_text('print("hi")\n')
    res = X.run_lang(str(tmp_path), "r", ["x.R"], k=1)
    if not X.lang_available("r"):
        assert res["ran_ok"] is False
        assert "interpreter" in res["meta"][0]["stderr_tail"]


def test_run_lang_unknown_lang(tmp_path):
    res = X.run_lang(str(tmp_path), "cobol", ["x.cob"], k=1)
    assert res["ran_ok"] is False


def test_select_subproject_picks_strongest(tmp_path):
    # projA: manifest but a weak (signal-less) script; projC: manifest + known entrypoint name + README → wins
    a = tmp_path / "projA"
    a.mkdir()
    (a / "requirements.txt").write_text("numpy\n")
    (a / "helper.py").write_text("x = 1\n")
    b = tmp_path / "projB"      # no manifest → ignored
    b.mkdir()
    (b / "thing.py").write_text("if __name__=='__main__':\n    print(1)\n")
    c = tmp_path / "projC"
    c.mkdir()
    (c / "requirements.txt").write_text("scikit-learn\n")
    (c / "eval.py").write_text("import sklearn\nif __name__=='__main__':\n    print(1)\n")
    (c / "README.md").write_text("Run `python eval.py`.\n")
    assert A.select_subproject(str(tmp_path)) == "projC"


def test_select_subproject_none_when_flat(tmp_path):
    (tmp_path / "eval.py").write_text("print(1)\n")
    assert A.select_subproject(str(tmp_path)) is None
