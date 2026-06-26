"""execprovider.base — the ExecutionProvider Protocol, the PreparedTemplate handle, and the single point that
maps the engine's run-dict onto RunResult (`from_engine_result`).

PURE STDLIB. The Protocol is the ONLY surface the control plane / verdict layer import. Local tiers
(seatbelt/bwrap/docker) are thin adapters over run_hermetic.py; remote tiers (e2b/k8s/northflank) implement the
same shape. Design doc: docs/internal/W1-execution-platform-foundation.md (§3.3).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .valuetypes import ResourceUsage, RunResult, RunSpec, TemplateSpec


def _engine():
    """Lazily resolve run_hermetic, adding the engine scripts dir (this package's parent) to sys.path if it
    is not already importable. Kept lazy so importing execprovider.types/base never forces the executor in."""
    try:
        import run_hermetic as H  # type: ignore
        return H
    except ImportError:
        import os
        scripts_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import run_hermetic as H  # type: ignore
        return H


def verified_tiers():
    """The single source of truth for which isolation_tier stamps count as VERIFIED — sourced from the
    engine's one canonical definition (calma.tiers.VERIFIED_TIERS; doc §5-I, now consolidated from the
    former 5 copies). A run whose isolation_tier is not in this set must be REFUSED for untrusted code."""
    try:
        import tiers  # type: ignore
        return tuple(tiers.VERIFIED_TIERS)
    except ImportError:
        return tuple(_engine()._VERIFIED_TIERS)  # _VERIFIED_TIERS IS tiers.VERIFIED_TIERS (same object)


@dataclass
class PreparedTemplate:
    """The handle prepare() returns and run()/doctor()/teardown() consume. Carries the probe context (the
    work `base` dir the engine doctors need — doc §5-A) plus provider-specific warm-pool state. For local
    tiers this is near-trivial; for e2b/k8s it would also hold the warm sandbox handle / snapshot id."""
    template: TemplateSpec
    base: str = ""                       # the work/base dir (where the engine plants the probe + runs)
    isolation: str | None = None         # the engine isolation key: seatbelt|bwrap|docker|e2b|None(auto)
    image_digest: str = ""
    handle: object = None                # provider-native warm handle (sandbox id / snapshot), if any
    meta: dict = field(default_factory=dict)


@runtime_checkable
class ExecutionProvider(Protocol):
    """The five-method contract. See the design doc §3.3 for the full semantics of each method; the
    load-bearing rules: doctor()/run() PROVE network-off with the in-VM _PROBE before trusting a tier;
    recompute NEVER happens here (host-side, over pulled artifacts); a sandbox is NEVER reused across
    tenants (teardown kills)."""
    name: str

    def available(self) -> "tuple[bool, str]": ...
    def prepare(self, template: TemplateSpec) -> PreparedTemplate: ...
    def doctor(self, prepared: PreparedTemplate) -> dict: ...
    def run(self, spec: RunSpec, prepared: PreparedTemplate) -> RunResult: ...
    def teardown(self, prepared: PreparedTemplate) -> None: ...


def refused(run_id: str, reason: str, isolation_tier: str = "host-not-isolated",
            exit_code: int = 3, doctor: dict | None = None) -> RunResult:
    """Build a fail-closed RunResult for a refused run. Mirrors the engine's refusal dicts
    ({phase:'refused', exit_code:3, ...}) so the state machine maps REFUSED uniformly."""
    return RunResult(
        run_id=run_id, isolation_tier=isolation_tier, tier_verified=False,
        run_exit_status=-1, exit_code=exit_code, killed=False,
        network_run="n/a", network_install="n/a", hermeticity="unverified",
        determinism_mode="uncontrolled", determinism_note="run refused before execution",
        reason=reason, phase="refused", doctor=doctor or {},
    )


def from_engine_result(run_id: str, eng: dict,
                       artifacts_manifest: tuple = (),
                       resource_usage: ResourceUsage | None = None,
                       determinism_digest: str = "") -> RunResult:
    """The ONE mapping point: the run_hermetic.py run-dict -> RunResult. Encodes the renames documented in
    doc §5-B (container_present->tier_verified, run_network->network_run, install_network->network_install)
    and leaves the NEW fields (artifacts_manifest/resource_usage/determinism_digest) at empty defaults unless
    the caller computed them host-side. Tolerant of the engine's refusal dicts (which omit most keys)."""
    g = eng.get
    return RunResult(
        run_id=run_id,
        isolation_tier=g("isolation_tier", "host-not-isolated"),
        tier_verified=bool(g("container_present", False)),
        run_exit_status=int(g("run_exit_status", g("exit_code", -1)) or -1),
        exit_code=int(g("exit_code", -1)),
        killed=bool(g("killed", False)),
        network_run=g("run_network", "n/a"),
        network_install=g("install_network", "n/a"),
        hermeticity=g("hermeticity", "unverified"),
        determinism_mode=g("determinism_mode", "uncontrolled"),
        determinism_note=g("determinism_note", ""),
        language=g("language", ""),
        interpreter=g("interpreter", ""),
        hardening=tuple(g("hardening") or ()),
        stdout_tail=g("stdout_tail", ""),
        stderr_tail=g("stderr_tail", ""),
        doctor=g("doctor", {}) or {},
        reason=g("reason", ""),
        phase=g("phase", "run"),
        artifacts_manifest=tuple(artifacts_manifest),
        resource_usage=resource_usage or ResourceUsage(),
        determinism_digest=determinism_digest,
    )
