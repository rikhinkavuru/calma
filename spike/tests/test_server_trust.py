"""The trust-layer API surface (features 3 / 12 / 13 / 18): receipt, signed attestation, transparency
inclusion proof, and the shields badge. All strictly downstream of a decided job — these check the wiring and
the CONFIRMED-only-green + fail-open properties end to end."""
import importlib
import sys
import time

import pytest

from core import verdict as VD


@pytest.fixture
def _srv(monkeypatch):
    monkeypatch.delenv("CALMA_VERIFY_TOKEN", raising=False)   # open local-operator flow
    monkeypatch.delenv("CALMA_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("CALMA_SIGNING_KEY", raising=False)
    monkeypatch.delenv("CALMA_KMS_KEY_ARN", raising=False)
    sys.modules.pop("server", None)
    srv = importlib.import_module("server")
    yield srv
    sys.modules.pop("server", None)


def _seed_job(srv, verdict=VD.CONFIRMED):
    from attest import receipt as RCPT
    rec = {"id": "c0", "metric": "accuracy", "claimed": "0.9", "verdict": verdict,
           "diff": {"claimed": "0.9", "produced": 0.9, "recomputed": 0.9}, "data_digest": "sha256:aa"}
    receipt = RCPT.build_receipt([rec], {"entry": "eval.py", "ran": True})
    job = {"id": "job1", "repo": "o/r", "status": "done", "stage": "done", "created": time.time(),
           "claims": [rec], "counts": {verdict: 1}, "receipt": receipt, "run": {}}
    srv.JOBS["job1"] = job
    return job


def test_badge_is_green_only_for_confirmed(_srv):
    from fastapi.testclient import TestClient
    c = TestClient(_srv.app)
    _seed_job(_srv, VD.CONFIRMED)
    b = c.get("/api/badge/job1").json()
    assert b["color"] == "brightgreen" and b["message"] == "CONFIRMED"
    _srv.JOBS["job1"]["claims"][0]["verdict"] = VD.INVALIDATED
    b2 = c.get("/api/badge/job1").json()
    assert b2["color"] != "brightgreen"


def test_signing_key_public_and_unconfigured(_srv):
    from fastapi.testclient import TestClient
    c = TestClient(_srv.app)
    r = c.get("/api/signing-key")
    assert r.status_code == 200 and r.json().get("configured") is False   # no key → honest, still 200


def test_receipt_and_attestation_and_inclusion_proof(_srv):
    from fastapi.testclient import TestClient
    c = TestClient(_srv.app)
    _seed_job(_srv, VD.CONFIRMED)
    rc = c.get("/api/jobs/job1/receipt").json()
    assert rc["receipt_sha256"].startswith("sha256:")
    att = c.get("/api/jobs/job1/attestation").json()
    assert att["attestations"][0]["verdict"] == VD.CONFIRMED
    env = att["attestations"][0]["envelope"]
    assert env["payloadType"] == "application/vnd.in-toto+json" and env["signatures"] == []
    proof = c.get("/api/jobs/job1/inclusion-proof").json()
    assert proof["chain_ok"] and proof["entries"]           # the attestation call logged a ledger entry


def test_receipt_409_when_absent(_srv):
    from fastapi.testclient import TestClient
    c = TestClient(_srv.app)
    srv = _srv
    srv.JOBS["job2"] = {"id": "job2", "repo": "o/r", "status": "done", "created": time.time(),
                        "claims": [], "receipt": None}
    assert c.get("/api/jobs/job2/receipt").status_code == 409
