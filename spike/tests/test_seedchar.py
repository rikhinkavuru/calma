"""Feature 15 — seed injection (characterization only). The delicate one: seeding is used to CHARACTERIZE
non-determinism, never to confirm a claim. These pin the seedinject hook's determinism and the
characterize_seed classification. The verdict-side disqualifier (a seed_injected run caps below CONFIRMED)
lives in test_interval.py."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)
sys.path.insert(0, os.path.join(_SPIKE, "capture"))

import seedinject  # noqa: E402
from core import seedchar as SC  # noqa: E402


def test_seed_all_makes_random_deterministic():
    import random
    seedinject.seed_all(1234)
    a = [random.random() for _ in range(5)]
    seedinject.seed_all(1234)
    b = [random.random() for _ in range(5)]
    assert a == b


def test_characterize_seed_detects_seed_controlled():
    def run_fn(env_extra):
        # unseeded -> varying; seeded -> constant (the seed controls the spread)
        return [0.85, 0.85] if env_extra and "CALMA_INJECT_SEED" in env_extra else [0.80, 0.88, 0.83]
    r = SC.characterize_seed(run_fn)
    assert r["seed_controls_spread"] and r["seeded_stable"] and not r["irreducibly_random"]
    assert "seed-controlled" in r["explanation"]


def test_characterize_seed_detects_irreducible_randomness():
    def run_fn(env_extra):
        return [0.85, 0.87]     # varies even with a seed injected
    r = SC.characterize_seed(run_fn)
    assert r["irreducibly_random"] and not r["seed_controls_spread"]


def test_characterize_seed_deterministic_repo():
    def run_fn(env_extra):
        return [0.85, 0.85]
    r = SC.characterize_seed(run_fn)
    assert not r["seed_controls_spread"] and not r["irreducibly_random"]


def test_inject_seed_env_gate_is_opt_in(monkeypatch):
    # with no CALMA_INJECT_SEED, install is a no-op (idempotent, fail-soft)
    monkeypatch.delenv("CALMA_INJECT_SEED", raising=False)
    seedinject._INSTALLED[0] = False
    seedinject.install_seed_from_env()          # must not raise
    assert seedinject._INSTALLED[0] is False
