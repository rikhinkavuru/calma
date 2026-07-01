"""Adaptive-k gate: verify a statically-proven-deterministic repo with ONE run (reaching CONFIRMED), but
NEVER drop to k=1 — and never CONFIRM — a repo whose randomness isn't seeded. The safety property is
asymmetric and absolute: a flaky number must not be confirmed. These tests exercise the real pipeline.
"""
import sys

import pipeline as PIPE
from core import determinism as DET
from core import verdict as VD

# A genuinely deterministic eval: seeded RNG, metric via sklearn (so it recomputes) → CONFIRMABLE.
_SEEDED = (
    "import numpy as np\n"
    "from sklearn.metrics import accuracy_score\n"
    "rng = np.random.default_rng(0)\n"
    "y = rng.integers(0, 2, 200)\n"
    "p = np.where(rng.random(200) < 0.2, 1 - y, y)\n"
    "print('accuracy=%.4f' % accuracy_score(y, p))\n"
)
# A genuinely FLAKY eval whose number drifts run-to-run — driven by the harness run counter (a controllable,
# deterministic-in-CI stand-in for an unseeded RNG / wall-clock, the same device fixtures/nondeterministic
# uses). Above-chance and balanced (no validity flag), with a LARGE drift so the k=2 spread is unmistakable.
_FLAKY = (
    "import os\n"
    "from sklearn.metrics import accuracy_score\n"
    "run = int(os.environ.get('CALMA_RUN_INDEX', '0'))\n"
    "y = [1, 0] * 50\n"
    "n_correct = 90 - run * 20\n"                    # run0: 0.90, run1: 0.70 — spread 0.20
    "p = [y[i] if i < n_correct else 1 - y[i] for i in range(100)]\n"
    "print('accuracy=%.4f' % accuracy_score(y, p))\n"
)


def _repo(tmp_path, code):
    (tmp_path / "eval.py").write_text(code)
    return str(tmp_path)


def _verify(repo, tmp_path, **opts):
    return PIPE.verify_repo(repo, PIPE.VerifyOptions(
        deep=True, runner="local", discover=True, k=2,
        venvs_dir=str(tmp_path / "venvs"), base_python=sys.executable, **opts))


def test_seeded_repo_confirms_at_k1(tmp_path):
    """Proven deterministic → ONE run → CONFIRMED by construction (tested=False, proven=True, k=1)."""
    repo = _repo(tmp_path, _SEEDED)
    assert DET.analyze(repo)["level"] == DET.DETERMINISTIC
    res = _verify(repo, tmp_path)
    acc = [c for c in res["claims"] if c["metric"] == "accuracy"]
    assert acc and acc[0]["verdict"] == VD.CONFIRMED
    det = acc[0]["determinism"]
    assert det["proven"] is True and det["tested"] is False and det["k"] == 1   # the k=1 proven path
    assert "by construction" in acc[0]["reason"]


def test_flaky_repo_is_never_confirmed(tmp_path):
    """THE safety property: an unseeded, run-to-run-varying number must NOT be CONFIRMED. The analyzer flags
    it at_risk (→ empirical k=2), the two runs disagree, and the verdict is NON-DETERMINISTIC — never a CONFIRM."""
    repo = _repo(tmp_path, _FLAKY)
    assert DET.analyze(repo)["level"] == DET.AT_RISK        # not eligible for k=1
    res = _verify(repo, tmp_path)
    for c in res["claims"]:
        assert c["verdict"] != VD.CONFIRMED, (c["metric"], c["verdict"], c["reason"])
    accs = [c for c in res["claims"] if c["metric"] == "accuracy"]
    assert accs and accs[0]["verdict"] == VD.NON_DETERMINISTIC   # caught, not silently passed
    assert accs[0]["determinism"]["tested"] is True and accs[0]["determinism"]["k"] == 2  # ran the empirical check


def test_adaptive_k_off_keeps_empirical_k2(tmp_path):
    """With adaptive_k disabled, even a seeded repo takes the empirical k=2 path (CONFIRMED, reproduced ×2)."""
    repo = _repo(tmp_path, _SEEDED)
    res = _verify(repo, tmp_path, adaptive_k=False)
    acc = [c for c in res["claims"] if c["metric"] == "accuracy"]
    assert acc and acc[0]["verdict"] == VD.CONFIRMED
    assert acc[0]["determinism"]["tested"] is True and acc[0]["determinism"]["k"] == 2


def test_empirical_instability_overrides_a_static_deterministic_claim():
    """Defense in depth: even if something were (wrongly) marked static-deterministic, an empirical k≥2 that
    OBSERVES disagreement must still win → NON-DETERMINISTIC. Static proof can never override observed flakiness."""
    from core import diff as D
    # each run's inputs recompute to its OWN result (so no INVALIDATED), but the two runs DISAGREE (0.8 vs 0.6).
    claim = {"id": "c1", "metric": "accuracy", "value": 0.8}
    y = [1, 0] * 5                                             # balanced (no degenerate/chance validity flag)
    run0 = [{"sink": "sklearn.metrics.accuracy_score", "metric": "accuracy", "result": 0.8,
             "inputs": {"y_true": y, "y_pred": [1, 0, 1, 0, 1, 0, 1, 0, 0, 1]},   # 8/10 = 0.8
             "captured_full": True, "user_site": True, "seq": 0}]
    run1 = [{"sink": "sklearn.metrics.accuracy_score", "metric": "accuracy", "result": 0.6,
             "inputs": {"y_true": y, "y_pred": [1, 0, 1, 0, 1, 0, 0, 1, 0, 1]},   # 6/10 = 0.6 — DISAGREES
             "captured_full": True, "user_site": True, "seq": 0}]
    rec = D.diff_claim(claim, [run0, run1], static_deterministic=True)   # static says "deterministic"...
    assert rec["verdict"] == VD.NON_DETERMINISTIC                       # ...but the observed spread wins
