"""calma.spike.attest.attestation — the one-call glue (feature 3): sign an in-toto verdict Statement whose
subject is the reproducibility-receipt digest. Pure downstream of the verdict — it reads a decided record,
never writes back into decide(). Unsigned-but-well-formed when no key is configured (fail-open on production).
"""
from __future__ import annotations

from . import receipt as RC
from . import signing as SG
from . import statement as ST


def build_attestation(record: dict, receipt, repo_uri: str, **statement_kw) -> dict:
    """Return the DSSE envelope wrapping the signed verdict Statement for one claim `record`. `receipt` may be
    the full receipt dict (its digest is used) or a `sha256:<hex>` string."""
    digest = RC.receipt_digest(receipt) if isinstance(receipt, dict) else receipt
    stmt = ST.build_statement(record, digest, repo_uri, **statement_kw)
    return SG.sign_envelope(stmt)
