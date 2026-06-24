"""control_plane.api.schemas — Pydantic request/response models. The PUBLIC identifier is always
`verification_id` (= jobs.id); `job_id`/`run_id` never appear in a payload (CANONICAL §2)."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ---------- shared ----------
class Claim(BaseModel):
    metric: str
    value: float


class Bundle(BaseModel):
    uri: str                      # R2 object key/uri of the code bundle (tar.gz)
    sha256: str
    entrypoint: str               # contract run.entrypoint inside the bundle
    language: str = "python"


class DataRef(BaseModel):
    uri: str
    sha256: str
    dest_rel: str                 # relative path inside the workdir (safe_join-checked)
    size_bytes: int = 0


class Limits(BaseModel):
    cpu_cores: float = 2.0
    mem_mb: int = 2048
    wall_seconds: int = 120


# ---------- submit ----------
class SubmitRequest(BaseModel):
    recipe_id: str
    recipe_version: str
    template_id: str
    trust: str = "untrusted-third-party"     # own-code | untrusted-third-party
    claim: Optional[Claim] = None
    bundle: Bundle
    data_refs: List[DataRef] = Field(default_factory=list)
    limits: Optional[Limits] = None
    env_passthrough: List[str] = Field(default_factory=list)


# ---------- responses ----------
class Recompute(BaseModel):
    value: Optional[float] = None
    abs_diff: Optional[float] = None
    within_tolerance: Optional[bool] = None


class Execution(BaseModel):
    isolation_tier: Optional[str] = None
    tier_verified: Optional[bool] = None
    network_run: Optional[str] = None
    determinism_mode: Optional[str] = None


class VerificationResponse(BaseModel):
    verification_id: str
    status: str
    recipe: dict
    created_at: str
    verdict: Optional[str] = None
    repo_verdict: Optional[str] = None
    claim: Optional[Claim] = None
    recomputed: Optional[Recompute] = None
    validity: Optional[dict] = None
    execution: Optional[Execution] = None
    proof: Optional[dict] = None
    reason: Optional[str] = None
    links: dict = Field(default_factory=dict)


class VerificationList(BaseModel):
    data: List[VerificationResponse]
    next_cursor: Optional[str] = None


# ---------- uploads ----------
class UploadRequest(BaseModel):
    kind: str                      # "bundle" | "input"
    sha256: str
    content_type: str = "application/octet-stream"


class UploadResponse(BaseModel):
    url: str                       # presigned PUT
    uri: str                       # the object key to reference in a submit
    expires_in: int


# ---------- provisioning + keys (first-party / dashboard) ----------
class ProvisionRequest(BaseModel):
    workos_user_id: str
    email: str
    org_name: str
    workos_org_id: Optional[str] = None


class ProvisionResponse(BaseModel):
    org_id: str
    tenant_id: str


class KeyCreate(BaseModel):
    environment: str = "live"      # live | test


class KeyInfo(BaseModel):
    id: str
    prefix: str
    environment: str
    created_at: str
    last_used_at: Optional[str] = None
    revoked: bool = False


class KeyCreated(KeyInfo):
    token: str                     # the plaintext key — shown ONCE
