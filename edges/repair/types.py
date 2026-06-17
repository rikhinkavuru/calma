"""The shared contract between the four A4 modules (orchestrate / checkpoints / review / memory)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Goalposts:
    """The immutable identity of a verification. Captured from the ORIGINAL run BEFORE any edit, and
    re-asserted on every re-verify (review.py diffs the new run against this). Nothing here may change."""
    claim_value: float                 # the ORIGINAL claimed_value (ledger claim.claimed_value)
    metric_id: str                     # the ORIGINAL metric (ledger claim.metric)
    contract_sha256: Optional[str]     # sha256 of <target>/verify.yaml (or the drafted contract) bytes
    artifact_paths: tuple              # the bound artifact paths the recompute reads (from verify.yaml)
    artifact_sha256: dict              # {path: sha256} of each bound artifact BEFORE the patch
    isolation_tier: Optional[str]      # the ORIGINAL isolation_tier (must not be downgraded)
    determinism_mode: Optional[str]    # the ORIGINAL determinism_mode (must not be loosened)


@dataclass
class Diagnosis:
    cause: str                         # the model's plain-language root cause
    locator: str                       # the finding locator it is addressing
    dimension: str                     # the driving_dimension it is addressing
    unified_diff: str                  # a minimal unified diff against the producing file(s)
    target_files: tuple                # files the diff touches (relpaths under target)
    rationale: str                     # why this closes the gap WITHOUT moving a goalpost


@dataclass
class HypothesisResult:
    index: int
    diagnosis: Diagnosis
    branch: str
    before_verdict: str
    after_verdict: Optional[str]
    before_gap: Optional[float]
    after_gap: Optional[float]
    effective_budget: Optional[float]
    gap_closed: bool
    reviewers_passed: bool
    review_reasons: list = field(default_factory=list)
    accepted: bool = False
    note: str = ""


@dataclass
class RepairResult:
    run_dir: str
    target: str
    accepted: bool
    before_verdict: str
    after_verdict: Optional[str]
    patch: Optional[str]               # the accepted unified diff, or None
    goalposts: Goalposts
    trajectory: list                   # [HypothesisResult, ...] in order tried
    one_shot: bool = False             # accepted on the first hypothesis (the KPI)
