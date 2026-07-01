"""Feature 5 — the KnownValueHint firewall (the FCR guard). A banked known value is a PRIOR for planning /
binding ONLY; it must have NO path into the verdict. This test enforces that structurally, mirroring the
edges/core CI-firewall discipline: the verdict-deciding modules never reference the experience bank or its
known-value namespace, and their signatures accept no known-value channel."""
import inspect
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from core import diff as D  # noqa: E402
from core import verdict as VD  # noqa: E402
from synth import experience as EXP  # noqa: E402

_VERDICT_MODULES = ("core/diff.py", "core/verdict.py")
_FORBIDDEN = ("experience", "KnownValueHint", "ExperienceBank", "bank_known_value", "known_value", ".hints(")


def test_verdict_modules_never_reference_the_known_value_bank():
    for rel in _VERDICT_MODULES:
        src = open(os.path.join(_SPIKE, rel)).read()
        for token in _FORBIDDEN:
            assert token not in src, "%s must not reference %r (known-value firewall)" % (rel, token)


def test_decide_and_diff_signatures_have_no_known_value_channel():
    decide_params = set(inspect.signature(VD.decide).parameters)
    # the ONLY value channels are the producer's claim + this run's produced + this run's recompute
    assert decide_params == {"claimed_raw", "produced", "recomputed", "recompute_known", "binding",
                             "determinism", "validity", "distribution", "seed_injected"}
    diff_params = set(inspect.signature(D.diff_claim).parameters)
    assert "known_value" not in diff_params and "hint" not in diff_params
    assert not (diff_params & {"bank", "experience", "known_values"})


def test_known_value_hint_is_not_a_verdict_input_type():
    # a KnownValueHint carries no produced/recomputed field a verdict could latch onto
    h = EXP.KnownValueHint(key="fam", metric="accuracy", value=0.9)
    assert not hasattr(h, "produced") and not hasattr(h, "recomputed")
