"""e2b_runner — run a repo entrypoint inside an E2B Firecracker microVM with capture armed.

This is the real isolation path for UNTRUSTED user code (rebuild guide §8: dedicated kernel, ~150ms boot,
infra-enforced egress control). The SDK usage is lifted from the proven backend in the old engine
(run_hermetic._RealE2BSession): Sandbox.create(template, allow_internet_access=…), commands.run,
files.write/read/list, kill.

Same return shape as local_runner so core.diff is runner-agnostic. The capture shim is uploaded to /capture
and put on PYTHONPATH, so the repo's `from sklearn.metrics import …` binds to our wrapped functions inside
the VM. Artifacts (the capture JSONL) are pulled host-side; the sandbox is killed after each run (never
reused across tenants).

Two network postures:
  allow_internet=False  the hardened default — run with egress denied (determinism + safety wall).
  allow_internet=True   only for a build phase that must `pip install` deps (the guide's build-runnable
                        step); the spike notes this and a production split would build-then-run-net-off.
"""
from __future__ import annotations

import json
import shlex
import os
import tempfile
import time

from . import CAPTURE_DIR, build, parse_capture

_SHIM_FILES = ("calma_capture.py", "sitecustomize.py")
_MAX_SANDBOX_S = 3600   # hard cap on a sandbox's lifetime (build + all k runs) — safety bound on cost/E2B limits


def _load_dotenv(path):
    env = {}
    if not os.path.isfile(path):
        return env
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.strip()
            # strip an inline comment (" # ...") that isn't inside quotes
            if not (v[:1] in ("'", '"')):
                hashpos = v.find(" #")
                if hashpos != -1:
                    v = v[:hashpos]
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def e2b_config(dotenv_path=None):
    """Resolve (api_key, endpoint, template) from the environment, falling back to the repo .env."""
    cfg = {k: os.environ.get(k) for k in ("CALMA_E2B_API_KEY", "CALMA_E2B_ENDPOINT", "CALMA_E2B_TEMPLATE")}
    if not cfg["CALMA_E2B_API_KEY"] and dotenv_path:
        de = _load_dotenv(dotenv_path)
        for k in cfg:
            cfg[k] = cfg[k] or de.get(k)
    return {"api_key": cfg["CALMA_E2B_API_KEY"], "domain": cfg["CALMA_E2B_ENDPOINT"],
            "template": cfg["CALMA_E2B_TEMPLATE"]}


def _create_sandbox(cfg, timeout, allow_internet):
    from e2b import Sandbox
    api = {"api_key": cfg["api_key"]}
    if cfg.get("domain"):
        api["domain"] = cfg["domain"]
    kw = dict(timeout=max(1, int(timeout)), allow_internet_access=allow_internet, **api)
    if cfg.get("template"):
        return Sandbox.create(template=cfg["template"], **kw)
    return Sandbox.create(**kw)


def _upload_dir(sbx, local_dir, dest):
    for root, _dirs, files in os.walk(local_dir):
        if "__pycache__" in root.split(os.sep):
            continue
        for fn in files:
            if fn.endswith(".pyc"):
                continue
            lp = os.path.join(root, fn)
            rel = os.path.relpath(lp, local_dir).replace(os.sep, "/")
            try:
                with open(lp, "rb") as fh:
                    sbx.files.write(dest + "/" + rel, fh.read())
            except OSError:
                pass


def _pull_capture(sbx, remote):
    """Read a capture JSONL out of the sandbox into a temp file; return its local path or None."""
    try:
        data = sbx.files.read(remote)
    except Exception:  # noqa: BLE001 — no calls captured (file may not exist)
        return None
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as tf:
        tf.write(data if isinstance(data, str) else data.decode("utf-8", "replace"))
        return tf.name


def _install(sbx, pip_install, pip_strict, timeout, pip_cmd="pip install -q", log=None):
    """Install deps ONCE. Strict (requirements.txt) → one command, failure surfaces, deps respected as pinned
    (faithful repro). Tolerant (inferred) → per-package, ignore misses so one bad guess can't abort the env,
    and swap heavy packages for their CPU wheels (avoids multi-GB CUDA downloads on the CPU tier). Streams
    install output (warnings/build logs) live, so a slow install is visible rather than a silent stall."""
    if not pip_install:
        return
    if pip_strict:
        _cmd_run(sbx, pip_cmd + " " + " ".join(pip_install), timeout=timeout, log=log, prefix="  pip| ", stream=True)
    else:
        for pkg in pip_install:
            try:
                args = build.cpu_pip_args(pkg)               # torch → CPU wheel, etc.
                _note(log, "  installing %s…" % pkg)
                _cmd_run(sbx, pip_cmd + " " + " ".join(shlex.quote(a) for a in args),
                         timeout=timeout, log=log, prefix="  pip| ", stream=True)
            except Exception:  # noqa: BLE001
                _note(log, "  (skipped %s — install failed, best-effort)" % pkg)


def _ensure_uv(sbx, timeout):
    """Bootstrap uv and CONFIRM `uv pip install --system` actually works on this base (a PEP-668
    externally-managed interpreter can reject it). Returns True only when uv is usable as the system
    installer — otherwise the caller falls back to plain pip, so we trade speed for nothing and never
    regress correctness. uv is 10-50x faster than pip on scientific stacks and is a pip-compatible drop-in."""
    try:
        sbx.commands.run("pip install -q uv", timeout=min(int(timeout), 180))
        sbx.commands.run("uv pip install -q --system packaging", timeout=min(int(timeout), 120))  # viability probe
        return True
    except Exception:  # noqa: BLE001
        return False


def _provision_python(sbx, version, timeout, log=None):
    """Resolve (python_exe, install_cmd, version_used). The installer is uv when it works (much faster);
    pip is the fallback. For a DECLARED version we also provision that interpreter via uv (faithful repro),
    falling back to the sandbox python if it can't be provisioned — an honest run on the default beats no run.
    --prefer-binary on the pip fallback avoids a silent multi-minute source build."""
    pip_default = ("python", "pip install -q --prefer-binary", None)
    if not version:
        if _ensure_uv(sbx, timeout):
            _note(log, "installer: uv (fast)")
            return "python", "uv pip install -q --system", None
        _note(log, "installer: pip (uv unavailable)")
        return pip_default
    try:
        sbx.commands.run("pip install -q uv", timeout=timeout)
        sbx.commands.run("uv python install %s" % shlex.quote(version), timeout=timeout)
        sbx.commands.run("uv venv --python %s /pyenv" % shlex.quote(version), timeout=timeout)
        py = "/pyenv/bin/python"
        return py, "uv pip install -q --python %s" % py, version
    except Exception:  # noqa: BLE001 — version not provisionable → sandbox python (still prefer uv as installer)
        if _ensure_uv(sbx, timeout):
            return "python", "uv pip install -q --system", None
        return pip_default


def _note(log, msg):
    """Forward one progress line to the job log, never letting a logging hiccup break a run."""
    if log:
        try:
            log(msg)
        except Exception:  # noqa: BLE001
            pass


def _streamer(log, prefix, cap=200):
    """An on_stdout/on_stderr callback that forwards the sandbox's LIVE output into the job log (capped, so a
    chatty training run can't flood it — the full tail is still captured for the final view)."""
    state = {"n": 0}

    def on_line(line):
        if not log:
            return
        s = (line or "").rstrip()
        if not s:
            return
        if state["n"] < cap:
            _note(log, prefix + s[:300])
        elif state["n"] == cap:
            _note(log, prefix + "… (live output truncated — full tail shown on completion)")
        state["n"] += 1

    return on_line


def _cmd_run(sbx, cmd, *, log=None, prefix="  | ", stream=False, **kw):
    """sbx.commands.run, optionally streaming the command's output into the job log live. Tolerant of SDK
    variants that don't accept on_stdout/on_stderr — falls back to a plain (still-captured) run."""
    if stream and log:
        try:
            return sbx.commands.run(cmd, on_stdout=_streamer(log, prefix),
                                    on_stderr=_streamer(log, prefix.rstrip()[:-1] + "! "), **kw)
        except TypeError:
            pass
    return sbx.commands.run(cmd, **kw)


def run_e2b(repo_dir, entry=None, *, k=2, hooks="sklearn", targets=None, timeout=600,
            allow_internet=False, pip_install=None, pip_strict=True, python_version=None,
            cfg=None, max_elems=None, log=None, resolve=None):
    """ONE sandbox: stage + install ONCE, then run the entrypoint k× inside it (each a fresh process with its
    own capture file). Reusing the sandbox across the determinism runs is the big cost lever — the dominant
    `pip install` is paid once, not k×, and it's MORE correct for determinism (identical env across runs, so
    only code-level nondeterminism shows). Returns the runner-agnostic shape + cost telemetry.

    `resolve`, if given, is a callable returning (entry, pip_install, pip_strict). It is invoked AFTER the
    microVM boots and the repo uploads — never before — so the caller can run an AI run-plan CONCURRENTLY with
    the boot and only block on it here, at the last moment before deps install. When `resolve` is set the deps
    are unknown at boot, so the sandbox's lifetime CEILING is sized conservatively (free: billing is per
    running-second and the sandbox is killed when done)."""
    cfg = cfg or e2b_config(os.path.join(os.path.dirname(CAPTURE_DIR), os.pardir, ".env"))
    if not cfg.get("api_key"):
        return {"runs": [], "meta": [], "ran_ok": False, "error": "no E2B api key configured",
                "hooks_armed": None, "n_calls": [], "cost": {}}
    entry = list(entry or [])
    runs, meta = [], []
    hooks_armed = None
    sbx = None
    pybin, python_used = "python", None
    t_start = time.time()
    build_seconds = 0.0
    # heavy deps (torch/tf/…) need a much bigger install budget than the run timeout. With a deferred `resolve`
    # the deps aren't known until after boot, so size the ceiling for the heavy case (harmless — see docstring).
    heavy = True if resolve else build.deps_are_heavy(pip_install)
    inst_timeout = max(timeout, 1800) if heavy else timeout
    # The sandbox must OUTLIVE the whole session — build + ALL k runs — or it hits its end-of-life mid-run and
    # the run is killed (StreamReset), capturing nothing. The old code created it with just the per-run
    # timeout, so a repo whose build + k·runs approached one run's timeout silently failed deep verify
    # (gb_kmer: the sandbox died at 600s during run 2 → 0 computations captured → fell back to discovery).
    sandbox_life = min(inst_timeout + max(1, k) * timeout + 120, _MAX_SANDBOX_S)
    try:
        _note(log, "E2B: creating microVM (lifetime %dm)…" % (sandbox_life // 60))
        sbx = _create_sandbox(cfg, sandbox_life,
                              allow_internet or resolve is not None or bool(pip_install) or bool(python_version))
        _note(log, "E2B: microVM up (%.1fs) — uploading repo + capture shim" % (time.time() - t_start))
        for fn in _SHIM_FILES:                                   # stage the capture shim + the repo (once)
            with open(os.path.join(CAPTURE_DIR, fn), "rb") as fh:
                sbx.files.write("/capture/" + fn, fh.read())
        _upload_dir(sbx, repo_dir, "/work")
        if resolve is not None:                                 # join the run-plan NOW — it ran during the boot
            entry, pip_install, pip_strict = resolve()
            entry = list(entry)
            heavy = build.deps_are_heavy(pip_install)           # deps known now → right-size the install budget
            inst_timeout = max(timeout, 1800) if heavy else timeout
        pybin, pip_cmd, python_used = _provision_python(sbx, python_version, inst_timeout, log=log)  # declared py (or default)
        if python_used:
            _note(log, "E2B: provisioned declared Python %s" % python_used)
        if pip_install:
            _note(log, "E2B: installing %d dep(s)%s — %s" % (
                len(pip_install), " [heavy: up to %dm]" % (inst_timeout // 60) if heavy else "",
                " ".join(pip_install)[:200]))
        _install(sbx, pip_install, pip_strict, inst_timeout, pip_cmd, log=log)  # install (once)
        build_seconds = time.time() - t_start
        _note(log, "E2B: environment ready (%.0fs total)" % build_seconds)
    except Exception as e:  # noqa: BLE001 — setup failed → every run fails identically
        build_seconds = time.time() - t_start
        _note(log, "E2B: setup failed after %.0fs — %s" % (build_seconds, str(e)[:200]))
        if sbx is not None:
            try:
                sbx.kill()
            except Exception:  # noqa: BLE001
                pass
        err = "e2b error: %s" % e
        meta = [{"returncode": -9, "killed": "timeout" in str(e).lower(), "seconds": 0.0,
                 "stdout_tail": "", "stderr_tail": err} for _ in range(max(1, k))]
        return {"runs": [[] for _ in range(max(1, k))], "meta": meta, "ran_ok": False,
                "hooks_armed": None, "n_calls": [], "error": err,
                "cost": {"sandbox_seconds": round(build_seconds, 2), "build_seconds": round(build_seconds, 2),
                         "runs": 0, "reused_sandbox": True}}

    run_seconds = 0.0
    try:
        for i in range(max(1, k)):
            out_remote = "/capture/calls_%d.jsonl" % i           # fresh capture file per run
            t0 = time.time()
            _note(log, "E2B: running `%s` (run %d/%d)…" % (" ".join(entry), i + 1, max(1, k)))
            try:
                envs = {"PYTHONPATH": "/capture", "CALMA_CAPTURE_OUT": out_remote,
                        "CALMA_CAPTURE_HOOKS": hooks, "CALMA_RUN_INDEX": str(i),
                        # determinism-enforcing env (core.determinism.enforced_env) — freeze hash/tz so a
                        # deterministic-by-construction repo reproduces cleanly (and adaptive-k is sound).
                        "PYTHONHASHSEED": "0", "TZ": "UTC"}
                if targets:
                    envs["CALMA_CAPTURE_TARGETS"] = json.dumps(targets)
                if max_elems:
                    envs["CALMA_CAPTURE_MAX_ELEMS"] = str(max_elems)
                # stream the run's stdout/stderr LIVE into the job log — the repo's own prints are the best
                # signal for "what is it actually doing" during a long run.
                r = _cmd_run(sbx, pybin + " " + " ".join(entry), cwd="/work", envs=envs, timeout=timeout,
                             log=log, prefix="  | ", stream=True)
                rc = getattr(r, "exit_code", 0) or 0
                out, err, killed = getattr(r, "stdout", "") or "", getattr(r, "stderr", "") or "", False
                out_local = _pull_capture(sbx, out_remote)
                if hooks_armed is None:
                    try:
                        h = sbx.files.read(out_remote + ".hooks")
                        hooks_armed = json.loads(h if isinstance(h, str) else h.decode())
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as e:  # noqa: BLE001 — this run errored; others may still succeed
                rc, out, err, killed, out_local = -9, "", "e2b error: %s" % e, "timeout" in str(e).lower(), None
            dt = time.time() - t0
            run_seconds += dt
            parsed = parse_capture(out_local) if out_local else []
            _note(log, "E2B: run %d/%d done — %.0fs, exit %d, %d computation(s) captured%s"
                  % (i + 1, max(1, k), dt, rc, len(parsed), " [killed: timeout]" if killed else ""))
            runs.append(parsed)
            if out_local:
                try:
                    os.remove(out_local)
                except OSError:
                    pass
            meta.append({"returncode": rc, "killed": killed, "seconds": dt,
                         "stdout_tail": (out or "")[-2000:], "stderr_tail": (err or "")[-2000:]})
    finally:
        if sbx is not None:
            try:
                sbx.kill()
            except Exception:  # noqa: BLE001
                pass
    ran_ok = bool(meta) and all(m["returncode"] == 0 for m in meta)
    return {"runs": runs, "meta": meta, "ran_ok": ran_ok, "hooks_armed": hooks_armed,
            "n_calls": [len(r) for r in runs],
            "cost": {"sandbox_seconds": round(build_seconds + run_seconds, 2),
                     "build_seconds": round(build_seconds, 2), "run_seconds": round(run_seconds, 2),
                     "runs": len(meta), "reused_sandbox": True, "python": python_used or "sandbox-default"}}
