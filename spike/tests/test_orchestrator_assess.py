"""Phase 1 — static assessment tools + assess() → RepoProfile. Each tool is checked on a synthesized repo
shape (package, src-layout, poetry, conda, notebook, monorepo, includes, editable-self), and assess()
assembles a correct deterministic profile with no LLM. Covers audit edge cases A1/A3/B1/B3/B4/B5/C2."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from orchestrator import assess as A  # noqa: E402
from orchestrator import tools_static as S  # noqa: E402


# ── A4: ranked entrypoints ────────────────────────────────────────────────────────────────────────────────────
def test_find_entrypoints_ranks_readme_pick_first(tmp_path):
    (tmp_path / "run_benchmark.py").write_text("import sklearn\nif __name__=='__main__':\n    print(1)\n")
    (tmp_path / "helper.py").write_text("x=1\n")
    (tmp_path / "README.md").write_text("Run: `python run_benchmark.py`\n")
    cands = S.find_entrypoints(str(tmp_path))
    assert cands and cands[0].argv == ["run_benchmark.py"]
    assert cands[0].confidence >= 0.85
    assert cands[0].kind == "script"


def test_find_entrypoints_readme_pick_keeps_safe_args(tmp_path):
    # the orchestrate path (find_entrypoints) must keep a README run-command's args + still fire the
    # "README run command" signal when the command carries args (regression guard: it used to require
    # exact equality readme == [script], which broke once _readme_run_command started preserving args).
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "a.yaml").write_text("x: 1\n")
    (tmp_path / "reproduce.py").write_text("import sklearn\nif __name__=='__main__':\n    print(1)\n")
    (tmp_path / "helper.py").write_text("x=1\n")
    (tmp_path / "README.md").write_text("Run: `python reproduce.py --config configs/a.yaml`\n")
    cands = S.find_entrypoints(str(tmp_path))
    top = cands[0]
    assert top.argv == ["reproduce.py", "--config", "configs/a.yaml"]   # args preserved
    assert top.confidence >= 0.85 and "README run command" in top.signals


def test_find_entrypoints_package_and_subdir(tmp_path):
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text("import numpy\nprint(1)\n")
    cands = S.find_entrypoints(str(tmp_path))
    argvs = [c.argv for c in cands]
    assert ["-m", "mypkg"] in argvs
    assert any(c.kind == "module" for c in cands)


# ── A1: notebooks ─────────────────────────────────────────────────────────────────────────────────────────────
def test_find_notebooks(tmp_path):
    (tmp_path / "analysis.ipynb").write_text("{}")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "explore.ipynb").write_text("{}")
    nbs = S.find_notebooks(str(tmp_path))
    assert set(nbs) == {"analysis.ipynb", os.path.join("sub", "explore.ipynb")}


# ── A3: make / language ───────────────────────────────────────────────────────────────────────────────────────
def test_find_make_targets(tmp_path):
    (tmp_path / "Makefile").write_text("all: run\n\nrun:\n\tpython eval.py\n\ntest:\n\tpytest\n")
    assert S.find_make_targets(str(tmp_path)) == ["all", "run", "test"]


def test_detect_language(tmp_path):
    (tmp_path / "a.py").write_text("x=1")
    (tmp_path / "b.py").write_text("y=2")
    assert S.detect_language(str(tmp_path)) == "python"
    (tmp_path / "s.R").write_text("x <- 1")
    (tmp_path / "t.R").write_text("y <- 2")
    assert S.detect_language(str(tmp_path)) == "mixed"


# ── B1: package manager + declared deps ───────────────────────────────────────────────────────────────────────
def test_detect_pkg_manager_variants(tmp_path):
    (tmp_path / "requirements.txt").write_text("numpy\n")
    assert S.detect_pkg_manager(str(tmp_path)) == "requirements"
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\ndependencies=['numpy']\n")
    assert S.detect_pkg_manager(str(tmp_path)) == "pyproject"
    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname='x'\n[tool.poetry.dependencies]\npython='^3.10'\nnumpy='^1.0'\n")
    assert S.detect_pkg_manager(str(tmp_path)) == "poetry"


def test_read_declared_deps_pep621_and_poetry(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='x'\ndependencies=['numpy>=1.20', 'scikit-learn', 'pandas']\n")
    deps = S.read_declared_deps(str(tmp_path))
    assert "numpy>=1.20" in deps and "scikit-learn" in deps and "pandas" in deps

    (tmp_path / "pyproject.toml").write_text(
        "[tool.poetry]\nname='x'\n[tool.poetry.dependencies]\npython='^3.10'\nnumpy='^1.24'\nrequests='*'\n")
    deps = S.read_declared_deps(str(tmp_path))
    assert "numpy" in deps and "requests" in deps and "python" not in deps


def test_read_declared_deps_conda(tmp_path):
    (tmp_path / "environment.yml").write_text(
        "name: env\nchannels:\n  - conda-forge\ndependencies:\n  - python=3.10\n  - numpy=1.24\n"
        "  - pip\n  - pip:\n    - scikit-learn==1.3.0\n")
    deps = S.read_declared_deps(str(tmp_path))
    assert "numpy==1.24" in deps
    assert "scikit-learn==1.3.0" in deps
    assert not any(d.startswith("python") for d in deps)


# ── B3: requirements includes / editable-self ────────────────────────────────────────────────────────────────
def test_resolve_requirements_includes(tmp_path):
    (tmp_path / "requirements.txt").write_text("-r base.txt\n-c constraints.txt\nrequests\n-e .\n")
    (tmp_path / "base.txt").write_text("numpy\nscipy\n")
    (tmp_path / "constraints.txt").write_text("numpy==1.24.0\n")
    res = S.resolve_requirements_includes(str(tmp_path))
    assert set(res["specs"]) == {"numpy", "scipy", "requests"}
    assert res["self_install"] is True
    assert "numpy==1.24.0" in res["constraints"]


def test_resolve_requirements_cycle_safe(tmp_path):
    (tmp_path / "requirements.txt").write_text("-r a.txt\n")
    (tmp_path / "a.txt").write_text("-r requirements.txt\nnumpy\n")   # cycle
    res = S.resolve_requirements_includes(str(tmp_path))
    assert res["specs"] == ["numpy"]


# ── B4: import → distribution ─────────────────────────────────────────────────────────────────────────────────
def test_import_to_dist():
    assert S.import_to_dist("sklearn") == "scikit-learn"   # metadata or alias table
    assert S.import_to_dist("cv2") == "opencv-python-headless"
    assert S.import_to_dist("numpy") == "numpy"            # identity


# ── B5: entry-seeded transitive imports ──────────────────────────────────────────────────────────────────────
def test_entry_seeded_imports_follows_local_collects_third_party(tmp_path):
    (tmp_path / "eval.py").write_text("import numpy\nimport helper\nprint(1)\n")
    (tmp_path / "helper.py").write_text("import sklearn\n")     # local module → followed
    got = S.entry_seeded_imports(str(tmp_path), ["eval.py"])
    assert got == ["numpy", "scikit-learn"]                     # sklearn mapped via B4; helper NOT included


def test_entry_seeded_imports_module_entry(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text("import pandas\n")
    assert S.entry_seeded_imports(str(tmp_path), ["-m", "pkg"]) == ["pandas"]


# ── C2: data references ───────────────────────────────────────────────────────────────────────────────────────
def test_find_data_refs(tmp_path):
    (tmp_path / "eval.py").write_text(
        "import pandas as pd\n"
        "df = pd.read_csv('data/train.csv')\n"          # missing → a need
        "present = pd.read_csv('here.csv')\n"           # present → not a need
        "remote = pd.read_csv('https://x/y.csv')\n")    # url → ignored
    (tmp_path / "here.csv").write_text("a,b\n1,2\n")
    refs = S.find_data_refs(str(tmp_path))
    assert "data/train.csv" in refs
    assert "here.csv" not in refs
    assert not any(r.startswith("http") for r in refs)


# ── fingerprint ───────────────────────────────────────────────────────────────────────────────────────────────
def test_repo_fingerprint_deterministic_and_sensitive(tmp_path):
    (tmp_path / "a.py").write_text("x=1\n")
    fp1 = S.repo_fingerprint(str(tmp_path))
    fp2 = S.repo_fingerprint(str(tmp_path))
    assert fp1 == fp2 and len(fp1) == 32
    (tmp_path / "b.py").write_text("y=2\n")            # new file changes size/tree
    assert S.repo_fingerprint(str(tmp_path)) != fp1


# ── assess() integration ──────────────────────────────────────────────────────────────────────────────────────
def test_assess_root_script_ml_repo(tmp_path):
    (tmp_path / "eval.py").write_text(
        "import sklearn\nfrom sklearn.metrics import accuracy_score\n"
        "if __name__=='__main__':\n    print('accuracy', 0.9)\n")
    (tmp_path / "requirements.txt").write_text("scikit-learn\nnumpy\n")
    (tmp_path / "README.md").write_text("Run `python eval.py`.\n")
    p = A.assess(str(tmp_path))
    assert p.language == "python"
    assert p.layout == "root-script"
    assert p.pkg_manager == "requirements"
    assert p.entry_candidates[0].argv == ["eval.py"]
    assert "scikit-learn" in p.declared_deps and "numpy" in p.declared_deps
    assert p.domain == "ml"
    assert p.fingerprint


def test_assess_notebook_layout(tmp_path):
    (tmp_path / "analysis.ipynb").write_text("{}")
    p = A.assess(str(tmp_path))
    assert p.layout == "notebook"
    assert p.notebooks == ["analysis.ipynb"]


def test_assess_src_layout(tmp_path):
    src = tmp_path / "src" / "proj"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "run.py").write_text("import numpy\nif __name__=='__main__':\n    print(1)\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='proj'\ndependencies=['numpy']\n")
    p = A.assess(str(tmp_path))
    assert p.layout == "src-layout"
    assert p.pkg_manager == "pyproject"


def test_report_lines_are_human_readable(tmp_path):
    (tmp_path / "eval.py").write_text("import sklearn\nif __name__=='__main__':\n    print(1)\n")
    (tmp_path / "requirements.txt").write_text("scikit-learn\n")
    p = A.assess(str(tmp_path))
    lines = A.report_lines(p)
    assert any("Assessment:" in ln for ln in lines)
    assert any("entrypoint" in ln.lower() for ln in lines)
