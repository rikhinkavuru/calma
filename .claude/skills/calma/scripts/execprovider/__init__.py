"""execprovider — the Calma execution-platform interface (W1 / master milestone P2-M0 -> P2-M1).

ONE swappable surface in front of every isolation tier. The control plane and the verdict layer import from
here and NEVER from a concrete driver, so E2B <-> Northflank <-> a customer cluster is a config change.

This package is ADDITIVE and PURE-STDLIB: nothing in the existing engine core path imports it, so it cannot
regress the core suite. The reference driver (LocalProvider) is fully wired to run_hermetic.py; the remote
drivers are honest skeletons that name their concrete mapping.

Design doc: docs/internal/W1-execution-platform-foundation.md.
"""
from __future__ import annotations

from .base import (ExecutionProvider, PreparedTemplate, from_engine_result, refused,
                   verified_tiers)
from .local_driver import LocalProvider
from .remote_drivers import K8sSandboxProvider, NorthflankProvider
from .valuetypes import (ArtifactRef, CodeBundle, DataRef, NetworkPolicy, ResourceLimits,
                         ResourceUsage, RunResult, RunSpec, TemplateSpec, MAX_ARTIFACT_BYTES,
                         OUTPUT_CAP)

__all__ = [
    # interface + helpers
    "ExecutionProvider", "PreparedTemplate", "from_engine_result", "refused", "verified_tiers",
    # drivers
    "LocalProvider", "NorthflankProvider", "K8sSandboxProvider",
    # value types
    "NetworkPolicy", "ResourceLimits", "DataRef", "CodeBundle", "TemplateSpec", "RunSpec",
    "ResourceUsage", "ArtifactRef", "RunResult",
    # constants (sourced from the engine)
    "MAX_ARTIFACT_BYTES", "OUTPUT_CAP",
]
