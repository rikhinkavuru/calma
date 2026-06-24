"""execprovider.local_driver — LocalProvider: the REFERENCE ExecutionProvider, fully wired to run_hermetic.py.

This is not a mock. run_hermetic.run(contract, base, isolation=tier) is ALREADY the multi-tier in-process
executor (_select_backend + the seatbelt/bwrap/docker/e2b dispatch), so LocalProvider is a thin typed adapter
that (a) builds the minimal contract the engine loads, (b) calls the real executor, (c) maps the run-dict to
RunResult, and (d) computes the NEW host-side fields the engine doesn't (artifacts_manifest + determinism_digest
+ a measured wall_seconds) — demonstrating those fields ARE computable from what the engine already produces.

`isolation`: "auto" (this OS's own-code tier) | "seatbelt" | "bwrap" | "docker" | "e2b". The e2b value drives
the engine's cold-boot Firecracker backend; warm-pool prepare()/snapshots are the M1.2 build (doc §5-H).

Design doc: docs/internal/W1-execution-platform-foundation.md (§3.4, §4). PURE STDLIB.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time

from .base import PreparedTemplate, from_engine_result, refused, _engine
from .valuetypes import (ArtifactRef, CodeBundle, ResourceLimits, ResourceUsage, RunSpec,
                         TemplateSpec)

# the determinism-controlling env the engine pins for every re-execution (run_hermetic.py:1627-1628 /
# _docker_env). The digest folds these in so a recipe's reproducibility anchor reflects the pinned context.
_DETERMINISM_ENV = (("PYTHONHASHSEED", "0"), ("TZ", "UTC"), ("LC_ALL", "C.UTF-8"),
                    ("PYTHONDONTWRITEBYTECODE", "1"))

_NAME = {"auto": "local-auto", "seatbelt": "local-seatbelt", "bwrap": "local-bwrap",
         "docker": "local-docker", "e2b": "e2b"}


def _base_from_uri(uri: str) -> str:
    """Resolve a local bundle uri to a base dir. Accepts file://<abs> or a bare path."""
    if uri.startswith("file://"):
        uri = uri[len("file://"):]
    return os.path.realpath(uri)


def _sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def _build_manifest(out_dir: str, limits: ResourceLimits):
    """Enumerate + hash the artifacts the run produced under <base>/runs, enforcing the pull-time caps
    (within_cap per file + output_bytes_max in total). NEW vs the engine (doc §5-E). Returns
    (manifest_tuple, total_bytes, over_cap_bool). Skips non-regular files / FIFOs (within_cap refuses them)."""
    H = _engine()
    try:
        from pathsafe import within_cap  # the SAME guard the host recompute uses
    except Exception:  # pragma: no cover
        within_cap = lambda p, mb=None: os.path.isfile(p)  # noqa: E731 (degraded fallback)
    refs = []
    total = 0
    over = False
    if not os.path.isdir(out_dir):
        return (), 0, False
    for root, _dirs, names in sorted(os.walk(out_dir)):
        for n in sorted(names):
            p = os.path.join(root, n)
            if not within_cap(p):           # missing / dir / FIFO / over the per-file cap -> skip
                if os.path.isfile(p):
                    over = True              # a real file that blew the per-file cap
                continue
            size = os.path.getsize(p)
            if total + size > limits.output_bytes_max:
                over = True
                break
            total += size
            rel = os.path.relpath(p, out_dir)
            refs.append(ArtifactRef(name=rel, sha256=_sha256_file(p), size_bytes=size))
    return tuple(refs), total, over


def _determinism_digest(manifest, run_exit_status: int, seed: int) -> str:
    """sha256 over the canonicalized {sorted artifact (name,sha256)} + run_exit_status + pinned determinism
    env + seed (doc §3.2/§5-G). Two runs of one RunSpec on a controlled-to-bit recipe MUST match here."""
    canon = {
        "artifacts": sorted([[a.name, a.sha256] for a in manifest]),
        "run_exit_status": run_exit_status,
        "determinism_env": [list(kv) for kv in _DETERMINISM_ENV],
        "seed": seed,
    }
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


class LocalProvider:
    """The reference ExecutionProvider over the in-process engine. Conformant to the ExecutionProvider
    Protocol (verified by _selfcheck via isinstance)."""

    def __init__(self, isolation: str = "auto"):
        if isolation not in _NAME:
            raise ValueError("isolation must be one of %s" % ", ".join(_NAME))
        self.isolation = isolation
        self.name = _NAME[isolation]

    # --- the engine isolation key (None == auto) the executor expects ---
    def _iso(self):
        return None if self.isolation == "auto" else self.isolation

    def available(self):
        """(usable, reason). Generalizes the engine's per-tier availability checks. `auto` is always usable
        (the host has SOME tier; the doctor decides whether it VERIFIES)."""
        H = _engine()
        if self.isolation == "seatbelt":
            ok = H._have_sandbox_exec()
            return ok, "" if ok else "sandbox-exec (Seatbelt) not present at /usr/bin/sandbox-exec"
        if self.isolation == "bwrap":
            ok = H._have_bwrap()
            return ok, "" if ok else "bwrap (bubblewrap) not found on PATH"
        if self.isolation == "docker":
            return H._docker_available()
        if self.isolation == "e2b":
            try:
                cfg, missing = H._e2b_config()
            except Exception as e:
                return False, "e2b config unreadable: %s" % e
            return (not missing), ("" if not missing else H._e2b_missing_msg(missing))
        return True, ""  # auto

    def prepare(self, template: TemplateSpec) -> PreparedTemplate:
        """Near-no-op for local tiers (the engine boots cold per run — doc §5-H). Pins the isolation + image
        digest; the per-run base comes from the RunSpec at run() time. A fresh temp dir is the probe context
        for a standalone doctor() floor-check."""
        return PreparedTemplate(template=template, base=tempfile.mkdtemp(prefix="calma_prep_"),
                                isolation=self._iso(), image_digest=template.image_digest)

    def doctor(self, prepared: PreparedTemplate) -> dict:
        """Standalone positive-control floor-check against prepared.base. Delegates to the engine's tier
        doctor (the SAME probe the run uses). For untrusted code the run path additionally re-checks."""
        H = _engine()
        base = prepared.base or os.getcwd()
        iso = prepared.isolation
        if iso == "docker":
            return H.docker_doctor(base)
        if iso == "e2b":
            return H.e2b_doctor(base)
        if iso == "bwrap":
            return H.bwrap_doctor(base)
        if iso == "seatbelt":
            return H.doctor(base)
        return H.native_doctor(base)  # auto: this OS's own-code tier

    def run(self, spec: RunSpec, prepared: PreparedTemplate):
        """Drive the real executor end-to-end. The engine's run() runs its own doctor against the run base
        before executing (run_hermetic.py:1584 et al), so the network-off gate fires per run. Recompute does
        NOT happen here — the worker does it host-side over `artifacts_manifest` (the invariant)."""
        H = _engine()
        base = _base_from_uri(spec.bundle.uri)
        # path containment: the contract entrypoint is untrusted input (pathsafe.safe_join) — refuse on escape.
        try:
            from pathsafe import safe_join
            safe_join(base, spec.bundle.entrypoint)
        except Exception as e:
            return refused(spec.run_id, "entrypoint escapes the bundle base: %s" % e, exit_code=2)

        contract = {
            "run": {"entrypoint": spec.bundle.entrypoint, "network": spec.network.value},
            "env": {"trust": spec.trust, "passthrough": list(spec.env_passthrough)},
            "artifacts": [], "metrics": [],
        }
        cf = tempfile.NamedTemporaryFile("w", suffix=".verify.json", delete=False)
        json.dump(contract, cf)
        cf.close()
        try:
            t0 = time.monotonic()
            eng = H.run(cf.name, base=base, timeout=spec.limits.wall_seconds,
                        trust_override=spec.trust, isolation=self._iso())
            wall = time.monotonic() - t0
        finally:
            try:
                os.unlink(cf.name)
            except OSError:
                pass

        # NEW host-side fields (doc §5-C/E/G), computed from what the engine produced.
        out_dir = os.path.join(base, "runs")
        manifest, _total, over = _build_manifest(out_dir, spec.limits)
        digest = _determinism_digest(manifest, int(eng.get("run_exit_status", -1) or -1),
                                     spec.determinism_seed)
        usage = ResourceUsage(wall_seconds=round(wall, 3))   # cpu/rss need cgroup accounting (M1.x)
        res = from_engine_result(spec.run_id, eng, artifacts_manifest=manifest,
                                 resource_usage=usage, determinism_digest=digest)
        if over and res.phase != "refused":
            # honest annotation: an artifact exceeded the pull cap (the host would not retrieve it whole)
            res = from_engine_result(
                spec.run_id, dict(eng, determinism_note=(eng.get("determinism_note", "") +
                    " [artifact exceeded output_bytes_max; truncated from manifest]").strip()),
                artifacts_manifest=manifest, resource_usage=usage, determinism_digest=digest)
        return res

    def teardown(self, prepared: PreparedTemplate) -> None:
        """The engine kills per-run (docker --rm / sbx.kill() / process-group SIGKILL), so there is no live
        sandbox to release here. We only clean the prepare() probe-context temp dir. NEVER reuse across
        tenants — for the hosted warm-pool drivers this is where the kill+clean-snapshot-replenish happens."""
        try:
            import shutil
            if prepared.base and prepared.base.startswith(tempfile.gettempdir()):
                shutil.rmtree(prepared.base, ignore_errors=True)
        except Exception:
            pass
