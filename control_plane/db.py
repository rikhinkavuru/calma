"""control_plane.db — minimal env loader + Postgres connection for the Calma control plane.

Reads the repo-root .env (gitignored) so DATABASE_URL / R2 / WorkOS creds resolve without exporting them
by hand. The control plane is a SEPARATE service from the pure-stdlib engine, so it is allowed third-party
deps (psycopg); the engine itself stays dependency-free.
"""
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env(path=None):
    """Parse a dotenv file into os.environ (existing values win, so a real export overrides .env)."""
    path = path or os.path.join(REPO_ROOT, ".env")
    if not os.path.exists(path):
        return
    for raw in open(path):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = re.split(r"\s+#", v, 1)[0].strip()          # drop trailing inline "  # comment"
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        if k and k not in os.environ:
            os.environ[k] = v


def dsn():
    load_env()
    d = os.environ.get("DATABASE_URL", "")
    if not d.startswith("postgresql://") and not d.startswith("postgres://"):
        raise SystemExit("DATABASE_URL is not a postgresql:// URI (got %r). Check .env."
                         % (d[:40] + "…" if d else ""))
    return d


def connect(autocommit=True):
    """A live psycopg3 connection. Raises a clear message if the driver isn't installed."""
    try:
        import psycopg
    except ImportError:
        raise SystemExit("psycopg not installed. Run: control_plane/setup-venv.sh  (or pip install 'psycopg[binary]')")
    return psycopg.connect(dsn(), autocommit=autocommit, connect_timeout=15)


_pool = None


def _reset(conn):
    # Clear the per-request tenant GUC before a connection goes back to the pool. Isolation is the explicit
    # `WHERE tenant_id=%s` in every query (the owner role bypasses RLS), so this is defense-in-depth.
    conn.execute("SELECT set_config('app.tenant_id', '', false)")


def pool():
    """A lazily-built, process-wide connection POOL. Establishing a fresh psycopg connection to Supabase
    costs ~0.5s (TLS + auth + pooler routing) — paid on EVERY request when we connect-per-request. On
    serverless (Vercel Fluid Compute) this module persists across warm invocations, so the pool REUSES
    connections instead. Safe with our tenant model: isolation is the explicit WHERE tenant_id, not
    connection state, and app.tenant_id is re-set per authenticated request (and cleared on return)."""
    global _pool
    if _pool is None:
        try:
            from psycopg_pool import ConnectionPool
        except ImportError:
            raise SystemExit("psycopg_pool not installed. Run: pip install 'psycopg[binary,pool]'")
        _pool = ConnectionPool(
            dsn(), min_size=1, max_size=8, open=True, timeout=15, max_idle=300,
            kwargs={"autocommit": True, "prepare_threshold": None},
            check=ConnectionPool.check_connection,   # ping on checkout: never hand out a dead connection
            reset=_reset,
        )
    return _pool
