"""Phase 3 — the execute tools. Pure-logic + locally-runnable tools are fully exercised; optional-backend
tools (papermill A1, micromamba B2) are checked for honest degradation and gated e2e. Edge cases A1/A2/A3/
B1/B2/C1/C2 + the cheap probe gate."""
import os
import shutil
import sys

import pytest

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from orchestrator import tools_exec as X  # noqa: E402
from orchestrator.assess import assess  # noqa: E402


# ── A2: add_argv / set_env ────────────────────────────────────────────────────────────────────────────────────
def test_add_argv_validates_path_args(tmp_path):
    (tmp_path / "here.csv").write_text("a\n")
    entry = X.add_argv(["eval.py"], ["--split", "test", "here.csv", "missing.csv", "../escape.csv"], str(tmp_path))
    assert entry == ["eval.py", "--split", "test", "here.csv"]   # missing + traversal path args dropped


def test_set_env_validates():
    assert X.set_env({}, "FOO=bar") == {"FOO": "bar"}
    assert X.set_env({"A": "1"}, {"B": "2", "bad key": "x"}) == {"A": "1", "B": "2"}


# ── B1: install_declared ──────────────────────────────────────────────────────────────────────────────────────
def test_install_declared_strictness(tmp_path):
    (tmp_path / "requirements.txt").write_text("numpy\nscikit-learn\n")
    plan = X.install_declared(assess(str(tmp_path)))
    assert plan["strict"] is True and "numpy" in plan["specs"]

    (tmp_path / "requirements.txt").unlink()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\ndependencies=['numpy']\n")
    plan = X.install_declared(assess(str(tmp_path)))
    assert plan["strict"] is False and "numpy" in plan["specs"]


# ── C1: interpreter-aware era pinning ─────────────────────────────────────────────────────────────────────────
def test_pyver_satisfies():
    assert X._pyver_satisfies(">=3.8", "3.10")
    assert X._pyver_satisfies(">=3.8,<3.12", "3.10")
    assert not X._pyver_satisfies(">=3.11", "3.9")
    assert not X._pyver_satisfies("<3.9", "3.10")
    assert X._pyver_satisfies("", "3.10")                 # unknown → compatible (never drop spuriously)


def test_era_pin_compat_relaxes_incompatible(tmp_path):
    # a pre-pinned spec that the interpreter can't support → relaxed to a bare name (let pip resolve)
    specs, _era, notes = X.era_pin_compat(
        ["numpy==1.26.0"], str(tmp_path), py_version="3.8",
        requires_python_fn=lambda n, v: ">=3.9")
    assert specs == ["numpy"]
    assert notes and "relaxed numpy" in notes[0]


def test_era_pin_compat_keeps_compatible(tmp_path):
    specs, _era, notes = X.era_pin_compat(
        ["numpy==1.24.0"], str(tmp_path), py_version="3.10",
        requires_python_fn=lambda n, v: ">=3.8")
    assert specs == ["numpy==1.24.0"] and not notes


# ── C2: rescan_outputs ────────────────────────────────────────────────────────────────────────────────────────
def test_rescan_outputs_finds_fresh_predictions(tmp_path):
    before = X.snapshot_outputs(str(tmp_path))
    (tmp_path / "predictions.csv").write_text("y_true,y_pred\n1,1\n0,0\n")
    (tmp_path / "notes.json").write_text("{}")
    changed = X.rescan_outputs(str(tmp_path), before)
    assert "predictions.csv" in changed
    assert changed[0] == "predictions.csv"               # prediction-shaped name ranked first


# ── probe gate (A2/A4, EnvBench static-import metric) ─────────────────────────────────────────────────────────
def test_probe_run_detects_missing_import(tmp_path):
    (tmp_path / "eval.py").write_text("import definitely_missing_pkg_xyz\nprint(1)\n")
    res = X.probe_run(str(tmp_path), ["eval.py"], python=sys.executable)
    assert res["ok"] is False and "definitely_missing_pkg_xyz" in res["missing"]


def test_probe_run_clean_entry(tmp_path):
    (tmp_path / "eval.py").write_text("import os, json\nprint(1)\n")
    res = X.probe_run(str(tmp_path), ["eval.py"], python=sys.executable)
    assert res["ok"] is True and res["missing"] == []


def test_probe_run_syntax_error(tmp_path):
    (tmp_path / "eval.py").write_text("def broken(:\n    pass\n")
    res = X.probe_run(str(tmp_path), ["eval.py"], python=sys.executable)
    assert res["ok"] is False and "syntax" in res["error"]


# ── A3: run_make ──────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not shutil.which("make"), reason="make not available")
def test_run_make_runs_target_with_capture(tmp_path):
    (tmp_path / "eval.py").write_text(
        "from sklearn.metrics import accuracy_score\n"
        "print('accuracy', accuracy_score([0,1,1,0],[0,1,1,1]))\n")
    # bake the venv interpreter into the recipe so `make` runs the python that has sklearn (a bare `python`
    # may be absent / the wrong interpreter); run_make only sets the capture env, it doesn't pick python.
    (tmp_path / "Makefile").write_text("run:\n\t%s eval.py\n" % sys.executable)
    res = X.run_make(str(tmp_path), "run", k=1)
    assert res["ran_ok"] is True
    # capture armed for the recipe's python child → the sklearn accuracy call was recorded
    assert res["n_calls"] and res["n_calls"][0] >= 1


def test_run_make_rejects_unsafe_target(tmp_path):
    res = X.run_make(str(tmp_path), "run; rm -rf /", k=1)
    assert res["ran_ok"] is False
    assert "unsafe" in res["meta"][0]["stderr_tail"]


# ── A1: run_notebook (degrades honestly; e2e gated) ───────────────────────────────────────────────────────────
def test_run_notebook_degrades_without_backend(tmp_path):
    (tmp_path / "nb.ipynb").write_text('{"cells":[],"metadata":{},"nbformat":4,"nbformat_minor":5}')
    res = X.run_notebook(str(tmp_path), "nb.ipynb", k=1)
    if not X.notebook_available():
        assert res["ran_ok"] is False
        assert "unavailable" in res["meta"][0]["stderr_tail"]


def test_run_notebook_missing_file(tmp_path):
    res = X.run_notebook(str(tmp_path), "nope.ipynb", k=1)
    assert res["ran_ok"] is False and "not found" in res["meta"][0]["stderr_tail"]


def test_run_notebook_e2e_captures(tmp_path):
    pytest.importorskip("nbclient")
    pytest.importorskip("nbformat")
    import nbformat
    from nbformat.v4 import new_code_cell, new_notebook
    nb = new_notebook(cells=[new_code_cell(
        "from sklearn.metrics import accuracy_score\n"
        "acc = accuracy_score([0,1,1,0],[0,1,1,1])\nprint('accuracy', acc)\n")])
    nbformat.write(nb, str(tmp_path / "run.ipynb"))
    res = X.run_notebook(str(tmp_path), "run.ipynb", k=1, python=sys.executable)
    assert res["ran_ok"] is True
    assert res["n_calls"] and res["n_calls"][0] >= 1      # kernel-armed capture recorded the sklearn call


# ── B2: build_conda (degrades honestly) ───────────────────────────────────────────────────────────────────────
def test_build_conda_no_env_file(tmp_path):
    res = X.build_conda(str(tmp_path))
    assert res["ok"] is False and "no environment.yml" in res["note"]


def test_build_conda_degrades_without_micromamba(tmp_path):
    (tmp_path / "environment.yml").write_text("name: e\ndependencies:\n  - python=3.10\n  - numpy\n")
    res = X.build_conda(str(tmp_path))
    if not X.micromamba_bin():
        assert res["ok"] is False and "micromamba" in res["note"]
