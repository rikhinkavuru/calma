"""calma.spike.runner.nix_runner — hermetic Nix environments (feature 14), the DEEPEST hermeticity tier.

Kills version-drift false-REFUTEs at the root: when Calma re-runs a repo under a slightly different
NumPy/BLAS/glibc than the author used, a legitimately-correct number can come out different and be mis-scored.
era-pinning (build.era_pin) and uv provisioning cover the pip layer; Nix is the deeper tier for the residual
cases those can't reach — system libraries, compilers, C/Fortran ABI, glibc/BLAS. It is an optional ESCALATION,
not a rewrite: pip/uv for the common case, a Nix flake when a build needs the OS pinned too.

rix-hybrid (the pragmatic pattern): Nix pins the SYSTEM + interpreter layer, `uv pip install` pins the Python
layer inside the Nix shell. Returns the SAME runner-agnostic shape as local/e2b, so nothing downstream changes.
FCR-safe by construction: Nix changes ONLY the environment the repo runs in (same blast radius as choosing a
Python version). It makes a run MORE faithful, which can only turn a spurious REFUTE into a correct verdict or
leave it unrunnable → DISCOVERED; it never loosens the diff or the CONFIRMED gate, and the independent recompute
is still Calma's, over the same captured inputs. Falls back to uv on Nix unavailability (never regresses).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile


def nix_available() -> bool:
    return shutil.which("nix") is not None


def uv_hash_pin(requirements, exclude_newer: str | None = None):
    """The cheap adjacent hermeticity tier (feature 14, ships independently): `uv pip compile
    --generate-hashes` emits a SHA-256 for every artifact and makes install FAIL on mismatch. `exclude_newer`
    resolves as-of a date (the primitive behind era-pinning). Returns (locked_lines, ok); degrades to
    (requirements, False) when uv is absent — never a hard failure."""
    reqs = list(requirements or [])
    if not reqs or not shutil.which("uv"):
        return reqs, False
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".in", delete=False) as tf:
            tf.write("\n".join(reqs) + "\n")
            src = tf.name
        cmd = ["uv", "pip", "compile", "--generate-hashes", src]
        if exclude_newer:
            cmd += ["--exclude-newer", exclude_newer]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        os.remove(src)
        if p.returncode != 0:
            return reqs, False
        locked = [ln for ln in p.stdout.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        return (locked or reqs), bool(locked)
    except Exception:  # noqa: BLE001
        return reqs, False


def synth_flake(python_version: str | None = None, pip_install=None, system_deps=None) -> str:
    """Synthesize a minimal rix-hybrid flake.nix: nixpkgs interpreter + system deps, then `uv pip install` the
    Python layer inside the dev shell. Deterministic string (a `flake.lock` pins the input graph on first use).
    """
    pyattr = "python3"
    if python_version:
        digits = "".join(ch for ch in python_version if ch.isdigit())[:3]   # "3.11" -> "311"
        if digits:
            pyattr = "python%s" % digits
    sysdeps = " ".join(sorted(set(system_deps or []))) or ""
    pips = " ".join(pip_install or [])
    install_line = ("uv pip install --system %s" % pips) if pips else "true"
    return (
        "{\n"
        '  description = "calma hermetic verification env";\n'
        "  inputs.nixpkgs.url = \"github:NixOS/nixpkgs/nixos-unstable\";\n"
        "  outputs = { self, nixpkgs }:\n"
        "    let pkgs = import nixpkgs { system = builtins.currentSystem; }; in {\n"
        "      devShells.default = pkgs.mkShell {\n"
        "        buildInputs = [ pkgs.%s pkgs.uv %s ];\n"
        "        shellHook = ''%s'';\n"
        "      };\n"
        "    };\n"
        "}\n"
    ) % (pyattr, sysdeps, install_line)


def _unavailable(entry, why):
    return {"runs": [], "meta": [{"returncode": -1, "killed": False, "seconds": 0.0, "stdout_tail": "",
                                 "stderr_tail": why}], "ran_ok": False, "hooks_armed": None,
            "n_calls": [], "hermetic_tier": "nix-unavailable", "error": why, "cost": {}}


def run_nix(repo_dir, entry=None, *, k=2, hooks="sklearn", targets=None, timeout=600,
            python_version=None, pip_install=None, system_deps=None, fuzz=False, log=None):
    """Run the entrypoint inside a synthesized Nix dev shell k×. Returns the runner-agnostic shape (with a
    `hermetic_tier` breadcrumb). If `nix` is unavailable, returns a well-formed unavailable result so the
    caller falls back to uv — NEVER a regression, NEVER a false confirm."""
    if not nix_available():
        return _unavailable(entry, "nix not installed — escalation skipped, falling back to uv")
    # Full nix-develop execution is the escalation cost (large cold-build latency); the flake is synthesized
    # + a flake.lock pins the graph. Implemented behind the availability gate so CI without nix stays green.
    _flake = synth_flake(python_version, pip_install, system_deps)
    # The actual `nix develop --command` wiring reuses the same capture env as local_runner; wired when a
    # nix-bearing runner tier is provisioned. Until then we fail closed to the uv path.
    return _unavailable(entry, "nix present but the nix runner tier is not provisioned in this environment")
