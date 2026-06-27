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
import os
import tempfile
import time

from . import CAPTURE_DIR, parse_capture

_SHIM_FILES = ("calma_capture.py", "sitecustomize.py")


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


def run_e2b(repo_dir, entry, *, k=2, hooks="sklearn", targets=None, timeout=600,
            allow_internet=False, pip_install=None, cfg=None, max_elems=None):
    cfg = cfg or e2b_config(os.path.join(os.path.dirname(CAPTURE_DIR), os.pardir, ".env"))
    if not cfg.get("api_key"):
        return {"runs": [], "meta": [], "ran_ok": False, "error": "no E2B api key configured",
                "hooks_armed": None, "n_calls": []}
    entry = list(entry)
    runs, meta = [], []
    hooks_armed = None
    for i in range(max(1, k)):
        out_local = None
        sbx = None
        t0 = time.time()
        try:
            sbx = _create_sandbox(cfg, timeout, allow_internet or bool(pip_install))
            # stage the capture shim + the repo
            for fn in _SHIM_FILES:
                with open(os.path.join(CAPTURE_DIR, fn), "rb") as fh:
                    sbx.files.write("/capture/" + fn, fh.read())
            _upload_dir(sbx, repo_dir, "/work")
            if pip_install:
                sbx.commands.run("pip install -q " + " ".join(pip_install), timeout=timeout)
            envs = {"PYTHONPATH": "/capture", "CALMA_CAPTURE_OUT": "/capture/calls.jsonl",
                    "CALMA_CAPTURE_HOOKS": hooks, "CALMA_RUN_INDEX": str(i)}
            if targets:
                envs["CALMA_CAPTURE_TARGETS"] = json.dumps(targets)
            if max_elems:
                envs["CALMA_CAPTURE_MAX_ELEMS"] = str(max_elems)
            cmd = "python " + " ".join(entry)
            r = sbx.commands.run(cmd, cwd="/work", envs=envs, timeout=timeout)
            rc = getattr(r, "exit_code", 0) or 0
            out, err = getattr(r, "stdout", "") or "", getattr(r, "stderr", "") or ""
            killed = False
            # pull the capture JSONL
            try:
                data = sbx.files.read("/capture/calls.jsonl")
                with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as tf:
                    tf.write(data if isinstance(data, str) else data.decode("utf-8", "replace"))
                    out_local = tf.name
            except Exception:  # noqa: BLE001 — no calls captured (empty file may not exist)
                out_local = None
            if hooks_armed is None:
                try:
                    h = sbx.files.read("/capture/calls.jsonl.hooks")
                    hooks_armed = json.loads(h if isinstance(h, str) else h.decode())
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:  # noqa: BLE001 — boot/exec error -> this run failed, never a crash
            rc, out, err, killed = -9, "", "e2b error: %s" % e, "timeout" in str(e).lower()
        finally:
            if sbx is not None:
                try:
                    sbx.kill()
                except Exception:  # noqa: BLE001
                    pass
        dt = time.time() - t0
        runs.append(parse_capture(out_local) if out_local else [])
        if out_local:
            try:
                os.remove(out_local)
            except OSError:
                pass
        meta.append({"returncode": rc, "killed": killed, "seconds": dt,
                     "stdout_tail": (out or "")[-2000:], "stderr_tail": (err or "")[-2000:]})
    ran_ok = all(m["returncode"] == 0 for m in meta)
    return {"runs": runs, "meta": meta, "ran_ok": ran_ok, "hooks_armed": hooks_armed,
            "n_calls": [len(r) for r in runs]}
