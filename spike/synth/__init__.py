"""calma.spike.synth — grow the trusted catalog on demand (the flywheel).

    formula.recompute_any(metric, inputs, kwargs)  -> Result with provenance (catalog | store | synth | none)
    store.get_store()                              -> the formula store (HelixDB if configured, else local)

Used as the `resolver` injected into core.diff for metrics the curated catalog doesn't recognise — so an
unknown metric becomes verifiable (and its formula banked) instead of stalling at reproduced-only.
"""
from . import formula, store  # noqa: F401
