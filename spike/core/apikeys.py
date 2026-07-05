"""core.apikeys — durable per-tenant API keys for programmatic access (CLI / CI / MCP).

The hosted engine is normally reached only by the trusted first-party Next proxy (which holds the service
token and forwards the WorkOS-resolved tenant + tier). An API key is the SECOND first-party credential: it
lets a user's own tooling — the `calma` CLI, a CI step, the MCP server — call the engine directly and be
metered/tier-gated exactly as their dashboard session is.

Security model:
  * The plaintext key (`calma_sk_<random>`) is shown exactly ONCE, at creation; only its SHA-256 is stored.
    A DB leak therefore can't be replayed as a key.
  * Lookup is by hash, then a constant-time compare, so validation isn't a timing oracle.
  * Each key carries its owning `tenant` and a `tier` snapshot (the plan at creation time — re-issue after an
    upgrade to move tiers). All admission control keys off the resolved tenant, so a key can never exceed its
    tenant's budgets or reach another tenant's jobs.
  * Stored alongside the job store on the persistent volume (CALMA_DATA_DIR), so keys survive a redeploy.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time

_PREFIX = "calma_sk_"


def _default_path() -> str:
    base = (os.environ.get("CALMA_DATA_DIR") or "").strip()
    if not base:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, ".calma")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "apikeys.db")


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _display(key: str) -> str:
    """A non-secret label for the UI: the prefix + first 4 random chars + an ellipsis (e.g. calma_sk_ab12…)."""
    tail = key[len(_PREFIX):len(_PREFIX) + 4] if key.startswith(_PREFIX) else key[:4]
    return _PREFIX + tail + "…"


class ApiKeyStore:
    def __init__(self, path: str | None = None):
        self.path = path or _default_path()
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
                    "CREATE TABLE IF NOT EXISTS api_keys ("
                    "  id TEXT PRIMARY KEY,"          # short public id (also the DELETE handle)
                    "  tenant TEXT NOT NULL,"
                    "  tier TEXT NOT NULL,"
                    "  name TEXT,"
                    "  hash TEXT NOT NULL UNIQUE,"    # sha256(plaintext) — the only copy of the secret
                    "  display TEXT,"                 # non-secret label: calma_sk_ab12…
                    "  created REAL,"
                    "  last_used REAL"
                    ")")
                c.execute("CREATE INDEX IF NOT EXISTS api_keys_hash ON api_keys(hash)")
                c.execute("CREATE INDEX IF NOT EXISTS api_keys_tenant ON api_keys(tenant)")
        except sqlite3.Error:
            pass

    def create(self, tenant: str, tier: str, name: str = "") -> dict | None:
        """Mint a key for `tenant`. Returns {id, key (PLAINTEXT — show once), display, name, tier, created}
        or None on error. The plaintext is never persisted."""
        if not tenant:
            return None
        key = _PREFIX + secrets.token_urlsafe(32)
        kid = secrets.token_hex(6)
        now = time.time()
        rec = {"id": kid, "tenant": tenant, "tier": tier, "name": (name or "").strip()[:80],
               "hash": _hash(key), "display": _display(key), "created": now, "last_used": None}
        try:
            with self._conn() as c:
                c.execute(
                    "INSERT INTO api_keys(id, tenant, tier, name, hash, display, created, last_used) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (rec["id"], rec["tenant"], rec["tier"], rec["name"], rec["hash"], rec["display"],
                     rec["created"], None))
        except sqlite3.Error:
            return None
        return {"id": kid, "key": key, "display": rec["display"], "name": rec["name"],
                "tier": tier, "created": now}

    def validate(self, key: str) -> dict | None:
        """Resolve a plaintext key → {id, tenant, tier, name} or None if unknown/revoked. Constant-time compare
        on the stored hash; stamps last_used (best-effort)."""
        if not key or not key.startswith(_PREFIX):
            return None
        h = _hash(key)
        try:
            with self._conn() as c:
                row = c.execute(
                    "SELECT id, tenant, tier, name, hash FROM api_keys WHERE hash=?", (h,)).fetchone()
        except sqlite3.Error:
            return None
        if not row or not hmac.compare_digest(row[4], h):
            return None
        try:
            with self._conn() as c:
                c.execute("UPDATE api_keys SET last_used=? WHERE id=?", (time.time(), row[0]))
        except sqlite3.Error:
            pass
        return {"id": row[0], "tenant": row[1], "tier": row[2], "name": row[3]}

    def list(self, tenant: str) -> list[dict]:
        """This tenant's keys — metadata only (never the plaintext or the hash), newest first."""
        try:
            with self._conn() as c:
                rows = c.execute(
                    "SELECT id, name, display, tier, created, last_used FROM api_keys "
                    "WHERE tenant=? ORDER BY created DESC", (tenant,)).fetchall()
        except sqlite3.Error:
            return []
        return [{"id": r[0], "name": r[1], "display": r[2], "tier": r[3],
                 "created": r[4], "last_used": r[5]} for r in rows]

    def revoke(self, tenant: str, key_id: str) -> bool:
        """Delete one of THIS tenant's keys (tenant-scoped so a guessed id can't revoke another's). True if a
        row was removed."""
        try:
            with self._conn() as c:
                cur = c.execute("DELETE FROM api_keys WHERE id=? AND tenant=?", (key_id, tenant))
                return cur.rowcount > 0
        except sqlite3.Error:
            return False


_STORE: ApiKeyStore | None = None


def get_store() -> ApiKeyStore:
    global _STORE
    if _STORE is None:
        _STORE = ApiKeyStore()
    return _STORE
