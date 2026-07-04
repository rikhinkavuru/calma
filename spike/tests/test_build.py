"""Make-runnable helpers: entrypoint detection + dependency inference (no network)."""

from runner import build


def test_detect_single_root_script(tmp_path):
    (tmp_path / "iris-svm.py").write_text("print(1)\n")
    (tmp_path / "README.md").write_text("# iris svm\nrun: python svm_iris.py\n")  # README names a missing file
    assert build.detect_entrypoint(str(tmp_path)) == ["iris-svm.py"]


def test_detect_repo_name_match(tmp_path):
    repo = tmp_path / "iris-svm-classification"
    repo.mkdir()
    (repo / "iris-svm.py").write_text("print(1)\n")
    (repo / "helpers.py").write_text("x = 1\n")        # >1 script, so the name match disambiguates
    assert build.detect_entrypoint(str(repo)) == ["iris-svm.py"]


def test_detect_main_guard(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text("if __name__ == '__main__':\n    print('go')\n")
    assert build.detect_entrypoint(str(tmp_path)) == ["b.py"]


def test_detect_ignores_setup_py(tmp_path):
    (tmp_path / "setup.py").write_text("from setuptools import setup\n")
    (tmp_path / "run.py").write_text("print(1)\n")     # known name wins anyway, but setup.py is excluded
    assert build.detect_entrypoint(str(tmp_path)) == ["run.py"]


def test_detect_skips_readme_env_setup_commands(tmp_path):
    # A README routinely shows `python -m venv ...` / `python -m pip ...` (env setup) BEFORE the real run
    # command. Picking the setup module produced `python -m venv` with no target dir and broke the run on
    # real repos (e.g. ml-in-10-lines). Skip setup modules, keep scanning for the actual entrypoint.
    (tmp_path / "iris.py").write_text("print(1)\n")
    (tmp_path / "helpers.py").write_text("x = 1\n")    # >1 script so the README is the disambiguator
    (tmp_path / "README.md").write_text(
        "## setup\npython3 -m venv iris-venv\npython -m pip install -r requirements.txt\n"
        "## run\npython iris.py\n")
    assert build.detect_entrypoint(str(tmp_path)) == ["iris.py"]


def test_detect_readme_subdir_path_preserved(tmp_path):
    # A README `python scripts/run.py` must run scripts/run.py, not a non-existent root run.py. The old code
    # stripped to basename and silently missed the subdir script (fell back to a fabricated eval.py).
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run.py").write_text("print(1)\n")
    (tmp_path / "helpers.py").write_text("x = 1\n")
    (tmp_path / "README.md").write_text("## run\npython scripts/run.py\n")
    assert build.detect_entrypoint(str(tmp_path)) == ["scripts/run.py"]


def test_detect_readme_stale_dash_m_rejected(tmp_path):
    # A README `-m pkg.missing` that no longer resolves must NOT be trusted (it would fail the run); detection
    # falls through to a real signal instead.
    (tmp_path / "only.py").write_text("print(1)\n")
    (tmp_path / "README.md").write_text("run: python -m pkg.gone\n")
    assert build.detect_entrypoint(str(tmp_path)) == ["only.py"]  # single root script, not the stale -m


def test_detect_runnable_package_main(tmp_path):
    # A package-shaped repo (no root script) with code/__main__.py → `python -m code`.
    pkg = tmp_path / "code"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text("if __name__ == '__main__':\n    print('go')\n")
    assert build.detect_entrypoint(str(tmp_path)) == ["-m", "code"]


def test_detect_subdir_driver_script(tmp_path):
    # No root script, no package __main__ — but code/run_eval.py is a __main__-guarded driver that imports a
    # metric lib. Detection reaches into the source subdir and returns the repo-relative path.
    pkg = tmp_path / "code"
    pkg.mkdir()
    (pkg / "utils.py").write_text("import os\nx = 1\n")            # a util (no metric lib, no guard) — skipped
    (pkg / "run_eval.py").write_text(
        "import numpy as np\nif __name__ == '__main__':\n    print(np.mean([1, 2]))\n")
    assert build.detect_entrypoint(str(tmp_path)) == ["code/run_eval.py"]


def test_detect_subdir_driver_prefers_driver_stem(tmp_path):
    # Two metric-importing, __main__-guarded scripts: the driver-ish stem (run_all) beats a plain analysis one.
    pkg = tmp_path / "src"
    pkg.mkdir()
    for name in ("zutils_score.py", "run_all.py"):
        (pkg / name).write_text("import sklearn\nif __name__ == '__main__':\n    pass\n")
    assert build.detect_entrypoint(str(tmp_path)) == ["src/run_all.py"]


def test_detect_none_when_no_signal(tmp_path):
    # A repo with only tests/docs and no driver → None (the pipeline then reports missing-entrypoint honestly
    # rather than fabricating a verdict).
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("import numpy\nif __name__ == '__main__':\n    pass\n")
    (tmp_path / "docs").mkdir()
    assert build.detect_entrypoint(str(tmp_path)) is None


def test_artifact_producer_reverse_map(tmp_path):
    # A committed results.csv + two scripts: run_all.py WRITES it (df.to_csv), quickstart.py only reads a
    # slice. The reverse map must pick the producer of the committed table, not the first runnable file.
    (tmp_path / "results.csv").write_text("model,accuracy\nresnet,0.91\n")
    (tmp_path / "quickstart.py").write_text(
        "import pandas as pd\nif __name__ == '__main__':\n    pd.read_csv('results.csv').head()\n")
    (tmp_path / "run_all.py").write_text(
        "import pandas as pd\nif __name__ == '__main__':\n"
        "    pd.DataFrame({'accuracy': [0.91]}).to_csv('results.csv')\n")
    assert build.artifact_producer(str(tmp_path)) == ["run_all.py"]


def test_artifact_producer_json_dump_under_results_dir(tmp_path):
    # metrics.json under results/ written via json.dump(open(...,"w")); the producer names the path indirectly.
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "metrics.json").write_text('{"accuracy": 0.9}')
    (tmp_path / "evaluate.py").write_text(
        "import json, numpy as np\nif __name__ == '__main__':\n"
        "    json.dump({'accuracy': float(np.mean([0.9]))}, open('results/metrics.json', 'w'))\n")
    assert build.artifact_producer(str(tmp_path)) == ["evaluate.py"]


def test_artifact_producer_none_without_committed_artifact(tmp_path):
    # No committed result file → no reverse map (fail-closed; name heuristics take over).
    (tmp_path / "run.py").write_text("import pandas as pd\npd.DataFrame().to_csv('out.csv')\n")
    assert build.artifact_producer(str(tmp_path)) is None


def test_artifact_producer_ignores_pure_reader(tmp_path):
    # A committed artifact but the only script merely READS it (no write call) → not a producer.
    (tmp_path / "summary.csv").write_text("a,accuracy\nx,0.8\n")
    (tmp_path / "plot.py").write_text("import pandas as pd\npd.read_csv('summary.csv').plot()\n")
    assert build.artifact_producer(str(tmp_path)) is None


def test_detect_entrypoint_prefers_artifact_producer_over_name(tmp_path):
    # Ladder integration: a generic-named train.py exists (would win by _ENTRY_NAMES), but run_all.py is the
    # proven producer of the committed results.csv → the evidence-based pick wins.
    (tmp_path / "results.csv").write_text("model,accuracy\nr,0.9\n")
    (tmp_path / "train.py").write_text("import sklearn\nif __name__ == '__main__':\n    pass\n")
    (tmp_path / "run_all.py").write_text(
        "import pandas as pd\nif __name__ == '__main__':\n"
        "    pd.DataFrame({'accuracy': [0.9]}).to_csv('results.csv')\n")
    assert build.detect_entrypoint(str(tmp_path)) == ["run_all.py"]


def test_detect_entrypoint_readme_still_beats_artifact_producer(tmp_path):
    # An explicit README run-command (human intent) still outranks the reverse map.
    (tmp_path / "results.csv").write_text("model,accuracy\nr,0.9\n")
    (tmp_path / "README.md").write_text("Run it:\n```\npython reproduce.py\n```\n")
    (tmp_path / "reproduce.py").write_text("print(1)\n")
    (tmp_path / "run_all.py").write_text(
        "import pandas as pd\npd.DataFrame().to_csv('results.csv')\n")
    assert build.detect_entrypoint(str(tmp_path)) == ["reproduce.py"]


def test_detect_skips_streamlit_app_prefers_eval(tmp_path):
    # a repo shipping a streamlit demo next to the real eval must pick the eval, not the server (which would
    # hang on .run() and never produced the committed metric).
    (tmp_path / "app.py").write_text("import streamlit as st\nif __name__ == '__main__':\n    st.title('demo')\n")
    (tmp_path / "run_eval.py").write_text("import sklearn\nif __name__ == '__main__':\n    print('acc', 0.9)\n")
    assert build.detect_entrypoint(str(tmp_path)) == ["run_eval.py"]


def test_detect_none_when_only_a_server_script(tmp_path):
    # only a flask app.py, no eval → do NOT return the server (a blocking .run() would hang the sandbox).
    (tmp_path / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\napp.run()\n")
    assert build.detect_entrypoint(str(tmp_path)) is None


def test_era_pin_nongit_and_pinned_passthrough(tmp_path):
    # not a git repo -> no era detected -> packages unchanged (no network call)
    pkgs, era = build.era_pin(["scikit-learn", "numpy==1.24.0", "pandas>=2"], str(tmp_path))
    assert era is None
    assert pkgs == ["scikit-learn", "numpy==1.24.0", "pandas>=2"]
    assert build.repo_commit_date(str(tmp_path)) is None


def test_era_pin_parallel_preserves_order_and_constraints(monkeypatch):
    """The PyPI lookups run concurrently (to cut N×20s of sequential latency) — results must still land in
    input order, constrained specs pass through untouched, and an unresolvable name stays unpinned."""
    monkeypatch.setattr(build, "repo_commit_date", lambda _d: "2021-06-01")
    versions = {"scikit-learn": "1.0", "numpy": "1.21.0", "pandas": "1.3.0", "mystery": None}
    seen = []
    def fake_lookup(name, date, timeout=20):
        seen.append(name)
        return versions.get(name)
    monkeypatch.setattr(build, "_pypi_version_at", fake_lookup)

    pkgs, era = build.era_pin(["scikit-learn", "torch==2.0", "numpy", "mystery", "pandas"], "/repo")
    assert era == "2021-06-01"
    assert pkgs == ["scikit-learn==1.0", "torch==2.0", "numpy==1.21.0", "mystery", "pandas==1.3.0"]
    assert set(seen) == {"scikit-learn", "numpy", "mystery", "pandas"}   # torch was constrained → no lookup


def test_infer_requirements_txt_wins(tmp_path):
    (tmp_path / "requirements.txt").write_text("scikit-learn==1.3.0\nnumpy  # pinned later\n-r other.txt\n\n")
    (tmp_path / "m.py").write_text("import torch\n")    # ignored: declared deps win
    reqs, src = build.infer_requirements(str(tmp_path))
    assert src == "requirements.txt"
    assert "scikit-learn==1.3.0" in reqs and "numpy" in reqs
    assert all(not r.startswith("-") for r in reqs)


def test_infer_from_imports_maps_and_filters(tmp_path):
    (tmp_path / "model.py").write_text(
        "import os, sys, json\n"
        "import numpy as np\n"
        "from sklearn.svm import SVC\n"
        "import cv2\n"
        "from helpers import thing\n"   # local module -> excluded
    )
    (tmp_path / "helpers.py").write_text("thing = 1\n")
    reqs, src = build.infer_requirements(str(tmp_path))
    assert src == "inferred from imports"
    assert "scikit-learn" in reqs           # sklearn -> scikit-learn
    assert "opencv-python-headless" in reqs # cv2 -> opencv-python-headless
    assert "numpy" in reqs
    assert "os" not in reqs and "sys" not in reqs and "json" not in reqs   # stdlib dropped
    assert "helpers" not in reqs                                            # local dropped


def test_detect_python_version_dotfile(tmp_path):
    (tmp_path / ".python-version").write_text("3.11.5\n")
    assert build.detect_python_version(str(tmp_path)) == "3.11"


def test_detect_python_version_runtime_txt(tmp_path):
    (tmp_path / "runtime.txt").write_text("python-3.10.2\n")
    assert build.detect_python_version(str(tmp_path)) == "3.10"


def test_detect_python_version_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.9,<3.12"\n')
    assert build.detect_python_version(str(tmp_path)) == "3.9"


def test_detect_python_version_poetry_caret(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.poetry.dependencies]\npython = "^3.10"\n')
    assert build.detect_python_version(str(tmp_path)) == "3.10"


def test_detect_python_version_setup_py(tmp_path):
    (tmp_path / "setup.py").write_text('setup(python_requires=">=3.8")\n')
    assert build.detect_python_version(str(tmp_path)) == "3.8"


def test_detect_python_version_priority_and_none(tmp_path):
    (tmp_path / ".python-version").write_text("3.12\n")
    (tmp_path / "pyproject.toml").write_text('requires-python = ">=3.8"\n')
    assert build.detect_python_version(str(tmp_path)) == "3.12"   # .python-version wins
    assert build.detect_python_version(str(tmp_path / "nope")) is None


def test_cpu_pip_args_swaps_heavy_wheels():
    assert build.cpu_pip_args("torch") == ["torch", "--index-url", "https://download.pytorch.org/whl/cpu"]
    assert build.cpu_pip_args("tensorflow") == ["tensorflow-cpu"]
    assert build.cpu_pip_args("tensorflow==2.15") == ["tensorflow-cpu"]
    assert build.cpu_pip_args("numpy") == ["numpy"]               # ordinary dep untouched


def test_deps_are_heavy():
    assert build.deps_are_heavy(["numpy", "torch"]) is True
    assert build.deps_are_heavy(["scikit-learn", "pandas"]) is False


def test_classify_failure_taxonomy():
    assert build.classify_failure("RuntimeError: No CUDA GPUs are available")["kind"] == "needs-gpu"
    assert build.classify_failure("...\nKilled")["kind"] == "too-heavy"
    assert build.classify_failure("MemoryError")["kind"] == "too-heavy"
    assert build.classify_failure("urllib HTTPError 403")["kind"] == "needs-network"
    assert build.classify_failure("FileNotFoundError: data/x.csv")["kind"] == "missing-data"
    assert build.classify_failure("ModuleNotFoundError: No module named 'x'")["kind"] == "missing-dep"
    assert build.classify_failure("\n[timeout]")["kind"] == "too-slow"
    assert build.classify_failure("some random traceback")["kind"] == "errored"
    # the interpreter can't open the entrypoint script itself → missing-ENTRYPOINT, not missing-data, even
    # though the same line contains "No such file or directory" (order in the taxonomy must screen it first).
    assert (build.classify_failure("python: can't open file '/work/eval.py': [Errno 2] No such file or "
                                   "directory")["kind"] == "missing-entrypoint")


def test_infer_excludes_local_modules_in_subdirs(tmp_path):
    """The DRIFT bug: local modules living in subdirs (imported as top-level on sys.path) must NOT be
    treated as PyPI packages — `pip install model` aborted the whole env build."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "model.py").write_text("class M: pass\n")
    (src / "dataset.py").write_text("data = []\n")
    (tmp_path / "embed").mkdir()
    (tmp_path / "embed" / "__init__.py").write_text("")
    (src / "run.py").write_text("import model\nimport dataset\nimport embed\nimport torch\nimport numpy\n")
    reqs, src_note = build.infer_requirements(str(tmp_path))
    assert "model" not in reqs and "dataset" not in reqs and "embed" not in reqs   # local, excluded
    assert "torch" in reqs and "numpy" in reqs                                      # real deps kept


def test_detect_notebook_when_no_py_entry(tmp_path):
    # a repo whose only runnable artifact is a notebook -> nb: routing (not `python file.ipynb`).
    (tmp_path / "analysis.ipynb").write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}')
    assert build.detect_entrypoint(str(tmp_path)) == ["nb:analysis.ipynb"]


def test_py_entry_beats_notebook(tmp_path):
    # a real .py eval outranks a notebook sitting beside it.
    (tmp_path / "explore.ipynb").write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}')
    (tmp_path / "run.py").write_text("import sklearn\nif __name__ == '__main__':\n    pass\n")
    assert build.detect_entrypoint(str(tmp_path)) == ["run.py"]
