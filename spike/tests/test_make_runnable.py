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
