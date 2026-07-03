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
# `python -m <module>` README commands that are ENV SETUP, not the eval entrypoint — a README routinely shows
# `python -m venv ...` / `python -m pip install ...` BEFORE the real run command; picking those breaks the
# run (e.g. `python -m venv` with no target dir). Skip them and keep scanning for the actual entrypoint.
_SETUP_MODULES = {"venv", "virtualenv", "pip", "ensurepip", "pipenv", "poetry", "build", "twine", "uv", "conda"}
# source dirs a runnable driver hides in when the repo root has no script (package-shaped repos)
_SRC_DIRS = ("src", "code", "scripts", "experiments", "experiment", "bin", "analysis", "pipeline", "notebooks")
# dirs that are never the headline entrypoint's home (tests/docs/examples) — skip when hunting a package/driver
_SKIP_DIRS = {"test", "tests", "testing", "docs", "doc", "examples", "example", ".git", "__pycache__",
              ".venv", "venv", "env", "node_modules", "build", "dist", ".github"}
# import roots that signal a file actually computes/reports numbers (vs a config/util module)
_METRIC_LIBS = frozenset({"sklearn", "numpy", "scipy", "pandas", "torch", "tensorflow", "xgboost",
                          "lightgbm", "catboost", "statsmodels", "jax"})
# driver-ish stems, most-likely-the-headline first (mirrors _ENTRY_NAMES, sans .py)
_DRIVER_STEMS = ("reproduce", "runall", "run", "main", "eval", "evaluate", "runeval", "benchmark",
                 "runbenchmark", "experiment", "analysis", "analyze", "figures", "results", "score")


def _root_scripts(repo_dir):
    if not os.path.isdir(repo_dir):
        return []
    return sorted(f for f in os.listdir(repo_dir)
                  if f.endswith(".py") and f not in _NOT_ENTRY
                  and os.path.isfile(os.path.join(repo_dir, f)))


def _has_main_guard(path):
    try:
        return "__main__" in open(path, errors="replace").read()
    except OSError:
        return False


def _module_exists(repo_dir, dotted):
    """True if `dotted` (pkg.mod) resolves to a file/package under repo_dir, so `python -m dotted` can run
    with cwd=repo_dir. Guards against a stale `-m` command in a README naming a module that no longer exists."""
    base = os.path.join(repo_dir, *dotted.split("."))
    return (os.path.isfile(base + ".py") or os.path.isfile(os.path.join(base, "__main__.py"))
            or os.path.isdir(base))


def _readme_run_command(repo_dir):
    """A `python …` command from a README/REPRODUCE doc that points at a file/module that ACTUALLY EXISTS.
    Two fixes over a naive scan: (a) preserve the relative PATH — `python scripts/run.py` must run
    scripts/run.py, not a non-existent root run.py (the old code stripped to basename and silently missed
    it); (b) validate a `-m pkg.mod` resolves under the repo before trusting it. Returns an argv list or None.
    Arguments are intentionally dropped for now (a README's `--data /abs/path` often won't exist in the
    sandbox); the AI planner / repair loop supply args."""
    for fn in ("README.md", "README.rst", "README.txt", "readme.md", "REPRODUCE.md", "REPRODUCIBILITY.md"):
        p = os.path.join(repo_dir, fn)
        if not os.path.isfile(p):
            continue
        try:
            text = open(p, errors="replace").read()
        except OSError:
            continue
        for m in _RUN_RE.finditer(text):
            tok = m.group(1).strip()
            if tok.startswith("-m"):
                mod = (tok.split() + [""])[1]
                if mod.split(".")[0] in _SETUP_MODULES:   # env setup (venv/pip/...), not the eval entrypoint
                    continue
                if _module_exists(repo_dir, mod):
                    return ["-m", mod]
                continue
            if os.path.isfile(os.path.join(repo_dir, tok)):   # keeps a subdir path intact
                return [tok]
            base = os.path.basename(tok)                       # tolerate a README naming just the basename
            if base != tok and os.path.isfile(os.path.join(repo_dir, base)):
                return [base]
    return None


def _runnable_package(repo_dir):
    """A top-level import package directly runnable via `python -m <pkg>` because it ships a
    `<pkg>/__main__.py` — the Pythonic entrypoint for a package-shaped repo with no root script (e.g. a
    `code/` or `<name>/` package). Only ROOT-level packages, so it runs with cwd=repo_dir and no PYTHONPATH
    juggling. Returns the package name or None."""
    try:
        entries = sorted(os.listdir(repo_dir))
    except OSError:
        return None
    for name in entries:
        d = os.path.join(repo_dir, name)
        if os.path.isdir(d) and name not in _SKIP_DIRS and os.path.isfile(os.path.join(d, "__main__.py")):
            return name
    return None


def _subdir_driver_script(repo_dir):
    """Last resort before giving up: look one level into the common source dirs (src/, code/, scripts/, the
    repo-name package, …) for a DRIVER — a `.py` with a `__main__` guard that imports a metric library
    (sklearn/numpy/…), i.e. a file that actually computes/reports, not a util or config. Ranked by a
    driver-ish stem (run/main/eval/reproduce/…). Returns a repo-relative argv (['code/run.py']) or None.

    Best-effort and fail-closed: a wrong pick can only produce a wrong/empty capture → DISCOVERED / REFUTED /
    INCONCLUSIVE, never a false CONFIRM (binding is by metric identity, not by the fact that something ran).
    That is strictly better than the old behavior of fabricating a non-existent `eval.py` that always failed."""
    reponame = os.path.basename(repo_dir.rstrip("/"))
    cands: list[tuple[int, str]] = []
    seen_dirs = set()
    for sub in _SRC_DIRS + (reponame,):
        d = os.path.join(repo_dir, sub)
        if sub in seen_dirs or not os.path.isdir(d):
            continue
        seen_dirs.add(sub)
        try:
            files = sorted(f for f in os.listdir(d) if f.endswith(".py") and f not in _NOT_ENTRY)
        except OSError:
            continue
        for f in files:
            path = os.path.join(d, f)
            if not (os.path.isfile(path) and _has_main_guard(path)):
                continue
            if not (_imported_roots(path) & _METRIC_LIBS):    # skip utils/config — no compute → not a driver
                continue
            stem = re.sub(r"[^a-z0-9]", "", f[:-3].lower())
            rank = next((i for i, s in enumerate(_DRIVER_STEMS) if s in stem), len(_DRIVER_STEMS))
            cands.append((rank, os.path.join(sub, f)))
    if not cands:
        return None
    cands.sort()
    return [cands[0][1]]


def detect_entrypoint(repo_dir):
    """Best-effort: find the script that produces the headline numbers, so deep verify works without the
    user naming it. In order of trust: a README run-command → a known entrypoint name at root → root-script
    heuristics (only script / repo-name match / __main__ guard) → a runnable package (`-m pkg` when
    `pkg/__main__.py` exists) → a __main__-guarded driver in a source subdir (code/, src/, …). Returns an
    argv list (e.g. ['iris-svm.py'], ['-m', 'code'], ['code/run.py']) or None. (make-runnable, guide §5.)"""
    # 1) a README run command that points at a file/module present in the repo (path- and module-validated)
    cmd = _readme_run_command(repo_dir)
    if cmd:
        return cmd
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
        if _has_main_guard(os.path.join(repo_dir, f)):
            return [f]
    # 4) a package-shaped repo (no root script): `python -m <pkg>` when `<pkg>/__main__.py` exists
    pkg = _runnable_package(repo_dir)
    if pkg:
        return ["-m", pkg]
    # 5) a __main__-guarded driver hiding in a source subdir (code/, src/, scripts/, the repo-name package)
    return _subdir_driver_script(repo_dir)


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
    """Every name importable from WITHIN the repo — so we never try to pip-install the repo's own modules.
    Walk the whole tree (not just the root): a top-level `import model` resolves to a `model.py` or `model/`
    that may live in any source dir. Misclassifying these as PyPI packages is what made `pip install model`
    abort the whole env build."""
    names = set()
    if not os.path.isdir(repo_dir):
        return names
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", "venv", "env")]
        names.add(os.path.basename(root.rstrip("/")))        # the dir itself = a package candidate
        for fn in files:
            if fn.endswith(".py"):
                names.add(fn[:-3])
    return names


# heavy / accelerator-bound deps. We can still TRY them on CPU (and prefer CPU wheels), but they need a
# bigger install budget and often want a GPU at runtime.
_HEAVY = frozenset({"torch", "torchvision", "torchaudio", "tensorflow", "tensorflow-gpu", "jax", "jaxlib",
                    "transformers", "accelerate", "deepspeed", "xgboost", "lightgbm", "catboost",
                    "vllm", "flash-attn", "bitsandbytes", "cupy", "rapids", "detectron2"})
# install args that pull the CPU build instead of the multi-GB CUDA wheel (inferred deps only — a repo's
# pinned requirements.txt is respected as-is for faithful repro).
_CPU_WHEELS = {
    "torch": ["torch", "--index-url", "https://download.pytorch.org/whl/cpu"],
    "torchvision": ["torchvision", "--index-url", "https://download.pytorch.org/whl/cpu"],
    "torchaudio": ["torchaudio", "--index-url", "https://download.pytorch.org/whl/cpu"],
    "tensorflow": ["tensorflow-cpu"],
    "tensorflow-gpu": ["tensorflow-cpu"],
}


def cpu_pip_args(pkg):
    """For an INFERRED heavy dep, the args that fetch the CPU wheel (avoids a giant CUDA download). Returns a
    list of pip args; default is just [pkg]."""
    base = re.split(r"[<>=!~ ]", pkg, maxsplit=1)[0].strip().lower()
    return list(_CPU_WHEELS.get(base, [pkg]))


def deps_are_heavy(pkgs):
    """True if any dep is a heavy/accelerator package → use a larger install budget."""
    for p in pkgs or []:
        base = re.split(r"[<>=!~ ]", p, maxsplit=1)[0].strip().lower()
        if base in _HEAVY:
            return True
    return False


def repo_commit_date(repo_dir):
    """YYYY-MM-DD of the repo's HEAD commit — the era to pin inferred packages to. None if unavailable."""
    try:
        out = subprocess.run(["git", "-C", repo_dir, "log", "-1", "--format=%cs"],
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    d = (out.stdout or "").strip()
    return d if re.match(r"^\d{4}-\d{2}-\d{2}$", d) else None


def _pypi_version_at(name, date, timeout=20):
    """The version of `name` most recently released on/before `date` (PyPI JSON API). Skips pre-releases.
    None on any failure → the caller leaves the package unpinned."""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/%s/json" % name, timeout=timeout) as fh:
            releases = json.load(fh).get("releases") or {}
    except Exception:  # noqa: BLE001 — network/parse failure → unpinned fallback
        return None
    best_ver, best_date = None, ""
    for ver, files in releases.items():
        if re.search(r"(a|b|rc|dev)\d", ver):           # skip 1.0a1 / 1.0rc1 / 1.0.dev0
            continue
        ups = [(f.get("upload_time_iso_8601") or f.get("upload_time") or "")[:10] for f in files]
        ups = [u for u in ups if u]
        if not ups:
            continue
        rel = min(ups)                                  # first upload of this version
        if rel > date:
            continue
        if best_ver is None or (rel, _ver_key(ver)) > (best_date, _ver_key(best_ver)):
            best_ver, best_date = ver, rel
    return best_ver


def _ver_key(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:4])


def era_pin(packages, repo_dir):
    """Pin each UNPINNED inferred package to the version released on/before the repo's commit date, so a repo
    runs against ITS ERA's libraries (a 2021 repo gets sklearn ~1.0 where `plot_roc_curve` still existed),
    not latest — the version-drift reproduction fix. Already-constrained specs and PyPI-unresolvable names
    pass through. Needs network. Returns (pinned_packages, era_date | None).

    The PyPI lookups run CONCURRENTLY: each is an independent HTTP call with a 20s timeout, so doing them
    sequentially made the worst case N×20s of pure latency before the install even started. A small thread
    pool collapses that to roughly one round-trip, order preserved."""
    date = repo_commit_date(repo_dir)
    if not date:
        return list(packages or []), None
    specs = list(packages or [])
    out: list[str | None] = [None] * len(specs)
    todo = []                                            # (index, name, spec) needing a PyPI lookup
    for i, spec in enumerate(specs):
        if re.search(r"[<>=!~]", spec):                  # respect an explicit constraint — no lookup
            out[i] = spec
            continue
        name = re.split(r"[<>=!~ \[]", spec, maxsplit=1)[0].strip()
        if name:
            todo.append((i, name, spec))
        else:
            out[i] = spec
    if todo:
        from concurrent.futures import ThreadPoolExecutor

        def _resolve(item):
            i, name, spec = item
            ver = _pypi_version_at(name, date)
            return i, ("%s==%s" % (name, ver) if ver else spec)

        with ThreadPoolExecutor(max_workers=min(8, len(todo))) as ex:
            for i, val in ex.map(_resolve, todo):
                out[i] = val
    return [v for v in out], date


# stderr signature → (kind, user-facing hint). The honest couldn't-reproduce taxonomy: tell the user WHY the
# re-run didn't produce a number, instead of a raw stack trace.
_FAILURE_TAXONOMY = [
    ("CUDA", ("needs-gpu", "the code requires a GPU (CUDA) — not available on the CPU tier")),
    ("cuda", ("needs-gpu", "the code requires a GPU (CUDA) — not available on the CPU tier")),
    ("No CUDA GPUs are available", ("needs-gpu", "the code requires a GPU (CUDA) — not available on the CPU tier")),
    ("nvidia", ("needs-gpu", "the code requires NVIDIA/GPU support — not available on the CPU tier")),
    ("out of memory", ("too-heavy", "ran out of memory — needs a larger tier")),
    ("Killed", ("too-heavy", "the process was killed (likely out of memory) — needs a larger tier")),
    ("MemoryError", ("too-heavy", "ran out of memory — needs a larger tier")),
    ("[timeout]", ("too-slow", "exceeded the time budget — scope the run or raise the timeout")),
    ("ModuleNotFoundError", ("missing-dep", "a dependency could not be installed/resolved")),
    ("No matching distribution", ("missing-dep", "a dependency could not be installed/resolved")),
    # pandas parquet needs pyarrow/fastparquet — an optional extra dep-inference can't see. Now bundled in the
    # image, but classify it as missing-dep (not a generic error) so the heal/revise can install it if absent.
    ("Unable to find a usable engine", ("missing-dep", "parquet support needs pyarrow — install it")),
    ("Missing optional dependency", ("missing-dep", "an optional dependency (e.g. pyarrow) is missing")),
    # The interpreter itself couldn't open the entrypoint SCRIPT (`python: can't open file '…'`). This is a
    # wrong/undetected entrypoint, NOT a missing data file — must be screened BEFORE the generic
    # "No such file or directory" below, which the same stderr line also contains.
    ("can't open file", ("missing-entrypoint", "couldn't find the script that runs this repo — name the "
                         "entrypoint (a .py file or `-m package.module`) under Advanced → Entrypoint")),
    ("FileNotFoundError", ("missing-data", "an input file/dataset is missing — connect the data")),
    ("No such file or directory", ("missing-data", "an input file/dataset is missing — connect the data")),
    ("HTTPError", ("needs-network", "a runtime download failed — the dataset/model isn't bundled")),
    ("ConnectionError", ("needs-network", "a runtime download failed — the dataset/model isn't bundled")),
    ("URLError", ("needs-network", "a runtime download failed — the dataset/model isn't bundled")),
]


def classify_failure(stderr):
    """Map a captured stderr to (kind, hint). Returns ('errored', generic) when nothing matches."""
    s = stderr or ""
    for sig, (kind, hint) in _FAILURE_TAXONOMY:
        if sig in s:
            return {"kind": kind, "hint": hint}
    return {"kind": "errored", "hint": "the entrypoint errored — see the full output"}


_PYVER_RE = re.compile(r"(\d+)\.(\d+)(?:\.\d+)?")


def sandbox_python() -> str:
    """The interpreter the E2B run image actually ships — the floor to relax era-pins against when a repo does
    NOT declare its own Python. Must track the template's CALMA_TEMPLATE_PY (kept in sync via CALMA_SANDBOX_PY).
    Without this, a repo with no declared Python got its era-pins (e.g. today's numpy==2.5.0, which needs 3.12)
    installed blind against whatever the image ships — a silent, total install failure if they mismatch.

    MUST track the DEPLOYED image: set the Fly secret CALMA_SANDBOX_PY to the running template's Python (3.11
    today; bump to 3.12 when the 3.12 template is rebuilt + pointed at). The default is the conservative 3.11
    (matches the current prod image): guessing LOWER than reality over-relaxes (harmless — pip resolves a
    compatible version); guessing HIGHER keeps a pin the interpreter can't load (the exact bug this fixes)."""
    return (os.environ.get("CALMA_SANDBOX_PY") or "3.11").strip()


def detect_python_version(repo_dir):
    """The Python version the repo was written for — so a faithful repro runs under it (not just whatever the
    sandbox ships), turning version-drift REFUTEDs into CONFIRMEDs under the original interpreter. Reads, in
    intent order, .python-version → runtime.txt → pyproject requires-python / poetry python → setup.py/cfg
    python_requires. Returns 'X.Y' or None."""
    def first_xy(text):
        m = _PYVER_RE.search(text or "")
        return "%s.%s" % (m.group(1), m.group(2)) if m else None

    p = os.path.join(repo_dir, ".python-version")
    if os.path.isfile(p):
        try:
            xy = first_xy(open(p, errors="replace").read())
            if xy:
                return xy
        except OSError:
            pass
    p = os.path.join(repo_dir, "runtime.txt")          # e.g. Heroku-style "python-3.11.5"
    if os.path.isfile(p):
        try:
            xy = first_xy(open(p, errors="replace").read())
            if xy:
                return xy
        except OSError:
            pass
    p = os.path.join(repo_dir, "pyproject.toml")
    if os.path.isfile(p):
        try:
            txt = open(p, errors="replace").read()
        except OSError:
            txt = ""
        for key in ("requires-python", "python"):       # PEP 621 + poetry
            m = re.search(key + r'\s*=\s*["\']([^"\']+)["\']', txt)
            if m:
                xy = first_xy(m.group(1))               # lower bound / pinned of ">=3.9", "^3.10", "==3.11"
                if xy:
                    return xy
    for fn in ("setup.py", "setup.cfg"):
        p = os.path.join(repo_dir, fn)
        if os.path.isfile(p):
            try:
                txt = open(p, errors="replace").read()
            except OSError:
                continue
            m = re.search(r"python_requires\s*=\s*[\"']([^\"']+)[\"']", txt)
            if m:
                xy = first_xy(m.group(1))
                if xy:
                    return xy
    return None


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
