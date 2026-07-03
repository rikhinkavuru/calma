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
import tarfile
import tempfile
import time

from . import CAPTURE_DIR, build, parse_capture
from . import effector

_SHIM_FILES = ("calma_capture.py", "sitecustomize.py", "reinvoke.py", "run_notebook_e2b.py")
_LANG_INTERP = effector.LANG_INTERP   # canonical map (shared with orchestrator.tools_exec); polyglot template only
_MAX_SANDBOX_S = effector.MAX_SANDBOX_S   # hard cap on a sandbox's lifetime (build + all k runs); see effector
_MAX_ARCHIVE_B = 200 * 1024 * 1024   # above this, fall back to per-file upload (keeps the child's memory bounded)


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
            if v[:1] not in ("'", '"'):
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


def _skip_upload(fn: str) -> bool:
    return fn.endswith(".pyc")


def _upload_dir(sbx, local_dir, dest, log=None):
    """Stage the repo in ONE round-trip: tar it locally, write the single archive, extract it in the sandbox.
    File-by-file `sbx.files.write` was N network round-trips — the dominant pre-install cost on any non-trivial
    repo (a tiny repo still cost ~4s). This collapses it to one write + one `tar` command. `.git` is dropped
    (a fresh checkout doesn't need VCS history to reproduce a number — era-pinning uses the LOCAL clone, which
    keeps it). Strictly best-effort: too large, or any failure, → the original per-file path (never regress)."""
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as tf:
            tmp = tf.name
        n = 0
        with tarfile.open(tmp, "w:gz") as tar:                          # streamed to disk → bounded memory
            for root, dirs, files in os.walk(local_dir):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
                for fn in files:
                    if _skip_upload(fn):
                        continue
                    lp = os.path.join(root, fn)
                    try:
                        tar.add(lp, arcname=os.path.relpath(lp, local_dir).replace(os.sep, "/"), recursive=False)
                        n += 1
                    except OSError:
                        pass
        size = os.path.getsize(tmp)
        if size > _MAX_ARCHIVE_B:
            raise ValueError("archive %dMB > cap" % (size // 1024 // 1024))
        # Write the archive INTO `dest` — the SDK's files.write creates the dir with the right perms (a shell
        # `mkdir /work` fails: the sandbox user can't create dirs at /). Then extract in place, no mkdir needed.
        arc = dest + "/_calma_repo.tgz"
        with open(tmp, "rb") as fh:
            sbx.files.write(arc, fh.read())
        r = sbx.commands.run("tar xzf %s -C %s && rm -f %s"
                             % (shlex.quote(arc), shlex.quote(dest), shlex.quote(arc)), timeout=300)
        if getattr(r, "exit_code", 0):
            raise RuntimeError("extract exit %s" % r.exit_code)
        _note(log, "E2B: staged %d file(s) as one %.1fMB archive" % (n, size / 1e6))
        return
    except Exception as e:  # noqa: BLE001 — bulk unavailable → per-file (memory-safe, one file at a time)
        _note(log, "E2B: bulk stage unavailable (%s) — uploading per-file" % str(e)[:120])
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
    for root, _dirs, files in os.walk(local_dir):                       # fallback: original per-file path
        if "__pycache__" in root.split(os.sep):
            continue
        for fn in files:
            if _skip_upload(fn):
                continue
            lp = os.path.join(root, fn)
            rel = os.path.relpath(lp, local_dir).replace(os.sep, "/")
            try:
                with open(lp, "rb") as fh:
                    sbx.files.write(dest + "/" + rel, fh.read())
            except OSError:
                pass


def _acquire_deps(repo_dir, acquire):
    """The deps the DOWNLOAD scripts need — distinct from the eval's. A research acquire pipeline almost always
    pulls from HuggingFace (`from datasets import …`, `huggingface_hub`) or over HTTP (`requests`); those aren't
    the eval's inferred deps, so without this the very first acquire step ImportErrors before a byte downloads
    (the composition-confound-vep failure: `01_get_traitgym.py: from datasets import …`). We seed the common
    data-fetch toolkit + whatever the acquire scripts actually import (mapped to PyPI dists, stdlib/local dropped)."""
    base = ["huggingface_hub", "datasets", "requests"]
    roots: set[str] = set()
    for argv in acquire or []:
        p = str(argv[0]) if argv else ""
        if p.endswith(".py"):
            fp = os.path.join(repo_dir, p)
            if os.path.isfile(fp):
                roots |= build._imported_roots(fp)
    stdlib = set(getattr(__import__("sys"), "stdlib_module_names", ())) | {"__future__"}
    local = build._local_module_names(repo_dir)
    extra = [build._PKG_ALIASES.get(r, r) for r in sorted(roots)
             if r and not r.startswith("_") and r not in stdlib and r not in local]
    out, seen = [], set()
    for d in base + extra:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _fetch_data_sources(sbx, data_fetch, timeout, log=None):
    """Download each {path, url} directly into the sandbox at /work/<path> — the bypass for a repo whose own
    download scripts fail. curl -fL, size-capped (5GB), best-effort per file. Paths are pre-validated by the
    planner (no traversal / absolute). Returns the count fetched (drives the caller's mismatch→INCONCLUSIVE cap)."""
    n = 0
    for it in data_fetch or []:
        path = str((it or {}).get("path") or "").lstrip("/")
        url = str((it or {}).get("url") or "")
        if not path or not url.lower().startswith("https://"):
            continue
        dest = "/work/" + path
        try:
            _note(log, "E2B: fetching %s ← %s" % (path, url[:90]))
            r = sbx.commands.run(
                'mkdir -p "$(dirname %s)" && curl -fL --retry 2 --max-filesize 5000000000 -o %s %s'
                % (shlex.quote(dest), shlex.quote(dest), shlex.quote(url)), timeout=timeout)
            if getattr(r, "exit_code", 1) == 0:
                n += 1
                _note(log, "E2B: fetched %s → ok" % path)
            else:
                _note(log, "E2B: fetch %s → failed (exit %s)" % (path, getattr(r, "exit_code", "?")))
        except Exception as e:  # noqa: BLE001
            _note(log, "E2B: fetch %s → error (%s)" % (path, str(e)[:100]))
    if n:
        _note(log, "E2B: auto-resolved %d data file(s) — a mismatch will be capped to INCONCLUSIVE, not REFUTED" % n)
    return n


def _set_egress(sbx, allow_out, log=None):
    """Restrict the sandbox's outbound traffic to `allow_out` (default-deny everything else) for the acquire
    phase. Uses E2B's live `update_network` (SNI/Host domain filtering on 443/80). Best-effort: an SDK/plan
    without it keeps the current posture — logged so it's never a silent security assumption."""
    fn = getattr(sbx, "update_network", None)
    if not callable(fn):
        _note(log, "E2B: egress allowlist unavailable on this SDK — acquire runs with full internet (gated)")
        return
    try:
        fn({"allow_out": list(allow_out), "deny_out": ["0.0.0.0/0"]})   # SDK takes ONE SandboxNetworkUpdate dict
        _note(log, "E2B: acquire egress limited to %s" % ", ".join(list(allow_out)[:8]))
    except Exception as e:  # noqa: BLE001
        _note(log, "E2B: could not set egress allowlist (%s) — acquire runs open (gated)" % str(e)[:120])


def _clear_egress(sbx, log=None):
    """Clear the acquire allowlist so the eval run returns to the sandbox's created network posture (the
    credential is gone by now, so this is behavior-preserving, not a security regression). Best-effort."""
    fn = getattr(sbx, "update_network", None)
    if not callable(fn):
        return
    try:
        fn({})                                          # empty update → clears all allow/deny rules
        _note(log, "E2B: acquire egress allowlist cleared for the eval run")
    except Exception:  # noqa: BLE001
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


def _route_template(cfg, cpu_cores):
    """Per-tier vCPU is realised by template routing: E2B fixes cores at template-build time, not per sandbox.
    A low core count uses the small template (env CALMA_E2B_TEMPLATE_SMALL) when it's been built + configured;
    otherwise the default template (the current 8-core calma-verify). Build the small template on the E2B
    account + set the env to actually cap a free tier's cores; until then every tier uses the default."""
    small = (os.environ.get("CALMA_E2B_TEMPLATE_SMALL") or "").strip()
    if cpu_cores and cpu_cores <= 2 and small:
        return {**cfg, "template": small}
    return cfg


def _command_for(pybin, entry):
    """Map an entry argv to the sandbox command. A plain script/module runs under `pybin`; a `nb:` entry runs
    through the in-sandbox notebook runner (kernel-armed capture); a `lang:` entry (r:/julia:/shell:) runs
    under its interpreter (four-unlocks §1/§3). The plain path is byte-for-byte the historical command."""
    head = str(entry[0]) if entry else ""
    if head.startswith("nb:"):
        return "%s /capture/run_notebook_e2b.py %s" % (pybin, shlex.quote(head[3:]))
    for lang, interp in _LANG_INTERP.items():
        if head.startswith(lang + ":"):
            rest = [head[len(lang) + 1:]] + [str(a) for a in entry[1:]]
            return "%s %s" % (interp, " ".join(shlex.quote(a) for a in rest))
    return pybin + " " + " ".join(entry)


def _build_conda_env(sbx, env_file_rel, timeout, log=None):
    """B2 in the sandbox: solve the repo's environment.yml with micromamba (baked into the image) and return the
    env's python. Prefers a committed conda lockfile (no solver, deterministic + fast) when present. Returns the
    interpreter path, or None on failure (caller keeps the default python → honest run/failure)."""
    prefix = "/opt/calma-conda"
    pybin = prefix + "/bin/python"
    # a committed explicit lockfile is the SOTA-reproducible path — create from it without hitting the solver.
    lock = None
    for cand in ("conda-lock.yml", "conda-lock.yaml", "conda-linux-64.lock", "environment.lock"):
        try:
            if sbx.commands.run("test -f /work/%s" % cand, timeout=20).exit_code == 0:
                lock = cand
                break
        except Exception:  # noqa: BLE001
            pass
    src = ("-f /work/%s" % lock) if lock else ("-f /work/%s" % env_file_rel)
    try:
        _note(log, "E2B: solving conda env via micromamba (%s)…" % (lock or env_file_rel))
        r = _cmd_run(sbx, "micromamba create -y -p %s %s" % (prefix, src),
                     timeout=timeout, log=log, prefix="  conda| ", stream=True)
        if getattr(r, "exit_code", 1) == 0:
            if sbx.commands.run("test -x %s" % pybin, timeout=20).exit_code == 0:
                return pybin
        _note(log, "E2B: conda solve failed — falling back to the default python")
    except Exception as e:  # noqa: BLE001
        _note(log, "E2B: conda error (%s) — default python" % str(e)[:120])
    return None


def run_e2b(repo_dir, entry=None, *, k=2, hooks="sklearn", targets=None, timeout=600,
            allow_internet=False, pip_install=None, pip_strict=True, python_version=None,
            cfg=None, max_elems=None, log=None, resolve=None, fuzz=False, cpu_cores=0, acquire=None,
            builder=None, acquire_env=None, acquire_allow_out=None, data_fetch=None):
    """ONE sandbox: stage + install ONCE, then run the entrypoint k× inside it (each a fresh process with its
    own capture file). Reusing the sandbox across the determinism runs is the big cost lever — the dominant
    `pip install` is paid once, not k×, and it's MORE correct for determinism (identical env across runs, so
    only code-level nondeterminism shows). Returns the runner-agnostic shape + cost telemetry.

    `resolve`, if given, is a callable returning (entry, pip_install, pip_strict, targets). It is invoked AFTER the
    microVM boots and the repo uploads — never before — so the caller can run an AI run-plan CONCURRENTLY with
    the boot and only block on it here, at the last moment before deps install. When `resolve` is set the deps
    are unknown at boot, so the sandbox's lifetime CEILING is sized conservatively (free: billing is per
    running-second and the sandbox is killed when done)."""
    cfg = cfg or e2b_config(os.path.join(os.path.dirname(CAPTURE_DIR), os.pardir, ".env"))
    cfg = _route_template(cfg, cpu_cores)          # tier vCPU → small template when configured
    if not cfg.get("api_key"):
        return {"runs": [], "meta": [], "ran_ok": False, "error": "no E2B api key configured",
                "hooks_armed": None, "n_calls": [], "cost": {}}
    entry = list(entry or [])
    runs, meta = [], []
    hooks_armed = None
    fuzz_records = None
    sbx = None
    pybin, python_used = "python", None
    t_start = time.time()
    build_seconds = 0.0
    data_fetched = 0
    # heavy deps (torch/tf/…) need a much bigger install budget than the run timeout. With a deferred `resolve`
    # the deps aren't known until after boot, so size the ceiling for the heavy case (harmless — see docstring).
    heavy = True if resolve else build.deps_are_heavy(pip_install)
    inst_timeout = max(timeout, 1800) if heavy else timeout
    # The sandbox must OUTLIVE the whole session — build + ALL k runs — or it hits its end-of-life mid-run and
    # the run is killed (StreamReset), capturing nothing. The old code created it with just the per-run
    # timeout, so a repo whose build + k·runs approached one run's timeout silently failed deep verify
    # (gb_kmer: the sandbox died at 600s during run 2 → 0 computations captured → fell back to discovery).
    sandbox_life = effector.size_sandbox_life(inst_timeout, k, timeout, _MAX_SANDBOX_S)
    try:
        _note(log, "E2B: creating microVM (lifetime %dm)…" % (sandbox_life // 60))
        sbx = _create_sandbox(cfg, sandbox_life,
                              allow_internet or resolve is not None or bool(pip_install)
                              or bool(python_version) or bool(acquire) or bool(data_fetch)
                              or builder == "conda-micromamba")   # conda solve needs the package channels
        _note(log, "E2B: microVM up (%.1fs) — uploading repo + capture shim" % (time.time() - t_start))
        for fn in _SHIM_FILES:                                   # stage the capture shim + the repo (once)
            with open(os.path.join(CAPTURE_DIR, fn), "rb") as fh:
                sbx.files.write("/capture/" + fn, fh.read())
        _upload_dir(sbx, repo_dir, "/work", log=log)
        if resolve is not None:                                 # join the run-plan NOW — it ran during the boot
            entry, pip_install, pip_strict, targets = resolve()
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
        if builder == "conda-micromamba":                       # B2: solve environment.yml in-sandbox via micromamba
            conda_py = _build_conda_env(sbx, "environment.yml", inst_timeout, log=log)
            if conda_py:
                pybin, python_used = conda_py, "conda"
        # data-acquisition (paid, gated upstream): run the repo's OWN download pipeline WITH network so the
        # datasets materialize before the eval. The sandbox was created with internet for this; the eval then
        # runs in the same sandbox (a documented tradeoff — the recompute is still independent, so FCR holds).
        if data_fetch:
            # BYPASS a broken/incomplete repo download pipeline: fetch the AI-identified canonical data files
            # DIRECTLY into the sandbox at the paths the repo expects, so the eval has its inputs even when the
            # repo's own scripts fail. Best-effort per file (a 404/other error just leaves it missing → the run
            # honestly fails on what's still absent). FCR: this only writes inputs — the number is still captured
            # + recomputed independently. The caller caps a MISMATCH to INCONCLUSIVE (auto-fetched data isn't the
            # repo's own output, so it must never false-REFUTE a correct claim).
            data_fetched = _fetch_data_sources(sbx, data_fetch, inst_timeout, log=log)
        if acquire:
            _note(log, "E2B: acquiring data — %d step(s) with network allowed" % len(acquire))
            # the download scripts need their OWN deps (datasets/huggingface_hub/requests/…), installed with open
            # net BEFORE the egress allowlist clamps down (the allowlist includes pypi, but install-first is safe).
            acq_deps = _acquire_deps(repo_dir, acquire)
            if acq_deps:
                _note(log, "E2B: installing %d acquire dep(s) — %s" % (len(acq_deps), " ".join(acq_deps)[:160]))
                _install(sbx, acq_deps, False, inst_timeout, pip_cmd, log=log)
            # four-unlocks §8: narrow egress to a default-deny data-host allowlist for the acquire phase, so a
            # prompt-injected acquire script (or a leaked credential injected below) can only reach the data
            # hosts — not an attacker-controlled server. Best-effort: an SDK without update_network keeps the
            # prior full-internet posture (still tier-gated). Secrets (acquire_env) inject into the acquire
            # commands ONLY — never the eval run below — so the recompute stays credential-free (FCR).
            if acquire_allow_out:
                _set_egress(sbx, acquire_allow_out, log=log)
            # Run every step BEST-EFFORT: a numbered pipeline isn't strictly linear — a later step may fetch a
            # dataset an earlier one didn't (e.g. clinvar downloaded by step 07, read by step 03). Stopping at the
            # first failure loses all of those. So we log each step's outcome and keep going; the eval then either
            # captures (enough data landed) or fails honestly on what's still missing. FCR-safe: acquire only
            # writes inputs; the number is still captured + recomputed independently.
            n_ok = 0
            for argv in acquire:
                inner = " ".join(shlex.quote(a) for a in argv)
                cmd = "cd /work && %s %s" % (pybin, inner) if str(argv[0]).endswith(".py") else "cd /work && " + inner
                try:
                    ra = sbx.commands.run(cmd, timeout=inst_timeout, envs=(acquire_env or None))
                    ok = getattr(ra, "exit_code", 1) == 0
                    n_ok += 1 if ok else 0
                    _note(log, "E2B: acquire `%s` → %s" % (" ".join(argv), "ok" if ok else "failed"))
                except Exception as e:  # noqa: BLE001
                    _note(log, "E2B: acquire `%s` → error (%s)" % (" ".join(argv), str(e)[:120]))
            _note(log, "E2B: acquire complete — %d/%d step(s) succeeded" % (n_ok, len(acquire)))
            # restore the sandbox's created network posture for the EVAL run (clear the acquire allowlist). The
            # credential is injected ONLY during acquire, so the exfil risk lives in that window (which the
            # allowlist covered); the eval run carries no secret, so its posture is unchanged from before —
            # behavior-preserving. Only when we tightened it (else the SDK/posture is already untouched).
            if acquire_allow_out:
                _clear_egress(sbx, log=log)
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
        return effector.shape_setup_error("e2b error: %s" % e, k, build_seconds)

    run_seconds = 0.0
    try:
        for i in range(max(1, k)):
            out_remote = "/capture/calls_%d.jsonl" % i           # fresh capture file per run
            t0 = time.time()
            _note(log, "E2B: running `%s` (run %d/%d)…" % (" ".join(entry), i + 1, max(1, k)))
            try:
                # the backend-agnostic capture-run env (runner.effector) — freezes hash/tz, points the shim at
                # this run's fresh JSONL, JSON-encodes targets, arms the fuzz emitter (feature 2/7/10).
                envs = effector.capture_run_env(i, out_remote, hooks=hooks, targets=targets,
                                                max_elems=max_elems, fuzz=fuzz)
                # stream the run's stdout/stderr LIVE into the job log — the repo's own prints are the best
                # signal for "what is it actually doing" during a long run.
                r = _cmd_run(sbx, _command_for(pybin, entry), cwd="/work", envs=envs, timeout=timeout,
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
                if fuzz and fuzz_records is None:                # first run's fuzz emit is enough (deterministic)
                    fz_local = _pull_capture(sbx, out_remote + ".fuzz")
                    if fz_local:
                        recs = parse_capture(fz_local)
                        if recs:
                            fuzz_records = recs
                        try:
                            os.remove(fz_local)
                        except OSError:
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
    result = effector.shape_result(runs, meta, build_seconds=build_seconds, run_seconds=run_seconds,
                                   hooks_armed=hooks_armed, fuzz=fuzz_records, python_used=python_used)
    if data_fetched:
        result["data_auto_resolved"] = True     # caller caps a mismatch → INCONCLUSIVE (not the repo's own data)
    return result
