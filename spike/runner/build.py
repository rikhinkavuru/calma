"""build — the 'make a repo runnable' step (rebuild guide §5: repo2docker → Repo2Run). The spike ships a
deliberately minimal version: resolve the source (a local path or a shallow git clone at a pinned commit)
and, for the local runner, build a per-repo venv and pip-install declared deps. The real agentic
env-synthesis (Repo2Run; cache the synthesized env per repo — the reproduction flywheel) is the next layer.
"""
from __future__ import annotations

import os
import subprocess
import sys


def ensure_repo(spec, workdir):
    """Return the local directory for this repo. kind=local -> the given path; kind=git -> shallow clone
    at the pinned commit. Returns (repo_dir, note)."""
    src = spec.get("source", {})
    kind = src.get("kind", "local")
    if kind == "local":
        path = src["path"]
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
        return path, "local"
    if kind == "git":
        dest = os.path.join(workdir, spec["name"])
        if os.path.isdir(os.path.join(dest, ".git")):
            return dest, "cached clone"
        os.makedirs(workdir, exist_ok=True)
        url, commit = src["url"], src.get("commit")
        subprocess.run(["git", "clone", "--quiet", "--depth", "1", url, dest], check=True, timeout=300)
        if commit:
            # fetch the specific commit shallowly, then check it out (pinned reproducibility)
            subprocess.run(["git", "-C", dest, "fetch", "--quiet", "--depth", "1", "origin", commit],
                           check=False, timeout=300)
            subprocess.run(["git", "-C", dest, "checkout", "--quiet", commit], check=False, timeout=120)
        subdir = src.get("subdir")
        return (os.path.join(dest, subdir) if subdir else dest), "cloned"
    raise ValueError("unknown source kind %r" % kind)


def ensure_venv(name, pip_install, venvs_dir, base_python=None):
    """Create (once) a per-repo venv and install deps. Returns the venv's python path. If no deps are
    declared, returns the base python (the harness venv, which already has numpy/sklearn for fixtures)."""
    base_python = base_python or sys.executable
    if not pip_install:
        return base_python, "harness python"
    venv_dir = os.path.join(venvs_dir, name)
    py = os.path.join(venv_dir, "bin", "python")
    if os.path.isfile(py):
        return py, "cached venv"
    os.makedirs(venvs_dir, exist_ok=True)
    subprocess.run([base_python, "-m", "venv", venv_dir], check=True, timeout=180)
    subprocess.run([py, "-m", "pip", "install", "-q", "--upgrade", "pip"], check=False, timeout=300)
    subprocess.run([py, "-m", "pip", "install", "-q", *pip_install], check=True, timeout=1800)
    return py, "built venv"
