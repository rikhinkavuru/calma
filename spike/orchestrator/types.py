"""calma.spike.orchestrator.types — the typed hand-off that IS the FCR firewall surface (build plan §3).

The orchestrator's *only* output is a validated ``RunApproach`` (its decision) and a ``RunResult`` (what
executing that decision produced). The deterministic verify core (``core/diff.py`` → ``core/verdict.py``,
via ``pipeline._diff_claims``) consumes ``RunResult.runs`` and is UNCHANGED. There is deliberately no field
here that carries a verdict, a claim value, a binding, or a recompute: if it isn't in ``RunResult.runs`` it
cannot reach a verdict, and ``runs`` carries only the repo's OWN captured computations (the same shape the
existing runners emit), never anything the orchestrator decided.

Everything is a plain stdlib dataclass with strict shape validation. ``from_dict`` is the boundary where an
LLM-proposed approach (untrusted JSON) is coerced into a typed value or rejected — the agent can never emit
anything outside these schemas. Keep this module free of any ``core.verdict`` / ``core.diff`` import: the
CI firewall test (``tests/test_orchestrator_firewall.py``) asserts it, mirroring the known-value firewall.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# ── the fixed vocabularies (a wrong value is a shape error, never a silent pass) ──────────────────────────────
# "modal-gpu" is the GPU backend (E2B can't do GPU). "e2b-gpu" is kept as a deprecated alias so no stored
# approach/config breaks; both resolve to the Modal runner at dispatch.
RUNNERS = ("local", "e2b", "modal-gpu", "e2b-gpu")
BUILDERS = ("venv-pip", "uv", "conda-micromamba", "declared", "none")
# entrypoint kinds the executor knows how to dispatch. Each maps to exactly one execute tool in the registry.
ENTRY_KINDS = ("script", "module", "notebook", "make", "shell", "lang")
LANGUAGES = ("python", "r", "julia", "shell", "mixed", "unknown")
LAYOUTS = ("root-script", "package", "src-layout", "notebook", "monorepo", "make-driven", "unknown")
PKG_MANAGERS = ("requirements", "pyproject", "poetry", "pipenv", "conda", "setup", "none")


def _is_str_list(x) -> bool:
    return isinstance(x, list) and all(isinstance(v, str) for v in x)


def _is_str_dict(x) -> bool:
    return isinstance(x, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in x.items())


class SchemaError(ValueError):
    """Raised when an (often LLM-proposed) payload does not conform to a typed hand-off schema. The caller
    treats it exactly like a failed run — fall back to a heuristic / next approach — never a crash."""


# ── the static assessment product ─────────────────────────────────────────────────────────────────────────────
@dataclass
class EntryCand:
    """One ranked entrypoint candidate. ``argv`` is repo-relative (``['code/run.py']`` / ``['-m','pkg']`` /
    ``['nb:analysis.ipynb']``). ``kind`` selects the execute tool; ``signals`` records WHY it ranked where it
    did (README command, __main__ guard, imports sklearn, …) for the Assessment Report."""
    argv: list[str]
    kind: str = "script"
    confidence: float = 0.5
    signals: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not _is_str_list(self.argv) or not self.argv:
            raise SchemaError("EntryCand.argv must be a non-empty list[str]")
        if self.kind not in ENTRY_KINDS:
            raise SchemaError("EntryCand.kind %r not in %r" % (self.kind, ENTRY_KINDS))
        self.confidence = _clamp01(self.confidence)
        if not _is_str_list(self.signals):
            raise SchemaError("EntryCand.signals must be list[str]")


@dataclass
class RepoProfile:
    """The deterministic static profile of a repo (build plan §3). Produced with ZERO LLM cost by the
    assessment tools; the LLM only ranks approaches over it when static signals are ambiguous."""
    language: str = "unknown"
    layout: str = "unknown"
    pkg_manager: str = "none"
    py_version: str | None = None
    entry_candidates: list[EntryCand] = field(default_factory=list)
    notebooks: list[str] = field(default_factory=list)
    make_targets: list[str] = field(default_factory=list)
    declared_deps: list[str] = field(default_factory=list)
    data_needs: list[str] = field(default_factory=list)
    determinism: dict = field(default_factory=dict)
    domain: str | None = None
    fingerprint: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── the agent's decision (untrusted until validated) ────────────────────────────────────────────────────────────
@dataclass
class RunApproach:
    """How to make a repo runnable and run it — the agent's ONLY decision surface. Note what is absent: no
    verdict, no claim value, no binding, no recompute. Whatever this says, the run still flows through the
    unchanged k-runs → identity-binding → recompute → fail-closed verdict."""
    runner: str = "local"
    builder: str = "venv-pip"
    entry: list[str] = field(default_factory=list)
    deps: list[str] = field(default_factory=list)
    capture_targets: list[dict] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    notes: str = ""
    confidence: float = 0.5

    def __post_init__(self):
        if self.runner not in RUNNERS:
            raise SchemaError("RunApproach.runner %r not in %r" % (self.runner, RUNNERS))
        if self.builder not in BUILDERS:
            raise SchemaError("RunApproach.builder %r not in %r" % (self.builder, BUILDERS))
        if not _is_str_list(self.entry):
            raise SchemaError("RunApproach.entry must be list[str]")
        if not _is_str_list(self.deps):
            raise SchemaError("RunApproach.deps must be list[str]")
        if not (isinstance(self.capture_targets, list)
                and all(isinstance(t, dict) for t in self.capture_targets)):
            raise SchemaError("RunApproach.capture_targets must be list[dict]")
        if not _is_str_dict(self.env):
            raise SchemaError("RunApproach.env must be dict[str,str]")
        if not isinstance(self.notes, str):
            raise SchemaError("RunApproach.notes must be str")
        self.confidence = _clamp01(self.confidence)

    @classmethod
    def from_dict(cls, d: dict) -> "RunApproach":
        """Coerce an (untrusted) proposal dict into a validated RunApproach or raise SchemaError. Unknown keys
        are dropped (an injected extra field can never take effect); missing keys take the safe defaults."""
        if not isinstance(d, dict):
            raise SchemaError("RunApproach payload must be an object")
        allowed = {f for f in cls.__dataclass_fields__}          # noqa: E1133 — dataclass field names
        clean = {k: v for k, v in d.items() if k in allowed}
        return cls(**clean)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RunResult:
    """What executing an approach produced → handed verbatim to the deterministic verify. ``runs`` is a list
    of capture-call lists (one per k), the SAME shape ``local_runner`` / ``e2b_runner`` already return, so the
    downstream diff is untouched. ``source_modified`` drives ``pipeline._apply_agent_modified_cap`` (any
    non-empty list caps every AFFIRMATIVE verdict to REPRODUCED-ONLY)."""
    ran_ok: bool = False
    runs: list = field(default_factory=list)
    meta: list = field(default_factory=list)
    cost: dict = field(default_factory=dict)
    source_modified: list[str] = field(default_factory=list)
    approach: RunApproach | None = None
    trace: list = field(default_factory=list)          # the ReAct step trace (Assessment Report / audit)

    def __post_init__(self):
        if not isinstance(self.ran_ok, bool):
            raise SchemaError("RunResult.ran_ok must be bool")
        if not isinstance(self.runs, list):
            raise SchemaError("RunResult.runs must be a list")
        if not _is_str_list(self.source_modified):
            raise SchemaError("RunResult.source_modified must be list[str]")
        if self.approach is not None and not isinstance(self.approach, RunApproach):
            raise SchemaError("RunResult.approach must be a RunApproach or None")

    def to_run_dict(self) -> dict:
        """The dict shape ``pipeline._run_repo`` returns today, so the orchestrator drops in as a replacement
        producer with no change to ``_diff_claims`` / the overlays. Deliberately emits ONLY run artifacts —
        never a verdict/binding/recompute."""
        return {"ran_ok": self.ran_ok, "runs": self.runs, "meta": self.meta,
                "cost": self.cost, "source_modified": self.source_modified,
                "approach": self.approach.to_dict() if self.approach else None,
                "trace": self.trace}


def _clamp01(x) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0
