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
