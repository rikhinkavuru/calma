"""Server-level proof of the crash-safety guarantee: a pathological job ends as a clean per-job error AND
the API keeps serving — the next job still runs to a correct result. This is the 502 the isolation fixes:
before, a repo that OOM'd in the in-process work took down the whole API and every job with it."""
import importlib
import sys
import time

import pytest


def _load_server(monkeypatch):
    monkeypatch.delenv("CALMA_VERIFY_TOKEN", raising=False)
    monkeypatch.delenv("CALMA_SERVICE_TOKEN", raising=False)
    monkeypatch.setenv("CALMA_FORCE_E2B", "0")        # local fixture path; deep=False does no execution anyway
    sys.modules.pop("server", None)
    return importlib.import_module("server")


@pytest.fixture
def _cleanup():
    yield
    sys.modules.pop("server", None)


def _wait_terminal(client, jid, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{jid}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.1)
    raise AssertionError("job %s never reached a terminal state (last=%s)" % (jid, job["status"]))


def test_bombing_job_errors_cleanly_and_api_keeps_serving(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    srv = _load_server(monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Demo\nWe report accuracy = 0.9 on the held-out set.\n")

    c = TestClient(srv.app)

    # 1) A job whose isolated work blows its memory budget. The child bombs; the API must NOT.
    monkeypatch.setenv("CALMA_VERIFY_SELFTEST", "memory")
    monkeypatch.setenv("CALMA_VERIFY_MEM_MB", "300")
    jid1 = c.post("/api/verify", json={"repo": str(repo), "runner": "local", "deep": False}).json()["id"]
    job1 = _wait_terminal(c, jid1)
    assert job1["status"] == "error"
    assert job1["stage"] == "exceeded budget"
    assert job1.get("failure_kind") == "memory"      # surfaced WHY, not a generic 500

    # 2) The API is alive and unharmed: it lists jobs and runs the NEXT job to a correct result.
    assert c.get("/api/jobs").status_code == 200
    monkeypatch.delenv("CALMA_VERIFY_SELFTEST")       # each job spawns a fresh child → next one is healthy
    monkeypatch.delenv("CALMA_VERIFY_MEM_MB")
    jid2 = c.post("/api/verify",
                  json={"repo": str(repo), "runner": "local", "deep": False, "discover": True}).json()["id"]
    job2 = _wait_terminal(c, jid2)
    assert job2["status"] == "done"
    assert job2["n_claims"] == 1
    assert job2["claims"][0]["metric"] == "accuracy"
