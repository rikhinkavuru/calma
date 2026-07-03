"""modal_runner — run a repo entrypoint on a GPU sandbox (Modal) with capture armed.

Why a second backend at all: E2B's Firecracker microVMs cannot do GPU passthrough (four-unlocks research —
confirmed across ZenML/Beam/Particula/AICraftGuide). Modal is the only mature sandbox that puts a GPU *inside*
the isolation boundary (gVisor), with the exact primitives we need — `gpu=`, `secrets=`, `block_network`,
`cidr_allowlist`, a configurable timeout. So GPU verification routes here; everything CPU stays on E2B.

This is a TRANSPORT only. The run contract — how a capture run is armed, how the sandbox lifetime is sized, the
result dict the deterministic verify consumes — is the shared `runner.effector`, identical to e2b_runner. That
keeps the two backends from drifting and keeps the FCR surface in one place: nothing here computes a verdict; it
returns the repo's OWN captured computations, and a misroute/failure yields an empty run → DISCOVERED.

Degrades honestly: if `modal` isn't installed or no token is configured, it returns the standard empty result
(the CPU verdict already stands; GPU escalation is simply declined) — never a crash, never a fabricated number.
"""
from __future__ import annotations

import os
import shlex
import tarfile
import tempfile
import time

from . import CAPTURE_DIR, effector, parse_capture
from .e2b_runner import _SHIM_FILES, _command_for, _note

# The GPU science image mirrors the E2B template but with CUDA wheels instead of CPU torch. Built once by Modal
# and cached; a repo's exact pins still install at runtime.
_ML = ["numpy", "scipy", "scikit-learn", "pandas", "matplotlib", "lightgbm", "xgboost", "statsmodels"]
_NOTEBOOK = ["nbclient", "nbformat", "ipykernel"]
_TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu121"

_DEFAULT_GPU = os.environ.get("CALMA_MODAL_GPU", "A100")
_APP_NAME = os.environ.get("CALMA_MODAL_APP", "calma-verify-gpu")


def modal_available() -> bool:
    """True iff the Modal SDK is importable AND a token is configured (env or ~/.modal.toml). Cheap gate so the
    reactive GPU escalation only fires when it can actually succeed."""
    try:
        import modal  # type: ignore[import-not-found]  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    if os.environ.get("MODAL_TOKEN_ID") and os.environ.get("MODAL_TOKEN_SECRET"):
        return True
    return os.path.isfile(os.path.expanduser("~/.modal.toml"))


def _gpu_image(python_version, pip_install):
    """The cached CUDA image: science stack + CUDA torch + notebook runtime, with the capture shim on
    /capture. Repo-specific deps install at runtime inside the sandbox (like E2B), not baked here."""
    import modal  # type: ignore[import-not-found]
    py = (python_version or "3.11")
    img = (modal.Image.debian_slim(python_version=py)
           .apt_install("git", "build-essential")
           .pip_install(*_ML, *_NOTEBOOK)
           .pip_install("torch", extra_options="--index-url %s" % _TORCH_CUDA_INDEX)
           .env({"PIP_PREFER_BINARY": "1", "MPLBACKEND": "Agg"}))
    return img


def _stage_repo(sb, repo_dir, dest="/work", log=None):
    """Tar the repo locally, write the single archive into the sandbox, extract in place — the same one
    round-trip staging as E2B (`.git`/`__pycache__` dropped). Best-effort per-file fallback on any failure."""
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as tf:
            tmp = tf.name
        with tarfile.open(tmp, "w:gz") as tar:
            for root, dirs, files in os.walk(repo_dir):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
                for fn in files:
                    if fn.endswith(".pyc"):
                        continue
                    lp = os.path.join(root, fn)
                    try:
                        tar.add(lp, arcname=os.path.relpath(lp, repo_dir).replace(os.sep, "/"), recursive=False)
                    except OSError:
                        pass
        sb.exec("mkdir", "-p", dest).wait()
        with open(tmp, "rb") as fh, sb.open(dest + "/_calma_repo.tgz", "wb") as rf:
            rf.write(fh.read())
        p = sb.exec("bash", "-lc", "tar xzf %s/_calma_repo.tgz -C %s && rm -f %s/_calma_repo.tgz"
                    % (dest, dest, dest))
        p.wait()
        _note(log, "Modal: staged repo archive → %s" % dest)
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def _upload_shim(sb, dest="/capture", log=None):
    sb.exec("mkdir", "-p", dest).wait()
    for fn in _SHIM_FILES:
        try:
            with open(os.path.join(CAPTURE_DIR, fn), "rb") as fh, sb.open(dest + "/" + fn, "wb") as rf:
                rf.write(fh.read())
        except OSError:
            pass


def _exec_capture(sb, argv_str, env, timeout, log=None):
    """Run one command in the sandbox, collect stdout/stderr, return (exit_code, out, err)."""
    p = sb.exec("bash", "-lc", "cd /work && " + argv_str, env=env, timeout=timeout)
    out = _read_stream(getattr(p, "stdout", None))
    err = _read_stream(getattr(p, "stderr", None))
    try:
        rc = p.wait()
    except Exception as e:  # noqa: BLE001
        rc, err = -9, (err + "\nmodal exec error: %s" % e)
    rc = 0 if rc is None else int(rc)
    return rc, out, err


def _read_stream(s):
    if s is None:
        return ""
    try:
        data = s.read()
    except Exception:  # noqa: BLE001
        return ""
    return data if isinstance(data, str) else (data.decode("utf-8", "replace") if data else "")


def run_modal(repo_dir, entry=None, *, k=2, hooks="sklearn", targets=None, timeout=1800, gpu=None,
              pip_install=None, pip_strict=True, python_version=None, cpu_cores=0, fuzz=False,
              max_elems=None, log=None, disk_gb=0):
    """Run `entry` k× on a GPU sandbox, capture armed, one sandbox reused across the k runs (deps install once).
    Returns the effector-standard result dict + GPU-seconds telemetry in cost. Honest empty result when Modal is
    unavailable — the caller keeps the CPU verdict."""
    gpu = gpu or _DEFAULT_GPU
    entry = list(entry or [])
    t_start = time.time()
    if not modal_available():
        _note(log, "Modal: unavailable (SDK/token missing) — GPU escalation declined")
        return effector.shape_setup_error("modal unavailable (no SDK/token) — GPU verify declined", k, 0.0)

    import modal  # type: ignore[import-not-found]
    sb = None
    build_seconds = 0.0
    inst_timeout = max(timeout, 1800)                  # a GPU repo is heavy by definition → generous install budget
    life = effector.size_sandbox_life(inst_timeout, k, timeout)
    try:
        app = modal.App.lookup(_APP_NAME, create_if_missing=True)
        image = _gpu_image(python_version, pip_install)
        _note(log, "Modal: creating GPU sandbox (%s, lifetime %dm)…" % (gpu, life // 60))
        create_kw = dict(app=app, image=image, gpu=gpu, timeout=life,
                         cpu=float(cpu_cores) if cpu_cores else 4.0, memory=16384,
                         block_network=False if pip_install else True, workdir="/work")
        if disk_gb:
            create_kw["ephemeral_disk"] = int(disk_gb) * 1024   # MiB — tier disk budget for big datasets
        sb = modal.Sandbox.create(**create_kw)
        _upload_shim(sb, log=log)
        _stage_repo(sb, repo_dir, log=log)
        if pip_install:
            _install(sb, pip_install, pip_strict, inst_timeout, log=log)
        build_seconds = time.time() - t_start
        _note(log, "Modal: environment ready (%.0fs)" % build_seconds)
    except Exception as e:  # noqa: BLE001 — setup failed → every run fails identically
        build_seconds = time.time() - t_start
        _note(log, "Modal: setup failed after %.0fs — %s" % (build_seconds, str(e)[:200]))
        if sb is not None:
            _terminate(sb)
        return effector.shape_setup_error("modal error: %s" % e, k, build_seconds)

    runs, meta = [], []
    hooks_armed = None
    fuzz_records = None
    run_seconds = 0.0
    try:
        for i in range(max(1, k)):
            out_remote = "/capture/calls_%d.jsonl" % i
            env = effector.capture_run_env(i, out_remote, hooks=hooks, targets=targets,
                                           max_elems=max_elems, fuzz=fuzz)
            t0 = time.time()
            _note(log, "Modal: running `%s` (run %d/%d)…" % (" ".join(entry), i + 1, max(1, k)))
            rc, out, err = _exec_capture(sb, _command_for("python", entry), env, timeout, log=log)
            out_local = _pull(sb, out_remote)
            parsed = parse_capture(out_local) if out_local else []
            if hooks_armed is None:
                harmed = _pull(sb, out_remote + ".hooks")
                if harmed:
                    try:
                        import json
                        with open(harmed) as fh:
                            hooks_armed = json.load(fh)
                    except Exception:  # noqa: BLE001
                        pass
            if fuzz and fuzz_records is None:
                fz = _pull(sb, out_remote + ".fuzz")
                if fz:
                    recs = parse_capture(fz)
                    if recs:
                        fuzz_records = recs
            dt = time.time() - t0
            run_seconds += dt
            _note(log, "Modal: run %d/%d done — %.0fs, exit %d, %d computation(s)"
                  % (i + 1, max(1, k), dt, rc, len(parsed)))
            runs.append(parsed)
            meta.append({"returncode": rc, "killed": "[timeout]" in err, "seconds": dt,
                         "stdout_tail": (out or "")[-2000:], "stderr_tail": (err or "")[-2000:]})
    finally:
        if sb is not None:
            _terminate(sb)
    gpu_seconds = round(build_seconds + run_seconds, 2)      # the whole sandbox held the GPU → meter all of it
    return effector.shape_result(runs, meta, build_seconds=build_seconds, run_seconds=run_seconds,
                                 hooks_armed=hooks_armed, fuzz=fuzz_records, python_used=python_version,
                                 extra_cost={"gpu_seconds": gpu_seconds, "gpu": gpu})


def _install(sb, pip_install, pip_strict, timeout, log=None):
    """Install deps once. Strict (requirements.txt) → one command; tolerant (inferred) → per-package, misses
    ignored. On GPU we do NOT swap for CPU wheels (the whole point is the accelerator)."""
    if not pip_install:
        return
    if pip_strict:
        sb.exec("bash", "-lc", "pip install -q " + " ".join(shlex.quote(p) for p in pip_install),
                timeout=timeout).wait()
    else:
        for pkg in pip_install:
            try:
                _note(log, "  installing %s…" % pkg)
                sb.exec("bash", "-lc", "pip install -q " + shlex.quote(pkg), timeout=timeout).wait()
            except Exception:  # noqa: BLE001
                _note(log, "  (skipped %s — install failed, best-effort)" % pkg)


def _pull(sb, remote):
    """Read a file out of the sandbox into a temp file; return its local path or None."""
    try:
        with sb.open(remote, "rb") as fh:
            data = fh.read()
    except Exception:  # noqa: BLE001
        return None
    with tempfile.NamedTemporaryFile("wb", suffix=".jsonl", delete=False) as tf:
        tf.write(data if isinstance(data, bytes) else str(data).encode())
        return tf.name


def _terminate(sb):
    for m in ("terminate", "kill"):
        fn = getattr(sb, m, None)
        if callable(fn):
            try:
                fn()
                return
            except Exception:  # noqa: BLE001
                pass
