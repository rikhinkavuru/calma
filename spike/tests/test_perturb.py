"""Feature 10 — perturbation-fabrication primitives. A genuine metric moves when its inputs are corrupted;
a fabricated constant does not. These pin: the perturbations actually move the trusted oracle (power), the
fabrication charge fires only on a value invariant across ≥2 oracle-moving perturbations (soundness), and a
genuine metric is never flagged (precision). Downgrade-only by construction — verdict_signal returns a note or
None, never a value."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from core import catalog as C  # noqa: E402
from core import perturb as PB  # noqa: E402


def test_perturbations_move_the_oracle_for_classification():
    inputs = {"y_true": [0, 1, 0, 1, 0, 1, 1, 0, 1, 0], "y_pred": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]}
    s = PB.sensitivity("accuracy", inputs, {}, C.recompute)
    assert s["moved"] and s["base"] is not None


def test_perturbations_move_the_oracle_for_auc():
    inputs = {"y_true": [0, 0, 1, 1, 1, 0, 1, 0], "y_score": [0.1, 0.2, 0.9, 0.7, 0.6, 0.3, 0.8, 0.4]}
    s = PB.sensitivity("roc_auc", inputs, {}, C.recompute)
    assert s["moved"]


def test_perturb_never_mutates_inputs():
    inputs = {"y_true": [0, 1, 0, 1], "y_pred": [0, 1, 1, 0]}
    snapshot = {k: list(v) for k, v in inputs.items()}
    PB.perturb_inputs("accuracy", inputs)
    assert inputs == snapshot


def test_verdict_signal_flags_a_fabricated_invariant_value():
    oracle = {"shuffle_pred": 0.30, "drop_tail": 0.08}   # oracle moves materially on both
    repo = {"shuffle_pred": 0.0, "drop_tail": 0.0}        # the repo's own value never budged
    note = PB.verdict_signal(oracle, repo)
    assert note and "does not depend on its inputs" in note


def test_verdict_signal_does_not_flag_a_genuine_metric():
    oracle = {"shuffle_pred": 0.30, "drop_tail": 0.08}
    repo = {"shuffle_pred": 0.29, "drop_tail": 0.07}      # the repo tracks the oracle → genuine
    assert PB.verdict_signal(oracle, repo) is None


def test_verdict_signal_requires_two_moving_perturbations():
    oracle = {"shuffle_pred": 0.30, "drop_tail": 0.0001}  # only one material mover
    repo = {"shuffle_pred": 0.0, "drop_tail": 0.0}
    assert PB.verdict_signal(oracle, repo) is None


def test_float_noise_is_not_input_sensitivity():
    # a repo value that wobbles at 1e-7 under perturbation is invariant for our purposes (< material rel).
    oracle = {"noise_score": 0.20, "drop_tail": 0.05}
    repo = {"noise_score": 1e-7, "drop_tail": 2e-8}
    assert PB.verdict_signal(oracle, repo) is not None    # still flagged — the wobble is below material
