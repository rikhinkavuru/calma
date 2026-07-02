"""calma.spike.orchestrator — the repo-assessment + tool-selection orchestrator (build plan §1).

After clone, ``assess`` profiles a repo statically (zero LLM cost) and ``orchestrate`` chooses HOW to make it
runnable from a typed tool registry, driving a bounded execute/observe/revise loop until the repo runs or is
honestly declared un-runnable. New edge cases become new registry rows, not new branches in a monolith.

The FCR firewall (§0) is structural: the agent's only output is a validated ``RunApproach`` / ``RunResult``;
the deterministic verify core consumes ``RunResult.runs`` unchanged. Nothing here imports ``core.verdict`` /
``core.diff`` — asserted by ``tests/test_orchestrator_firewall.py``.
"""
from __future__ import annotations

from .types import (
    BUILDERS,
    ENTRY_KINDS,
    LANGUAGES,
    LAYOUTS,
    PKG_MANAGERS,
    RUNNERS,
    EntryCand,
    RepoProfile,
    RunApproach,
    RunResult,
    SchemaError,
)

__all__ = [
    "EntryCand", "RepoProfile", "RunApproach", "RunResult", "SchemaError",
    "RUNNERS", "BUILDERS", "ENTRY_KINDS", "LANGUAGES", "LAYOUTS", "PKG_MANAGERS",
]
