"""In-memory JOBS retention is bounded (no memory leak) and never evicts active work; /healthz is live."""
import importlib
import sys

from fastapi.testclient import TestClient


def _load(monkeypatch, max_jobs):
    monkeypatch.delenv("CALMA_VERIFY_TOKEN", raising=False)
    monkeypatch.setenv("CALMA_MAX_JOBS", str(max_jobs))
    sys.modules.pop("server", None)
    return importlib.import_module("server")


def test_evict_bounds_terminal_jobs_and_keeps_active(monkeypatch):
    srv = _load(monkeypatch, 3)
    try:
        for i in range(5):                              # 5 finished (created 0..4)
            jid = "done%d" % i
            srv.JOBS[jid] = {"id": jid, "status": "done", "created": float(i), "updated": float(i)}
        srv.JOBS["run"] = {"id": "run", "status": "running", "created": 100.0, "updated": 100.0}
        with srv._LOCK:
            srv._evict_jobs()
        assert "run" in srv.JOBS                         # active work is never evicted
        assert len(srv.JOBS) <= 3                         # bounded to the cap
        assert "done0" not in srv.JOBS and "done1" not in srv.JOBS   # oldest terminal go first
        assert "done4" in srv.JOBS                        # newest terminal retained
    finally:
        sys.modules.pop("server", None)


def test_healthz_is_open_and_minimal(monkeypatch):
    srv = _load(monkeypatch, 500)
    try:
        r = TestClient(srv.app).get("/healthz")
        assert r.status_code == 200
        assert r.json()["ok"] is True
    finally:
        sys.modules.pop("server", None)
