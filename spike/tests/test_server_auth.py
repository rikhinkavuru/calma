"""The verification API is first-party only when a service token is configured: the WorkOS-gated dashboard
proxies submissions with the token; a tokenless browser cannot hit it directly. Fail-closed when set, open
for the local operator when unset."""
import importlib
import sys

import pytest


def _load_server(monkeypatch, token):
    if token is None:
        monkeypatch.delenv("CALMA_VERIFY_TOKEN", raising=False)
        monkeypatch.delenv("CALMA_SERVICE_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CALMA_VERIFY_TOKEN", token)
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
