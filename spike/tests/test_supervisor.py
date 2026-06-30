"""Process-isolation supervisor: prove the API can never share the fate of a pathological repo.

These tests exercise the real machinery — a fresh child subprocess, the RSS watchdog, OS resource limits,
process-group kills, and crash classification — not mocks. The load-bearing assertion is test_parent_survives:
after a child is OOM-killed, the supervisor runs the very next job to a correct result. That is the guarantee.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from runner import supervisor as SUP
import pipeline as PIPE


def _fixture_repo(tmp_path, claim="accuracy = 0.93"):
    (tmp_path / "README.md").write_text("# Demo\nWe report %s on the held-out set.\n" % claim)
    return str(tmp_path)


# ── end-to-end: the isolated path returns the same result the in-process path would ──────────────────────────

def test_isolated_happy_path_returns_result_and_streams_progress(tmp_path):
    repo = _fixture_repo(tmp_path)
    events = []
    res = SUP.run_isolated(repo, PIPE.VerifyOptions(deep=False, discover=True),
                           update=lambda **kw: events.append(("update", kw)),
                           log=lambda m: events.append(("log", m)))
    assert res["n_claims"] == 1
    assert res["counts"].get("DISCOVERED") == 1
    assert res["claims"][0]["metric"] == "accuracy"
    assert float(res["claims"][0]["claimed"]) == pytest.approx(0.93)
    # progress streamed over the pipe, so the live UI is identical to the in-process path
    stages = [kw.get("stage") for k, kw in events if k == "update"]
    assert "discovering" in stages and "done" in stages


def test_isolated_result_matches_in_process(tmp_path):
    """Isolation must be transparent: same verdicts/counts/values as calling verify_repo directly — the JSON
    round-trip through the child must not alter the result."""
    repo = _fixture_repo(tmp_path, claim="accuracy = 0.81")
    direct = PIPE.verify_repo(repo, PIPE.VerifyOptions(deep=False, discover=True))
    isolated = SUP.run_isolated(repo, PIPE.VerifyOptions(deep=False, discover=True))
    assert isolated["counts"] == direct["counts"]
    assert isolated["n_claims"] == direct["n_claims"]
    assert {(c["metric"], c["claimed"], c["verdict"]) for c in isolated["claims"]} == \
           {(c["metric"], c["claimed"], c["verdict"]) for c in direct["claims"]}


# ── the four guards, end-to-end through run_isolated (fault-injected child, real supervisor path) ────────────

def test_memory_budget_kills_child_not_api(tmp_path, monkeypatch):
    """A child whose work grows past its memory budget is killed and surfaced as a clean memory
    BudgetExceeded — never a crash of the supervising process. Exercises the full spawn → RSS-monitor →
    killpg → contain path through the real production code."""
    monkeypatch.setenv("CALMA_VERIFY_SELFTEST", "memory")
    monkeypatch.setenv("CALMA_VERIFY_MEM_MB", "300")
    with pytest.raises(SUP.BudgetExceeded) as ei:
        SUP.run_isolated(_fixture_repo(tmp_path), PIPE.VerifyOptions(deep=False))
    assert ei.value.kind == "memory"


def test_wall_clock_budget_times_out_endtoend(tmp_path, monkeypatch):
    """A hang that burns no CPU is stopped by the parent-side wall clock — end to end through run_isolated."""
    monkeypatch.setenv("CALMA_VERIFY_SELFTEST", "hang")
    with pytest.raises(SUP.BudgetExceeded) as ei:
        SUP.run_isolated(_fixture_repo(tmp_path), PIPE.VerifyOptions(deep=False), wall_seconds=1)
    assert ei.value.kind == "timeout"


def test_cpu_budget_stops_busy_loop_endtoend(tmp_path, monkeypatch):
    """An infinite busy loop under a generous wall clock is stopped by RLIMIT_CPU in the child."""
    monkeypatch.setenv("CALMA_VERIFY_SELFTEST", "cpu")
    monkeypatch.setenv("CALMA_VERIFY_CPU_SECONDS", "1")
    with pytest.raises(SUP.BudgetExceeded) as ei:
        SUP.run_isolated(_fixture_repo(tmp_path), PIPE.VerifyOptions(deep=False), wall_seconds=20)
    assert ei.value.kind == "cpu"


def test_native_crash_contained_endtoend(tmp_path, monkeypatch):
    """A native segfault in the child is caught and classified as 'crashed', not propagated."""
    monkeypatch.setenv("CALMA_VERIFY_SELFTEST", "crash")
    with pytest.raises(SUP.BudgetExceeded) as ei:
        SUP.run_isolated(_fixture_repo(tmp_path), PIPE.VerifyOptions(deep=False), wall_seconds=20)
    assert ei.value.kind == "crashed"


def test_wall_clock_kills_hung_subprocess():
    """Unit-level: a hang that burns no CPU is stopped by the parent-side wall clock, leaving no leak."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(999)"], start_new_session=True)
    reason = SUP._supervise(p, mem_cap=4096, wall=1, log=None)
    SUP._reap(p)
    assert reason == "timeout"
    assert p.poll() is not None                      # the hung process is dead, not leaked


def test_rss_monitor_catches_gradual_growth():
    """The monitor must catch a steady leak (not just one huge alloc), and kill the whole tree."""
    bomb = "x=[]\nimport time\nwhile True:\n    x.append(bytearray(16*1024*1024)); time.sleep(0.01)\n"
    p = subprocess.Popen([sys.executable, "-c", bomb], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    reason = SUP._supervise(p, mem_cap=200, wall=30, log=None)
    SUP._reap(p)
    assert reason == "memory"
    assert p.poll() is not None


# ── crash classification: every way a child can die maps to a precise, friendly reason ──────────────────────

@pytest.mark.parametrize("rc,expect_kind", [
    (-11, "crashed"),                                 # SIGSEGV — a segfault in a C extension
    (-9, "memory"),                                   # SIGKILL we didn't send ≈ container OOM-killer
    (1, "error"),                                     # ordinary non-zero exit
])
def test_exit_classification(rc, expect_kind):
    err = SUP._exit_error(rc, mem_cap=700, stderr="boom")
    assert isinstance(err, SUP.BudgetExceeded)
    assert err.kind == expect_kind


def test_sigxcpu_classified_as_cpu():
    import signal
    err = SUP._exit_error(-signal.SIGXCPU, mem_cap=700, stderr="")
    assert err.kind == "cpu"


def test_real_segfault_is_contained(tmp_path):
    """A genuine segfaulting child is caught and classified, not propagated."""
    p = subprocess.Popen([sys.executable, "-c", "import ctypes; ctypes.string_at(0)"],
                         start_new_session=True, stderr=subprocess.DEVNULL)
    p.wait()
    err = SUP._exit_error(p.returncode, mem_cap=700, stderr="")
    assert err.kind == "crashed"


# ── THE GUARANTEE: a killed child does not take the supervisor down ─────────────────────────────────────────

def test_parent_survives_and_serves_next_job(tmp_path, monkeypatch):
    """The property the whole architecture exists for: kill a job by OOM, then immediately verify another
    repo to a correct result in the SAME process. No shared fate."""
    bomb_repo = _fixture_repo(tmp_path)
    monkeypatch.setenv("CALMA_VERIFY_SELFTEST", "memory")
    monkeypatch.setenv("CALMA_VERIFY_MEM_MB", "300")
    with pytest.raises(SUP.BudgetExceeded):
        SUP.run_isolated(bomb_repo, PIPE.VerifyOptions(deep=False))

    # ... the supervisor is unharmed and serves the next job normally.
    monkeypatch.delenv("CALMA_VERIFY_SELFTEST")
    monkeypatch.delenv("CALMA_VERIFY_MEM_MB")
    good = tmp_path / "good"
    good.mkdir()
    res = SUP.run_isolated(_fixture_repo(good, claim="f1 = 0.7"), PIPE.VerifyOptions(deep=False, discover=True))
    assert res["n_claims"] == 1
    assert res["claims"][0]["metric"] == "f1"


# ── budget sizing ───────────────────────────────────────────────────────────────────────────────────────────

def test_mem_budget_env_override(monkeypatch):
    monkeypatch.setenv("CALMA_VERIFY_MEM_MB", "321")
    assert SUP._mem_budget_mb() == 321


def test_mem_budget_reserves_parent_headroom(monkeypatch):
    """Sized from the container, the child cap must always leave the reserve free for the parent + OS, and
    never drop below the per-child floor."""
    monkeypatch.delenv("CALMA_VERIFY_MEM_MB", raising=False)
    monkeypatch.delenv("CALMA_VERIFY_CONCURRENCY", raising=False)
    monkeypatch.setattr(SUP, "_cgroup_total_mb", lambda: 1024)
    cap = SUP._mem_budget_mb()
    assert SUP._MIN_CHILD_MB <= cap <= 1024 - SUP._RESERVE_MB


def test_concurrency_and_cap_collectively_fit_container(monkeypatch):
    """The load-bearing safety invariant: concurrency × per-child cap fits the container's available memory,
    so N legitimate jobs can't co-OOM the box. The 1 GB deploy serializes (1); a bigger box parallelizes but
    stays bounded."""
    monkeypatch.delenv("CALMA_VERIFY_CONCURRENCY", raising=False)
    monkeypatch.delenv("CALMA_VERIFY_MEM_MB", raising=False)
    for total in (1024, 2048, 4096):
        monkeypatch.setattr(SUP, "_cgroup_total_mb", lambda t=total: t)
        permits, cap = SUP._concurrency(), SUP._mem_budget_mb()
        assert 1 <= permits <= SUP._MAX_CONCURRENCY
        assert permits * cap <= total - SUP._RESERVE_MB          # collectively bounded — the whole point
    monkeypatch.setattr(SUP, "_cgroup_total_mb", lambda: 1024)
    assert SUP._concurrency() == 1                                # the 1 GB single-instance deploy serializes


def test_concurrency_env_override(monkeypatch):
    monkeypatch.setenv("CALMA_VERIFY_CONCURRENCY", "5")
    assert SUP._concurrency() == 5


# ── budget covers a heavy build (the gb_kmer timeout fix) + heartbeat observability ─────────────────────────

def test_deep_wall_budget_covers_heavy_build():
    """A deep verify's wall budget must clear the heavy-deps install allowance + k runs — not just one run.
    The old timeout+300 (=900s) killed gb_kmer mid-install; the budget must now be far larger."""
    deep = PIPE.VerifyOptions(deep=True, timeout=600, k=2)
    shallow = PIPE.VerifyOptions(deep=False, timeout=600)
    assert SUP._default_wall(deep) >= SUP._HEAVY_BUILD_S + 2 * 600    # build + k runs
    assert SUP._default_wall(deep) > 900                              # strictly more than the old budget
    assert SUP._default_wall(shallow) == 900                          # no run → tight is fine
    # the CPU budget must clear the same bar, or RLIMIT_CPU would kill a legit long build
    assert SUP._limits(deep)["cpu_seconds"] >= SUP._HEAVY_BUILD_S


def test_heartbeat_emits_progress(monkeypatch):
    """The supervisor pulses a 'still working' line so a long silent phase (a heavy install) shows life and
    time climbing toward the budget — not a frozen UI."""
    monkeypatch.setattr(SUP, "_HEARTBEAT_S", 1)
    logs = []
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"], start_new_session=True)
    SUP._supervise(p, mem_cap=4096, wall=30, log=logs.append)
    SUP._reap(p)
    beats = [m for m in logs if "still working" in m]
    assert len(beats) >= 2
    assert "elapsed" in beats[0] and "budget" in beats[0]


def test_rss_probe_reads_self():
    rss = SUP._rss_mb(os.getpid())
    assert rss is not None and rss > 0


# ── isolation must be transparent for the heavy (deep, sub-process-spawning) path too ───────────────────────

def test_deep_local_verify_through_isolation(tmp_path):
    """The real workload: a deep verify runs the repo's entrypoint in a sub-process INSIDE the isolated child,
    captures it, and recomputes. Isolation must carry that whole flow through to a correct CONFIRMED verdict."""
    fixture = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "clean_eval")
    res = SUP.run_isolated(
        fixture,
        PIPE.VerifyOptions(deep=True, runner="local", discover=True, k=2,
                           venvs_dir=str(tmp_path / "venvs"), base_python=sys.executable),
    )
    assert (res.get("run") or {}).get("ran") is True
    accs = [c for c in res["claims"] if c["metric"] == "accuracy"]
    assert accs and accs[0]["verdict"] == "CONFIRMED"


def test_kill_tree_reaps_grandchildren(tmp_path):
    """A process-group kill must take down the whole tree — a hung run sub-process (or a fork-bomb) the child
    spawned cannot be left orphaned when the job is stopped."""
    marker = str(tmp_path / "gc.pid")
    child_code = (
        "import subprocess,sys,time\n"
        "subprocess.Popen([sys.executable,'-c',"
        "\"import os,time;open(%r,'w').write(str(os.getpid()));time.sleep(999)\"])\n"
        "time.sleep(999)\n" % marker
    )
    p = subprocess.Popen([sys.executable, "-c", child_code], start_new_session=True)
    for _ in range(50):                               # wait for the grandchild to record its pid
        if os.path.exists(marker) and open(marker).read().strip():
            break
        time.sleep(0.1)
    gc_pid = int(open(marker).read().strip())
    SUP._kill_tree(p)
    SUP._reap(p)
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):           # the grandchild is gone, not orphaned
        os.kill(gc_pid, 0)
