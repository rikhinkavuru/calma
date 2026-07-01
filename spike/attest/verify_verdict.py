#!/usr/bin/env python3
"""calma.spike.attest.verify_verdict — verify a Calma verdict attestation OFFLINE (feature 3).

A verdict attestation is a DSSE envelope (attest.signing) wrapping an in-toto Statement (attest.statement).
This checks the signature against the PINNED public key(s) — attest/signing_pubkey.json (committed), NOT any key
inside the envelope — and returns the verified verdict. Fail-closed: an unsigned or invalid envelope is NEVER
reported as verified (exit 2), mirroring the prior engine's verify_proof posture.

Usage:
    python -m attest.verify_verdict envelope.json
    python -m attest.verify_verdict - < envelope.json
    python -m attest.verify_verdict env.json --pubkey-b64 <base64>
Exit: 0 = VALID, 2 = INVALID/unsigned, 1 = usage/parse error.
"""
from __future__ import annotations

import base64
import json
import os
import sys

from . import signing

HERE = os.path.dirname(os.path.abspath(__file__))
PINNED = os.path.join(HERE, "signing_pubkey.json")


def load_trusted(pin_path: str | None = None) -> list[dict]:
    p = pin_path or PINNED
    try:
        pin = json.load(open(p))
    except (OSError, ValueError):
        return []
    return pin.get("trusted") or ([pin["current"]] if pin.get("current") else [])


def verify_verdict(envelope: dict, trusted: list[dict] | None = None) -> tuple[bool, dict | None, str]:
    """(ok, statement, message). ok is True only if a signature verifies against a pinned trusted key whose
    keyid matches (or an untyped key). Fail-closed on unsigned/invalid."""
    if not isinstance(envelope, dict) or not envelope.get("signatures"):
        return False, None, "UNSIGNED — envelope carries no signatures"
    trusted = trusted if trusted is not None else load_trusted()
    if not trusted:
        return False, None, "no pinned trusted keys to verify against"
    for key in trusted:
        if not key or not key.get("public_key_b64"):
            continue
        # only try a key whose keyid matches a signature's keyid (or keys with no keyid pin)
        kid = key.get("keyid")
        if kid and not any(s.get("keyid") == kid for s in envelope["signatures"]):
            continue
        try:
            pub = base64.b64decode(key["public_key_b64"])
        except (ValueError, TypeError):
            continue
        if signing.verify_envelope(envelope, pub):
            return True, signing.decode_payload(envelope), "VALID — signature verifies against a pinned key"
    return False, None, "INVALID — no signature verifies against the pinned trusted key(s)"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("envelope", help="path to the attestation JSON, or '-' for stdin")
    ap.add_argument("--pubkey-b64", help="base64 public key to pin (default: signing_pubkey.json)")
    a = ap.parse_args()
    raw = sys.stdin.read() if a.envelope == "-" else open(a.envelope).read()
    try:
        env = json.loads(raw)
    except ValueError as e:
        print("not valid JSON: %s" % e, file=sys.stderr)
        return 1
    trusted = [{"keyid": None, "algorithm": None, "public_key_b64": a.pubkey_b64}] if a.pubkey_b64 else None
    ok, stmt, msg = verify_verdict(env, trusted)
    print(msg)
    if ok and stmt:
        pred = (stmt.get("predicate") or {})
        rec = pred.get("calmaVerdict") or {}
        print("  result : %s" % pred.get("verificationResult"))
        print("  verdict: %s  metric=%s claimed=%s" % (rec.get("verdict"), rec.get("metric"), rec.get("claimed")))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
