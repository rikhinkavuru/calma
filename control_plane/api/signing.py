"""control_plane.api.signing — DSSE (Dead Simple Signing Envelope) over the proof bundle.

The control-plane VOUCHES for a verification by signing the evidence with a Calma-controlled ed25519 key.
The private key lives ONLY as the CALMA_SIGNING_KEY env secret (base64 of the 32-byte ed25519 seed) — never
in the repo, never returned by the API. The PUBLIC key is published (committed at
control_plane/signing_pubkey.json + served at /v1/signing-key) so anyone can verify a proof OFFLINE without
trusting the API at fetch time. A verifier MUST pin the published public key; the keyid in the envelope only
identifies which key to use, it is not itself a root of trust.

Envelope shape (DSSE v1, https://github.com/secure-systems-lab/dsse):
    {"payloadType": "...", "payload": b64(json), "signatures": [{"keyid": "...", "sig": b64, "algorithm": "ed25519"}]}
PAE(type, body) = b"DSSEv1 " + len(type) + b" " + type + b" " + len(body) + b" " + body  (signed, not the raw body).
When no key is configured, sign_envelope still returns a well-formed envelope with signatures: [] so the proof
shape is stable (consumers always decode `payload`); it is simply unsigned.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os

PAYLOAD_TYPE = "application/vnd.calma.proof+json"
ALGORITHM = "ed25519"


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _ub64(s: str) -> bytes:
    return base64.b64decode(s)


def _pae(payload_type: bytes, payload: bytes) -> bytes:
    return b"DSSEv1 %d %s %d %s" % (len(payload_type), payload_type, len(payload), payload)


def _canonical(payload_obj) -> bytes:
    # deterministic bytes so the signature is reproducible and re-verifiable from the stored payload.
    return json.dumps(payload_obj, separators=(",", ":"), sort_keys=True).encode("utf-8")


def key_id(pub_raw: bytes) -> str:
    return hashlib.sha256(pub_raw).hexdigest()[:16]


def _load_private():
    raw = os.environ.get("CALMA_SIGNING_KEY", "").strip()
    if not raw:
        return None
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.from_private_bytes(_ub64(raw))


def _public_raw(priv) -> bytes:
    from cryptography.hazmat.primitives import serialization
    return priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def public_key_info():
    """{algorithm, keyid, public_key_b64} for the configured key, or None if signing is not configured."""
    priv = _load_private()
    if priv is None:
        return None
    pub = _public_raw(priv)
    return {"algorithm": ALGORITHM, "keyid": key_id(pub), "public_key_b64": _b64(pub)}


def sign_envelope(payload_obj) -> dict:
    """Wrap payload_obj in a DSSE envelope. Signed when CALMA_SIGNING_KEY is set; otherwise signatures: []."""
    payload = _canonical(payload_obj)
    env = {"payloadType": PAYLOAD_TYPE, "payload": _b64(payload), "signatures": []}
    priv = _load_private()
    if priv is None:
        return env
    pt = PAYLOAD_TYPE.encode("ascii")
    sig = priv.sign(_pae(pt, payload))
    env["signatures"].append({"keyid": key_id(_public_raw(priv)), "sig": _b64(sig), "algorithm": ALGORITHM})
    return env


def verify_envelope(envelope: dict, pub_raw: bytes) -> bool:
    """True iff ANY signature on the envelope verifies against the PINNED public key (pub_raw). The caller is
    responsible for pinning pub_raw out-of-band (the committed/published key) — never trust a key inside the
    envelope."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    pub = Ed25519PublicKey.from_public_bytes(pub_raw)
    pt = envelope["payloadType"].encode("ascii")
    pae = _pae(pt, _ub64(envelope["payload"]))
    for s in envelope.get("signatures", []):
        try:
            pub.verify(_ub64(s["sig"]), pae)
            return True
        except (InvalidSignature, ValueError, KeyError):
            continue
    return False


def decode_payload(envelope: dict):
    """The verified-intent payload object inside an envelope (does NOT verify; call verify_envelope first)."""
    return json.loads(_ub64(envelope["payload"]))
