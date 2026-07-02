"""Cycle-2 binding fix, real end-to-end: a repo with a from-scratch hand-rolled accuracy function (no
sklearn import at all — nothing for the library capture hooks to see) still gets its reported number caught
via runner/target_discovery.py's static, NAME-matched fallback target, wired through the full
pipeline.verify_repo() orchestration with no explicit targets given (auto-discovery, not a test stub).

Before this fix this claim reached DISCOVERED/INCONCLUSIVE with zero information (nothing captured at all —
the digits-softmax corpus gap, spike/optimize/binding.py). After: a real misreport is caught (REFUTED) and a
genuine match is capped at REPRODUCED-ONLY/INCONCLUSIVE rather than a bare CONFIRMED (never on a guess alone
— see optimize/redteam.py's static_target_coincidence attack for the adversarial proof)."""
import pipeline


_HAND_ROLLED = (
    "def accuracy(y_true, y_pred):\n"
    "    correct = sum(1 for a, b in zip(y_true, y_pred) if a == b)\n"
    "    return correct / len(y_true)\n"
    "\n"
    "y_true = [0, 1, 1, 0, 1, 0, 1, 0, 1, 0]\n"
    "y_pred = [0, 1, 1, 0, 1, 0, 1, 0, 1, 1]\n"   # 9/10 correct = 0.90
    "acc = accuracy(y_true, y_pred)\n"
    "print('Accuracy: %.1f%%' % (acc * 100))\n"    # honestly prints the REAL computed value
)

# claims 99% in the printed line, but the function it actually ran and returned 0.90 — a genuine misreport.
_MISREPORT = (
    "def accuracy(y_true, y_pred):\n"
    "    correct = sum(1 for a, b in zip(y_true, y_pred) if a == b)\n"
    "    return correct / len(y_true)\n"
    "\n"
    "y_true = [0, 1, 1, 0, 1, 0, 1, 0, 1, 0]\n"
    "y_pred = [0, 1, 1, 0, 1, 0, 1, 0, 1, 1]\n"   # 9/10 correct = 0.90
    "acc = accuracy(y_true, y_pred)\n"
    "print('Accuracy: 99.0%%')\n"                  # hardcoded, ignores the real `acc` — the misreport
)


def _repo(tmp_path, src):
    (tmp_path / "eval.py").write_text(src)
    return str(tmp_path)


def _opts(**kw):
    return pipeline.VerifyOptions(runner="local", deep=True, entry="eval.py", discover=True, k=2,
                                  timeout=60, plan=False, hooks="sklearn", **kw)


def test_hand_rolled_metric_is_captured_via_static_fallback_and_capped(tmp_path):
    out = pipeline.verify_repo(_repo(tmp_path, _HAND_ROLLED), _opts())
    assert out["run"]["ran"], out["run"]
    claims = out["claims"]
    accuracy_claims = [c for c in claims if c["metric"] == "accuracy"]
    assert accuracy_claims, "the static fallback target should have captured the hand-rolled accuracy call"
    for c in accuracy_claims:
        # exactly matches: never a bare CONFIRMED on a name-matched guess alone (the franchise).
        assert c["verdict"] not in ("CONFIRMED", "CONFIRMED-STOCHASTIC"), c
        assert c["diff"]["produced"] == 0.9


def test_hand_rolled_misreport_is_still_caught(tmp_path):
    """The real value (SOTA fix): a genuine misreport through a hand-rolled function — previously invisible
    (nothing captured → INCONCLUSIVE) — is now a real REFUTED catch."""
    out = pipeline.verify_repo(_repo(tmp_path, _MISREPORT), _opts())
    assert out["run"]["ran"], out["run"]
    accuracy_claims = [c for c in out["claims"] if c["metric"] == "accuracy"]
    assert accuracy_claims
    assert any(c["verdict"] == "REFUTED" for c in accuracy_claims), accuracy_claims
