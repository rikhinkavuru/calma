"""build — the 'make a repo runnable' step (rebuild guide §5: repo2docker → Repo2Run). The spike ships a
deliberately minimal version: resolve the source (a local path or a shallow git clone at a pinned commit)
and, for the local runner, build a per-repo venv and pip-install declared deps. The real agentic
env-synthesis (Repo2Run; cache the synthesized env per repo — the reproduction flywheel) is the next layer.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys

# common eval/run entrypoint names, in rough priority order (most-likely-the-headline first)
_ENTRY_NAMES = ("reproduce.py", "run.py", "main.py", "eval.py", "evaluate.py", "run_eval.py",
                "benchmark.py", "run_benchmark.py", "experiment.py", "demo.py", "train.py", "test.py")
# a README run command: ```python foo.py``` / `python3 foo.py` / `python -m pkg.mod`
_RUN_RE = re.compile(r"python3?\s+(-m\s+[\w.]+|[\w./-]+\.py)(?:\s+[^\n`]*)?", re.I)
# packaging/scaffolding scripts that are never the headline entrypoint
_NOT_ENTRY = {"setup.py", "conftest.py", "__init__.py", "_version.py", "version.py", "setup_helpers.py"}


def _root_scripts(repo_dir):
    if not os.path.isdir(repo_dir):
        return []
    return sorted(f for f in os.listdir(repo_dir)
                  if f.endswith(".py") and f not in _NOT_ENTRY
                  and os.path.isfile(os.path.join(repo_dir, f)))


def detect_entrypoint(repo_dir):
    """Best-effort: find the script that produces the headline numbers, so deep verify works without the
    user naming it. README run-command → a known entrypoint name → a single root script → a repo-name match
    → a script with a __main__ guard. Returns an argv list (e.g. ['iris-svm.py']) or None. (make-runnable,
    guide §5.)"""
    # 1) a run command in the README that points at a file present in the repo
    for fn in ("README.md", "README.rst", "README.txt", "readme.md", "REPRODUCE.md", "REPRODUCIBILITY.md"):
        p = os.path.join(repo_dir, fn)
        if not os.path.isfile(p):
            continue
        try:
            text = open(p, errors="replace").read()
        except OSError:
            continue
        for m in _RUN_RE.finditer(text):
            tok = m.group(1)
            if tok.startswith("-m"):
                return tok.split()                      # python -m pkg.mod
            if os.path.isfile(os.path.join(repo_dir, os.path.basename(tok))):
                return [os.path.basename(tok)]
    # 2) a known entrypoint filename present at the repo root
    for name in _ENTRY_NAMES:
        if os.path.isfile(os.path.join(repo_dir, name)):
            return [name]
    # 3) heuristics over the root scripts (the README/known-name paths missed it)
    roots = _root_scripts(repo_dir)
    if len(roots) == 1:                                  # the only script — almost certainly it
        return [roots[0]]
    base = re.sub(r"[^a-z0-9]", "", os.path.basename(repo_dir.rstrip("/")).lower())
    for f in roots:                                      # a script whose name matches the repo (iris-svm.py)
        stem = re.sub(r"[^a-z0-9]", "", f[:-3].lower())
        if stem and len(stem) >= 4 and (stem in base or base in stem):
            return [f]
    for f in roots:                                      # a script with an `if __name__ == "__main__"` guard
        try:
            if "__main__" in open(os.path.join(repo_dir, f), errors="replace").read():
                return [f]
        except OSError:
            continue
    return None


# import name → PyPI package, where they differ (otherwise the import name is the package name)
_PKG_ALIASES = {
    "sklearn": "scikit-learn", "cv2": "opencv-python-headless", "PIL": "pillow", "yaml": "pyyaml",
    "bs4": "beautifulsoup4", "skimage": "scikit-image", "Bio": "biopython", "dotenv": "python-dotenv",
    "dateutil": "python-dateutil", "attr": "attrs", "OpenSSL": "pyOpenSSL", "yaml_": "pyyaml",
    "matplotlib": "matplotlib", "mpl_toolkits": "matplotlib", "google": "google-api-python-client",
}


def _imported_roots(py_path):
    try:
        tree = ast.parse(open(py_path, errors="replace").read())
    except (OSError, SyntaxError, ValueError):
        return set()
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                roots.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])        # level>0 = a relative (local) import — skip
    return roots


def _local_module_names(repo_dir):
    names = set()
    if not os.path.isdir(repo_dir):
        return names
    for fn in os.listdir(repo_dir):
        p = os.path.join(repo_dir, fn)
        if fn.endswith(".py"):
            names.add(fn[:-3])
        elif os.path.isdir(p) and os.path.isfile(os.path.join(p, "__init__.py")):
            names.add(fn)
    return names


def infer_requirements(repo_dir, max_files=120):
    """Resolve the pip deps to install so a repo runs in a clean sandbox, WITHOUT the user listing them.
    Declared deps win (requirements.txt); otherwise infer from the actual imports — map import roots to PyPI
    names and drop the standard library + the repo's own modules. Returns (pip_args, source_note). This is
    the make-runnable / 'agentic env build' step kept deliberately simple."""
    req = os.path.join(repo_dir, "requirements.txt")
    if os.path.isfile(req):
        out = []
        try:
            for line in open(req, errors="replace"):
                line = line.split("#")[0].strip()
                if line and not line.startswith("-"):
                    out.append(line)
        except OSError:
            out = []
        if out:
            return out[:100], "requirements.txt"

    stdlib = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
    local = _local_module_names(repo_dir)
    found, n = set(), 0
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", "venv", "env")]
        for fn in files:
            if fn.endswith(".py"):
                n += 1
                if n > max_files:
                    break
                found |= _imported_roots(os.path.join(root, fn))
        if n > max_files:
            break
    pkgs, seen = [], set()
    for m in sorted(found):
        if not m or m.startswith("_") or m in stdlib or m in local:
            continue
        pkg = _PKG_ALIASES.get(m, m)
        if pkg not in seen:
            seen.add(pkg)
            pkgs.append(pkg)
    return pkgs, ("inferred from imports" if pkgs else "no deps detected")


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
