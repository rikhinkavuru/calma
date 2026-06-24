"""control_plane.api.keys — API-key generation + verification.

Format (CANONICAL §1):  calma_sk_<env>_<keyid8>_<secret48>   env ∈ {live,test}
Hashing = SHA-256 of the full token (CANONICAL §1: 256-bit random keys don't need a slow KDF), with a
CONSTANT-TIME compare. The secret is never stored — only key_id (public, indexed) + key_hash.
The secret uses hex (no '_' / '-') so the token parses unambiguously on '_'.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets


def _sha256(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def generate(environment: str = "live") -> dict:
    """Mint a new key. Returns the one-time plaintext `token` (shown once, never stored) plus the row
    fields to persist (key_id / prefix / key_hash / environment)."""
    if environment not in ("live", "test"):
        raise ValueError("environment must be live|test")
    key_id = secrets.token_hex(4)        # 8 hex chars — public, indexed
    secret = secrets.token_hex(24)       # 48 hex chars — ~192 bits
    token = "calma_sk_%s_%s_%s" % (environment, key_id, secret)
    return {"token": token, "key_id": key_id, "environment": environment,
            "prefix": "calma_sk_%s_%s" % (environment, key_id), "key_hash": _sha256(token)}


def parse(token: str):
    """Extract (environment, key_id) from a presented token, or None if it isn't well-formed."""
    if not token or not token.startswith("calma_sk_"):
        return None
    bits = token[len("calma_sk_"):].split("_")
    if len(bits) < 3:
        return None
    env, key_id = bits[0], bits[1]
    if env not in ("live", "test") or len(key_id) != 8:
        return None
    return {"environment": env, "key_id": key_id}


def verify(token: str, key_hash) -> bool:
    """Constant-time check of a presented token against the stored SHA-256 hash."""
    return hmac.compare_digest(_sha256(token), bytes(key_hash))
