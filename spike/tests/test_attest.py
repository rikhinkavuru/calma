"""Features 16 / 18 / 3 — the trust stack. Content-addressed data digests, a self-hashing reproducibility
receipt, and DSSE-signed in-toto verdict attestations. Everything here is strictly downstream of the verdict:
these pin determinism (same run → same digest/receipt), tamper-evidence, PASSED-iff-CONFIRMED, and the
FCR firewall (building/signing a record never changes it)."""
import base64
import os
import sys

import pytest

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from attest import receipt as RCPT  # noqa: E402
from attest import statement as STMT  # noqa: E402
from attest import verify_receipt as VR  # noqa: E402
from attest import verify_verdict as VV  # noqa: E402
from core import datahash as DH  # noqa: E402
from core import verdict as VD  # noqa: E402

_HAS_CRYPTO = True
try:
    import cryptography  # noqa: F401
except Exception:  # noqa: BLE001
    _HAS_CRYPTO = False


# ---- feature 16: content-addressed data digests --------------------------------------------------
def test_same_inputs_same_digest():
    a = {"y_true": [0, 1, 1, 0], "y_pred": [0, 1, 0, 0]}
    assert DH.canonical_sha256(a) == DH.canonical_sha256(dict(a))
    assert DH.canonical_sha256(a).startswith("sha256:")


def test_one_element_change_changes_digest():
    a = {"y_true": [0, 1, 1, 0], "y_pred": [0, 1, 0, 0]}
    b = {"y_true": [0, 1, 1, 0], "y_pred": [0, 1, 0, 1]}
    assert DH.canonical_sha256(a) != DH.canonical_sha256(b)


def test_empty_inputs_digest_is_none():
    assert DH.canonical_sha256(None) is None and DH.canonical_sha256({}) is None


# ---- feature 18: reproducibility receipts --------------------------------------------------------
def _records():
    return [
        {"id": "c0", "metric": "accuracy", "claimed": "0.9", "verdict": VD.CONFIRMED,
         "diff": {"claimed": "0.9", "produced": 0.9, "recomputed": 0.9}, "data_digest": "sha256:aa",
         "provenance": "catalog", "determinism": {"tested": True, "stable": True, "proven": False, "k": 2}},
        {"id": "c1", "metric": "roc_auc", "claimed": "0.8", "verdict": VD.REFUTED,
         "diff": {"claimed": "0.8", "produced": 0.7, "recomputed": 0.7}, "data_digest": "sha256:bb"},
    ]


def test_receipt_is_deterministic_across_runs():
    r1 = RCPT.build_receipt(_records(), {"cost": {"sandbox_seconds": 1.2, "runs": 2}, "calls": 5})
    r2 = RCPT.build_receipt(_records(), {"cost": {"sandbox_seconds": 9.9, "runs": 2}, "calls": 5})
    assert r1["receipt_sha256"] == r2["receipt_sha256"]        # measurement differs, claim-hash identical


def test_receipt_changes_when_a_digest_changes():
    recs = _records()
    r1 = RCPT.build_receipt(recs, {})
    recs[0]["data_digest"] = "sha256:CHANGED"
    r2 = RCPT.build_receipt(recs, {})
    assert r1["receipt_sha256"] != r2["receipt_sha256"]


def test_verify_receipt_roundtrip_and_tamper():
    r = RCPT.build_receipt(_records(), {})
    ok, _msg = VR.verify_receipt(r)
    assert ok
    r["claim"]["outputs"][0]["verdict"] = VD.CONFIRMED if r["claim"]["outputs"][0]["verdict"] != VD.CONFIRMED else VD.REFUTED
    ok2, _m2 = VR.verify_receipt(r)
    assert not ok2                                            # claim block altered → self-hash fails


def test_building_a_receipt_does_not_mutate_records():
    recs = _records()
    verdicts_before = [r["verdict"] for r in recs]
    RCPT.build_receipt(recs, {})
    assert [r["verdict"] for r in recs] == verdicts_before    # FCR firewall: inert w.r.t. the decision


# ---- feature 3: in-toto statement + DSSE signing -------------------------------------------------
def test_statement_passed_iff_confirmed():
    rec_c = _records()[0]
    st = STMT.build_statement(rec_c, "sha256:deadbeef", "git+https://github.com/o/r@abc")
    assert st["predicate"]["verificationResult"] == "PASSED"
    assert st["predicate"]["verifiedLevels"] == ["CALMA_CONFIRMED"]
    assert st["subject"][0]["digest"]["sha256"] == "deadbeef"
    rec_r = _records()[1]
    st2 = STMT.build_statement(rec_r, "sha256:deadbeef", "git+https://github.com/o/r@abc")
    assert st2["predicate"]["verificationResult"] == "FAILED"


@pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography not installed")
def test_sign_verify_roundtrip_and_tamper(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    from attest import signing

    seed = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    monkeypatch.setenv("CALMA_SIGNING_KEY", base64.b64encode(seed).decode())
    monkeypatch.delenv("CALMA_KMS_KEY_ARN", raising=False)

    st = STMT.build_statement(_records()[0], "sha256:deadbeef", "git+https://github.com/o/r@abc")
    env = signing.sign_envelope(st)
    assert env["signatures"], "env-seed key should have signed"
    info = signing.public_key_info()
    trusted = [{"keyid": info["keyid"], "algorithm": info["algorithm"], "public_key_b64": info["public_key_b64"]}]
    ok, stmt, _msg = VV.verify_verdict(env, trusted)
    assert ok and stmt["predicate"]["verificationResult"] == "PASSED"

    tampered = dict(env)
    raw = base64.b64decode(env["payload"])
    tampered["payload"] = base64.b64encode(raw[:-1] + bytes([raw[-1] ^ 1])).decode()
    ok2, _s2, _m2 = VV.verify_verdict(tampered, trusted)
    assert not ok2                                            # a flipped payload byte → signature fails


def test_unsigned_envelope_is_fail_closed():
    env = {"payloadType": "application/vnd.in-toto+json", "payload": base64.b64encode(b"{}").decode(),
           "signatures": []}
    ok, _stmt, msg = VV.verify_verdict(env, trusted=[{"public_key_b64": "AA=="}])
    assert not ok and "UNSIGNED" in msg
