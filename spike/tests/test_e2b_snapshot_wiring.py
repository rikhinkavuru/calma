"""S5 wiring — run_e2b resumes a warm snapshot (skipping boot + upload + install) and pauses + caches the env
on success. Fully hermetic: a fake e2b SDK (no key/network) + a tmp snapshot cache. Proves the flag-ON logic
end-to-end and that the flag-OFF path is byte-for-byte the old behavior (killed, never paused). The real E2B
pause/resume fidelity is the separate live smoke."""
import json
import sys
import types

import pytest

from orchestrator import cache as OCACHE
from orchestrator.cache import SnapshotCache
from orchestrator.tools_static import repo_fingerprint
from runner import e2b_runner

_LOG: dict = {}


class _Files:
    def write(self, path, data):
        _LOG.setdefault("writes", []).append(path)

    def read(self, path):
        if path.endswith("calma_runctx.json"):
            return json.dumps({"pybin": "python", "python_used": None})
        if path.endswith(".hooks"):
            return '{"sklearn": true}'
        if path.endswith(".jsonl"):
            return '{"metric": "accuracy", "result": 0.9, "inputs": {"y_true": [1,0], "y_pred": [1,0]}, "seq": 0}\n'
        raise FileNotFoundError(path)


class _Cmds:
    def run(self, cmd, on_stdout=None, **kw):
        _LOG.setdefault("cmds", []).append(cmd)
        if on_stdout:
            on_stdout("x")
        return types.SimpleNamespace(exit_code=0, stdout="", stderr="")


class _Sbx:
    created = 0
    connected: list = []

    def __init__(self, sid="sbx-1"):
        self.files = _Files()
        self.commands = _Cmds()
        self.sandbox_id = sid

    @classmethod
    def create(cls, **kw):
        cls.created += 1
        return cls("sbx-new")

    @classmethod
    def connect(cls, sandbox_id, timeout=None, **kw):          # resume-by-id (class-method-variant in the real SDK)
        cls.connected.append(sandbox_id)
        return cls(sandbox_id)

    @classmethod
    def kill(cls, sandbox_id=None, **kw):                      # both sbx.kill() and Sandbox.kill(id) route here
        _LOG.setdefault("killed_ids", []).append(sandbox_id)
        return True

    def pause(self):
        _LOG["paused"] = _LOG.get("paused", 0) + 1
        return True


@pytest.fixture
def fake_e2b(tmp_path, monkeypatch):
    global _LOG
    _LOG = {}
    _Sbx.created = 0
    _Sbx.connected = []
    fake = types.ModuleType("e2b")
    fake.Sandbox = _Sbx
    monkeypatch.setitem(sys.modules, "e2b", fake)
    # a fresh, isolated snapshot cache (the global singleton) at a tmp path; kill_fn just records
    killed: list = []
    monkeypatch.setattr(OCACHE, "_SNAPSHOTS",
                        SnapshotCache(path=str(tmp_path / "snap.json"), kill_fn=killed.append))
    return killed


def _repo(tmp_path):
    d = tmp_path / "repo"                                      # a SUBDIR — keep the cache file out of the repo so
    d.mkdir(exist_ok=True)                                     # the repo fingerprint stays stable across the run
    (d / "eval.py").write_text("print('hi')\n")
    return str(d)


_CFG = {"api_key": "x", "domain": None, "template": None}


def test_flag_off_is_unchanged_boot_and_kill(fake_e2b, tmp_path, monkeypatch):
    monkeypatch.delenv("CALMA_E2B_SNAPSHOT", raising=False)
    repo = _repo(tmp_path)
    fp = repo_fingerprint(repo)                                # BEFORE the run (which drops capture artifacts)
    res = e2b_runner.run_e2b(repo, ["eval.py"], k=1, cfg=_CFG)
    assert res["ran_ok"] and _Sbx.created == 1
    assert _LOG.get("paused", 0) == 0                          # never paused when the flag is off
    assert None in _LOG.get("killed_ids", [])                 # sandbox killed (instance kill) — today's behavior
    assert OCACHE._SNAPSHOTS.get(fp) is None                  # nothing cached


def test_cold_run_pauses_and_caches_the_warm_env(fake_e2b, tmp_path, monkeypatch):
    monkeypatch.setenv("CALMA_E2B_SNAPSHOT", "1")
    repo = _repo(tmp_path)
    fp = repo_fingerprint(repo)                                # the fingerprint run_e2b caches under (pre-run)
    res = e2b_runner.run_e2b(repo, ["eval.py"], k=1, pip_install=["scikit-learn"], cfg=_CFG)
    assert res["ran_ok"] and _Sbx.created == 1
    assert _LOG.get("paused", 0) == 1                          # env built → paused, NOT killed
    assert "/calma_runctx.json" in _LOG.get("writes", [])     # run-context saved into the snapshot
    assert OCACHE._SNAPSHOTS.get(fp) == "sbx-new"             # warm snapshot cached by fingerprint


def test_warm_run_resumes_and_skips_install(fake_e2b, tmp_path, monkeypatch):
    monkeypatch.setenv("CALMA_E2B_SNAPSHOT", "1")
    repo = _repo(tmp_path)
    OCACHE._SNAPSHOTS.put(repo_fingerprint(repo), "sbx-cached")   # a prior successful build is cached (pre-run fp)
    res = e2b_runner.run_e2b(repo, ["eval.py"], k=1, pip_install=["scikit-learn"], cfg=_CFG)
    assert res["ran_ok"]
    assert _Sbx.connected == ["sbx-cached"] and _Sbx.created == 0     # RESUMED, never booted a fresh microVM
    cmds = _LOG.get("cmds", [])
    assert not any("install" in c for c in cmds)              # install SKIPPED — the snapshot already has deps
    assert any(c.startswith("python ") and "/capture/" not in c for c in cmds)   # the entrypoint still ran
