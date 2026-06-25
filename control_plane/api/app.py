"""control_plane.api.app — the FastAPI app. Resource = `verifications`; the public id is `verification_id`.
Auth = Bearer API key -> tenant. Errors are RFC-9457 problem+json. One DB connection per request (closed by
the dependency), with app.tenant_id set for RLS + explicit tenant scoping in every query."""
from __future__ import annotations

import base64
import hmac
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, Query
from fastapi.responses import Response

from . import bootstrap, config, errors, keys, repo, service, signing, storage
from .schemas import (KeyCreate, KeyCreated, ProvisionRequest, ProvisionResponse, SubmitRequest,
                      UploadRequest, UploadResponse)

app = FastAPI(title="Calma Verifications API", version="0.1.0",
              description="Re-execute a claimed metric to ground truth and recompute it from raw outputs.")
app.add_exception_handler(errors.Problem, errors.problem_handler)


def _is_service(token):
    # constant-time compare against EACH configured token (rotation overlap); empty list -> service path off.
    if not token or not config.SERVICE_TOKENS:
        return False
    return any(hmac.compare_digest(token, t) for t in config.SERVICE_TOKENS)


def _authenticate(conn, authorization, service_token, service_tenant):
    # first-party service path: the dashboard authenticates as a tenant via the shared service token.
    if _is_service(service_token):
        if not service_tenant:
            raise errors.unauthorized("missing X-Calma-Tenant-Id")
        tenant = repo.get_tenant(conn, service_tenant)
        if not tenant:
            raise errors.unauthorized("unknown tenant")
        repo.set_tenant(conn, tenant["id"])
        return tenant, None
    # bearer API-key path.
    if not authorization or not authorization.lower().startswith("bearer "):
        raise errors.unauthorized()
    token = authorization.split(" ", 1)[1].strip()
    parsed = keys.parse(token)
    if not parsed:
        raise errors.unauthorized("malformed API key")
    row = repo.get_api_key(conn, parsed["key_id"])
    if not row or not keys.verify(token, row["key_hash"]):
        raise errors.unauthorized()
    if row["revoked_at"] is not None:
        raise errors.unauthorized("key revoked")
    if row["expires_at"] is not None and row["expires_at"] < datetime.now(timezone.utc):
        raise errors.unauthorized("key expired")
    tenant = repo.get_tenant(conn, row["tenant_id"])
    if not tenant:
        raise errors.unauthorized("tenant not found")
    repo.set_tenant(conn, tenant["id"])
    repo.touch_api_key(conn, row["id"])
    return tenant, row["id"]


def request_ctx(authorization: Optional[str] = Header(None),
                x_calma_service_token: Optional[str] = Header(None),
                x_calma_tenant_id: Optional[str] = Header(None)):
    # Pooled connection (reused across warm requests) instead of a ~0.5s per-request reconnect.
    with config.pool().connection() as conn:
        tenant, api_key_id = _authenticate(conn, authorization, x_calma_service_token, x_calma_tenant_id)
        yield {"conn": conn, "tenant": tenant, "api_key_id": api_key_id}


def service_ctx(x_calma_service_token: Optional[str] = Header(None)):
    if not _is_service(x_calma_service_token):
        raise errors.unauthorized("invalid service token")
    with config.pool().connection() as conn:
        yield {"conn": conn}


def _key_info(r):
    return {"id": str(r["id"]), "prefix": r["prefix"], "environment": r["environment"],
            "created_at": r["created_at"].isoformat(),
            "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None,
            "revoked": r["revoked_at"] is not None}


def _enc_cursor(job) -> str:
    raw = "%s|%s" % (job["created_at"].isoformat(), job["id"])
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _dec_cursor(c):
    if not c:
        return None, None
    try:
        created, jid = base64.urlsafe_b64decode(c.encode()).decode().split("|", 1)
        return created, jid
    except Exception:
        raise errors.malformed("invalid cursor")


@app.get("/healthz")
def healthz():
    try:
        with config.pool().connection() as c:
            c.execute("SELECT 1")
        return {"ok": True}
    except Exception as e:
        raise errors.internal("db unreachable: %s" % e)


@app.get("/v1/signing-key")
def signing_key():
    """The PUBLIC ed25519 key the control-plane signs proofs with (no auth — it is meant to be public, and
    pinned out-of-band). Also committed at control_plane/signing_pubkey.json for offline pinning."""
    info = signing.public_key_info()
    if not info:
        raise errors.not_found("proof signing is not configured on this deployment")
    return info


@app.post("/v1/verifications")
def create_verification(req: SubmitRequest, ctx=Depends(request_ctx),
                        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    return service.submit(ctx["conn"], ctx["tenant"], ctx["api_key_id"], req, idempotency_key)


@app.get("/v1/verifications/{vid}")
def get_verification(vid: str, ctx=Depends(request_ctx)):
    job = repo.get_job(ctx["conn"], ctx["tenant"]["id"], vid)
    if not job:
        raise errors.not_found()
    return service.response_for_job(ctx["conn"], ctx["tenant"], job)


@app.get("/v1/verifications/{vid}/result")
def get_result(vid: str, ctx=Depends(request_ctx)):
    job = repo.get_job(ctx["conn"], ctx["tenant"]["id"], vid)
    if not job:
        raise errors.not_found()
    return service.response_for_job(ctx["conn"], ctx["tenant"], job)


@app.get("/v1/verifications/{vid}/proof")
def get_proof(vid: str, ctx=Depends(request_ctx)):
    v = repo.get_verdict_for_job(ctx["conn"], ctx["tenant"]["id"], vid)
    if not v or not v["proof_uri"]:
        raise errors.not_found("no proof for this verification")
    return Response(content=storage.get_bytes(v["proof_uri"]), media_type="application/json")


@app.get("/v1/verifications")
def list_verifications(ctx=Depends(request_ctx), limit: int = Query(50, le=200, ge=1),
                       cursor: Optional[str] = None):
    cc, ci = _dec_cursor(cursor)
    rows = repo.list_jobs(ctx["conn"], ctx["tenant"]["id"], limit + 1, cc, ci)
    has_more = len(rows) > limit
    rows = rows[:limit]
    data = [service.response_for_job(ctx["conn"], ctx["tenant"], r) for r in rows]
    return {"data": data, "next_cursor": _enc_cursor(rows[-1]) if (has_more and rows) else None}


@app.post("/v1/uploads", response_model=UploadResponse)
def create_upload(req: UploadRequest, ctx=Depends(request_ctx)):
    if req.kind not in ("bundle", "input"):
        raise errors.malformed("kind must be bundle|input")
    sub = "bundles" if req.kind == "bundle" else "inputs"
    name = ("%s.tar.gz" % req.sha256) if req.kind == "bundle" else req.sha256
    key = storage.tenant_key(ctx["tenant"]["id"], sub, name)
    url = storage.presign_put(key, req.content_type)
    return UploadResponse(url=url, uri=key, expires_in=config.UPLOAD_URL_TTL_S)


# ---------- first-party / dashboard ----------
@app.post("/internal/provision", response_model=ProvisionResponse)
def provision(req: ProvisionRequest, ctx=Depends(service_ctx)):
    res = repo.provision_tenant(ctx["conn"], workos_user_id=req.workos_user_id, email=req.email,
                                org_name=req.org_name, workos_org_id=req.workos_org_id)
    bootstrap.seed_registry(ctx["conn"])          # ensure recipes/templates exist so submits FK-resolve
    return res


@app.get("/v1/keys")
def list_keys(ctx=Depends(request_ctx)):
    return {"data": [_key_info(r) for r in repo.list_api_keys(ctx["conn"], ctx["tenant"]["id"])]}


@app.post("/v1/keys", response_model=KeyCreated)
def create_key(req: KeyCreate, ctx=Depends(request_ctx)):
    if req.environment not in ("live", "test"):
        raise errors.malformed("environment must be live|test")
    k = keys.generate(req.environment)
    row = repo.insert_api_key(ctx["conn"], ctx["tenant"]["id"], k["prefix"], k["key_id"],
                              k["key_hash"], k["environment"])
    repo.insert_audit(ctx["conn"], tenant_id=ctx["tenant"]["id"], actor_type="user", actor_id=None,
                      action="key.create", resource_type="api_key", resource_id=row["id"],
                      metadata={"prefix": k["prefix"]})
    return KeyCreated(id=str(row["id"]), prefix=k["prefix"], environment=k["environment"],
                      created_at=row["created_at"].isoformat(), token=k["token"])


@app.delete("/v1/keys/{kid}")
def revoke_key(kid: str, ctx=Depends(request_ctx)):
    if not repo.revoke_api_key(ctx["conn"], ctx["tenant"]["id"], kid):
        raise errors.not_found("key not found or already revoked")
    repo.insert_audit(ctx["conn"], tenant_id=ctx["tenant"]["id"], actor_type="user", actor_id=None,
                      action="key.revoke", resource_type="api_key", resource_id=kid, metadata={})
    return {"revoked": True}
