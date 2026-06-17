"""P3.2 acceptance tests -- stage-tagged counterexample -> sharp, localized feedback. Golden, no LLM.

The differential formatter localizes the likely wrong DSL operation from the numeric relationship between
oracle-expected and program-got (a ddof off-by-a-factor, a sign flip, a missing sqrt). Feedback is
advisory to the synthesizer; it never relaxes the gate.
"""
from edges.synth import feedback as FB


def test_differential_ddof_factor_names_ddof():
    # sem ddof=0 vs ddof=1 on n=7: ratio ~0.816 -> the "off by a constant factor" ddof branch
    ce = {"stage": "differential", "oracle": "scipy.stats.sem", "seed": 0, "n": 7,
          "expected": "0.5773502691896257", "got": "0.4714045207910317",
          "inputs": {"value": [1, 2, 3, 4, 5, 6, 7]}}
    msg = FB.format_counterexample(ce)
    assert "ddof" in msg
    assert "DIFFERENTIAL" in msg and "scipy.stats.sem" in msg


def test_differential_sign_error():
    ce = {"stage": "differential", "oracle": "o", "seed": 1, "n": 3,
          "expected": "1.25", "got": "-1.25", "inputs": {"value": [1, 2, 3]}}
    assert "SIGN" in FB.format_counterexample(ce)


def test_differential_missing_sqrt():
    ce = {"stage": "differential", "oracle": "o", "seed": 1, "n": 3,
          "expected": "3.0", "got": "9.0", "inputs": {"value": [1, 2, 3]}}   # got == expected**2
    assert "sqrt" in FB.format_counterexample(ce)


def test_differential_oracle_error_blames_the_spec():
    ce = {"stage": "differential", "oracle": "scipy.stats.sem", "seed": 0, "n": 3,
          "error": "TypeError: sem() got an unexpected keyword argument 'bias'"}
    msg = FB.format_counterexample(ce)
    assert "oracle" in msg.lower() and "Fix the oracle spec" in msg


def test_degenerate_raise_says_degrade_to_nan():
    ce = {"stage": "degenerate", "case": "empty", "error": "ZeroDivisionError"}
    msg = FB.format_counterexample(ce)
    assert "degrade to NaN" in msg and "never raise" in msg


def test_metamorphic_scale_mentions_invariant_vs_homogeneous():
    ce = {"stage": "metamorphic", "relation": "scale", "index": 0, "seed": 2, "n": 7,
          "expected": "1.0", "got": "7.0"}
    msg = FB.format_counterexample(ce)
    assert "scale" in msg.lower()
    assert "INVARIANT" in msg and "HOMOGENEOUS" in msg


def test_metamorphic_bounds():
    ce = {"stage": "metamorphic", "relation": "bounds", "seed": 1, "n": 3,
          "expected": "in [0, 1]", "got": "1.4"}
    assert "bounds" in FB.format_counterexample(ce).lower()


def test_bitstability_message():
    ce = {"stage": "bit-stability", "seed": 1, "n": 3, "run1": "0.5", "run2": "0.5000000001"}
    assert "BIT-STABILITY" in FB.format_counterexample(ce)


def test_unknown_stage_is_a_string_and_does_not_raise():
    out = FB.format_counterexample({"stage": "???"})
    assert isinstance(out, str) and "Unknown" in out
