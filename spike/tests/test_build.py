"""Make-runnable helpers: entrypoint detection + dependency inference (no network)."""
import os

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
