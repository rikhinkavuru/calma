"""Unit tests for the hosted-execution wiring (no network, no DB): the isolation flag the API hands the
engine and the provider string it records. The full E2B round-trip is exercised by the engine's own suite
(run_hermetic) + the live e2e test with CALMA_EXEC_ISOLATION=e2b.

Run:  ~/.calma/cp-venv/bin/python -m control_plane.api.tests.test_e2b_wiring
"""
from __future__ import annotations

import sys

from control_plane.api import config, engine, service

_n = _fail = 0


def ok(cond, label):
    global _n, _fail
    _n += 1
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        _fail += 1


def test_isolation_flag_threaded(monkeypatch_iso):
    """run_verify appends --isolation only when one is pinned; auto/empty stays on the engine's auto path."""
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd

        class P:  # minimal CompletedProcess stand-in
            stdout, stderr, returncode = "{}", "", 0
        return P()

    orig_run = engine.subprocess.run
    engine.subprocess.run = fake_run
    try:
        for iso, expect in (("", False), ("auto", False), ("e2b", True), ("docker", True)):
            config.EXEC_ISOLATION = iso
            engine.run_verify("/tmp/nowhere", "own-code", 5)
            cmd = captured["cmd"]
            has = "--isolation" in cmd
            ok(has is expect, "isolation=%r -> --isolation present=%s" % (iso, has))
            if expect:
                ok(cmd[cmd.index("--isolation") + 1] == iso, "  flag value is %r" % iso)
    finally:
        engine.subprocess.run = orig_run
        config.EXEC_ISOLATION = monkeypatch_iso


def test_provider_derivation():
    """The recorded provider tells the truth about WHERE the code ran, from the engine's tier stamp."""
    saved = config.EXEC_ISOLATION
    try:
        config.EXEC_ISOLATION = "e2b"
        ok(service._provider_for("e2b-firecracker") == "e2b", "e2b-firecracker tier -> provider 'e2b'")
        ok(service._provider_for("e2b-firecracker (self-hosted)") == "e2b", "self-hosted e2b -> 'e2b'")
        ok(service._provider_for("n/a") == "e2b", "no tier but configured e2b -> 'e2b' (stage/parse fail)")
        config.EXEC_ISOLATION = ""
        ok(service._provider_for("seatbelt-verified") == "local", "seatbelt tier -> provider 'local'")
        ok(service._provider_for("n/a") == "local", "no tier, local backend -> 'local'")
        ok(service._provider_for(None) == "local", "None tier -> 'local'")
    finally:
        config.EXEC_ISOLATION = saved


def test_bad_isolation_rejected():
    """A typo'd CALMA_EXEC_ISOLATION fails loudly at config load, not silently as host-default."""
    import importlib
    import os
    saved = os.environ.get("CALMA_EXEC_ISOLATION")
    os.environ["CALMA_EXEC_ISOLATION"] = "sandybox"
    raised = False
    try:
        importlib.reload(config)
    except ValueError:
        raised = True
    finally:
        if saved is None:
            os.environ.pop("CALMA_EXEC_ISOLATION", None)
        else:
            os.environ["CALMA_EXEC_ISOLATION"] = saved
        importlib.reload(config)
    ok(raised, "bad CALMA_EXEC_ISOLATION raises at import")


def main():
    saved = config.EXEC_ISOLATION
    test_isolation_flag_threaded(saved)
    test_provider_derivation()
    test_bad_isolation_rejected()
    config.EXEC_ISOLATION = saved
    print("\n%d checks, %d failed" % (_n, _fail))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
