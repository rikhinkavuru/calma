"""calma.spike.runner.supervisor — process-isolation supervisor: run verify_repo so it can NEVER crash the API.

The architectural guarantee behind "connect any repo, the backend stays up":

    server.run_job  ──spawn──▶  isolated_verify.py (child, OS-resource-capped)
         (supervises only)         └─ does ALL heavy work: discovery / leakage / diff / E2B orchestration

The API process does no heavy work, so nothing a repo does in that work can crash it. The child runs under
hard OS limits and a parent-side watchdog; the worst case is ONE job ending cleanly as "exceeded budget"
while the API and every other job keep running. This is the only design that delivers the property — capping
individual operations can't, because the next repo finds a new way to allocate too much.

Independent guards, layered so each covers the others' blind spots:
  1. RSS monitor (here, parent)   — polls the child's RESIDENT memory; kills before the cgroup OOM-killer can
                                     fire (which on a small box could otherwise take the whole machine). RSS,
                                     not virtual size, is what actually OOMs — so RSS is what we watch.
  2. Wall-clock deadline (here)   — kills hangs / sleeps / blocked I/O that burn no CPU.
  3. RLIMIT_CPU (child)           — kills busy/infinite loops that burn CPU under a generous wall clock.
  4. RLIMIT_AS backstop (child)   — turns an absurd single allocation into a clean MemoryError instantly.
  5. Concurrency gate (here)      — bounds how many children run at once so N legit jobs can't co-OOM the box;
                                     the per-child cap only protects against ONE runaway.
  + a result-size cap on what the parent loads back, so even the final hand-off can't OOM the supervisor.

The child is launched in its own session (start_new_session) so a kill takes down the WHOLE process tree —
any grandchildren (a stuck local subprocess, a fork-bomb) die with it. Progress (stage/log) streams back as
NDJSON so the live UI is unchanged; the final result returns over a temp file.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable

_CHILD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "isolated_verify.py")
_MAX_RESULT_BYTES = 128 * 1024 * 1024   # cap the result the parent will load back — keeps the supervisor bounded


class BudgetExceeded(Exception):
    """The verification was killed or failed inside its isolated child. Carries a UI-friendly kind/detail so
    the server can show WHY (out of memory / timed out / crashed) instead of a generic error — while the API
    itself stays perfectly healthy."""

    def __init__(self, kind: str, message: str, detail: str = ""):
        super().__init__(message)
        self.kind = kind          # "memory" | "timeout" | "cpu" | "crashed" | "error"
        self.detail = detail      # captured stderr tail / traceback, for logs


# ── resource-budget sizing ────────────────────────────────────────────────────────────────────────────────

def _cgroup_total_mb() -> int | None:
    """Total memory the container is allowed (cgroup v2 memory.max, then v1), in MB. None if not containerized
    (e.g. local macOS dev) — then we fall back to a fixed default."""
    for path in ("/sys/fs/cgroup/memory.max",                       # cgroup v2
                 "/sys/fs/cgroup/memory/memory.limit_in_bytes"):    # cgroup v1
        try:
            raw = open(path).read().strip()
        except OSError:
            continue
        if raw and raw != "max":
            try:
                val = int(raw)
            except ValueError:
                continue
            # v1 reports a sentinel ~2^63 when unlimited; ignore absurd values.
            if 0 < val < (1 << 62):
                return val // (1024 * 1024)
    return None


# The memory model is intentionally coherent with the concurrency model: pick how many children may run at
# once, then split the container's available memory evenly among them. That guarantees (concurrency × cap +
# reserve) ≤ total, so N legitimate jobs can't co-OOM the box. Reserve is generous: the API process itself is
# tiny (~50 MB — numpy/sklearn are lazy and never load in it), so most of the container is free for children.
_RESERVE_MB = 300          # parent API + OS + the brief overshoot a fast allocator reaches between RSS polls
_MIN_CHILD_MB = 450        # a per-child floor: the scientific-stack import (~165 MB) + bounded work + margin
_MAX_CONCURRENCY = 8       # never fan out beyond this regardless of box size


def _avail_mb(total: int) -> int:
    return max(_MIN_CHILD_MB, total - _RESERVE_MB)


def _concurrency() -> int:
    """How many isolated children may run at once. Explicit env wins; else as many as fit at the per-child
    floor — 1 on the 1 GB deploy (jobs queue), more on a bigger box."""
    n = (os.environ.get("CALMA_VERIFY_CONCURRENCY") or "").strip()
    if n:
        try:
            return max(1, int(n))
        except ValueError:
            pass
    total = _cgroup_total_mb()
    if total:
        return max(1, min(_MAX_CONCURRENCY, _avail_mb(total) // _MIN_CHILD_MB))
    return 2  # uncontained dev default — modest parallelism, never unbounded


def _mem_budget_mb() -> int:
    """The child's resident-memory budget. Explicit env wins; else the container's available memory split
    evenly across the concurrency limit, so the child is killed with headroom left for the parent + OS BEFORE
    the cgroup OOM-killer can fire."""
    env = (os.environ.get("CALMA_VERIFY_MEM_MB") or "").strip()
    if env:
        try:
            return max(128, int(env))
        except ValueError:
            pass
    total = _cgroup_total_mb()
    if total:
        return _avail_mb(total) // _concurrency()   # cap × concurrency ≈ available → collectively bounded
    return 700  # uncontained dev default


def _limits(opts) -> dict:
    """The OS limits handed to the child. Memory (RSS) is enforced by the parent monitor; here we compute the
    child-side CPU limit and a HIGH virtual-address backstop (see isolated_verify._apply_limits)."""
    mem_mb = _mem_budget_mb()
    cpu = _int_env("CALMA_VERIFY_CPU_SECONDS", getattr(opts, "timeout", 600) + 120)
    # RLIMIT_AS is a backstop for absurd single allocations, NOT the real cap — keep it well above any
    # legitimate VIRT footprint (numpy/BLAS reserve a lot) so it never breaks startup or stalls BLAS.
    as_mb = _int_env("CALMA_VERIFY_AS_MB", max(4096, mem_mb * 5))
    return {"mem_mb": mem_mb, "cpu_seconds": cpu,
            "as_bytes": as_mb * 1024 * 1024 if as_mb > 0 else 0}


def _int_env(name: str, default: int) -> int:
    v = (os.environ.get(name) or "").strip()
    if v:
        try:
            return int(v)
        except ValueError:
            pass
    return default


# The concurrency gate (sized by _concurrency above): a job beyond the limit queues on this semaphore rather
# than spawning a child that could push total memory past the container. Bounded once at import — the deploy's
# memory/CPU are fixed at process start.
_GATE = threading.Semaphore(_concurrency())


# ── resident-memory probe (portable: /proc on Linux, ps on macOS) ───────────────────────────────────────────

def _rss_mb(pid: int) -> float | None:
    """Resident set size of `pid` in MB, or None if it can't be read. Linux: /proc/<pid>/status VmRSS (fast,
    no fork). macOS/BSD: `ps -o rss=` (KB). RSS — real committed pages — is what the OOM-killer accounts, so
    it's the right thing to bound, unlike RLIMIT_AS's virtual size."""
    try:
        with open("/proc/%d/status" % pid) as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0   # kB → MB
    except OSError:
        pass
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=2)
        s = out.stdout.strip()
        if s:
            return int(s.split()[0]) / 1024.0              # kB → MB
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


# ── the supervisor ──────────────────────────────────────────────────────────────────────────────────────────

def run_isolated(
    repo_dir: str,
    opts,
    *,
    update: Callable[..., None] | None = None,
    log: Callable[[str], None] | None = None,
    wall_seconds: int | None = None,
) -> dict:
    """Run verify_repo(repo_dir, opts) in a disposable resource-capped child and return its result dict.

    Streams progress through `update`/`log` exactly as the in-process path does. Raises BudgetExceeded if the
    child is killed (memory / wall-clock / CPU) or dies (crash / internal error) — the caller turns that into
    a clean per-job error. This function never lets the failure propagate as a process-killing event: the API
    is the supervisor, and supervisors don't share the fate of what they supervise.
    """
    limits = _limits(opts)
    mem_cap = limits["mem_mb"]
    wall = wall_seconds or _int_env("CALMA_VERIFY_WALL_SECONDS", getattr(opts, "timeout", 600) + 300)

    import dataclasses
    opts_dict = dataclasses.asdict(opts) if dataclasses.is_dataclass(opts) else dict(opts)

    rf = tempfile.NamedTemporaryFile(prefix="calma_result_", suffix=".json", delete=False)
    result_path = rf.name
    rf.close()
    request = json.dumps({"repo_dir": repo_dir, "opts": opts_dict, "result_path": result_path,
                          "limits": {"as_bytes": limits["as_bytes"], "cpu_seconds": limits["cpu_seconds"]}})

    # Bound concurrent children so they collectively fit the container (see _GATE). A job beyond the limit
    # queues here rather than risk a co-OOM that would defeat the whole point of isolating it.
    if not _GATE.acquire(blocking=False):
        if log:
            log("waiting for an isolation slot (concurrency limit reached)")
        _GATE.acquire()

    proc = None
    try:
        if log:
            log("isolating verification in a resource-capped child (mem≤%dMB, cpu≤%ds, wall≤%ds)"
                % (mem_cap, limits["cpu_seconds"], wall))

        # Fresh subprocess (not a fork): no inherited locks/threads from the API event loop, clean memory,
        # true isolation. start_new_session puts it in its own process group so a kill takes the whole tree.
        proc = subprocess.Popen(
            [sys.executable, _CHILD],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=_spike_dir(), env=_child_env(), start_new_session=True,
        )
        try:
            proc.stdin.write(request)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

        state = {"error": None, "done": False, "stderr": ""}
        t_out = threading.Thread(target=_drain_events, args=(proc.stdout, update, log, state), daemon=True)
        t_err = threading.Thread(target=_drain_stderr, args=(proc.stderr, state), daemon=True)
        t_out.start()
        t_err.start()

        killed = _supervise(proc, mem_cap, wall, log)

        # Let the drain threads flush the last events / the error payload (the child may have emitted an error
        # line just before exiting); bounded join so a wedged pipe can't hang the supervisor.
        t_out.join(timeout=5)
        t_err.join(timeout=5)
        rc = proc.returncode if proc.returncode is not None else proc.poll()

        if killed:
            raise _killed_error(killed, mem_cap, wall, state["stderr"])
        if state["error"]:
            e = state["error"]
            raise BudgetExceeded(e.get("kind", "error"),
                                 _friendly(e.get("kind", "error"), e.get("error", "verification failed")),
                                 e.get("traceback") or state["stderr"])
        if rc not in (0, None):
            raise _exit_error(rc, mem_cap, state["stderr"])
        # The parent's last unbounded step is loading the child's result — guard it, or a pathological repo
        # that produced a giant result could OOM the SUPERVISOR (the discovery bounds make this never trigger
        # in practice; this closes the theoretical hole so the parent's memory stays bounded no matter what).
        try:
            if os.path.getsize(result_path) > _MAX_RESULT_BYTES:
                raise BudgetExceeded("error", "the verification produced an oversized result and was rejected")
        except OSError:
            pass
        result = _load_result(result_path)
        if result is None:
            raise BudgetExceeded("crashed", "the verification ended without producing a result",
                                 state["stderr"])
        return result
    finally:
        if proc is not None:
            _reap(proc)
        try:
            os.remove(result_path)
        except OSError:
            pass
        _GATE.release()


def _supervise(proc, mem_cap: int, wall: int, log) -> str | None:
    """The watchdog loop. Every ~50 ms, checks child liveness + resident memory + the wall clock. Returns the
    kill reason ("memory"/"timeout") if WE killed it, or None if it exited on its own. RSS is read every
    iteration — on Linux that's a near-free /proc read — so even a fast allocator is caught within one tick,
    keeping the overshoot small enough that the kill lands before the cgroup OOM-killer would fire."""
    deadline = time.monotonic() + wall
    while True:
        if proc.poll() is not None:
            return None                              # child exited on its own (success or its own failure)
        rss = _rss_mb(proc.pid)
        if rss is not None and rss > mem_cap:
            if log:
                log("memory budget exceeded (%.0fMB > %dMB) — killing the isolated job" % (rss, mem_cap))
            _kill_tree(proc)
            return "memory"
        if time.monotonic() > deadline:
            if log:
                log("wall-clock budget exceeded (%ds) — killing the isolated job" % wall)
            _kill_tree(proc)
            return "timeout"
        time.sleep(0.05)


def _drain_events(stream, update, log, state: dict) -> None:
    """Read the child's NDJSON progress stream and replay it onto the parent's update/log callbacks, so the
    job's stage/log timeline looks identical to the in-process path. Tolerant of any non-JSON noise a library
    might print to stdout — only well-formed typed events are acted on."""
    if stream is None:
        return
    for line in stream:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue                                  # stray library print — ignore, never let it corrupt state
        if not isinstance(ev, dict):
            continue
        kind = ev.get("type")
        if kind == "update" and update:
            try:
                update(**(ev.get("kw") or {}))
            except Exception:  # noqa: BLE001 — a bad callback must not kill the drain thread
                pass
        elif kind == "log" and log:
            try:
                log(ev.get("msg", ""))
            except Exception:  # noqa: BLE001
                pass
        elif kind == "done":
            state["done"] = True
        elif kind == "error":
            state["error"] = ev


def _drain_stderr(stream, state: dict) -> None:
    """Keep the child's stderr pipe drained (so a chatty child can't deadlock on a full buffer) and retain the
    tail for crash diagnostics — the last lines are what explain a segfault we otherwise have no event for."""
    if stream is None:
        return
    buf: list[str] = []
    size = 0
    for line in stream:
        buf.append(line)
        size += len(line)
        while size > 16384 and len(buf) > 1:          # bounded ring: keep ~16 KB of the most recent stderr
            size -= len(buf.pop(0))
    state["stderr"] = ("".join(buf))[-16384:]


# ── failure classification → UI-friendly BudgetExceeded ─────────────────────────────────────────────────────

def _killed_error(reason: str, mem_cap: int, wall: int, stderr: str) -> BudgetExceeded:
    if reason == "memory":
        return BudgetExceeded("memory",
                              "exceeded the memory budget (>%dMB) and was stopped — the API stayed up" % mem_cap,
                              stderr)
    return BudgetExceeded("timeout",
                          "exceeded the time budget (>%ds) and was stopped — the API stayed up" % wall, stderr)


def _exit_error(rc: int, mem_cap: int, stderr: str) -> BudgetExceeded:
    """The child exited on its own with a non-zero code — most importantly a fatal SIGNAL (negative rc on
    POSIX), which is how an OOM-kill (SIGKILL), a segfault (SIGSEGV), or a CPU-limit (SIGXCPU) surface."""
    if rc < 0:
        sig = -rc
        name = signal.Signals(sig).name if sig in {s.value for s in signal.Signals} else "signal %d" % sig
        if sig == signal.SIGXCPU:
            return BudgetExceeded("cpu", "exceeded the CPU budget and was stopped — the API stayed up", stderr)
        if sig in (signal.SIGKILL, getattr(signal, "SIGABRT", 6)):
            # SIGKILL we didn't send ≈ the container OOM-killer reaped the child (RSS spiked between polls).
            # Either way the child absorbed it; the parent is fine.
            return BudgetExceeded("memory",
                                  "the verification was killed (%s) — likely out of memory; the API stayed up"
                                  % name, stderr)
        return BudgetExceeded("crashed",
                              "the verification crashed (%s) — the API stayed up" % name, stderr)
    return BudgetExceeded("error", "the verification failed (exit %d) — the API stayed up" % rc, stderr)


def _friendly(kind: str, msg: str) -> str:
    if kind == "memory":
        return "exceeded the memory budget — " + msg
    return msg


# ── process lifecycle helpers ───────────────────────────────────────────────────────────────────────────────

def _kill_tree(proc) -> None:
    """SIGKILL the child's whole process group — child + any grandchildren it spawned — so nothing is left
    behind. Falls back to killing just the child if the group send isn't available."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def _reap(proc) -> None:
    """Ensure the child is dead and reaped (no zombie), even on the success path."""
    if proc.poll() is None:
        _kill_tree(proc)
    try:
        proc.wait(timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        pass
    for s in (proc.stdin, proc.stdout, proc.stderr):
        try:
            if s and not s.closed:
                s.close()
        except OSError:
            pass


def _load_result(path: str) -> dict | None:
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _spike_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _child_env() -> dict:
    """The child inherits the parent's env (E2B/Exa keys, gh auth) and gets the same PYTHONPATH priming the
    server uses, so `import pipeline`/`capture` resolve regardless of where uvicorn was launched from."""
    env = dict(os.environ)
    spike = _spike_dir()
    extra = os.pathsep.join([spike, os.path.join(spike, "capture")])
    env["PYTHONPATH"] = extra + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env
