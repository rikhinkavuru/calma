#!/usr/bin/env python
"""calma.spike.runner.isolated_verify — the disposable child that does the heavy verification work.

This is layer 2 of the crash-safety architecture (see runner/supervisor.py): the API never runs the
in-process work (discovery / leakage / diff / artifact reads / E2B orchestration) itself. It spawns THIS
script as a fresh, resource-capped subprocess and only supervises. So when a pathological repo OOMs,
segfaults, or runs away, it kills this child — the API and every other job keep running.

Contract (spoken over three OS channels, no shared memory with the parent):
  • stdin   — one JSON request: {repo_dir, opts, result_path, limits:{as_bytes, cpu_seconds}}
  • stdout  — newline-delimited JSON progress events: {"type":"update"|"log"|"done"|"error", ...}
  • a file  — the final verify_repo() result dict, written to result_path (read by the parent on exit 0)

The child applies its OWN OS resource limits at startup (RLIMIT_CPU, a high RLIMIT_AS backstop) so a
runaway loop or an absurd single allocation dies cleanly even before the parent's RSS monitor notices.
"""
from __future__ import annotations

import json
import os
import sys
import traceback

# Self-locate: this file is spike/runner/isolated_verify.py, so the engine root is two dirs up. Put it (and
# capture/, which sitecustomize lives in) on sys.path so `import pipeline` and friends resolve — the child is
# a bare `python isolated_verify.py`, with none of the server's sys.path priming.
_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_SPIKE, os.path.join(_SPIKE, "capture")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _emit(obj: dict) -> None:
    """Write one progress event as a single JSON line and flush — the parent reads these live."""
    try:
        sys.stdout.write(json.dumps(obj, default=str) + "\n")
        sys.stdout.flush()
    except (BrokenPipeError, ValueError):
        # parent went away / killed us mid-write — nothing we can do, and nothing we need to do.
        pass


def _apply_limits(limits: dict) -> None:
    """Set this process's OWN hard resource limits. Best-effort: the parent's RSS monitor + wall-clock are
    the portable guarantees, so a platform that rejects a given rlimit (macOS is finicky about RLIMIT_AS)
    must not abort the run — it just leans on the parent-side guards instead."""
    try:
        import resource
    except ImportError:  # non-POSIX — rely entirely on the parent supervisor
        return

    cpu = int(limits.get("cpu_seconds") or 0)
    if cpu > 0:
        # SIGXCPU at the soft limit (default action: terminate), SIGKILL a few seconds later at the hard
        # limit if somehow ignored. Catches busy/infinite loops that burn CPU but never touch the wall clock
        # in a way the parent can also see. Counts CPU-seconds across all threads.
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 5))
        except (ValueError, OSError):
            pass

    as_bytes = int(limits.get("as_bytes") or 0)
    if as_bytes > 0 and hasattr(resource, "RLIMIT_AS"):
        # A HIGH virtual-address-space backstop — deliberately not the real memory cap. RLIMIT_AS limits
        # VIRT, not RSS; numpy/OpenBLAS reserve large VIRT arenas, so a tight cap breaks startup or hangs
        # BLAS in an mmap retry loop. Set it well above any legitimate footprint so it only ever catches an
        # absurd single allocation (turning it into a clean MemoryError); the parent's RSS monitor enforces
        # the actual resident-memory budget.
        try:
            resource.setrlimit(resource.RLIMIT_AS, (as_bytes, as_bytes))
        except (ValueError, OSError):
            pass


def _selftest(mode: str) -> None:
    """Fault injection for the supervisor's own tests — gated entirely by CALMA_VERIFY_SELFTEST, which is
    never set in production. Lets the test suite drive every kill path (OOM / hang / crash / CPU) through the
    REAL run_isolated → child → supervisor machinery, deterministically, without a contrived malicious repo.
    """
    if not mode:
        return
    if mode == "memory":
        hog = []
        while True:                                   # steady leak until the parent's RSS monitor kills us
            hog.append(bytearray(16 * 1024 * 1024))
            __import__("time").sleep(0.01)
    elif mode == "hang":
        __import__("time").sleep(99999)               # burns no CPU → only the wall-clock can stop it
    elif mode == "cpu":
        while True:                                   # burns CPU → RLIMIT_CPU stops it under a long wall clock
            pass
    elif mode == "crash":
        import ctypes
        ctypes.string_at(0)                           # SIGSEGV — a native crash, as from a bad C extension


def main() -> int:
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError) as e:
        _emit({"type": "error", "error": "bad request to isolated child: %s" % e})
        return 2

    _apply_limits(req.get("limits") or {})
    _selftest(os.environ.get("CALMA_VERIFY_SELFTEST", ""))

    repo_dir = req.get("repo_dir")
    result_path = req.get("result_path")
    opts_dict = req.get("opts") or {}

    try:
        # Import the engine only AFTER limits are set, so even the (heavy) numpy/sklearn import is bounded —
        # and inside the guard, so an import/construction failure becomes a structured error, not a bare crash.
        import dataclasses

        import pipeline as PIPE

        fields = {f.name for f in dataclasses.fields(PIPE.VerifyOptions)}
        opts = PIPE.VerifyOptions(**{k: v for k, v in opts_dict.items() if k in fields})
        result = PIPE.verify_repo(
            repo_dir,
            opts,
            update=lambda **kw: _emit({"type": "update", "kw": kw}),
            log=lambda msg: _emit({"type": "log", "msg": str(msg)}),
        )
    except MemoryError:
        # The RLIMIT_AS backstop (or a genuine allocation failure) fired — report it as a clean budget
        # outcome, not a crash. The parent's RSS monitor usually beats us to it; this covers the single
        # huge-allocation case the monitor's poll interval could miss.
        _emit({"type": "error", "error": "out of memory (the verification exceeded its memory budget)",
               "kind": "memory"})
        return 4
    except BaseException as e:  # noqa: BLE001 — the whole point is to never let anything escape uncontained
        _emit({"type": "error", "error": "%s: %s" % (type(e).__name__, str(e)[:300]),
               "kind": "error", "traceback": traceback.format_exc()[-1200:]})
        return 3

    # Hand the full result back over the file channel (robust for large results — hundreds of claims — vs.
    # one giant stdout line), then signal completion on the event stream.
    try:
        with open(result_path, "w") as fh:
            json.dump(result, fh, default=str)
    except OSError as e:
        _emit({"type": "error", "error": "could not write result: %s" % e, "kind": "error"})
        return 5
    _emit({"type": "done"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
