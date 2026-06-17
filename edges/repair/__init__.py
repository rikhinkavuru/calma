"""A4 -- execution-grounded agentic repair.

A Calma REFUTED/INVALIDATED already IS the trustworthy, deterministic, fail-on-bug/pass-on-fix test
that every 2026 repair framework struggles to synthesize. A4 wraps the proven repair mechanics around
that test: AI proposes a minimal patch; the deterministic core re-verifies the PATCHED code from
scratch and owns the verdict. The goalposts (claim, metric, contract, artifact identity, isolation
tier, determinism mode) are immutable across a repair; the user's working branch is never mutated.

This package calls `anthropic` (the proposer) but reaches the verdict ONLY through the P0 black-box
subprocess bridge edges.common.engine.verify -- it never imports verdict/ledger/compare/recompute/
numeric (the firewall enforces it).
"""
