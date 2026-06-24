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
