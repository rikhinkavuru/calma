"""calma.spike.core — the trusted recompute + three-way-diff correctness core.

Pure-stdlib. The independent oracle (catalog) deliberately shares no code with the repo under test.
Public surface:
    catalog.recompute(metric, inputs, kwargs) -> Result
    diff.diff_repo(claims, runs) -> {"claims": [...], "counts": {...}}
    verdict.{CONFIRMED, REFUTED, INVALIDATED, REPRODUCED_ONLY, NON_DETERMINISTIC, INCONCLUSIVE}
"""
from . import catalog, diff, tolerance, validity, verdict  # noqa: F401
