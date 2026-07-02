"""calma.spike.orchestrator.tools_exec — the execute tools (build plan §4b, Phase 3).

These are the make-runnable EXPANSIONS: the tools the loop reaches for when the baseline script-run isn't
enough — notebooks (A1), conda (B2), declared-dep install (B1), interpreter-aware era pinning (C1), argv/env
revise (A2), Make targets (A3), post-run output rescan (C2), and a cheap probe gate. Each is FCR-safe: it
only changes HOW the repo runs; the captured computations still flow through the unchanged verify. Tools that
RUN code are ``kind="exec"`` (the pipeline runs them under the supervisor's RSS/CPU/wall caps); pure
transforms/analysis are ``kind="static"``.

Capture arming is uniform: every execution path prepends ``spike/capture`` to PYTHONPATH and sets
``CALMA_CAPTURE_OUT`` (``runner.capture_env``), so the shim auto-installs at interpreter startup — for a
script subprocess, a Make recipe's ``python`` child, AND a notebook kernel (GAP vs the plan: the notebook's
kernel is launched with that same env, so no fragile in-cell shim injection is needed).

Optional heavy deps (papermill/nbclient for A1, micromamba for B2) live in the E2B image, not the local dev
venv; those tools import-/binary-guard and degrade to an honest failed run when the backend is absent.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time

from core import limits as LIM
from runner import build
from runner import capture_env, parse_capture

from . import registry as REG
from .tools_static import _safe_join, _walk


def _s(x) -> str:
    """Coerce a subprocess stream (str | bytes | None — TimeoutExpired.stdout/stderr can be bytes) to str."""
    if isinstance(x, bytes):
        return x.decode("utf-8", "replace")
    return x or ""


# ── A2: argv / env revise (validated) ─────────────────────────────────────────────────────────────────────────
_PATHY = re.compile(r"[/\\]|\.\w{1,5}$")   # looks like a path/filename (a slash or a short extension)


@REG.register("add_argv", kind="static", cost="free",
              summary="Append validated args to an entrypoint argv (A2); path-like args must resolve in the repo.")
def add_argv(entry: list[str], args, repo_dir: str) -> list[str]:
    """A2: many entrypoints need args (`--split test`, `data/x.csv`). Append them, but VALIDATE: a path-like
    arg (contains a separator or a file extension) must resolve inside the repo — a prompt-injected README
    can't send the runner at `/etc/shadow` or a phantom file. Flags/values pass through."""
    argv = list(entry)
    extra = args if isinstance(args, list) else str(args or "").split()
    for a in extra:
        a = str(a)
        if _PATHY.search(a) and not a.startswith("-"):
            full = _safe_join(repo_dir, a)
            if not full or not os.path.exists(full):
                continue                                   # drop a path arg that doesn't resolve in the repo
        argv.append(a)
    return argv


@REG.register("set_env", kind="static", cost="free",
              summary="Merge validated string env vars into an approach's env (A2).")
def set_env(env: dict, kv) -> dict:
    out = dict(env or {})
    if isinstance(kv, dict):
        for k, v in kv.items():
            if isinstance(k, str) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k):
                out[k] = str(v)
    elif isinstance(kv, str) and "=" in kv:
        k, v = kv.split("=", 1)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k):
            out[k] = v
    return out


# ── B1: install spec from the declared manifest ───────────────────────────────────────────────────────────────
@REG.register("install_declared", kind="static", cost="free",
              summary="Build the pip spec list + strict flag from a repo's declared manifest (B1).")
def install_declared(profile) -> dict:
    """B1: turn the profile's declared deps into an install plan. requirements.txt is installed STRICTLY
    (faithful repro); any other manifest (pyproject/poetry/conda-pip/Pipfile) installs tolerantly. `-e .`
    self-install (B3) is surfaced so the caller can add it. Deps are sanitized (prompt-injection rail)."""
    specs = LIM.sanitize_pip(list(getattr(profile, "declared_deps", []) or []))
    strict = getattr(profile, "pkg_manager", "none") == "requirements"
    return {"specs": specs, "strict": strict}


# ── C1: interpreter-aware era pinning ─────────────────────────────────────────────────────────────────────────
_SPEC_OP = re.compile(r"(>=|<=|==|!=|~=|<|>)\s*([0-9][0-9A-Za-z.\*]*)")


def _ver_tuple(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def _pyver_satisfies(requires_python: str, py_version: str) -> bool:
    """Does interpreter ``py_version`` (e.g. '3.10') satisfy a PEP 440 ``requires_python`` (e.g.
    '>=3.8,<3.12')? Best-effort for the common operators; unknown/empty → True (never drop a dep on a parse
    miss). Pure — unit-tested without network."""
    if not requires_python:
        return True
    want = _ver_tuple(py_version)
    for op, ver in _SPEC_OP.findall(requires_python):
        b = _ver_tuple(ver)
        n = min(len(want), len(b)) or 1
        w, bb = want[:n], b[:n]
        if op == ">=" and not (w >= bb):
            return False
        if op == ">" and not (w > bb):
            return False
        if op == "<=" and not (w <= bb):
            return False
        if op == "<" and not (w < bb):
            return False
        if op == "==" and not (w == bb):
            return False
        if op == "!=" and w == bb:
            return False
    return True


def _pypi_requires_python(name: str, version: str, timeout: int = 15):
    import urllib.request
    try:
        url = "https://pypi.org/pypi/%s/%s/json" % (name, version)
        with urllib.request.urlopen(url, timeout=timeout) as fh:
            return (json.load(fh).get("info") or {}).get("requires_python") or ""
    except Exception:  # noqa: BLE001 — network/parse failure → treat as compatible (never drop spuriously)
        return ""


@REG.register("era_pin_compat", kind="static", cost="moderate",
              summary="Era-pin inferred deps, then relax any pin incompatible with the repo's interpreter (C1).")
def era_pin_compat(specs, repo_dir: str, py_version: str | None = None, requires_python_fn=None) -> tuple:
    """C1: build.era_pin pins to the repo's commit-date era but ignores whether that pinned wheel supports the
    declared interpreter. Here we pin, then for each ``name==ver`` check ``requires_python`` against
    ``py_version``; if incompatible, RELAX the pin to a bare name (let pip resolve a compatible version) rather
    than run under a wheel the interpreter can't load. ``requires_python_fn`` is injectable for tests.
    Returns (specs, era_date, notes)."""
    pinned, era = build.era_pin(specs, repo_dir)
    if not py_version:
        return pinned, era, []
    fn = requires_python_fn or _pypi_requires_python
    out, notes = [], []
    for spec in pinned:
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][0-9A-Za-z.\-_]*)$", spec)
        if not m:
            out.append(spec)
            continue
        name, ver = m.group(1), m.group(2)
        rp = fn(name, ver)
        if rp and not _pyver_satisfies(rp, py_version):
            out.append(name)                               # relax the incompatible pin
            notes.append("relaxed %s (era pin %s needs Python %s, repo targets %s)" % (name, ver, rp, py_version))
        else:
            out.append(spec)
    return out, era, notes


# ── C2: post-run output rescan ────────────────────────────────────────────────────────────────────────────────
def snapshot_outputs(repo_dir: str) -> dict:
    """Fingerprint candidate data/prediction files (path→size) BEFORE a run, so rescan_outputs can find what
    the run freshly produced."""
    snap: dict[str, int] = {}
    for abs_p, rel in _walk(repo_dir):
        if os.path.splitext(rel)[1].lower() in (".csv", ".parquet", ".json", ".jsonl", ".npy", ".npz", ".tsv"):
            try:
                snap[rel] = os.path.getsize(abs_p)
            except OSError:
                pass
    return snap


@REG.register("rescan_outputs", kind="static", cost="cheap",
              summary="Prediction files NEWLY created/changed by a run — recapture fresh outputs, not just "
                      "committed ones (C2).")
def rescan_outputs(repo_dir: str, before: dict) -> list[str]:
    """C2: a repo may WRITE its predictions at runtime rather than commit them. After a run, diff the output
    snapshot against ``before`` and return the new/changed data files, so core.artifacts can recompute from a
    fresh run's outputs — not only committed files. Best-effort; returns relative paths."""
    after = snapshot_outputs(repo_dir)
    changed = [rel for rel, size in after.items() if before.get(rel) != size]
    # rank prediction-shaped names first
    changed.sort(key=lambda r: (0 if re.search(r"pred|proba|score|output|result", r, re.I) else 1, r))
    return changed


# ── A2/A4: cheap probe gate (EnvBench static missing-import + import smoke) ────────────────────────────────────
@REG.register("probe_run", kind="exec", cost="cheap",
              summary="Fast pre-run gate: byte-compile the entry + import its third-party roots to catch "
                      "missing deps in ~2s before a full k-run (A2/A4; EnvBench static-import metric).")
def probe_run(repo_dir: str, entry: list[str], python: str | None = None, timeout: int = 30) -> dict:
    """A cheap gate before a full k-run: (1) byte-compile the entry file (syntax), (2) import each third-party
    root it needs in the target interpreter. Returns {"ok", "missing":[...], "error"}. Kills a doomed approach
    fast so the loop can revise (add the dep) without paying for a full run. Never executes the repo's code —
    only imports library roots (an import can run module top-level code, so this stays inside the sandbox
    interpreter the caller provides; the supervisor caps it)."""
    python = python or sys.executable
    argv = list(entry)
    rel = None
    if argv and argv[0] == "-m" and len(argv) > 1:
        base = os.path.join(repo_dir, *argv[1].split("."))
        rel = next((os.path.relpath(c, repo_dir) for c in (base + ".py", os.path.join(base, "__main__.py"))
                    if os.path.isfile(c)), None)
    elif argv and str(argv[0]).endswith(".py") and os.path.isfile(os.path.join(repo_dir, argv[0])):
        rel = argv[0]
    if not rel:
        return {"ok": False, "missing": [], "error": "entrypoint file not found for probe"}

    full = os.path.join(repo_dir, rel)
    try:
        p = subprocess.run([python, "-c", "import py_compile,sys; py_compile.compile(sys.argv[1], doraise=True)", full],
                           cwd=repo_dir, capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            return {"ok": False, "missing": [], "error": "syntax: " + (p.stderr or "")[-300:]}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "missing": [], "error": "probe compile failed: %s" % e}

    import sys as _sys
    stdlib = set(getattr(_sys, "stdlib_module_names", ())) | {"__future__"}
    local = build._local_module_names(repo_dir)
    roots = [r for r in build._imported_roots(full) if r and not r.startswith("_")
             and r not in stdlib and r not in local]
    missing = []
    for r in roots:
        try:
            chk = subprocess.run([python, "-c", "import %s" % r], cwd=repo_dir,
                                 capture_output=True, text=True, timeout=timeout)
            if chk.returncode != 0 and "ModuleNotFoundError" in (chk.stderr or ""):
                missing.append(r)
        except (OSError, subprocess.SubprocessError):
            continue
    return {"ok": not missing, "missing": missing, "error": ""}


# ── A3: Make target ───────────────────────────────────────────────────────────────────────────────────────────
@REG.register("run_make", kind="exec", cost="moderate",
              summary="Run a Makefile target with capture armed; a `python` recipe child auto-arms the shim (A3).")
def run_make(repo_dir: str, target: str, *, k: int = 2, hooks: str = "sklearn", targets=None,
             timeout: int = 600, env_extra=None) -> dict:
    """A3: dispatch `make <target>` k times with the capture env set, so any `python …` the recipe launches
    auto-arms capture (PYTHONPATH inheritance). Returns the same shape as run_local. `target` is validated to a
    safe token (no shell metacharacters) — the action space is a Make target name, never arbitrary shell."""
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", target or ""):
        return {"runs": [], "meta": [{"stderr_tail": "unsafe make target %r" % target}], "ran_ok": False,
                "hooks_armed": None, "fuzz": None, "n_calls": []}
    runs, meta = [], []
    for i in range(max(1, k)):
        with tempfile.NamedTemporaryFile(prefix="calma_cap_", suffix=".jsonl", delete=False) as tf:
            out_path = tf.name
        base = dict(os.environ)
        base.setdefault("MPLBACKEND", "Agg")
        base.setdefault("PYTHONHASHSEED", "0")
        base.setdefault("TZ", "UTC")
        if env_extra:
            base.update(env_extra)
        base["CALMA_RUN_INDEX"] = str(i)
        env = capture_env(base, out_path, hooks=hooks, targets=targets)
        t0 = time.time()
        try:
            p = subprocess.run(["make", target], cwd=repo_dir, env=env, timeout=timeout,
                               capture_output=True, text=True)
            rc, out, err, killed = p.returncode, p.stdout, p.stderr, False
        except subprocess.TimeoutExpired as e:
            rc, out, err, killed = -9, _s(e.stdout), _s(e.stderr) + "\n[timeout]", True
        except (OSError, subprocess.SubprocessError) as e:
            rc, out, err, killed = -1, "", "make unavailable: %s" % e, False
        runs.append(parse_capture(out_path))
        meta.append({"returncode": rc, "killed": killed, "seconds": time.time() - t0,
                     "stdout_tail": (out or "")[-2000:], "stderr_tail": (err or "")[-2000:]})
        try:
            os.remove(out_path)
        except OSError:
            pass
    return {"runs": runs, "meta": meta, "ran_ok": all(m["returncode"] == 0 for m in meta),
            "hooks_armed": None, "fuzz": None, "n_calls": [len(r) for r in runs]}


# ── A1: notebook execution (papermill/nbclient, env-armed kernel) ─────────────────────────────────────────────
def notebook_available() -> bool:
    try:
        import nbclient  # noqa: F401
        import nbformat  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


@REG.register("run_notebook", kind="exec", cost="heavy",
              summary="Execute a Jupyter notebook with the capture shim armed in the kernel env; per-cell "
                      "timeout, errors surface (A1).")
def run_notebook(repo_dir: str, nb_rel: str, *, k: int = 2, hooks: str = "sklearn", targets=None,
                 timeout: int = 600, cell_timeout: int = 300, python: str | None = None) -> dict:
    """A1: run a notebook end-to-end and capture the metric calls its cells make. The kernel is launched with
    the SAME capture env as a script subprocess (PYTHONPATH + CALMA_CAPTURE_OUT), so the shim auto-arms — no
    in-cell injection. Per SOTA notebook-as-a-job practice: pin kernel python3, enforce a per-cell timeout,
    and let cell errors surface (a silent half-run is worse than a clean failure). Same return shape as
    run_local. Degrades to an honest failed run when nbclient/nbformat aren't installed (they ship in the E2B
    image, not the local dev venv)."""
    nb_path = _safe_join(repo_dir, nb_rel[3:] if nb_rel.startswith("nb:") else nb_rel)
    if not nb_path or not os.path.isfile(nb_path):
        return _nb_fail("notebook not found: %s" % nb_rel)
    if not notebook_available():
        return _nb_fail("notebook runner unavailable (install nbclient/nbformat; ships in the E2B image)")

    import nbformat
    from nbclient import NotebookClient
    from nbclient.exceptions import CellExecutionError

    runs, meta = [], []
    for i in range(max(1, k)):
        with tempfile.NamedTemporaryFile(prefix="calma_cap_", suffix=".jsonl", delete=False) as tf:
            out_path = tf.name
        base = dict(os.environ)
        base.setdefault("MPLBACKEND", "Agg")
        base.setdefault("PYTHONHASHSEED", "0")
        base.setdefault("TZ", "UTC")
        base["CALMA_RUN_INDEX"] = str(i)
        env = capture_env(base, out_path, hooks=hooks, targets=targets)
        t0, rc, err, killed = time.time(), 0, "", False
        prev_env = dict(os.environ)
        try:
            os.environ.update(env)                          # the kernel inherits os.environ → capture auto-arms
            nb = nbformat.read(nb_path, as_version=4)
            client = NotebookClient(nb, timeout=cell_timeout, kernel_name="python3",
                                    allow_errors=False, resources={"metadata": {"path": repo_dir}})
            client.execute()
        except CellExecutionError as e:
            rc, err = 1, str(e)[-2000:]
        except Exception as e:  # noqa: BLE001 — kernel/startup failure → honest failed run
            rc, err = 1, ("notebook execution failed: %s" % e)[-2000:]
        finally:
            os.environ.clear()
            os.environ.update(prev_env)
        runs.append(parse_capture(out_path))
        meta.append({"returncode": rc, "killed": killed, "seconds": time.time() - t0,
                     "stdout_tail": "", "stderr_tail": err})
        try:
            os.remove(out_path)
        except OSError:
            pass
    return {"runs": runs, "meta": meta, "ran_ok": all(m["returncode"] == 0 for m in meta),
            "hooks_armed": None, "fuzz": None, "n_calls": [len(r) for r in runs]}


def _nb_fail(msg: str) -> dict:
    return {"runs": [], "meta": [{"returncode": 1, "killed": False, "seconds": 0.0,
                                  "stdout_tail": "", "stderr_tail": msg}],
            "ran_ok": False, "hooks_armed": None, "fuzz": None, "n_calls": []}


# ── B2: conda environment (micromamba) ────────────────────────────────────────────────────────────────────────
def micromamba_bin() -> str | None:
    import shutil
    return shutil.which("micromamba") or shutil.which("mamba") or shutil.which("conda")


# ── A3 long tail: R / Julia / shell interpreters ──────────────────────────────────────────────────────────────
_LANG_INTERP = {"r": "Rscript", "julia": "julia", "shell": "bash", "sh": "sh"}


def lang_available(lang: str) -> bool:
    import shutil
    return bool(shutil.which(_LANG_INTERP.get(lang, "")))


@REG.register("run_lang", kind="exec", cost="moderate",
              summary="Run an R/Julia/shell entrypoint with the capture env set (a python child auto-arms); "
                      "honest degradation when the interpreter is absent (A3 long tail).")
def run_lang(repo_dir: str, lang: str, argv, *, k: int = 1, hooks: str = "sklearn", targets=None,
             timeout: int = 600, env_extra=None) -> dict:
    """A3 remainder (build plan Phase 5): dispatch a non-Python entrypoint. The capture env is still set, so
    any `python` the R/Julia/shell script shells out to auto-arms the shim (a common polyglot shape). The
    interpreters ship in the E2B polyglot image, not the local dev venv — absent → an honest failed run."""
    import shutil
    interp = _LANG_INTERP.get(lang)
    binp = shutil.which(interp) if interp else None
    if not binp:
        return _lang_fail("no %s interpreter (%s) — ships in the E2B polyglot image" % (lang, interp or lang))
    argv = list(argv) if isinstance(argv, (list, tuple)) else [str(argv)]
    runs, meta = [], []
    for i in range(max(1, k)):
        with tempfile.NamedTemporaryFile(prefix="calma_cap_", suffix=".jsonl", delete=False) as tf:
            out_path = tf.name
        base = dict(os.environ)
        base.setdefault("MPLBACKEND", "Agg")
        base.setdefault("PYTHONHASHSEED", "0")
        base.setdefault("TZ", "UTC")
        if env_extra:
            base.update(env_extra)
        base["CALMA_RUN_INDEX"] = str(i)
        env = capture_env(base, out_path, hooks=hooks, targets=targets)
        t0 = time.time()
        try:
            p = subprocess.run([binp, *argv], cwd=repo_dir, env=env, timeout=timeout,
                               capture_output=True, text=True)
            rc, out, err, killed = p.returncode, p.stdout, p.stderr, False
        except subprocess.TimeoutExpired as e:
            rc, out, err, killed = -9, _s(e.stdout), _s(e.stderr) + "\n[timeout]", True
        except (OSError, subprocess.SubprocessError) as e:
            rc, out, err, killed = -1, "", "%s failed: %s" % (interp, e), False
        runs.append(parse_capture(out_path))
        meta.append({"returncode": rc, "killed": killed, "seconds": time.time() - t0,
                     "stdout_tail": (out or "")[-2000:], "stderr_tail": (err or "")[-2000:]})
        try:
            os.remove(out_path)
        except OSError:
            pass
    return {"runs": runs, "meta": meta, "ran_ok": all(m["returncode"] == 0 for m in meta),
            "hooks_armed": None, "fuzz": None, "n_calls": [len(r) for r in runs]}


def _lang_fail(msg: str) -> dict:
    return {"runs": [], "meta": [{"returncode": 1, "killed": False, "seconds": 0.0,
                                  "stdout_tail": "", "stderr_tail": msg}],
            "ran_ok": False, "hooks_armed": None, "fuzz": None, "n_calls": []}


@REG.register("build_conda", kind="exec", cost="heavy",
              summary="Create a conda env from environment.yml via micromamba; returns the env's python (B2).")
def build_conda(repo_dir: str, env_file: str = "environment.yml", *, envs_dir: str | None = None,
                name: str = "calma-conda", timeout: int = 1800) -> dict:
    """B2: build a conda environment from environment.yml with micromamba (fast, no base conda). Returns
    {"ok", "python", "note"} — the env's interpreter path for the runner to use. Degrades honestly when no
    micromamba/mamba/conda binary is present (it ships in the E2B conda image variant, not the local venv)."""
    envf = _safe_join(repo_dir, env_file)
    if not envf or not os.path.isfile(envf):
        return {"ok": False, "python": None, "note": "no %s in repo" % env_file}
    mm = micromamba_bin()
    if not mm:
        return {"ok": False, "python": None, "note": "no micromamba/conda binary (ships in the E2B conda image)"}
    envs_dir = envs_dir or os.path.join(os.path.dirname(repo_dir), ".conda-envs")
    prefix = os.path.join(envs_dir, name)
    py = os.path.join(prefix, "bin", "python")
    if os.path.isfile(py):
        return {"ok": True, "python": py, "note": "cached conda env"}
    os.makedirs(envs_dir, exist_ok=True)
    try:
        cmd = [mm, "create", "-y", "-p", prefix, "-f", envf] if "micromamba" in mm or "mamba" in mm \
            else [mm, "env", "create", "-p", prefix, "-f", envf]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if p.returncode == 0 and os.path.isfile(py):
            return {"ok": True, "python": py, "note": "built conda env"}
        return {"ok": False, "python": None, "note": "conda create failed: " + (p.stderr or "")[-300:]}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "python": None, "note": "conda create error: %s" % e}
