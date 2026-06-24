"""execprovider.remote_drivers — skeletons for the genuinely-not-yet-built remote providers.

WHY THESE ARE SKELETONS (and E2B is not here): run_hermetic.py ALREADY ships a cold-boot E2B/Firecracker
backend (_run_e2b_backend / _RealE2BSession), so the in-process E2B path is reachable today via
LocalProvider(isolation="e2b"). What does NOT exist is the *productized* warm-pool E2B driver — prepare()
that builds a Build-System-2.0 template + memory snapshot, a claim-from-warm-pool run(), the in-the-run-VM
probe (doc §5-A), and pull-time artifact caps. That is the M1.2 build and should EXTEND LocalProvider's mapping.

Northflank (2nd source, on-prem/air-gapped — M1.8) and K8s-Sandbox (customer-cluster BYOC portability — M1.8 /
P3-M6) have no engine backend at all yet; they are Protocol-shaped stubs that name their concrete mapping so
M1.8 is a fill-in, not a design. Each raises NotImplementedError from the lifecycle methods (honest: the shape
is real, the body is not), while available() returns a truthful "not built" so the fleet's provider-selection
can skip them without a crash.

Design doc: docs/internal/W1-execution-platform-foundation.md (§3.4). PURE STDLIB (no SDKs imported here).
"""
from __future__ import annotations

from .base import PreparedTemplate
from .valuetypes import RunSpec, TemplateSpec

_NOT_BUILT = "driver not implemented yet (master milestone P2-M1.8 / P3-M6) — see docs/internal/W1-execution-platform-foundation.md §3.4"


class _SkeletonProvider:
    """Shared no-op base for the unbuilt remote drivers. Conformant to the ExecutionProvider Protocol shape
    (the methods exist); the lifecycle bodies refuse honestly until built."""
    name = "skeleton"
    #: the concrete mapping a builder fills in — kept as data so it shows up in docs/inspection.
    mapping: dict = {}

    def available(self):
        return False, _NOT_BUILT

    def prepare(self, template: TemplateSpec) -> PreparedTemplate:
        raise NotImplementedError("%s.prepare: %s" % (self.name, _NOT_BUILT))

    def doctor(self, prepared: PreparedTemplate) -> dict:
        return {"tier": "host-not-isolated", "note": "%s: %s" % (self.name, _NOT_BUILT)}

    def run(self, spec: RunSpec, prepared: PreparedTemplate):
        raise NotImplementedError("%s.run: %s" % (self.name, _NOT_BUILT))

    def teardown(self, prepared: PreparedTemplate) -> None:
        return None


class NorthflankProvider(_SkeletonProvider):
    """2nd execution source (on-prem / air-gapped / cost hedge). M1.8 — the fleet spills E2B->Northflank on a
    capacity 429 rather than queueing forever."""
    name = "northflank"
    mapping = {
        "available": "Northflank API reachable + project/template configured",
        "prepare":   "build a Northflank sandbox template (Kata/Firecracker/gVisor selectable)",
        "doctor":    "boot a sandbox network-OFF, run the _PROBE battery in-sandbox, verify zero egress",
        "run":       "REST sandbox lifecycle: create -> stage over control channel -> probe -> exec -> pull",
        "teardown":  "delete the sandbox; never reuse across tenants",
        "isolation": "Kata/Firecracker/gVisor (per project config)",
    }


class K8sSandboxProvider(_SkeletonProvider):
    """Customer-cluster BYOC via the Kubernetes Agent Sandbox CRDs (the portability contract — K5). M1.8 /
    P3-M6. Carries the WarmPool CWE-770 guardrails (doc §2.4): CEL-bounded spec.replicas + ResourceQuota +
    slowStartBatch + an independent global ceiling."""
    name = "k8s-sandbox"
    mapping = {
        "available": "Agent Sandbox controller installed in the target cluster",
        "prepare":   "ensure SandboxTemplate + SandboxWarmPool exist (replicas CEL-bounded; ResourceQuota set)",
        "doctor":    "create a SandboxClaim, run the _PROBE in-pod under a default-deny NetworkPolicy",
        "run":       "claim a warm sandbox -> stage -> probe -> exec via the Sandbox Router -> snapshot pull",
        "teardown":  "release/kill the claim; warm-pool replenishes from a CLEAN snapshot only (T4/T6)",
        "isolation": "gVisor/Kata, default-deny netpol",
    }
