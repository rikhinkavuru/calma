#!/usr/bin/env python3
"""verify_proof.py — verify a Calma proof DSSE envelope OFFLINE against the pinned public key.

A proof from GET /v1/verifications/{id}/proof is a DSSE envelope signed by the control-plane's ed25519 key.
This checks the signature against the PINNED public key (control_plane/signing_pubkey.json — committed, NOT the
key embedded in any envelope) and prints the verified verdict. Anyone can run this without trusting the API at
fetch time; the only root of trust is the committed/published public key.

Usage:
    python control_plane/verify_proof.py proof.json
    curl -s -H "..." .../v1/verifications/<id>/proof | python control_plane/verify_proof.py -
    python control_plane/verify_proof.py proof.json --pubkey-b64 <base64>     # pin an explicit key

Needs: pip install cryptography
Exit: 0 = signature VALID, 2 = INVALID/unsigned, 1 = usage/parse error.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PINNED = os.path.join(HERE, "signing_pubkey.json")


def _pae(payload_type: bytes, payload: bytes) -> bytes:
    return b"DSSEv1 %d %s %d %s" % (len(payload_type), payload_type, len(payload), payload)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("envelope", help="path to the proof JSON, or '-' for stdin")
    ap.add_argument("--pubkey-b64", help="base64 ed25519 public key to pin (default: signing_pubkey.json)")
    a = ap.parse_args()

    raw = sys.stdin.read() if a.envelope == "-" else open(a.envelope).read()
    try:
        env = json.loads(raw)
    except ValueError as e:
        print("not valid JSON: %s" % e, file=sys.stderr)
        return 1

    # Pinned trusted keys: signing_pubkey.json `trusted` (current KMS ECDSA-P256 + retired ed25519), or an
    # explicit --pubkey-b64. A signature verifies only against the key matching its keyid (never a key in
    # the envelope). Algorithm-aware: ed25519 (raw 32-byte) + ecdsa-p256-sha256 (DER SPKI).
    if a.pubkey_b64:
        trusted = [{"keyid": None, "algorithm": None, "public_key_b64": a.pubkey_b64}]
    else:
        pin = json.load(open(PINNED))
        trusted = pin.get("trusted") or [pin.get("current")] or []

    sigs = env.get("signatures") or []
    if not sigs:
        print("UNSIGNED — envelope carries no signatures (proof signing was not configured)")
        return 2

    pae = _pae(env["payloadType"].encode("ascii"), base64.b64decode(env["payload"]))

    def _verify(algo, pub_b64, sig):
        from cryptography.exceptions import InvalidSignature
        pub_bytes = base64.b64decode(pub_b64)
        try:
            if algo == "ed25519" or (algo is None and len(pub_bytes) == 32):
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
                Ed25519PublicKey.from_public_bytes(pub_bytes).verify(sig, pae)
                return True
            from cryptography.hazmat.primitives.serialization import load_der_public_key
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import hashes
            load_der_public_key(pub_bytes).verify(sig, pae, ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, ValueError, KeyError):
            return False

    ok, used = False, None
    for s in sigs:
        sig = base64.b64decode(s["sig"])
        for k in trusted:
            if k.get("keyid") and s.get("keyid") and k["keyid"] != s["keyid"]:
                continue
            if _verify(k.get("algorithm") or s.get("algorithm"), k["public_key_b64"], sig):
                ok, used = True, s
                break
        if ok:
            break

    if not ok:
        print("INVALID — no signature verifies against the pinned trusted key(s)")
        return 2

    payload = json.loads(base64.b64decode(env["payload"]))
    res = payload.get("result") or {}
    print("VALID ✓  signed by keyid %s (%s)" % (used.get("keyid"), used.get("algorithm")))
    print("  verification_id: %s" % payload.get("verification_id"))
    print("  verdict        : %s" % res.get("verdict"))
    print("  metric         : %s  claimed=%s recomputed=%s"
          % (res.get("metric"), res.get("claimed"), res.get("recomputed")))
    print("  isolation_tier : %s" % res.get("isolation_tier"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
