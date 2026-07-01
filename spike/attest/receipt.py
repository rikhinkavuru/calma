"""calma.spike.attest.receipt — reproducibility receipts (feature 18).

Assembles the ingredients Calma already computed — inputs (data digests, #16), env (determinism, python), code
(repo sha), outputs (the three-way diff + verdict) — into a canonical, content-addressed receipt. The CLAIM
block is timestamp-free and measurement-free, so re-verifying the same run yields the SAME `receipt_sha256`
(the attestation is idempotent, which is what makes transparency-log dedupe meaningful). The MEASUREMENT block
(sandbox seconds, k) is kept OUT of the hash. The receipt never feeds decide(); it is a serialization of its
output.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA = "https://schemas.trycalma.ai/receipt/v1"


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _det_summary(det) -> dict | None:
    """The deterministic-given-the-run subset of the determinism block (drops nothing that varies run-to-run
    for the same inputs)."""
    if not det:
        return None
    return {k: det.get(k) for k in ("tested", "stable", "proven", "k") if k in det}


def _claim_block(records, job_run, repo_meta) -> dict:
    repo_meta = repo_meta or {}
    job_run = job_run or {}
    outputs = []
    for r in sorted(records, key=lambda x: str(x.get("id"))):
        outputs.append({
            "id": r.get("id"), "metric": r.get("metric"), "claimed": r.get("claimed"),
            "verdict": r.get("verdict"), "diff": r.get("diff"),
            "data_digest": r.get("data_digest"), "provenance": r.get("provenance"),
            "determinism": _det_summary(r.get("determinism")),
            "convention": r.get("convention"),
        })
    env = {"python": job_run.get("python") or repo_meta.get("python"),
           "entry": job_run.get("entry"), "ran": job_run.get("ran")}
    return {"repo": repo_meta.get("repo"), "repo_sha": repo_meta.get("commit") or repo_meta.get("sha"),
            "outputs": outputs, "env": env}


def build_receipt(records, job_run=None, repo_meta=None) -> dict:
    """Return {schema, claim, measurement, receipt_sha256}. `receipt_sha256` hashes ONLY the claim block, so it
    is stable across re-verifications of the same run."""
    claim = _claim_block(records, job_run, repo_meta)
    receipt_sha256 = "sha256:" + hashlib.sha256(_canonical(claim)).hexdigest()
    cost = (job_run or {}).get("cost") or {}
    measurement = {"sandbox_seconds": cost.get("sandbox_seconds"), "k": cost.get("runs"),
                   "calls": (job_run or {}).get("calls")}
    return {"schema": SCHEMA, "claim": claim, "measurement": measurement, "receipt_sha256": receipt_sha256}


def receipt_digest(receipt: dict) -> str:
    return receipt.get("receipt_sha256") or ("sha256:" + hashlib.sha256(_canonical(receipt.get("claim"))).hexdigest())
