"""calma.spike.runner.rr_runner — determinism escalation (feature 20): the shim tier + rr record/replay.

Two tiers, cheap-first:
  * SHIM (the 80%): SOURCE_DATE_EPOCH + PYTHONHASHSEED + TZ + single-core — the DebuggAI/libfate 80/20 of rr.
    Rescues most clock/urandom/hash NON-DETERMINISTICs with NONE of rr's constraints. Only REMOVES noise, same
    category as enforced_env — it can turn a spurious NON-DETERMINISTIC clean, never manufacture agreement.
  * rr (the escalation, narrow reach): records all non-deterministic inputs once, replays bit-for-bit — a
    determinism proof stronger than k=N sampling. Linux/x86 or Apple-M, single-core, needs HW perf counters
    (may be absent inside Firecracker), so it is gated + graceful.

FCR-safe: replay proving determinism gates CONFIRMED ONLY in conjunction with the independent recompute (it
substitutes for the empirical k≥2 check exactly where static-proof-of-construction already does today), never
alone — replay answers "does this run repeat?", not "is the number right?". If record OR replay fails, or a
syscall is unsupported, or perf counters are unavailable → fall through to the existing k≥2 path (one wasted
attempt, never a false confirm).
"""
from __future__ import annotations

import shutil

from core import determinism as DET


def rr_available() -> bool:
    return shutil.which("rr") is not None


def shim_env(base_env: dict | None = None) -> dict:
    """The shim-tier determinism env: enforced_env(shim=True) (adds SOURCE_DATE_EPOCH) merged over `base_env`.
    Set OMP/MKL single-thread too, so thread-reduction wobble is removed for the characterization run."""
    env = dict(base_env or {})
    env.update(DET.enforced_env(shim=True))
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("MKL_NUM_THREADS", "1")
    return env


def run_rr(repo_dir, entry=None, *, k=1, log=None, **_kw):
    """Attempt an rr record→replay. Returns {replay_proven, available, reason}. If rr / perf counters are
    unavailable, `available=False` and the caller falls through to the empirical k≥2 path (fail-closed)."""
    if not rr_available():
        return {"replay_proven": False, "available": False,
                "reason": "rr not installed — escalation skipped, using the empirical k≥2 determinism check"}
    # rr record/replay wiring is the escalation (needs virtualized HW perf counters in the sandbox). Behind the
    # availability gate so CI without rr stays green; until provisioned, we do NOT claim replay_proven (so the
    # verdict keeps the k≥2 check — fail-closed, never a false CONFIRM).
    return {"replay_proven": False, "available": True,
            "reason": "rr present but the perf-counter-virtualized replay tier is not provisioned here"}
