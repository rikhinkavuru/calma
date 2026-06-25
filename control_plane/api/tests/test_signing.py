"""Unit tests for DSSE proof signing (no network, no DB). Roundtrip, tamper-detection, wrong-key, no-key.

Run:  ~/.calma/cp-venv/bin/python -m control_plane.api.tests.test_signing
"""
from __future__ import annotations

import base64
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from control_plane.api import signing

_n = _fail = 0


def ok(cond, label):
    global _n, _fail
    _n += 1
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        _fail += 1


def _fresh_key_env():
    priv = Ed25519PrivateKey.generate()
    seed = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())
    os.environ["CALMA_SIGNING_KEY"] = base64.b64encode(seed).decode()
    return signing._public_raw(priv)


def main():
    evidence = {"verification_id": "v1", "result": {"verdict": "CONFIRMED", "recomputed": 0.0077}}

    # signed roundtrip
    pub = _fresh_key_env()
    env = signing.sign_envelope(evidence)
    ok(env["payloadType"] == signing.PAYLOAD_TYPE and env["payload"], "envelope has payloadType + payload")
    ok(len(env["signatures"]) == 1 and env["signatures"][0]["algorithm"] == "ed25519", "one ed25519 signature")
    ok(signing.verify_envelope(env, pub) is True, "verifies against the correct pinned key")
    ok(signing.decode_payload(env) == evidence, "decoded payload == original evidence")
    ok(env["signatures"][0]["keyid"] == signing.key_id(pub), "keyid matches the public key")

    # tamper the payload -> signature must NOT verify
    tampered = dict(env)
    bad = {"verification_id": "v1", "result": {"verdict": "CONFIRMED", "recomputed": 9.9999}}
    tampered["payload"] = base64.b64encode(signing._canonical(bad)).decode()
    ok(signing.verify_envelope(tampered, pub) is False, "tampered payload FAILS verification")

    # a different key must NOT verify a genuine envelope
    other = _fresh_key_env()  # rotates env to a new key
    ok(signing.verify_envelope(env, other) is False, "wrong pinned key FAILS verification")

    # public_key_info reflects the configured key
    info = signing.public_key_info()
    ok(info and info["algorithm"] == "ed25519" and info["keyid"] == signing.key_id(other),
       "public_key_info returns the configured key")

    # no key configured -> well-formed but UNSIGNED envelope (stable shape), verify is False
    os.environ.pop("CALMA_SIGNING_KEY", None)
    unsigned = signing.sign_envelope(evidence)
    ok(unsigned["signatures"] == [] and signing.decode_payload(unsigned) == evidence,
       "no key -> unsigned envelope, payload still decodable")
    ok(signing.verify_envelope(unsigned, pub) is False, "unsigned envelope does not verify")
    ok(signing.public_key_info() is None, "public_key_info is None when no key configured")

    print("\n%d checks, %d failed" % (_n, _fail))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
