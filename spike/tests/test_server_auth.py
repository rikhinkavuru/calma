"""The verification API is first-party only when a service token is configured: the WorkOS-gated dashboard
proxies submissions with the token; a tokenless browser cannot hit it directly. Fail-closed when set, open
for the local operator when unset."""
import importlib
import sys

import pytest


def _load_server(monkeypatch, token, force_e2b=False):
    if token is None:
        monkeypatch.delenv("CALMA_VERIFY_TOKEN", raising=False)
        monkeypatch.delenv("CALMA_SERVICE_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CALMA_VERIFY_TOKEN", token)
    monkeypatch.setenv("CALMA_FORCE_E2B", "1" if force_e2b else "0")
    sys.modules.pop("server", None)
    return importlib.import_module("server")


@pytest.fixture
def _cleanup():
    yield
    sys.modules.pop("server", None)


def test_gate_rejects_without_token(monkeypatch, _cleanup):
    from fastapi.testclient import TestClient
    srv = _load_server(monkeypatch, "s3cret")
    c = TestClient(srv.app)
    assert c.post("/api/verify", json={"repo": "x/y"}).status_code == 401
    assert c.get("/api/jobs").status_code == 401


def test_gate_allows_with_token(monkeypatch, _cleanup):
    from fastapi.testclient import TestClient
    srv = _load_server(monkeypatch, "s3cret")
    c = TestClient(srv.app)
    assert c.get("/api/jobs", headers={"X-Calma-Service-Token": "s3cret"}).status_code == 200


def test_gate_open_when_unset(monkeypatch, _cleanup):
    from fastapi.testclient import TestClient
    srv = _load_server(monkeypatch, None)
    c = TestClient(srv.app)
    # no token configured -> the local-first operator flow stays open
    assert c.get("/api/jobs").status_code == 200


def test_force_e2b_overrides_local_runner(monkeypatch, _cleanup):
    """On a public deployment (CALMA_FORCE_E2B), a `local` submission must be forced into E2B isolation —
    untrusted code never runs on the host."""
    from fastapi.testclient import TestClient
    srv = _load_server(monkeypatch, "s3cret", force_e2b=True)
    c = TestClient(srv.app)
    r = c.post("/api/verify", json={"repo": "x/y", "runner": "local"},
               headers={"X-Calma-Service-Token": "s3cret"})
    assert r.status_code == 200
    jid = r.json()["id"]
    job = c.get(f"/api/jobs/{jid}", headers={"X-Calma-Service-Token": "s3cret"}).json()
    assert job["runner"] == "e2b"


def test_local_runner_allowed_when_not_forced(monkeypatch, _cleanup):
    from fastapi.testclient import TestClient
    srv = _load_server(monkeypatch, None, force_e2b=False)
    c = TestClient(srv.app)
    jid = c.post("/api/verify", json={"repo": "x/y", "runner": "local"}).json()["id"]
    assert c.get(f"/api/jobs/{jid}").json()["runner"] == "local"


def test_clone_falls_back_to_git_when_gh_missing(monkeypatch, _cleanup):
    """On a server (no `gh` binary) a missing gh must fall through to plain git, not crash the job."""
    srv = _load_server(monkeypatch, None)
    calls = []

    class _R:
        def __init__(self, rc):
            self.returncode = rc
            self.stderr = ""

    def fake_run(argv, *a, **k):
        calls.append(argv[0])
        if argv[0] == "gh":
            raise FileNotFoundError("gh")           # not installed
        return _R(0)                                  # git clone succeeds
    monkeypatch.setattr(srv.subprocess, "run", fake_run)
    monkeypatch.setattr(srv.GH, "configured", lambda: False)

    job = {"logs": [], "updated": 0.0}
    dest = srv._clone("owner/name", "/tmp/calma_clone_test_dest", job)
    assert dest == "/tmp/calma_clone_test_dest"
    assert "gh" in calls and "git" in calls          # tried gh, fell back to git


def test_clone_never_logs_the_installation_token_on_failure(monkeypatch, _cleanup):
    """The clone URL embeds the live installation token (x-access-token:{tok}@...); git's own error text
    commonly echoes the remote URL back verbatim. A clone failure must never let that token reach the job
    log — logs are readable later (get_job_logs)."""
    srv = _load_server(monkeypatch, None)
    secret_token = "ghs_SUPERSECRETTOKEN12345"

    class _R:
        def __init__(self, rc, stderr):
            self.returncode = rc
            self.stderr = stderr

    def fake_run(argv, *a, **k):
        if argv[0] == "git":
            # a realistic git error: it echoes the full remote URL, credential included
            url = srv.GH.clone_url(secret_token, "owner/name")
            return _R(128, "fatal: unable to access '%s/': The requested URL returned error: 403\n" % url)
        raise FileNotFoundError(argv[0])
    monkeypatch.setattr(srv.subprocess, "run", fake_run)
    monkeypatch.setattr(srv.GH, "configured", lambda: True)
    monkeypatch.setattr(srv.GH, "installation_token_for", lambda iid: secret_token)

    job = {"logs": [], "updated": 0.0}
    try:
        srv._clone("owner/name", "/tmp/calma_clone_test_dest2", job, installation_id="42")
    except Exception:  # noqa: BLE001 — the fallback paths (gh/git) also fail in this test; only the log matters
        pass
    logged = " ".join(job["logs"])
    assert secret_token not in logged, logged
