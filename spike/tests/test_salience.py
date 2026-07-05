"""Salience degenerate-value guard: a claim with a missing/None value is not a headline and must not crash."""
from discovery import salience


def test_degenerate_handles_none_and_missing_value():
    # Phase 2 mypy fix: float(None) previously relied on the except; a None/absent value now short-circuits to
    # False explicitly. Behavior is unchanged — a non-numeric value is still degenerate-safe (returns False).
    assert salience._degenerate({"value": None}) is False
    assert salience._degenerate({}) is False
    assert salience._degenerate({"value": "not-a-number"}) is False
    assert salience._degenerate({"value": 0.0}) is True        # exact-zero placeholder cell -> degenerate
    assert salience._degenerate({"value": 0.87}) is False      # a real, quotable metric value
