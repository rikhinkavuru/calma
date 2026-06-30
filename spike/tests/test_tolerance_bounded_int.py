"""Regression: a bounded [0,1] metric claimed as a bare integer ("1"/"0") means exactly that, not ±0.5.

The half-ULP-of-the-units-digit tolerance is right for counts ("1000 samples" → 1000±0.5) but a FALSE
CONFIRM for rates ("recall: 1" must not match a produced 0.9667). Found by optimize/corpus_synth.py.
"""
from core import tolerance as T


def test_bounded_integer_claim_refutes_a_different_value():
    assert not T.claim_close("1", 0.9667)[0]      # over-claimed perfect score
    assert not T.claim_close("1", 0.55)[0]
    assert not T.claim_close("0", 0.2)[0]


def test_bounded_integer_claim_confirms_an_exact_value():
    assert T.claim_close("1", 1.0)[0]
    assert T.claim_close("1", 0.9999)[0]          # float noise around a true 1.0
    assert T.claim_close("0", 0.0)[0]


def test_large_magnitude_integer_keeps_half_ulp():
    # counts/sums reported as integers still mean ±0.5 (the rounding model is correct there)
    assert T.claim_close("1000", 1000.3)[0]
    assert not T.claim_close("1000", 1002)[0]
