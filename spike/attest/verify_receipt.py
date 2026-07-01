"""calma.spike.attest.verify_receipt — re-check a reproducibility receipt's self-hash (feature 18).

Re-hashes the receipt's CLAIM block and compares to the recorded `receipt_sha256`. A changed input digest,
verdict, or diff → a different hash → the receipt fails. Measurement changes (seconds, k) do NOT change the
claim hash. Fail-closed: any structural problem returns (False, reason).
"""
from __future__ import annotations

import hashlib

from .receipt import _canonical


def verify_receipt(receipt: dict) -> tuple[bool, str]:
    if not isinstance(receipt, dict) or "claim" not in receipt:
        return False, "malformed receipt (no claim block)"
    expect = receipt.get("receipt_sha256")
    if not expect:
        return False, "receipt carries no receipt_sha256"
    got = "sha256:" + hashlib.sha256(_canonical(receipt["claim"])).hexdigest()
    if got != expect:
        return False, "receipt self-hash mismatch (claim block was altered)"
    return True, "receipt self-hash verifies"
