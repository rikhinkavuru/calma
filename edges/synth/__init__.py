"""A3 -- recipe coverage via an agent-in-the-CEGIS-loop.

The synthesizer (LLM) PROPOSES a calma/recipe-draft@1; the deterministic gate (compiler.admit) DISPOSES
-- a draft becomes a shipped recipe only when differential-vs-oracle + metamorphic + degeneracy +
bit-stability all pass. Stage-tagged counterexamples are the feedback; a cross-recipe constraint DB
accumulates them so the model stops re-making known mistakes. Goal: scale the recipe library 623 ->
thousands WITHOUT ever moving the gate.

A3 is the only edge allowed to import core modules, and exactly two -- `compiler` and `dsl` (the gate).
It never imports verdict/ledger/compare/recompute (firewall allowlist EDGES_ALLOWED_CORE_IMPORTS).
"""
