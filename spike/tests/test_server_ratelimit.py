"""Admission control at the verification API: tiered rate limits, quotas, and feature gates (PRICING.md,
made real) plus the untrusted-input hardening (local-path block, cross-tenant installation guard,
constant-time token). The verdict is never gated — only how much / how deep. All hermetic: run_job is stubbed
so no clone/sandbox is attempted, and the process-wide limiter is reset per test."""
import importlib
import sys

import pytest


def _load(monkeypatch, token="s3cret", force_e2b=False, install_secret=None):
    if token is None:
        monkeypatch.delenv("CALMA_VERIFY_TOKEN", raising=False)
        monkeypatch.delenv("CALMA_SERVICE_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CALMA_VERIFY_TOKEN", token)
    monkeypatch.setenv("CALMA_FORCE_E2B", "1" if force_e2b else "0")
    if install_secret is None:
        monkeypatch.delenv("CALMA_INSTALL_SECRET", raising=False)
    else:
        monkeypatch.setenv("CALMA_INSTALL_SECRET", install_secret)
    sys.modules.pop("server", None)
    srv = importlib.import_module("server")
    # reset the process-wide limiter so counters don't leak between tests
    srv.LIM._LIMITER = None

    # stub the background worker: no clone/sandbox, but faithfully free the concurrency slot like the real one
    def fake_run_job(job, req):
        if job.get("_slot"):
            srv.LIM.get_limiter().release_slot(job.get("_tenant", "anon"))
        job["status"] = "done"
    monkeypatch.setattr(srv, "run_job", fake_run_job)
    return srv


def _client(srv):
    from fastapi.testclient import TestClient
    return TestClient(srv.app)


def _hdr(token="s3cret", tenant="userA", tier="free"):
    h = {}
    if token is not None:
        h["X-Calma-Service-Token"] = token
    if tenant is not None:
        h["X-Calma-Tenant"] = tenant
    if tier is not None:
        h["X-Calma-Tier"] = tier
    return h


@pytest.fixture
def _cleanup():
    yield
    sys.modules.pop("server", None)


def test_constant_time_token_still_gates(monkeypatch, _cleanup):
    srv = _load(monkeypatch)
    c = _client(srv)
    assert c.post("/api/verify", json={"repo": "x/y"}).status_code == 401
    assert c.post("/api/verify", json={"repo": "x/y"}, headers=_hdr(token="wrong")).status_code == 401
    assert c.post("/api/verify", json={"repo": "x/y"}, headers=_hdr()).status_code == 200


def test_api_rate_limit_returns_429_with_retry_after(monkeypatch, _cleanup):
    srv = _load(monkeypatch)
    c = _client(srv)
    # pre-seed the burst window at the free ceiling so the next request trips the limit deterministically
    free = srv.LIM.resolve_tier("free")
    import time
    srv.LIM.get_limiter()._api["userA"] = (int(time.time() // 60), free.api_rpm)
    r = c.post("/api/verify", json={"repo": "x/y"}, headers=_hdr())
    assert r.status_code == 429 and int(r.headers.get("Retry-After", "0")) >= 1


def test_daily_quota_downgrades_deep_to_discovery(monkeypatch, _cleanup):
    srv = _load(monkeypatch)
    c = _client(srv)
    lim = srv.LIM.get_limiter()
    free = srv.LIM.resolve_tier("free")
    import time
    day = time.strftime("%Y-%m-%d", time.gmtime())
    lim._scans[("userA", day)] = free.deep_verify_per_day        # quota already spent
    r = c.post("/api/verify", json={"repo": "x/y", "deep": True}, headers=_hdr())
    assert r.status_code == 200
    body = r.json()
    assert body["deep"] is False                                 # deep deferred, funnel stays open
    assert any("quota" in n for n in body["limit_notes"])


def test_discovery_only_never_draws_the_scan_quota(monkeypatch, _cleanup):
    srv = _load(monkeypatch)
    c = _client(srv)
    lim = srv.LIM.get_limiter()
    for _ in range(20):                                          # well past free=5/day
        assert c.post("/api/verify", json={"repo": "x/y", "deep": False}, headers=_hdr()).status_code == 200
    import time
    day = time.strftime("%Y-%m-%d", time.gmtime())
    assert lim._scans.get(("userA", day), 0) == 0                # discovery is ~free; it never meters


def test_deep_verify_draws_quota_and_frees_slot(monkeypatch, _cleanup):
    srv = _load(monkeypatch)
    c = _client(srv)
    lim = srv.LIM.get_limiter()
    assert c.post("/api/verify", json={"repo": "x/y", "deep": True}, headers=_hdr()).status_code == 200
    import time
    day = time.strftime("%Y-%m-%d", time.gmtime())
    assert lim._scans.get(("userA", day), 0) == 1               # one deep verify metered
    assert lim._inflight.get("userA", 0) == 0                    # stub released the concurrency slot


def test_free_tier_gates_private_repo_installation(monkeypatch, _cleanup):
    srv = _load(monkeypatch)
    c = _client(srv)
    r = c.post("/api/verify", json={"repo": "x/y", "installation_id": "999"}, headers=_hdr(tier="free"))
    assert r.status_code == 402 and "private" in r.json()["detail"].lower()


def test_free_tier_gates_fetch_data(monkeypatch, _cleanup):
    srv = _load(monkeypatch)
    c = _client(srv)
    r = c.post("/api/verify", json={"repo": "x/y", "fetch_data": True}, headers=_hdr(tier="free"))
    assert r.status_code == 402


def test_public_deploy_blocks_local_path_repo(monkeypatch, _cleanup):
    srv = _load(monkeypatch, force_e2b=True)
    c = _client(srv)
    for local in ("/app", "/etc/passwd", "./secrets", "../../x"):
        r = c.post("/api/verify", json={"repo": local}, headers=_hdr())
        assert r.status_code == 400, local
    # a real GitHub slug is accepted
    assert c.post("/api/verify", json={"repo": "owner/name"}, headers=_hdr()).status_code == 200


def test_installation_bound_to_tenant_blocks_cross_tenant_use(monkeypatch, _cleanup):
    srv = _load(monkeypatch)
    c = _client(srv)
    # tenant A connects installation 555 (as the setup redirect would, via the proxy forwarding the tenant)
    c.get("/connect/github/setup?installation_id=555&setup_action=install",
          headers={"X-Calma-Service-Token": "s3cret", "X-Calma-Tenant": "userA"})
    # tenant B (paid, so the private-repo gate is passed) cannot use A's installation
    r = c.post("/api/verify", json={"repo": "x/y", "installation_id": "555"},
               headers=_hdr(tenant="userB", tier="pro"))
    assert r.status_code == 403
    # the owner (tenant A) can
    assert c.post("/api/verify", json={"repo": "x/y", "installation_id": "555"},
                  headers=_hdr(tenant="userA", tier="pro")).status_code == 200
    # and B cannot enumerate A's repos either
    assert c.get("/api/gh/repos?installation_id=555", headers=_hdr(tenant="userB", tier="pro")).status_code == 403


def test_job_endpoints_are_tenant_scoped(monkeypatch, _cleanup):
    """get_job / get_job_logs / list_jobs used to check ONLY the service token, never the job's owning
    tenant — any authed caller (including the public demo route, which authenticates with the token but not
    a real user) could read any other tenant's full job record (claims, verdicts, raw logs) by guessing/
    reusing a job id (e.g. one seen on a public /api/badge/{id})."""
    srv = _load(monkeypatch)
    c = _client(srv)
    jid = c.post("/api/verify", json={"repo": "x/y"}, headers=_hdr(tenant="userA")).json()["id"]

    # the owning tenant can read its own job + logs, and sees it in its own list
    assert c.get("/api/jobs/%s" % jid, headers=_hdr(tenant="userA")).status_code == 200
    assert c.get("/api/jobs/%s/logs" % jid, headers=_hdr(tenant="userA")).status_code == 200
    assert jid in [j["id"] for j in c.get("/api/jobs", headers=_hdr(tenant="userA")).json()]

    # a different tenant gets an opaque 404 — not 403 (never confirms the job exists), on every job route,
    # and the job is absent from tenant B's own list
    assert c.get("/api/jobs/%s" % jid, headers=_hdr(tenant="userB")).status_code == 404
    assert c.get("/api/jobs/%s/logs" % jid, headers=_hdr(tenant="userB")).status_code == 404
    assert jid not in [j["id"] for j in c.get("/api/jobs", headers=_hdr(tenant="userB")).json()]

    # the local/unmetered operator (no token) still sees everything — the trusted single-operator flow
    srv2 = _load(monkeypatch, token=None)
    c2 = _client(srv2)
    jid2 = c2.post("/api/verify", json={"repo": "x/y"}).json()["id"]
    assert c2.get("/api/jobs/%s" % jid2).status_code == 200


def test_installation_proof_survives_redeploy(monkeypatch, _cleanup):
    """The in-memory INSTALLATIONS map is wiped on every redeploy (it's a plain process dict) — that used to
    silently 403 every existing connection with a confusing "not connected" error even though the GitHub App
    was still installed. The stateless proof (CALMA_INSTALL_SECRET) must let the SAME tenant keep using the
    SAME installation across that wipe, while still refusing a forged/cross-tenant proof."""
    srv = _load(monkeypatch, install_secret="topsecret")
    c = _client(srv)
    r = c.get("/connect/github/setup?installation_id=555&setup_action=install",
              headers={"X-Calma-Service-Token": "s3cret", "X-Calma-Tenant": "userA"},
              follow_redirects=False)
    proof = r.headers.get("x-calma-install-proof")
    assert proof

    # simulate a redeploy: the process-wide map is gone, but the client kept the proof it was handed.
    srv.INSTALLATIONS.clear()

    # the owning tenant, with its proof, still works with zero server memory of the binding
    assert c.post("/api/verify", json={"repo": "x/y", "installation_id": "555", "installation_proof": proof},
                  headers=_hdr(tenant="userA", tier="pro")).status_code == 200
    assert c.get("/api/gh/repos?installation_id=555&installation_proof=%s" % proof,
                 headers=_hdr(tenant="userA", tier="pro")).status_code != 403

    # without a proof (and the map wiped) it's correctly unauthorized again — no silent bypass
    r2 = c.post("/api/verify", json={"repo": "x/y", "installation_id": "555"},
               headers=_hdr(tenant="userA", tier="pro"))
    assert r2.status_code == 403

    # a forged/cross-tenant proof (someone else's installation_id under a different tenant) is refused
    assert c.post("/api/verify", json={"repo": "x/y", "installation_id": "555", "installation_proof": proof},
                  headers=_hdr(tenant="userB", tier="pro")).status_code == 403


def test_owner_flow_unmetered_when_token_unset(monkeypatch, _cleanup):
    srv = _load(monkeypatch, token=None)
    c = _client(srv)
    # local operator: no token, no headers — unmetered, private installs allowed, never rate-limited
    for _ in range(50):
        assert c.post("/api/verify", json={"repo": "x/y", "deep": True}).status_code == 200


def test_usage_endpoint_reports_tenant_meters(monkeypatch, _cleanup):
    srv = _load(monkeypatch)
    c = _client(srv)
    c.post("/api/verify", json={"repo": "x/y", "deep": True}, headers=_hdr())
    u = c.get("/api/usage", headers=_hdr()).json()
    assert u["tier"] == "free" and u["scans_today"] == 1 and u["scans_per_day"] == 5


def test_tier_clamps_k_to_ceiling(monkeypatch, _cleanup):
    srv = _load(monkeypatch)
    c = _client(srv)
    captured = {}

    def capture_run_job(job, req):
        captured["k"] = req.k
        captured["top_k"] = req.top_k
        if job.get("_slot"):
            srv.LIM.get_limiter().release_slot(job.get("_tenant", "anon"))
    monkeypatch.setattr(srv, "run_job", capture_run_job)
    c.post("/api/verify", json={"repo": "x/y", "deep": True, "k": 99}, headers=_hdr(tier="free"))
    assert captured["k"] == 2 and captured["top_k"] == 3          # free: max_k=2, top_k=3
