"""Make-runnable env-build helpers: dedup the pip list, relax pins on a resolution failure, and parse the
Python a resolver demands so a version conflict REPAIRS (reprovision + retry) instead of dead-ending."""
from runner import build


def test_dedup_pip_prefers_pinned_over_bare():
    # the exact shape from the ebv-ms log: declared pins echoed alongside bare names -> installed twice.
    raw = ["numpy==2.4.6", "scipy==1.18.0", "pandas==3.0.3", "biopython==1.87", "matplotlib==3.11.0",
           "numpy", "scipy", "pandas", "biopython", "matplotlib"]
    assert build.dedup_pip(raw) == [
        "numpy==2.4.6", "scipy==1.18.0", "pandas==3.0.3", "biopython==1.87", "matplotlib==3.11.0"]


def test_dedup_pip_order_stable_upgrade_and_edges():
    assert build.dedup_pip(["b", "a==1", "a", "b>=2"]) == ["b>=2", "a==1"]   # bare 'b' upgraded to 'b>=2'
    assert build.dedup_pip(["torch", "torch", "numpy==1"]) == ["torch", "numpy==1"]
    assert build.dedup_pip([]) == []
    assert build.dedup_pip(None) is None


def test_pkg_base_normalizes():
    assert build.pkg_base("NumPy==2.4.6") == "numpy"
    assert build.pkg_base("scikit_learn>=1.0") == "scikit-learn"
    assert build.pkg_base("torch[cuda]") == "torch"
    assert build.pkg_base("pkg @ git+https://x") == "pkg"
    assert build.pkg_base("--index-url") == ""


def test_relax_pins_drops_versions_keeps_urls_and_flags():
    assert build.relax_pins(["numpy==2.4.6", "scipy>=1.1", "pandas"]) == ["numpy", "scipy", "pandas"]
    keep = ["pkg @ git+https://x", "--index-url", "torch"]
    assert build.relax_pins(keep) == keep


def test_required_python_from_error_parses_the_uv_conflict():
    err = ("Because the current Python version (3.10.20) does not satisfy Python>=3.11 and "
           "numpy==2.4.6 depends on Python>=3.11, we can conclude that numpy==2.4.6 cannot be used.")
    assert build.required_python_from_error(err) == "3.11"
    assert build.required_python_from_error("some unrelated error") is None
    assert build.required_python_from_error("needs Python>=3.9 ... also Python >= 3.12") == "3.12"


# ── Slice 3: ground the run from the repo's CI workflow (the strongest 'how to run this' source) ───────────────
def _write_ci(tmp_path, body):
    (tmp_path / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(body)


def test_ci_workflow_signals_extracts_entry_python_deps_apt(tmp_path):
    (tmp_path / "train.py").write_text("print(1)\n")
    _write_ci(tmp_path,
              "jobs:\n  run:\n    steps:\n"
              "      - uses: actions/setup-python@v5\n"
              "        with:\n          python-version: '3.11'\n"
              "      - run: sudo apt-get install -y foldseek hmmer\n"
              "      - run: pip install numpy scipy\n"
              "      - run: python train.py --epochs 5\n")
    sig = build.ci_workflow_signals(str(tmp_path))
    assert sig["python"] == "3.11"
    assert ["train.py"] in sig["entry"]
    assert "numpy" in sig["deps"] and "scipy" in sig["deps"]
    assert "foldseek" in sig["apt"] and "hmmer" in sig["apt"]


def test_ci_signals_ignore_a_step_naming_a_missing_script(tmp_path):
    _write_ci(tmp_path, "steps:\n  - run: python ghost.py\n")     # ghost.py doesn't exist -> no misleading entry
    assert build.ci_workflow_signals(str(tmp_path))["entry"] == []


def test_detect_python_version_falls_back_to_ci(tmp_path):
    _write_ci(tmp_path, "steps:\n  - uses: actions/setup-python@v5\n    with:\n      python-version: '3.12'\n")
    assert build.detect_python_version(str(tmp_path)) == "3.12"


def test_detect_entrypoint_uses_ci_over_filename_guessing(tmp_path):
    (tmp_path / "a.py").write_text("print(1)\n")
    (tmp_path / "b.py").write_text("print(2)\n")        # two indistinguishable scripts -> guessing is ambiguous
    _write_ci(tmp_path, "steps:\n  - run: python b.py\n")
    assert build.detect_entrypoint(str(tmp_path)) == ["b.py"]
