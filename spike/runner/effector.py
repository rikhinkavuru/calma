"""runner.effector — the backend-agnostic run contract shared by every sandbox effector (E2B, Modal, …).

Clean-architecture note (separation of concerns): a sandbox effector is really two things bolted together —
(1) TRANSPORT: boot a VM, upload the repo, install deps, exec a command, pull a file (backend-specific); and
(2) the CONTRACT: how a capture run is armed (env vars), how long the sandbox must live, and the exact result
dict the deterministic verify consumes (backend-INDEPENDENT). Historically both lived inside e2b_runner, so a
second backend (Modal, for GPU) would have to copy the contract and drift from it. This module is the contract,
extracted once, imported by every transport. Pure stdlib, no e2b/modal import — unit-testable without a sandbox.

FCR invariant: nothing here carries a verdict/claim/binding. `capture_run_env` only sets WHERE the shim writes
and WHICH functions it wraps; `shape_result` only reshapes the repo's OWN captured computations. The verdict is
still computed downstream from `runs`, untouched.
"""
from __future__ import annotations

import json
import os

# Where the capture shim is mounted inside every sandbox (on PYTHONPATH so sitecustomize auto-arms it).
CAPTURE_MOUNT = "/capture"
# The canonical non-Python interpreter map (four-unlocks §3). Lives here — the runner layer — so both the E2B
# transport and the orchestrator's run_lang tool share ONE definition (no drift). A `lang:` entry runs under
# these; the metric is recomputed in Python from the emitted predictions (the capture shim is Python-only).
LANG_INTERP = {"r": "Rscript", "julia": "julia", "shell": "bash", "sh": "sh"}
# Hard cap on a sandbox's lifetime (build + all k runs) — a safety bound on cost / backend limits. E2B and
# Modal both honour it; Modal's own max is 24h, well above this. Env-tunable because the genomics ICP has
# legitimate heavy benchmarks (gb_kmer: install + k·~40-min sweeps) that need > 60 min or the microVM hits
# end-of-life mid-run-2 and captures nothing. Raising it is cost-safe: the per-tenant MONTHLY sandbox-second
# budget (core/limits.py) still bounds total spend; this only lifts the per-sandbox ceiling. Set
# CALMA_MAX_SANDBOX_S=10800 (3h) on the hosted engine for the heavy-benchmark tier — but only if the E2B
# plan's own max-lifetime allows it (create() rejects a timeout above the account ceiling).
MAX_SANDBOX_S = int(os.environ.get("CALMA_MAX_SANDBOX_S") or 3600)


def capture_run_env(index: int, out_remote: str, *, hooks: str = "sklearn", targets=None,
                    max_elems=None, fuzz: bool = False, extra: dict | None = None,
                    repo_root: str | None = None) -> dict:
    """The env that arms one capture run inside a sandbox. Identical across backends: PYTHONPATH puts the shim
    first so it auto-installs at interpreter startup; CALMA_CAPTURE_OUT points it at this run's fresh JSONL;
    PYTHONHASHSEED/TZ freeze the two ambient nondeterminism sources so a deterministic-by-construction repo
    reproduces cleanly (and adaptive-k stays sound). `extra` merges backend/tenant additions (e.g. an
    acquire-phase secret) LAST — callers are responsible for only injecting secrets on non-eval phases.

    `repo_root`: the repo's run directory (e.g. /work in E2B). Added to PYTHONPATH so a subdir entrypoint
    (`python pipeline/x.py`, `scripts/run.py`) can still import the repo's OWN top-level package — Python only
    puts the SCRIPT's dir on sys.path, not the cwd, so `import <pkg>` for a root-level package otherwise fails
    with ModuleNotFoundError (found running Choices: `python pipeline/…` → `No module named 'choices'`). The
    shim stays FIRST so its sitecustomize auto-arms; this is HOW-only, never a verdict channel."""
    pythonpath = (CAPTURE_MOUNT + ":" + repo_root) if repo_root else CAPTURE_MOUNT
    env = {
        "PYTHONPATH": pythonpath,
        "CALMA_CAPTURE_OUT": out_remote,
        "CALMA_CAPTURE_HOOKS": hooks,
        "CALMA_RUN_INDEX": str(index),
        "PYTHONHASHSEED": "0",
        "TZ": "UTC",
    }
    if targets:
        env["CALMA_CAPTURE_TARGETS"] = json.dumps(targets)
    if max_elems:
        env["CALMA_CAPTURE_MAX_ELEMS"] = str(max_elems)
    if fuzz:
        env["CALMA_FUZZ"] = "1"
    if extra:
        env.update(extra)
    return env


def size_sandbox_life(inst_timeout: int, k: int, run_timeout: int, cap: int = MAX_SANDBOX_S) -> int:
    """A sandbox must OUTLIVE the whole session — install + ALL k runs — or it hits end-of-life mid-run and the
    run is killed (StreamReset), capturing nothing. Size for install budget + k·run + margin, capped."""
    return min(inst_timeout + max(1, k) * run_timeout + 120, cap)


def shape_result(runs, meta, *, build_seconds: float, run_seconds: float, hooks_armed=None, fuzz=None,
                 python_used=None, reused_sandbox: bool = True, extra_cost: dict | None = None) -> dict:
    """The runner-agnostic result dict core.diff consumes — the SAME shape local_runner/e2b_runner emit, so the
    downstream verify is untouched. `extra_cost` folds backend-specific telemetry (e.g. gpu_seconds) into cost."""
    ran_ok = bool(meta) and all(m.get("returncode") == 0 for m in meta)
    cost = {
        "sandbox_seconds": round(build_seconds + run_seconds, 2),
        "build_seconds": round(build_seconds, 2),
        "run_seconds": round(run_seconds, 2),
        "runs": len(meta),
        "reused_sandbox": reused_sandbox,
        "python": python_used or "sandbox-default",
    }
    if extra_cost:
        cost.update(extra_cost)
    return {"runs": runs, "meta": meta, "ran_ok": ran_ok, "hooks_armed": hooks_armed,
            "fuzz": fuzz, "n_calls": [len(r) for r in runs], "cost": cost}


def shape_setup_error(err: str, k: int, build_seconds: float) -> dict:
    """A setup failure (boot/upload/install) fails every run identically — the honest empty result. Never a
    fabricated verdict: `runs` is empty lists, so downstream every claim goes DISCOVERED/REFUTED, never CONFIRM."""
    killed = "timeout" in (err or "").lower()
    meta = [{"returncode": -9, "killed": killed, "seconds": 0.0, "stdout_tail": "", "stderr_tail": err}
            for _ in range(max(1, k))]
    return {"runs": [[] for _ in range(max(1, k))], "meta": meta, "ran_ok": False,
            "hooks_armed": None, "n_calls": [], "error": err,
            "cost": {"sandbox_seconds": round(build_seconds, 2), "build_seconds": round(build_seconds, 2),
                     "runs": 0, "reused_sandbox": True}}
