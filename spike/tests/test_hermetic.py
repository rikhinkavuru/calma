"""Features 14 / 20 — the deep determinism tiers. These are ESCALATIONS (effort ≫ marginal reach), so the tests
pin the cheap, always-available sub-pieces (flake synthesis shape, the shim determinism env, uv hash-pinning)
and the GRACEFUL-SKIP contract for the heavy binaries — all FCR-safe by construction (they change only the
environment, never the diff or the verdict)."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from core import determinism as DET  # noqa: E402
from runner import nix_runner as NIX  # noqa: E402
from runner import rr_runner as RR  # noqa: E402


def test_enforced_env_shim_adds_source_date_epoch():
    assert "SOURCE_DATE_EPOCH" not in DET.enforced_env()
    shim = DET.enforced_env(shim=True)
    assert shim["SOURCE_DATE_EPOCH"] and shim["PYTHONHASHSEED"] == "0" and shim["TZ"] == "UTC"


def test_shim_env_merges_and_single_threads():
    env = RR.shim_env({"CALMA_CAPTURE_OUT": "/x"})
    assert env["CALMA_CAPTURE_OUT"] == "/x"                 # base preserved
    assert env["SOURCE_DATE_EPOCH"] and env["OMP_NUM_THREADS"] == "1" and env["MKL_NUM_THREADS"] == "1"


def test_synth_flake_shape():
    flake = NIX.synth_flake(python_version="3.11", pip_install=["numpy==1.26", "scikit-learn"],
                            system_deps=["gfortran"])
    assert "python311" in flake and "pkgs.uv" in flake and "gfortran" in flake
    assert "uv pip install --system numpy==1.26 scikit-learn" in flake
    assert flake.count("{") == flake.count("}")             # balanced braces — a plausible flake


def test_synth_flake_defaults_python3():
    flake = NIX.synth_flake()
    assert "pkgs.python3 " in flake and "shellHook = ''true''" in flake


def test_nix_run_is_graceful_without_nix():
    if NIX.nix_available():
        return                                              # env has nix — skip the absent-path assertion
    res = NIX.run_nix("/tmp/repo", ["eval.py"])
    assert res["ran_ok"] is False and res["hermetic_tier"] == "nix-unavailable"
    assert res["runs"] == [] and "n_calls" in res           # runner-agnostic shape preserved


def test_rr_run_is_graceful_without_rr():
    res = RR.run_rr("/tmp/repo", ["eval.py"])
    # whether rr is present or not, we NEVER claim replay_proven unless the perf-counter tier is provisioned
    assert res["replay_proven"] is False and "reason" in res


def test_uv_hash_pin_is_graceful():
    import shutil
    locked, ok = NIX.uv_hash_pin(["numpy"])
    if not shutil.which("uv"):
        assert locked == ["numpy"] and ok is False
    else:
        assert isinstance(locked, list)                     # uv present — returns a (possibly hashed) list
    assert NIX.uv_hash_pin([]) == ([], False)               # empty in → no-op
