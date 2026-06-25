"""control_plane.api.storage — Cloudflare R2 (S3-compatible) object storage. Per-tenant key prefixes
(t/<tenant_id>/...) so a path bug can't cross a tenant boundary (spec-01 §7). Boto3 client, lazily built."""
from __future__ import annotations

import os

from . import config

_client = None


def client():
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config
        _client = boto3.client(
            "s3", endpoint_url=config.R2_ENDPOINT,
            aws_access_key_id=config.R2_ACCESS_KEY_ID,
            aws_secret_access_key=config.R2_SECRET_ACCESS_KEY,
            region_name="auto",
            # D9-04: bound every R2 call. connect/read timeouts stop a hung R2 from holding the (inline)
            # request open to the Vercel function limit; adaptive retries add client-side rate-limiting +
            # backoff (circuit-breaker behaviour) so a flaky/throttling R2 degrades instead of stampeding.
            config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=30,
                          retries={"max_attempts": 3, "mode": "adaptive"}))
    return _client


def _bucket():
    return config.R2_BUCKET


def tenant_key(tenant_id, *parts) -> str:
    return "t/%s/%s" % (tenant_id, "/".join(str(p).strip("/") for p in parts))


def key_under_tenant(key, tenant_id) -> bool:
    """A caller-supplied object key is in-scope only if it lives under THIS tenant's prefix (t/<id>/...).
    Guards against a tenant referencing another tenant's R2 objects (BOLA/IDOR): every key the dashboard /
    uploads API hands back is already a tenant_key(), so legitimate flows pass unchanged."""
    return isinstance(key, str) and key.startswith("t/%s/" % tenant_id)


def presign_put(key, content_type="application/octet-stream", ttl=None) -> str:
    # ContentType is intentionally NOT signed so a PUT (server- or browser-side) needs no exact header match.
    return client().generate_presigned_url(
        "put_object",
        Params={"Bucket": _bucket(), "Key": key},
        ExpiresIn=ttl or config.UPLOAD_URL_TTL_S)


def put_bytes(key, data, content_type="application/octet-stream"):
    client().put_object(Bucket=_bucket(), Key=key, Body=data, ContentType=content_type)


def get_bytes(key) -> bytes:
    return client().get_object(Bucket=_bucket(), Key=key)["Body"].read()


def download_to(key, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    client().download_file(_bucket(), key, path)


def upload_file(path, key, content_type="application/octet-stream"):
    client().upload_file(path, _bucket(), key, ExtraArgs={"ContentType": content_type})


def delete(key):
    """Remove an object (used to drop the raw input bundle after a run — the no-raw-retention control)."""
    client().delete_object(Bucket=_bucket(), Key=key)


def delete_prefix(prefix) -> int:
    """Delete EVERY object under a key prefix (DSR / right-to-erasure tenant purge). Returns the count."""
    c, b, n = client(), _bucket(), 0
    for page in c.get_paginator("list_objects_v2").paginate(Bucket=b, Prefix=prefix):
        objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if objs:
            c.delete_objects(Bucket=b, Delete={"Objects": objs})
            n += len(objs)
    return n


def exists(key) -> bool:
    try:
        client().head_object(Bucket=_bucket(), Key=key)
        return True
    except Exception:
        return False
