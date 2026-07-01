"""calma.spike.core.datahash — content-addressed dataset digests (feature 16).

Calma already holds the evaluation inputs (the captured `y_true`/`y_pred`/`y_score` arrays) and, deep-verified,
any committed prediction/split files. Hashing them gives a stable content address for *the data the number was
actually computed on* — a field on every claim record, a subject of the reproducibility receipt (#18), and a
BINDING key (two claims for the same metric on different `data_digest`s are distinct computations).

FCR posture: adding a hash can only ever ADD information or an advisory note. It is never a verdict gate — a
digest can't flip an INCONCLUSIVE/REFUTED to CONFIRMED, and a declared-dataset mismatch surfaces as an advisory,
never an upgrade. Pure stdlib (`hashlib`/`json`).
"""
from __future__ import annotations

import hashlib
import json


def _canonical(obj) -> bytes:
    """Deterministic bytes for a captured-inputs dict: sorted keys, compact separators, stable float repr.
    The same arrays → the same bytes → the same digest, on any run/host."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def canonical_sha256(inputs) -> str | None:
    """`sha256:<hex>` over the canonical serialization of the captured evaluation inputs, or None if there is
    nothing to hash. This is the evaluation-input digest — the data the metric consumed."""
    if not inputs:
        return None
    try:
        return "sha256:" + hashlib.sha256(_canonical(inputs)).hexdigest()
    except (TypeError, ValueError):
        return None


def file_sha256(path: str, _chunk: int = 1 << 20) -> str | None:
    """`sha256:<hex>` of a file's bytes (streamed), or None if unreadable. For committed prediction/split files."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(_chunk), b""):
                h.update(block)
    except OSError:
        return None
    return "sha256:" + h.hexdigest()


def digest_field(inputs, n=None, source="captured", declared=None, matches_declared=None) -> dict:
    """The `data` block folded into the receipt (#18) and thus the attestation (#3)."""
    return {"digest": canonical_sha256(inputs), "n": n, "source": source,
            "declared": declared, "matches_declared": matches_declared}
