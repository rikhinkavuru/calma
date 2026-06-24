"""execprovider.valuetypes — the typed request/result value objects for the Calma execution platform (W1).

(Named `valuetypes`, NOT `types`, on purpose: a module named `types.py` shadows the stdlib `types` module
whenever this directory lands on sys.path[0] — e.g. running a sibling script directly — which breaks
functools/enum imports. Spec-01 §1.2 sketched `execprovider/types.py`; this is the safe rename.)

PURE STDLIB. NO provider SDK imports anywhere in this module (a remote driver lazily imports its SDK only
when actually selected, exactly as run_hermetic._RealE2BSession does). These dataclasses are the ONLY surface
the control plane and the verdict layer depend on — so swapping E2B <-> Northflank <-> a customer cluster is a
config change, not a code change.

Design doc: docs/internal/W1-execution-platform-foundation.md (§3.2). Several RunResult fields are mapped 1:1
from the engine's run_hermetic.py run-dict; a few (resource_usage, artifacts_manifest, determinism_digest) are
NEW and default to empty so the in-process LocalProvider can leave them blank and the hosted platform can fill
them in later WITHOUT changing this contract. See §5-C/E/G of the doc for which is which.
"""
from __future__ import annotations  # 3.9-safe: keeps `X | None` annotations as strings

import os
from dataclasses import dataclass, field
from enum import Enum

# The artifact byte-cap, sourced from the engine's single definition so the platform can never set a looser
# cap than the host verifier actually enforces. Falls back to the literal default if pathsafe isn't importable
# (e.g. someone imports types.py in isolation) — the value matches pathsafe.MAX_ARTIFACT_BYTES.
try:  # pragma: no cover - exercised whenever the engine is on sys.path
    from pathsafe import MAX_ARTIFACT_BYTES  # noqa: F401  (re-exported)
except Exception:  # pragma: no cover
    MAX_ARTIFACT_BYTES = int(float(os.environ.get("CALMA_MAX_ARTIFACT_MB", "256")) * 1024 * 1024)

# The in-flight stdout/stderr DRAIN cap (run_hermetic._OUTPUT_CAP = 4MB). Distinct from the ~500-byte tail the
# engine RETAINS in the run-dict — see doc §5-F. We re-derive the literal here to avoid importing run_hermetic
# (which pulls in the whole executor) just for a constant.
OUTPUT_CAP = 4 * 1024 * 1024
RETAINED_TAIL = 500


class NetworkPolicy(Enum):
    """The egress posture of a run. OFF is the ONLY value used in a production verification RUN phase; the
    raw-data-never-leaves invariant depends on it. ALLOW_LIST is RESERVED for a future restore/install phase
    and must never be selected for the run phase."""
    OFF = "off"
    ALLOW_LIST = "allow-list"


@dataclass(frozen=True)
class ResourceLimits:
    """Per-run caps. Maps onto docker flags / firecracker vcpu+mem / k8s limits. Defaults mirror the engine's
    hardening (run_hermetic._docker_hardening: --cpus 2, --memory 2g, --pids-limit 512) and pathsafe's cap."""
    cpu_cores: float = 2.0
    mem_mb: int = 2048
    wall_seconds: int = 120            # engine timeout; group-SIGKILL on expiry -> exit_code 4
    disk_mb: int = 4096                # writable scratch ceiling (tmpfs/overlay)
    pids_max: int = 512                # fork-bomb containment
    output_bytes_max: int = MAX_ARTIFACT_BYTES   # total pulled-artifact cap; enforced at PULL time
    stdout_tail_bytes: int = RETAINED_TAIL       # what is RETAINED in the result (engine slices [-500:])
    stdout_drain_bytes: int = OUTPUT_CAP         # in-flight OOM guard (run_hermetic._OUTPUT_CAP)


@dataclass(frozen=True)
class DataRef:
    """A reference to a staged input, resolved to a sandbox-local path BEFORE egress is cut. The provider
    stages it over the control channel (the guest never reaches out for it) and verifies `sha256` AFTER
    staging — the lineage/tamper check that is NEW vs the engine (doc §5-D)."""
    uri: str                 # s3://tenant-<id>/inputs/<sha256>  OR  file://<abs>  (local driver)
    sha256: str
    dest_rel: str            # relative path inside /work; MUST pass pathsafe.safe_join against the base
    size_bytes: int
    ttl_class: str = "ephemeral"   # ephemeral | retained


@dataclass(frozen=True)
class CodeBundle:
    """The code under test. For the local driver, `uri` is file://<base-dir> and the engine runs in place."""
    uri: str
    sha256: str
    entrypoint: str          # contract run.entrypoint, relative; safe_join-checked
    language: str            # python|r|julia|node|shell|c|cpp|rust  (run_hermetic._lang_dispatch set)
    contract_yaml_sha256: str = ""


@dataclass(frozen=True)
class TemplateSpec:
    """A per-language runtime snapshot — the warm-pool key. `prepare()` builds/warms one (templates.id row)."""
    template_id: str         # "python-3.11" | "r-4.4" | "julia-1.11" | ...
    language: str
    image_digest: str = ""   # sha256-pinned base image (T7); "" for host (seatbelt/bwrap) tiers
    provider: str = "local"  # local | e2b | k8s-sandbox | northflank | lambda-microvm


@dataclass(frozen=True)
class RunSpec:
    """One verification execution request. `run_id` is the internal per-attempt anchor (NOT the public
    verification_id; the API maps jobs.id -> verification_id per CANONICAL §2)."""
    run_id: str
    recipe_id: str
    recipe_version: str
    template: TemplateSpec
    bundle: CodeBundle
    data_refs: tuple = ()                          # tuple[DataRef, ...]
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    network: NetworkPolicy = NetworkPolicy.OFF
    trust: str = "untrusted-third-party"           # own-code | untrusted-third-party (run_hermetic._select_backend)
    env_passthrough: tuple = ()                    # whitelisted names only (contract env.passthrough)
    determinism_seed: int = 0


@dataclass(frozen=True)
class ResourceUsage:
    """NEW — the engine produces NONE of this today (doc §5-C). The provider layer fills what it can:
    LocalProvider measures wall_seconds; cpu_seconds/peak_rss_mb need provider/cgroup accounting (M1.x)."""
    cpu_seconds: float | None = None
    peak_rss_mb: float | None = None
    wall_seconds: float | None = None
    exit_signal: int | None = None


@dataclass(frozen=True)
class ArtifactRef:
    """NEW — the engine writes outputs to <base>/runs/ but does not enumerate/hash them (doc §5-E). The
    provider builds this manifest at PULL time, enforcing output_bytes_max + within_cap per file."""
    name: str
    sha256: str
    size_bytes: int
    uri: str = ""            # object-store ref in the hosted path; "" for local


@dataclass(frozen=True)
class RunResult:
    """The uniform result every driver returns. The first block maps 1:1 from the engine run-dict (some
    renamed — doc §5-B: container_present->tier_verified, run_network->network_run); the second block is NEW
    and defaults to empty when the engine did not supply it."""
    run_id: str
    # ---- mapped 1:1 from the engine's run_hermetic.py run-dict ----
    isolation_tier: str              # MUST be in VERIFIED_TIERS for a real run, else REFUSED (exit 3)
    tier_verified: bool              # engine: container_present
    run_exit_status: int             # engine: run_exit_status (raw rc)
    exit_code: int                   # 0 ok / 1 run-fail / 2 contract / 3 refused / 4 timeout
    killed: bool
    network_run: str                 # engine: run_network ("off" only on a verified tier)
    network_install: str             # engine: install_network
    hermeticity: str
    determinism_mode: str            # controlled-to-bit | measured-band | uncontrolled
    determinism_note: str
    language: str = ""
    interpreter: str = ""
    hardening: tuple = ()            # engine: hardening (native tier only)
    stdout_tail: str = ""
    stderr_tail: str = ""
    doctor: dict = field(default_factory=dict)
    reason: str = ""                 # refused / contract-invalid explanation
    phase: str = "run"               # run | refused
    # ---- NEW fields the platform computes host-side (do NOT exist in the engine dict) ----
    artifacts_manifest: tuple = ()   # tuple[ArtifactRef, ...]  (doc §5-E)
    resource_usage: ResourceUsage = field(default_factory=ResourceUsage)   # (doc §5-C)
    determinism_digest: str = ""     # the reproducibility anchor (doc §5-G; M1.6 gate)
