"""build — the 'make a repo runnable' step (rebuild guide §5: repo2docker → Repo2Run). The spike ships a
deliberately minimal version: resolve the source (a local path or a shallow git clone at a pinned commit)
and, for the local runner, build a per-repo venv and pip-install declared deps. The real agentic
env-synthesis (Repo2Run; cache the synthesized env per repo — the reproduction flywheel) is the next layer.
"""
from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
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
# web-app / server frameworks: a script that imports one is a SERVER (a demo UI / API), never the script
# that produced a committed headline metric — and worse, its blocking `.run()`/`serve` HANGS the sandbox
# until the timeout. Never pick one as an entrypoint (real ICP repos ship a streamlit/flask demo next to the
# actual eval; picking the demo is both wrong and a hang). General across the whole market, not ML-specific.
_SERVER_LIBS = frozenset({"streamlit", "flask", "gradio", "dash", "fastapi", "uvicorn", "django", "bottle",
                          "tornado", "aiohttp", "sanic", "starlette", "chainlit", "panel", "shiny", "flet",
                          "nicegui", "reflex", "waitress", "gunicorn"})
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


def _is_server_script(path):
    """True if the script imports a web-server / app framework — a demo UI or API, never the producer of a
    committed headline metric, and a blocking-serve hang risk. Cheap: reuses the import scan."""
    return bool(_imported_roots(path) & _SERVER_LIBS)


def _notebook_entry(repo_dir):
    """A runnable notebook to use when no .py entrypoint exists — huge in the real market (a repo whose whole
    analysis IS a .ipynb). Returns ['nb:<path>'] (routed to the kernel-armed notebook runner), ranked by a
    driver-ish stem; checkpoint/Untitled notebooks are deprioritized. Roots + a notebooks/ dir."""
    cands: list[tuple[int, str]] = []
    for sub in ("", "notebooks", "notebook", "nb"):
        d = os.path.join(repo_dir, sub) if sub else repo_dir
        if not os.path.isdir(d):
            continue
        try:
            files = sorted(f for f in os.listdir(d) if f.endswith(".ipynb") and not f.startswith("."))
        except OSError:
            continue
        for f in files:
            stem = re.sub(r"[^a-z0-9]", "", f[:-6].lower())
            rank = next((i for i, s in enumerate(_DRIVER_STEMS) if s in stem), len(_DRIVER_STEMS))
            if "checkpoint" in f.lower() or "untitled" in stem:
                rank += 100                                  # scratch notebooks are rarely the reproduction
            cands.append((rank, os.path.join(sub, f) if sub else f))
    if not cands:
        return None
    cands.sort()
    return ["nb:" + cands[0][1]]


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


# committed result artifacts whose numbers ARE the headline table (bucket B: "ran a quickstart, not the
# suite that wrote the committed table"). Root result-named files + any tabular file under a results/ dir.
_ARTIFACT_DIRS = ("results", "result", "output", "outputs", "artifacts", "reports", "logs")
_ARTIFACT_ROOT_NAMES = ("results.json", "metrics.json", "result.json", "scores.json", "eval.json",
                        "results.csv", "metrics.csv", "scores.csv", "summary.csv", "leaderboard.csv",
                        "leaderboard.json", "benchmark.json", "benchmarks.csv")
_ARTIFACT_EXTS = (".csv", ".json", ".parquet", ".tsv")
# method/builtin calls that EMIT a results file — so the script that calls one with the artifact's name is
# its producer (df.to_csv("results.csv"), json.dump(x, open("metrics.json","w")), np.savez(...), plt.savefig)
_WRITE_METHODS = frozenset({"to_csv", "to_json", "to_parquet", "to_pickle", "to_feather", "to_hdf",
                            "to_excel", "savefig", "save", "savez", "savez_compressed", "savetxt", "dump",
                            "write_csv", "write_parquet", "write_json", "write_ndjson"})


def _result_artifacts(repo_dir):
    """Committed result files present in the repo. Returns a set of basenames (the distinctive filenames a
    producer script would name), bounded."""
    names = set()
    for name in _ARTIFACT_ROOT_NAMES:
        if os.path.isfile(os.path.join(repo_dir, name)):
            names.add(name)
    for d in _ARTIFACT_DIRS:
        dd = os.path.join(repo_dir, d)
        if os.path.isdir(dd):
            try:
                for fn in sorted(os.listdir(dd)):
                    if fn.lower().endswith(_ARTIFACT_EXTS) and os.path.isfile(os.path.join(dd, fn)):
                        names.add(fn)
            except OSError:
                pass
            if len(names) > 60:
                break
    return names


def _strings_under(node):
    """Every string-constant fragment anywhere under an AST node — covers os.path.join('results','x.csv')
    and f-strings (whose literal parts are Constants)."""
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _is_write_open(call):
    """open(path, 'w'|'a'|'x') — a file opened for writing (positional or mode= keyword)."""
    if not (isinstance(call.func, ast.Name) and call.func.id == "open"):
        return False
    mode = ""
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant) and isinstance(call.args[1].value, str):
        mode = call.args[1].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            mode = kw.value.value
    return any(c in mode for c in ("w", "a", "x"))


def _writes_artifact(py_path, basenames):
    """How tightly a script writes any of `basenames`: 2 = the filename is an argument to a write call
    (df.to_csv("results.csv"), open("metrics.json","w")); 1 = the file has a write call AND names the
    artifact somewhere (path built indirectly); 0 = no. Reverse map: which .py produces the committed table."""
    try:
        tree = ast.parse(open(py_path, errors="replace").read(1_000_000))
    except (OSError, SyntaxError, ValueError):
        return 0
    has_write = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (
                _is_write_open(node) or (isinstance(node.func, ast.Attribute)
                                         and node.func.attr in _WRITE_METHODS)):
            has_write = True
            for s in _strings_under(node):
                if any(b in s for b in basenames):
                    return 2
    if has_write and any(b in s for s in _strings_under(tree) for b in basenames):
        return 1
    return 0


def _candidate_scripts(repo_dir):
    """Runnable .py to test as producers: root scripts + one level into source dirs (skip test/doc dirs)."""
    out = list(_root_scripts(repo_dir))
    for sub in _SRC_DIRS:
        d = os.path.join(repo_dir, sub)
        if not os.path.isdir(d):
            continue
        try:
            for f in sorted(os.listdir(d)):
                if f.endswith(".py") and f not in _NOT_ENTRY and os.path.isfile(os.path.join(d, f)):
                    out.append(os.path.join(sub, f))
        except OSError:
            pass
    return out[:200]


def artifact_producer(repo_dir):
    """The script that WRITES the repo's committed result artifact — the true reproduction entrypoint, found
    by reverse-mapping (which .py writes results/summary.csv?) instead of guessing by filename. Closes the
    'ran a quickstart, not the suite that produced the committed table' gap (bucket B). Returns a
    repo-relative argv (['run_all.py'], ['src/evaluate.py']) or None. Fail-closed: only fires on a clear
    producer; otherwise the caller's name heuristics proceed. Run-planning ONLY — never the verdict."""
    basenames = _result_artifacts(repo_dir)
    if not basenames:
        return None
    best = None    # (score-tuple, argv)
    for rel in _candidate_scripts(repo_dir):
        path = os.path.join(repo_dir, rel)
        tight = _writes_artifact(path, basenames)
        if tight == 0:
            continue
        score = tight * 100
        if _has_main_guard(path):
            score += 20
        if _imported_roots(path) & _METRIC_LIBS:
            score += 10
        stem = re.sub(r"[^a-z0-9]", "", os.path.basename(rel)[:-3].lower())
        rank = next((i for i, s in enumerate(_DRIVER_STEMS) if s in stem), len(_DRIVER_STEMS))
        score += len(_DRIVER_STEMS) - rank                 # driver-ish name bonus
        cand = (score, -rel.count(os.sep))                 # tie-break: prefer a shallower (root) script
        if best is None or cand > best[0]:
            best = (cand, [rel])
    return best[1] if best else None


def detect_entrypoint(repo_dir):
    """Best-effort: find the script that produces the headline numbers, so deep verify works without the
    user naming it. In order of trust: a README run-command → the script that writes the committed result
    artifact (reverse map) → a known entrypoint name at root → root-script heuristics (only script /
    repo-name match / __main__ guard) → a runnable package (`-m pkg` when `pkg/__main__.py` exists) → a
    __main__-guarded driver in a source subdir (code/, src/, …). Returns an argv list (e.g. ['iris-svm.py'],
    ['-m', 'code'], ['code/run.py']) or None. (make-runnable, guide §5.)"""
    # 1) a README run command that points at a file/module present in the repo (path- and module-validated)
    cmd = _readme_run_command(repo_dir)
    if cmd:
        return cmd
    # 2) the script that WRITES the committed result artifact — evidence ("this .py produced results.csv")
    #    beats the filename guesses below. The real reproduction script, not a quickstart (bucket B).
    prod = artifact_producer(repo_dir)
    if prod:
        return prod
    # 3) a known entrypoint filename present at the repo root (but never a server-framework script)
    for name in _ENTRY_NAMES:
        p = os.path.join(repo_dir, name)
        if os.path.isfile(p) and not _is_server_script(p):
            return [name]
    # 4) heuristics over the root scripts (the README/known-name paths missed it) — with server apps
    #    (streamlit/flask demos) filtered out: they never produced the committed metric and would hang.
    roots = [f for f in _root_scripts(repo_dir) if not _is_server_script(os.path.join(repo_dir, f))]
    if len(roots) == 1:                                  # the only (non-server) script — almost certainly it
        return [roots[0]]
    base = re.sub(r"[^a-z0-9]", "", os.path.basename(repo_dir.rstrip("/")).lower())
    for f in roots:                                      # a script whose name matches the repo (iris-svm.py)
        stem = re.sub(r"[^a-z0-9]", "", f[:-3].lower())
        if stem and len(stem) >= 4 and (stem in base or base in stem):
            return [f]
    for f in roots:                                      # a script with an `if __name__ == "__main__"` guard
        if _has_main_guard(os.path.join(repo_dir, f)):
            return [f]
    # 5) no runnable .py entry — a notebook IS the analysis in a huge share of real repos; run it as one
    #    (kernel-armed capture) rather than feeding raw .ipynb JSON to python (which NameErrors on `null`).
    nb = _notebook_entry(repo_dir)
    if nb:
        return nb
    # 6) a package-shaped repo (no root script): `python -m <pkg>` when `<pkg>/__main__.py` exists
    pkg = _runnable_package(repo_dir)
    if pkg:
        return ["-m", pkg]
    # 7) a __main__-guarded driver hiding in a source subdir (code/, src/, scripts/, the repo-name package)
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
    ("FileNotFoundError", ("missing-data", "an input file/dataset is missing — commit a predictions file "
                           "(id,y_true,y_score) to verify the metric without the data, or connect the data")),
    ("No such file or directory", ("missing-data", "an input file/dataset is missing — commit a predictions file "
                                   "(id,y_true,y_score) to verify the metric without the data, or connect the data")),
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


_COMPAT_PYTHONS = ("python3.12", "python3.11", "python3.10")
# a proven-lenient older science stack (wheels on py3.12) to RETRY a run that failed purely because the
# LATEST stack tightened behavior the repo relied on (sklearn rejecting label types / NaN it once tolerated,
# a removed API). Env-only repair — the repo's compute is untouched, so it's FCR-safe.
_COMPAT_STACK = {"scikit-learn": "scikit-learn==1.3.2", "sklearn": "scikit-learn==1.3.2",
                 "pandas": "pandas==2.2.3", "numpy": "numpy==1.26.4", "scipy": "scipy==1.11.4"}


def downgrade_science(specs):
    """Return `specs` with the core science libs pinned to a proven-compatible older stack (leaving other
    deps and already-constrained pins alone). Used to retry a version-drift failure in its era's environment."""
    out = []
    for s in specs or []:
        name = re.split(r"[<>=!~ ]", str(s), maxsplit=1)[0].strip().lower()
        out.append(_COMPAT_STACK.get(name, s) if not re.search(r"[<>=!~]", str(s)) else s)
    return out


def _find_python(names):
    import shutil
    for nm in names:
        p = shutil.which(nm) or os.path.expanduser("~/.local/bin/%s" % nm)
        if p and os.path.isfile(p):
            return p
    return None


def compat_python(era_date=None):
    """An ERA-APPROPRIATE interpreter for building a per-repo venv. A repo's era stack needs an era python: a
    2019 sklearn/pandas has no py3.14 (or even py3.12) wheels, so the pin gets relaxed and the version-drift
    failure returns. The E2B product provisions any Python; locally we use uv-installed 3.9/3.10/3.12. Maps
    the commit era → a python that HAS wheels for that era, newest-first with fallbacks. Defaults to 3.12."""
    order = list(_COMPAT_PYTHONS)                          # 3.12, 3.11, 3.10 (current + recent)
    if era_date:
        if era_date < "2021":
            order = ["python3.8", "python3.9", "python3.10"] + order   # 2016-2020 stacks (sklearn 0.x/pandas 0-1)
        elif era_date < "2023":
            order = ["python3.9", "python3.10"] + order     # 2021-2022 stacks
    return _find_python(order) or sys.executable


def python_version(py):
    """The 'X.Y' version of an interpreter path (for era_pin_compat's requires-python relax), or None."""
    try:
        out = subprocess.run([py, "-c", "import sys;print('%d.%d'%sys.version_info[:2])"],
                             capture_output=True, text=True, timeout=15)
        v = (out.stdout or "").strip()
        return v if re.match(r"^\d+\.\d+$", v) else None
    except (OSError, subprocess.SubprocessError):
        return None


def ensure_venv(name, pip_install, venvs_dir, base_python=None):
    """Create (once) a per-repo venv and install deps. Returns the venv's python path. If no deps are
    declared, returns the base python (the harness venv, which already has numpy/sklearn for fixtures)."""
    base_python = base_python or sys.executable
    if not pip_install:
        return base_python, "harness python"
    venv_dir = os.path.join(venvs_dir, name)
    py = os.path.join(venv_dir, "bin", "python")
    # A success sentinel keyed on the exact dep set. `python -m venv` creates bin/python BEFORE the deps install,
    # so gating the cache on bin/python alone (the old bug) returns a half-built venv with NO deps if the install
    # failed — a ModuleNotFoundError on the NEXT run that also defeats the caller's latest-fallback. And keying by
    # `name` alone reuses a venv built for a DIFFERENT (e.g. pre-era-pin) dep set. The sentinel — written only
    # AFTER a successful install — fixes both: cache-hit iff it exists and matches this run's dep hash.
    sentinel = os.path.join(venv_dir, ".calma_installed")
    want = hashlib.sha1("\n".join(sorted(str(d) for d in pip_install)).encode()).hexdigest()
    if os.path.isfile(py) and os.path.isfile(sentinel):
        try:
            if open(sentinel).read().strip() == want:
                return py, "cached venv"
        except OSError:
            pass
    if os.path.isdir(venv_dir):                    # half-built or stale-dep venv → rebuild from scratch
        shutil.rmtree(venv_dir, ignore_errors=True)
    os.makedirs(venvs_dir, exist_ok=True)
    subprocess.run([base_python, "-m", "venv", venv_dir], check=True, timeout=180)
    subprocess.run([py, "-m", "pip", "install", "-q", "--upgrade", "pip"], check=False, timeout=300)
    subprocess.run([py, "-m", "pip", "install", "-q", *pip_install], check=True, timeout=1800)
    with open(sentinel, "w") as fh:                # only now is the venv usable (a failed install raises above)
        fh.write(want)
    return py, "built venv"
