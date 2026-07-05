"""API keys — the store, plus the end-to-end auth flow (create via dashboard → use the key directly)."""

import importlib
import os

import pytest
from fastapi.testclient import TestClient

from core import apikeys as AK


# ── store ────────────────────────────────────────────────────────────────────────────────────────────────
def test_create_returns_plaintext_once_then_only_hash(tmp_path):
    s = AK.ApiKeyStore(str(tmp_path / "k.db"))
    out = s.create("tenant-1", "pro", "laptop")
    assert out and out["key"].startswith("calma_sk_")
    # the plaintext is never in the listing; the display is masked
    listed = s.list("tenant-1")
    assert len(listed) == 1
    assert "key" not in listed[0] and listed[0]["display"].endswith("…")
    assert listed[0]["name"] == "laptop" and listed[0]["tier"] == "pro"


def test_validate_resolves_tenant_and_tier(tmp_path):
    s = AK.ApiKeyStore(str(tmp_path / "k.db"))
    out = s.create("tenant-2", "enterprise")
    rec = s.validate(out["key"])
    assert rec and rec["tenant"] == "tenant-2" and rec["tier"] == "enterprise"
    assert s.validate("calma_sk_not-a-real-key") is None
    assert s.validate("bogus") is None


def test_revoke_is_tenant_scoped(tmp_path):
    s = AK.ApiKeyStore(str(tmp_path / "k.db"))
    a = s.create("owner-A", "pro")
    assert s.revoke("owner-B", a["id"]) is False        # another tenant can't revoke it
    assert s.validate(a["key"]) is not None              # still valid
    assert s.revoke("owner-A", a["id"]) is True
    assert s.validate(a["key"]) is None                  # gone


# ── end-to-end through the app ───────────────────────────────────────────────────────────────────────────
@pytest.fixture
def app(tmp_path, monkeypatch):
    # A hosted-style engine: service token SET (so anon is free-tier), keys/data under a temp dir.
    monkeypatch.setenv("CALMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CALMA_VERIFY_TOKEN", "svc-tok")
    monkeypatch.setenv("CALMA_FORCE_E2B", "0")
    import server
    importlib.reload(server)
    return server


def test_key_management_requires_service_token(app):
    c = TestClient(app.app)
    # no service token → key management refused (a plain API-key holder can't mint keys)
    assert c.post("/api/keys", json={"name": "x"}).status_code == 401
    # with the service token + tenant, minting works
    r = c.post("/api/keys", headers={"X-Calma-Service-Token": "svc-tok", "X-Calma-Tenant": "acme",
                                     "X-Calma-Tier": "pro"}, json={"name": "ci"})
    assert r.status_code == 200
    assert r.json()["key"].startswith("calma_sk_")


def test_api_key_authenticates_direct_calls(app):
    c = TestClient(app.app)
    key = c.post("/api/keys", headers={"X-Calma-Service-Token": "svc-tok", "X-Calma-Tenant": "acme",
                                       "X-Calma-Tier": "pro"}, json={}).json()["key"]
    # the key alone (no service token) authenticates /api/jobs as tenant "acme"
    r = c.get("/api/jobs", headers={"Authorization": "Bearer " + key})
    assert r.status_code == 200 and isinstance(r.json(), list)
    # a bogus key is rejected
    assert c.get("/api/jobs", headers={"Authorization": "Bearer calma_sk_nope"}).status_code == 401
    # no credential at all is rejected
    assert c.get("/api/jobs").status_code == 401


def test_api_key_cannot_manage_keys(app):
    c = TestClient(app.app)
    key = c.post("/api/keys", headers={"X-Calma-Service-Token": "svc-tok", "X-Calma-Tenant": "acme",
                                       "X-Calma-Tier": "pro"}, json={}).json()["key"]
    # using the API key to LIST/CREATE keys is refused (dashboard_identity rejects a bearer key)
    assert c.get("/api/keys", headers={"Authorization": "Bearer " + key}).status_code == 401
    assert c.post("/api/keys", headers={"Authorization": "Bearer " + key}, json={}).status_code == 401
