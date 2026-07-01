"""calma.spike.attest.statement — the in-toto Statement + verdict/v1 predicate (feature 3).

Emits an in-toto Statement v1 whose SUBJECT is the reproducibility receipt digest (#18) — so the signature
commits to *what was verified*, not just the verdict string — and whose PREDICATE is a SLSA-VSA-compatible
record of the decision. `verificationResult` is PASSED iff the verdict is in verdict.POSITIVE (CONFIRMED); every
other verdict is FAILED, and the real 7-value verdict rides in `verifiedLevels` + `calmaVerdict`. This is pure
assembly of an already-decided record — it never calls decide().
"""
from __future__ import annotations

from core import verdict as VD

PREDICATE_TYPE = "https://schemas.trycalma.ai/verdict/v1"


def build_statement(record: dict, receipt_digest: str, repo_uri: str, *, engine_sha=None,
                    catalog_hash=None, time_verified=None, input_attestations=None) -> dict:
    """Build the in-toto Statement v1 for one decided claim record. `receipt_digest` is `sha256:<hex>` (#18);
    `repo_uri` like `git+https://github.com/<owner/repo>@<sha>`. `time_verified` is caller-supplied (kept out of
    the receipt hash so signing stays idempotent)."""
    verdict = record.get("verdict")
    passed = verdict in VD.POSITIVE
    sha = receipt_digest.split(":", 1)[-1] if receipt_digest else ""
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": "%s#%s" % (repo_uri, record.get("metric")), "digest": {"sha256": sha}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "verifier": {"id": "https://trycalma.ai",
                         "version": {"engine": engine_sha, "catalog": catalog_hash}},
            "timeVerified": time_verified,
            "resourceUri": repo_uri,
            "policy": {"uri": "https://trycalma.ai/policy/fcr0"},
            "verificationResult": "PASSED" if passed else "FAILED",
            "verifiedLevels": ["CALMA_" + str(verdict)],
            "inputAttestations": input_attestations or [{"digest": {"sha256": sha}}],
            "calmaVerdict": record,
        },
    }
