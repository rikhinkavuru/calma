"""Features 13 / 12 / 9 / 3-glue — badges, transparency log, bug-bounty triage. All strictly downstream of the
verdict. The load-bearing guards: a badge is green ONLY for CONFIRMED (and never for a stale/moved repo); the
ledger is tamper-evident and its submit path is fail-open; and bounty triage flags a false-CONFIRM as the only
Critical while the standing corpus yields zero valid bounties."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)
sys.path.insert(0, os.path.join(_SPIKE, "optimize"))

from attest import attestation as ATT  # noqa: E402
from attest import badge as BADGE  # noqa: E402
from attest import receipt as RCPT  # noqa: E402
from attest import tlog as TLOG  # noqa: E402
from core import verdict as VD  # noqa: E402
import bounty as BOUNTY  # noqa: E402


# ---- feature 13: badges (CONFIRMED-only-green) ---------------------------------------------------
def test_only_confirmed_is_green():
    assert BADGE.is_green(BADGE.badge(VD.CONFIRMED))
    for v in (VD.REFUTED, VD.INVALIDATED, VD.REPRODUCED_ONLY, VD.NON_DETERMINISTIC, VD.INCONCLUSIVE, "DISCOVERED"):
        assert not BADGE.is_green(BADGE.badge(v)), v


def test_stale_badge_is_never_green():
    e = BADGE.registry_entry("o/r", "abc123", "c0", VD.CONFIRMED)
    assert BADGE.is_stale(e, "def456")                       # repo moved past the pinned SHA
    b = BADGE.badge_for_entry(e, current_sha="def456")
    assert not BADGE.is_green(b) and "stale" in b["message"]
    assert BADGE.is_green(BADGE.badge_for_entry(e, current_sha="abc123"))   # same SHA → green


# ---- feature 12: transparency ledger -------------------------------------------------------------
def _env(payload="x"):
    return {"payloadType": "application/vnd.in-toto+json", "payload": payload, "signatures": []}


def test_ledger_chain_intact_and_tamper_evident(tmp_path):
    led = TLOG.LocalLedger(str(tmp_path / "ledger.json"))
    led.append("v0", _env("a"))
    led.append("v1", _env("b"))
    ok, _m = led.verify_chain()
    assert ok
    led.entries[0]["leaf"] = "sha256:TAMPERED"               # retro-edit a past entry
    bad, msg = led.verify_chain()
    assert not bad and "tampered" in msg


def test_submit_is_fail_open_on_rekor_outage(tmp_path):
    led = TLOG.LocalLedger(str(tmp_path / "l.json"))

    def _boom(_leaf):
        raise RuntimeError("rekor down")
    out = TLOG.submit(_env("z"), "v0", ledger=led, rekor_submit=_boom)
    assert out["local"] is not None and out["rekor"] is None    # local logged, rekor failed silently
    assert led.verify_chain()[0]


# ---- feature 9: bounty triage --------------------------------------------------------------------
def test_triage_flags_a_false_confirm_only():
    # a mock verifier that (wrongly) CONFIRMS a known-bad submission → a valid Critical bounty
    hit = BOUNTY.triage({"metric": "accuracy", "capability": "cheating-formula"},
                        verify_fn=lambda s: {"verdict": VD.CONFIRMED})
    assert hit["is_false_confirm"] and hit["valid"]
    # a correct INVALIDATED → not a bounty
    miss = BOUNTY.triage({"metric": "accuracy", "capability": "cheating-formula"},
                         verify_fn=lambda s: {"verdict": VD.INVALIDATED})
    assert not miss["is_false_confirm"]


def test_standing_attack_corpus_has_zero_valid_bounties():
    import redteam
    valid = [n for n, claim, runs in redteam.attacks()
             if BOUNTY.triage({"claim": claim, "runs": runs, "metric": claim.get("metric"), "capability": n})["is_false_confirm"]]
    assert valid == []                                       # the engine holds FCR=0 → no wild breaches


def test_promote_emits_a_regression_fixture():
    stub = BOUNTY.promote_to_fixture({"metric": "accuracy", "capability": "fabricated",
                                      "claim": {"metric": "accuracy", "value": "0.99"}, "runs": [[]]})
    assert stub["kind"] == "redteam_attack" and stub["stub"]["must_not_confirm"]
    repo_stub = BOUNTY.promote_to_fixture({"repo": "o/r", "metric": "accuracy", "capability": "leaked"})
    assert repo_stub["kind"] == "repos_yaml_t4" and repo_stub["stub"]["tier"] == "T4"


# ---- feature 3 glue: attestation over a receipt --------------------------------------------------
def test_build_attestation_wraps_the_statement(monkeypatch):
    monkeypatch.delenv("CALMA_SIGNING_KEY", raising=False)
    monkeypatch.delenv("CALMA_KMS_KEY_ARN", raising=False)
    rec = {"id": "c0", "metric": "accuracy", "claimed": "0.9", "verdict": VD.CONFIRMED,
           "diff": {}, "data_digest": "sha256:aa"}
    receipt = RCPT.build_receipt([rec], {})
    env = ATT.build_attestation(rec, receipt, "git+https://github.com/o/r@abc")
    assert env["payloadType"] == "application/vnd.in-toto+json"
    assert env["signatures"] == []                           # no key → unsigned but well-formed
    from attest import signing
    payload = signing.decode_payload(env)
    assert payload["predicate"]["verificationResult"] == "PASSED"
    assert payload["subject"][0]["digest"]["sha256"] == receipt["receipt_sha256"].split(":")[1]
