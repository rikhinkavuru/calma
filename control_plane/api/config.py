"""control_plane.api.config — env-driven settings. Importing this also loads the repo-root .env and puts
control_plane/ on sys.path so `import db` (the psycopg connection) resolves."""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))            # control_plane/api
CONTROL_PLANE = os.path.dirname(HERE)                        # control_plane
REPO_ROOT = os.path.dirname(CONTROL_PLANE)                   # repo root

if CONTROL_PLANE not in sys.path:
    sys.path.insert(0, CONTROL_PLANE)
import db as _db  # noqa: E402  (control_plane/db.py)

_db.load_env()
connect = _db.connect          # re-export: a psycopg connection from DATABASE_URL
pool = _db.pool                # re-export: the process-wide connection pool (reused across warm requests)

# the pure-stdlib engine, invoked as a subprocess (the API is a thin host; it never reimplements verify).
# Resolve the engine interpreter: explicit override wins, then the system python3 (the dev-Mac default,
# byte-identical to prior behavior), else the interpreter running this process (Vercel/Fluid Compute has no
# /usr/bin/python3 on PATH but sys.executable is the function's own python).
def _engine_python():
    explicit = os.environ.get("CALMA_ENGINE_PYTHON")
    if explicit:
        return explicit
    if os.path.exists("/usr/bin/python3"):
        return "/usr/bin/python3"
    return sys.executable or "/usr/bin/python3"


ENGINE_PYTHON = _engine_python()
ENGINE_SCRIPT = os.path.join(REPO_ROOT, ".claude", "skills", "calma", "scripts", "calma.py")

# Isolation tier the engine must establish for untrusted code. Empty = let the engine auto-select the best
# LOCAL tier (seatbelt on macOS, bwrap/docker on Linux) — correct for a dev host. On a host WITHOUT a local
# sandbox (Vercel/Fluid Compute, plain containers) set CALMA_EXEC_ISOLATION=e2b so runs go to the hosted
# microVM (E2B/Firecracker) rather than fail-closed REFUSE. Validated against the engine's allowed set so a
# typo fails loudly at submit, not silently as host-default.
_ISO_OK = ("", "auto", "seatbelt", "bwrap", "docker", "firecracker", "e2b")
EXEC_ISOLATION = os.environ.get("CALMA_EXEC_ISOLATION", "").strip()
if EXEC_ISOLATION not in _ISO_OK:
    raise ValueError("CALMA_EXEC_ISOLATION must be one of %r (got %r)" % (_ISO_OK, EXEC_ISOLATION))

# Cloudflare R2 (S3-compatible) object storage.
R2_ENDPOINT = os.environ.get("R2_ENDPOINT", "")
R2_BUCKET = os.environ.get("R2_BUCKET", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")

# first-party service token: the dashboard (a trusted first party) authenticates to this API with
# X-Calma-Service-Token + X-Calma-Tenant-Id instead of a per-tenant API key.
SERVICE_TOKEN = os.environ.get("CALMA_SERVICE_TOKEN", "")

DEFAULT_WALL_SECONDS = int(os.environ.get("CALMA_DEFAULT_WALL_S", "120"))
UPLOAD_URL_TTL_S = int(os.environ.get("CALMA_UPLOAD_URL_TTL_S", "900"))
ERROR_BASE = "https://calma.dev/errors/"
