"""control_plane.api.errors — RFC-9457 problem+json. One exception type the routes raise, one handler
that renders application/problem+json with the canonical Calma error catalogue (spec-01 §8)."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import ERROR_BASE


class Problem(Exception):
    def __init__(self, status: int, type_: str, title: str, detail: str = "", **extra):
        self.status = status
        self.type = ERROR_BASE + type_
        self.title = title
        self.detail = detail
        self.extra = extra
        super().__init__(detail or title)

    def body(self) -> dict:
        d = {"type": self.type, "title": self.title, "status": self.status}
        if self.detail:
            d["detail"] = self.detail
        d.update(self.extra)
        return d


# the canonical catalogue (spec-01 §8) as constructors, so routes stay terse and consistent.
def unauthorized(detail="missing or invalid API key"):
    return Problem(401, "unauthorized", "Unauthorized", detail)

def forbidden(detail="scope or tenant mismatch"):
    return Problem(403, "forbidden", "Forbidden", detail)

def not_found(detail="resource not found"):
    return Problem(404, "not-found", "Not Found", detail)

def malformed(detail="malformed request"):
    return Problem(400, "malformed", "Bad Request", detail)

def idempotency_conflict(detail="same Idempotency-Key, different request body"):
    return Problem(409, "idempotency-conflict", "Idempotency Conflict", detail)

def artifact_over_cap(detail="artifact exceeds the 256MB cap"):
    return Problem(413, "artifact-over-cap", "Payload Too Large", detail)

def tier_unverified(detail, **extra):
    return Problem(422, "tier-unverified", "Isolation tier did not verify", detail, **extra)

def quota_exceeded(detail="quota exceeded", retry_after=None):
    extra = {"retry_after": retry_after} if retry_after else {}
    return Problem(429, "quota-exceeded", "Quota Exceeded", detail, **extra)

def capacity(detail="capacity exceeded; queued or spilled"):
    return Problem(503, "capacity", "Service Unavailable", detail)

def internal(detail="internal error"):
    return Problem(500, "internal", "Internal Server Error", detail)


async def problem_handler(request: Request, exc: Problem):
    return JSONResponse(status_code=exc.status, content=exc.body(),
                        media_type="application/problem+json")
