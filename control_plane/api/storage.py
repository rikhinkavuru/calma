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
            region_name="auto", config=Config(signature_version="s3v4"))
    return _client


def _bucket():
    return config.R2_BUCKET


def tenant_key(tenant_id, *parts) -> str:
    return "t/%s/%s" % (tenant_id, "/".join(str(p).strip("/") for p in parts))


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


def exists(key) -> bool:
    try:
        client().head_object(Bucket=_bucket(), Key=key)
        return True
    except Exception:
        return False
