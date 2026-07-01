"""calma.spike.attest.signing — DSSE signing of a decided verdict (feature 3), lifted from the prior engine's
control-plane signer (legacy/control_plane/api/signing.py) and re-pointed at the in-toto verdict statement.

The verifier VOUCHES for a verification by signing the in-toto Statement (receipt digest as subject) with a
Calma-controlled key. The private key lives ONLY as an env secret — the ed25519 seed in CALMA_SIGNING_KEY, or
(preferred) a non-exportable AWS KMS ECDSA-P256 key whose private half never enters this process (only a digest
is sent to sign). The PUBLIC key is published (attest/signing_pubkey.json + GET /api/signing-key) so anyone can
verify OFFLINE without trusting the API at fetch time. A verifier MUST pin the published key; the keyid in the
envelope only selects which key, it is not itself a root of trust.

DSSE v1: {payloadType, payload: b64(json), signatures:[{keyid, sig: b64, algorithm}]}.
PAE(type, body) = b"DSSEv1 " + len(type) + b" " + type + b" " + len(body) + b" " + body (signed, not raw body).
With no key configured, sign_envelope still returns a well-formed envelope with signatures: [] — the artifact
shape is stable and a signing outage can NEVER block or change a verdict (fail-open on production; verification
stays fail-closed).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os

PAYLOAD_TYPE = "application/vnd.in-toto+json"     # the standard DSSE payloadType for an in-toto Statement
ALGORITHM = "ed25519"
ALGORITHM_KMS = "ecdsa-p256-sha256"
_KMS: dict = {}


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _ub64(s: str) -> bytes:
    return base64.b64decode(s)


def _pae(payload_type: bytes, payload: bytes) -> bytes:
    return b"DSSEv1 %d %s %d %s" % (len(payload_type), payload_type, len(payload), payload)


def _canonical(payload_obj) -> bytes:
    return json.dumps(payload_obj, separators=(",", ":"), sort_keys=True).encode("utf-8")


def key_id(pub_raw: bytes) -> str:
    return hashlib.sha256(pub_raw).hexdigest()[:16]


def _kms_arn():
    return os.environ.get("CALMA_KMS_KEY_ARN", "").strip() or None


def _kms():
    if "client" not in _KMS:
        import boto3
        _KMS["client"] = boto3.client("kms", region_name=os.environ.get("AWS_REGION") or "us-west-2")
    if "der" not in _KMS:
        _KMS["der"] = _KMS["client"].get_public_key(KeyId=_kms_arn())["PublicKey"]
    return _KMS["client"], _KMS["der"]


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
    """{algorithm, keyid, public_key_b64, key_format} for the CURRENT signing key — KMS ECDSA-P256 (DER SPKI)
    when CALMA_KMS_KEY_ARN is set, else the ed25519 env-seed key (raw), else None."""
    if _kms_arn():
        _c, der = _kms()
        return {"algorithm": ALGORITHM_KMS, "keyid": key_id(der), "public_key_b64": _b64(der),
                "key_format": "spki-der"}
    priv = _load_private()
    if priv is None:
        return None
    pub = _public_raw(priv)
    return {"algorithm": ALGORITHM, "keyid": key_id(pub), "public_key_b64": _b64(pub), "key_format": "raw"}


def sign_envelope(payload_obj) -> dict:
    """Wrap payload_obj in a DSSE envelope. KMS ECDSA-P256 when CALMA_KMS_KEY_ARN is set; else the ed25519 env
    seed; else signatures: [] (unsigned but well-formed). Any signer error is caught → unsigned, never raised,
    so a signing outage can't block a verdict."""
    payload = _canonical(payload_obj)
    env: dict = {"payloadType": PAYLOAD_TYPE, "payload": _b64(payload), "signatures": []}
    pae = _pae(PAYLOAD_TYPE.encode("ascii"), payload)
    try:
        if _kms_arn():
            client, der = _kms()
            sig = client.sign(KeyId=_kms_arn(), Message=pae, MessageType="RAW",
                              SigningAlgorithm="ECDSA_SHA_256")["Signature"]
            env["signatures"].append({"keyid": key_id(der), "sig": _b64(sig), "algorithm": ALGORITHM_KMS})
            return env
        priv = _load_private()
        if priv is None:
            return env
        sig = priv.sign(pae)
        env["signatures"].append({"keyid": key_id(_public_raw(priv)), "sig": _b64(sig), "algorithm": ALGORITHM})
    except Exception:  # noqa: BLE001 — HSM/KMS/crypto outage → unsigned-but-well-formed (fail-open)
        return {"payloadType": PAYLOAD_TYPE, "payload": _b64(payload), "signatures": []}
    return env


def verify_envelope(envelope: dict, pub_bytes: bytes) -> bool:
    """True iff ANY signature verifies against the PINNED public key (pub_bytes). Algorithm-aware: ed25519 (raw
    32-byte) + ecdsa-p256-sha256 (DER SPKI). The caller pins pub_bytes out-of-band — never trust a key inside
    the envelope."""
    from cryptography.exceptions import InvalidSignature
    try:
        pae = _pae(envelope["payloadType"].encode("ascii"), _ub64(envelope["payload"]))
    except (KeyError, ValueError):
        return False
    for s in envelope.get("signatures", []):
        try:
            sig, algo = _ub64(s["sig"]), s.get("algorithm")
            if algo == ALGORITHM:
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
                Ed25519PublicKey.from_public_bytes(pub_bytes).verify(sig, pae)
                return True
            if algo == ALGORITHM_KMS:
                from cryptography.hazmat.primitives.serialization import load_der_public_key
                from cryptography.hazmat.primitives.asymmetric import ec
                from cryptography.hazmat.primitives import hashes
                pub = load_der_public_key(pub_bytes)
                if isinstance(pub, ec.EllipticCurvePublicKey):     # KMS key is ECDSA-P256 (narrow the key union)
                    pub.verify(sig, pae, ec.ECDSA(hashes.SHA256()))
                    return True
        except (InvalidSignature, ValueError, KeyError):
            continue
    return False


def decode_payload(envelope: dict):
    """The payload object inside an envelope (does NOT verify; call verify_envelope first)."""
    return json.loads(_ub64(envelope["payload"]))
