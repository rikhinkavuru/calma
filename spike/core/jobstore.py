"""core.jobstore — durable job persistence so verification runs survive a backend redeploy.

The engine keeps jobs in an in-memory dict (server.JOBS) for speed. That dict is wiped on every Fly
redeploy / machine restart, which orphaned every finished run: the dashboard's localStorage index still
knew the id but the backend 404'd it ("expired — can't open"), and the Overview metrics (derived from the
job list) reset to zero. This module write-throughs terminal + status-transition snapshots to a SQLite file
on a persistent volume, and reloads them on boot, so a redeploy no longer loses history.

Design:
  * SQLite, stdlib only (no new dependency; the zero-install guarantee holds). One row per job, the whole
    job dict stored as JSON (logs + claims included, so a reopened past run still shows its console).
  * A fresh connection per call (WAL, short busy-timeout) — simplest thing that is safe under the API's
    worker threads without a shared-connection lock.
  * Best-effort: any store error is swallowed by the caller (a DB hiccup must never fail a live job).
  * On reload, a job left non-terminal by a crash is surfaced as `error / interrupted`, never resurrected as
    "running" (the instance that ran it is gone).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

_TERMINAL = ("done", "stopped", "error")


def default_path() -> str:
    """Where the job DB lives. A mounted volume (CALMA_DATA_DIR, e.g. /data on Fly) when present, else a
    local dir under the engine — so local dev persists too, just not across a container rebuild."""
    base = (os.environ.get("CALMA_DATA_DIR") or "").strip()
    if not base:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, ".calma")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "jobs.db")


class JobStore:
    """A tiny durable index of verification jobs. Thread-safe by using a new connection per operation."""

    def __init__(self, path: str | None = None):
        self.path = path or default_path()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=5.0)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        return c

    def _init(self) -> None:
        try:
            with self._conn() as c:
                c.execute(
                    "CREATE TABLE IF NOT EXISTS jobs ("
                    "  id TEXT PRIMARY KEY,"
                    "  tenant TEXT,"
                    "  status TEXT,"
                    "  created REAL,"
                    "  updated REAL,"
                    "  data TEXT"
                    ")")
                c.execute("CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created)")
        except sqlite3.Error:
            pass   # a broken store must not stop the engine from booting — it just runs without persistence

    def save(self, job: dict) -> None:
        """Persist one job's full state (upsert). Best-effort; a store error is swallowed."""
        try:
            data = json.dumps(job, default=str)
        except (TypeError, ValueError):
            return
        try:
            with self._conn() as c:
                c.execute(
                    "INSERT INTO jobs(id, tenant, status, created, updated, data) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET tenant=excluded.tenant, status=excluded.status, "
                    "updated=excluded.updated, data=excluded.data",
                    (job.get("id"), job.get("_tenant"), job.get("status"),
                     float(job.get("created") or 0), float(job.get("updated") or time.time()), data))
        except sqlite3.Error:
            pass

    def load_all(self, limit: int = 500) -> list[dict]:
        """Reload the most-recent `limit` jobs, newest first. A job the DB still shows as non-terminal was
        interrupted by the restart that just happened → surface it honestly rather than as a stuck 'running'."""
        try:
            with self._conn() as c:
                rows = c.execute(
                    "SELECT data FROM jobs ORDER BY created DESC LIMIT ?", (int(limit),)).fetchall()
        except sqlite3.Error:
            return []
        out: list[dict] = []
        for (data,) in rows:
            try:
                job = json.loads(data)
            except (TypeError, ValueError):
                continue
            if not isinstance(job, dict) or not job.get("id"):
                continue
            if job.get("status") not in _TERMINAL:
                job["status"] = "error"
                job["stage"] = "interrupted"
                job["progress"] = ""
                job["error"] = job.get("error") or "interrupted by a backend restart — re-run to verify"
                job["_slot"] = False               # never hold a concurrency slot for a dead job
            out.append(job)
        return out

    def prune(self, keep: int = 500) -> None:
        """Drop all but the newest `keep` terminal rows so the file can't grow without bound."""
        try:
            with self._conn() as c:
                c.execute(
                    "DELETE FROM jobs WHERE id IN ("
                    "  SELECT id FROM jobs ORDER BY created DESC LIMIT -1 OFFSET ?)", (int(keep),))
        except sqlite3.Error:
            pass


_STORE: JobStore | None = None


def get_store() -> JobStore:
    global _STORE
    if _STORE is None:
        _STORE = JobStore()
    return _STORE
