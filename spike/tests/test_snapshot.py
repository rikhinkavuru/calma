"""S5 — E2B snapshot primitives + the warm-env SnapshotCache. Hermetic: a fake sandbox + a monkeypatched SDK
(no live E2B — the live smoke is the ops step to flip CALMA_E2B_SNAPSHOT on). Asserts pause returns the
resumable id, resume/kill are best-effort (never raise), and the cache REAPS a replaced/evicted snapshot so a
paused sandbox (retained indefinitely by E2B) can't leak."""
import os
import sys
import types

from orchestrator.cache import SnapshotCache
from runner import snapshot as SNAP


def _fake_e2b(monkeypatch, sandbox_cls):
    # inject a fake `e2b` module into sys.modules — works whether or not the real SDK is installed (it is NOT
    # in CI), unlike setattr on the real module which needs it importable. resume/kill do `from e2b import Sandbox`.
    fake = types.ModuleType("e2b")
    fake.Sandbox = sandbox_cls
    monkeypatch.setitem(sys.modules, "e2b", fake)


# ── primitives ────────────────────────────────────────────────────────────────────────────────────────────────
class _Sbx:
    def __init__(self, sid="snap-1", ok=True, boom=False):
        self.sandbox_id = sid
        self._ok = ok
        self._boom = boom

    def pause(self):
        if self._boom:
            raise RuntimeError("e2b pause failed")
        return self._ok


def test_snapshots_enabled_flag(monkeypatch):
    monkeypatch.delenv("CALMA_E2B_SNAPSHOT", raising=False)
    assert SNAP.snapshots_enabled() is False
    monkeypatch.setenv("CALMA_E2B_SNAPSHOT", "1")
    assert SNAP.snapshots_enabled() is True
    monkeypatch.setenv("CALMA_E2B_SNAPSHOT", "0")
    assert SNAP.snapshots_enabled() is False


def test_pause_sandbox_returns_id_or_none():
    assert SNAP.pause_sandbox(_Sbx(sid="abc")) == "abc"      # paused → resumable id
    assert SNAP.pause_sandbox(_Sbx(ok=False)) is None        # pause returned False → no snapshot
    assert SNAP.pause_sandbox(_Sbx(boom=True)) is None       # pause raised → best-effort None (never breaks the run)


class _FakeSDK:
    calls = {"connect": [], "kill": []}

    @classmethod
    def connect(cls, sandbox_id, timeout=None, **api):
        cls.calls["connect"].append(sandbox_id)
        return _Sbx(sid=sandbox_id)

    @classmethod
    def kill(cls, sandbox_id, **api):
        cls.calls["kill"].append(sandbox_id)
        return True


def test_resume_and_kill_use_the_sdk_by_id(monkeypatch):
    _FakeSDK.calls = {"connect": [], "kill": []}
    _fake_e2b(monkeypatch, _FakeSDK)
    cfg = {"api_key": "k", "domain": "d"}
    sbx = SNAP.resume_sandbox("snap-9", cfg)
    assert sbx and sbx.sandbox_id == "snap-9" and _FakeSDK.calls["connect"] == ["snap-9"]
    assert SNAP.kill_snapshot("snap-9", cfg) is True and _FakeSDK.calls["kill"] == ["snap-9"]
    assert SNAP.resume_sandbox(None, cfg) is None            # no id → no call
    assert SNAP.kill_snapshot("", cfg) is False


def test_resume_never_raises_on_dead_snapshot(monkeypatch):
    class _Boom:
        @classmethod
        def connect(cls, *a, **k):
            raise RuntimeError("sandbox not found")
    _fake_e2b(monkeypatch, _Boom)
    assert SNAP.resume_sandbox("dead", {"api_key": "k"}) is None   # → caller boots fresh, unchanged behavior


# ── SnapshotCache: reaping on replace/evict (no leaked sandboxes) ──────────────────────────────────────────────
def _cache(tmp_path, killed, **kw):
    return SnapshotCache(path=os.path.join(str(tmp_path), "snap.json"), kill_fn=killed.append, **kw)


def test_cache_roundtrip_and_replacement_reaps_old(tmp_path):
    killed = []
    c = _cache(tmp_path, killed)
    c.put("fp1", "snapA")
    assert c.get("fp1") == "snapA" and killed == []
    c.put("fp1", "snapB")                                    # replace → the old snapshot must be killed
    assert c.get("fp1") == "snapB" and killed == ["snapA"]


def test_cache_eviction_reaps_oldest(tmp_path):
    killed = []
    c = _cache(tmp_path, killed, max_entries=2)
    c.put("fp1", "s1")
    c.put("fp2", "s2")
    c.put("fp3", "s3")                                       # over cap → evict + kill the oldest (s1)
    assert killed == ["s1"] and c.get("fp1") is None and len(c) == 2


def test_cache_discard_reaps_and_persists(tmp_path):
    killed = []
    p = os.path.join(str(tmp_path), "snap.json")
    c = SnapshotCache(path=p, kill_fn=killed.append)
    c.put("fp1", "s1")
    c.discard("fp1")                                         # resume failed → drop + kill the dead id
    assert killed == ["s1"] and c.get("fp1") is None
    assert SnapshotCache(path=p).get("fp1") is None          # persisted (a fresh instance also sees it gone)
