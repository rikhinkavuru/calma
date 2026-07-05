"""Every response carries baseline security headers (defence-in-depth on the network-facing verify API)."""
import importlib
import sys

from fastapi.testclient import TestClient


def test_baseline_security_headers_on_every_response(monkeypatch):
    # Open (tokenless) flow — the headers apply regardless of auth, on any response (incl. errors).
    monkeypatch.delenv("CALMA_VERIFY_TOKEN", raising=False)
    monkeypatch.delenv("CALMA_SERVICE_TOKEN", raising=False)
    sys.modules.pop("server", None)
    srv = importlib.import_module("server")
    try:
        r = TestClient(srv.app).get("/api/catalog")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
        assert r.headers.get("Referrer-Policy") == "no-referrer"
        assert "max-age=" in (r.headers.get("Strict-Transport-Security") or "")
    finally:
        sys.modules.pop("server", None)
