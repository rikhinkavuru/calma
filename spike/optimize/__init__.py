"""calma.spike.optimize — the meta-evaluation + optimization loop.

This package measures CALMA ITSELF (the verifier), not the user's metric. It generates labeled
synthetic claims against captured ground truth and scores the confusion matrix the go/no-go harness
doesn't: catch-rate, false-refute, false-confirm-under-injection, and the MDE sensitivity curve.

Two-step, by design:
  capture_fixtures.py   run each base fixture ONCE (k runs), persist the raw capture to captures/
  measure.py            replay thousands of injected claims against the captures, score, write metrics.json

Replaying persisted captures keeps the loop fast and isolates what we optimize (binding / diff / tolerance
/ verdict logic) from the slow, occasionally-flaky run step.
"""
