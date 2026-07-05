"""runner.snapshot — E2B pause/resume snapshot primitives for the make-runnable flywheel (build plan §4.4, S5).

E2B sandboxes support pause/resume on ALL plans: a pause saves the sandbox's filesystem AND memory; a resume
restores the exact state in ~1s (vs a full boot + dependency install of minutes). Two uses:

  • warm-env flywheel — RECORD a successful build as a live snapshot, RESUME it on a repeat/sibling scan (the
    RunPlan contract as a live image; Repo2Run's Dockerfile synthesis, but a warm snapshot), and
  • speculative execution — trial a candidate fix from a checkpoint and roll back cheaply (SetupX's LIFO).

HOW-only: a snapshot changes only HOW FAST / SAFELY a repo is made runnable — never a captured value or a
verdict. A resumed env still flows through the unchanged k-runs → recompute → fail-closed verdict, so a stale
snapshot can only cost coverage (a failed run → DISCOVERED), never a false CONFIRM.

Verified against the installed SDK (e2b==2.30.0): ``sbx.pause() -> bool`` (id via ``sbx.sandbox_id``),
``Sandbox.connect(sandbox_id, timeout=...) -> Sandbox`` (resume by id — a class-method-variant descriptor),
``Sandbox.kill(sandbox_id) -> bool``. Gated OFF by default (``CALMA_E2B_SNAPSHOT``); flip on only after a live
smoke (E2B state cannot be validated hermetically). Best-effort throughout — any SDK error → None/False and the
caller boots a fresh sandbox (today's behavior), so enabling this can never break a run, only speed it up.
"""
from __future__ import annotations

import os


def snapshots_enabled() -> bool:
    """The kill-switch: snapshots are OFF until a live smoke proves pause/resume works on the deployed template."""
    return os.environ.get("CALMA_E2B_SNAPSHOT", "0").strip().lower() not in ("0", "", "false", "no")


def _api(cfg: dict) -> dict:
    api = {"api_key": cfg.get("api_key")}
    if cfg.get("domain"):
        api["domain"] = cfg["domain"]
    return api


def pause_sandbox(sbx) -> str | None:
    """Pause a running sandbox (snapshot memory + filesystem); return its resumable id, or None on any failure.
    A failed pause just means no snapshot is cached — the next scan boots fresh (unchanged behavior)."""
    try:
        if sbx.pause():
            return getattr(sbx, "sandbox_id", None) or None
    except Exception:  # noqa: BLE001 — best-effort; pause must never break the run it just finished
        return None
    return None


def resume_sandbox(snapshot_id: str | None, cfg: dict, timeout: int = 300):
    """Resume a paused sandbox by id → a running Sandbox (~1s), or None (→ the caller boots a fresh sandbox and
    installs, exactly as today). Never raises: a dead/expired/killed snapshot resolves to None."""
    if not snapshot_id:
        return None
    try:
        from e2b import Sandbox  # noqa: PLC0415 — lazy: the SDK is only needed on the E2B path
        return Sandbox.connect(snapshot_id, timeout=max(1, int(timeout)), **_api(cfg))
    except Exception:  # noqa: BLE001 — any resume failure → fall back to a fresh boot
        return None


def kill_snapshot(snapshot_id: str | None, cfg: dict) -> bool:
    """Kill a paused/running sandbox by id to release its resources. E2B retains paused sandboxes INDEFINITELY
    (no TTL), so a snapshot cache MUST reap on eviction/replacement or it leaks live sandboxes → cost. Returns
    True on a confirmed kill, False otherwise; best-effort (a double-kill / already-gone id is not an error)."""
    if not snapshot_id:
        return False
    try:
        from e2b import Sandbox  # noqa: PLC0415
        return bool(Sandbox.kill(snapshot_id, **_api(cfg)))
    except Exception:  # noqa: BLE001
        return False
