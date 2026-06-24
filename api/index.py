"""Vercel Python (Fluid Compute) entrypoint for the Calma Verifications API.

`@vercel/python` detects the module-level ASGI `app` and serves it; all routes are sent here by
api.vercel.json (routes -> this function), so FastAPI sees the original path (/v1/..., /internal/..., /healthz).

Why the two env defaults below:
  * CALMA_ENGINE_PYTHON = this function's own interpreter — the engine is spawned as a subprocess and, on the
    E2B path, imports the `e2b` SDK; only sys.executable's site-packages has it (a stray /usr/bin/python3 would
    not). An explicit Project env var still wins (setdefault).
  * the engine + control_plane trees are bundled via api.vercel.json `includeFiles`; nothing else to stage.
"""
from __future__ import annotations

import os
import sys

# repo root (this file is at <root>/api/index.py) -> make `control_plane` importable.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# pin the engine subprocess to the interpreter that actually has the installed deps (e2b/boto3/...).
os.environ.setdefault("CALMA_ENGINE_PYTHON", sys.executable)

# @vercel/python puts the installed deps (the e2b SDK etc.) on THIS process's sys.path, but the engine runs
# as a FRESH subprocess that resolves its own site dirs and would miss them ("No module named 'e2b'" ->
# --isolation e2b REFUSED). Propagate our sys.path via PYTHONPATH; engine.run_verify inherits os.environ, so
# the child can import the SDK. Same interpreter (CALMA_ENGINE_PYTHON=sys.executable) -> no ABI mismatch.
_pp = os.pathsep.join(p for p in sys.path if p)
_existing = os.environ.get("PYTHONPATH", "")
os.environ["PYTHONPATH"] = (_pp + os.pathsep + _existing) if _existing else _pp

from control_plane.api.app import app  # noqa: E402  (ASGI app Vercel serves)

__all__ = ["app"]
