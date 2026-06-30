"""E2B runner cost behaviour: ONE sandbox is created, deps install ONCE, the entrypoint runs k× inside it.
Mocks the e2b SDK so it runs offline (no key, no network)."""
import sys
import types

from runner import e2b_runner


class _Files:
    def __init__(self, log):
        self.log = log

    def write(self, path, data):
        self.log.setdefault("writes", []).append(path)

    def read(self, path):
        if path.endswith(".hooks"):
            return '{"sklearn": true}'
        if path.endswith(".jsonl"):
            # one captured accuracy call so parse_capture yields a computation
            return '{"metric": "accuracy", "result": 0.9, "inputs": {"y_true": [1,0], "y_pred": [1,0]}, "seq": 0}\n'
        raise FileNotFoundError(path)


class _Cmds:
    def __init__(self, log):
        self.log = log

    def run(self, cmd, **kw):
        self.log.setdefault("cmds", []).append(cmd)
        if self.log.get("fail_on") and self.log["fail_on"] in cmd:
            raise RuntimeError("simulated failure: " + cmd)
        return types.SimpleNamespace(exit_code=0, stdout="", stderr="")


class _Sbx:
    created = 0

    def __init__(self, log):
        self.files = _Files(log)
        self.commands = _Cmds(log)
        self.log = log

    @classmethod
    def create(cls, **kw):
        cls.created += 1
        return cls(_LOG)

    def kill(self):
        self.log["killed"] = self.log.get("killed", 0) + 1


_LOG = {}


def _install_fake_e2b(monkeypatch):
    global _LOG
    _LOG = {}
    _Sbx.created = 0
    fake = types.ModuleType("e2b")
    fake.Sandbox = _Sbx
    monkeypatch.setitem(sys.modules, "e2b", fake)


def test_install_once_run_k_times(tmp_path, monkeypatch):
    _install_fake_e2b(monkeypatch)
    (tmp_path / "eval.py").write_text("print('hi')\n")
    cfg = {"api_key": "x", "domain": None, "template": None}
    res = e2b_runner.run_e2b(str(tmp_path), ["eval.py"], k=3, pip_install=["scikit-learn"], cfg=cfg)

    assert _Sbx.created == 1                                    # ONE sandbox for all k runs
    cmds = _LOG.get("cmds", [])
    assert sum(1 for c in cmds if "pip install" in c) == 1     # deps installed ONCE
    assert sum(1 for c in cmds if c.startswith("python ")) == 3  # entrypoint ran k×
    assert len(res["runs"]) == 3 and res["ran_ok"]
    assert res["cost"]["runs"] == 3 and res["cost"]["reused_sandbox"] is True
    assert _LOG.get("killed", 0) == 1                          # sandbox killed once at the end


def test_tolerant_install_for_inferred_deps(tmp_path, monkeypatch):
    _install_fake_e2b(monkeypatch)
    (tmp_path / "eval.py").write_text("print('hi')\n")
    cfg = {"api_key": "x", "domain": None, "template": None}
    # inferred (pip_strict=False) → installs per-package
    e2b_runner.run_e2b(str(tmp_path), ["eval.py"], k=1, pip_install=["numpy", "scikit-learn"],
                       pip_strict=False, cfg=cfg)
    installs = [c for c in _LOG.get("cmds", []) if "pip install" in c]
    assert len(installs) == 2                                   # one command per package


def test_inferred_heavy_dep_uses_cpu_wheel(tmp_path, monkeypatch):
    _install_fake_e2b(monkeypatch)
    (tmp_path / "eval.py").write_text("print('hi')\n")
    cfg = {"api_key": "x", "domain": None, "template": None}
    e2b_runner.run_e2b(str(tmp_path), ["eval.py"], k=1, pip_install=["torch", "numpy"],
                       pip_strict=False, cfg=cfg)
    cmds = _LOG.get("cmds", [])
    assert any("download.pytorch.org/whl/cpu" in c for c in cmds)   # torch → CPU wheel, no CUDA download


def test_provisions_declared_python_version(tmp_path, monkeypatch):
    _install_fake_e2b(monkeypatch)
    (tmp_path / "eval.py").write_text("print('hi')\n")
    cfg = {"api_key": "x", "domain": None, "template": None}
    res = e2b_runner.run_e2b(str(tmp_path), ["eval.py"], k=1, pip_install=["numpy"],
                             python_version="3.11", cfg=cfg)
    cmds = _LOG.get("cmds", [])
    assert any("uv python install 3.11" in c for c in cmds)
    assert any("uv venv --python 3.11 /pyenv" in c for c in cmds)
    assert any(c.startswith("/pyenv/bin/python ") for c in cmds)        # ran under the provisioned interp
    assert any("uv pip install" in c and "/pyenv/bin/python" in c for c in cmds)  # installed into it
    assert res["cost"]["python"] == "3.11"


def test_python_provision_falls_back_gracefully(tmp_path, monkeypatch):
    _install_fake_e2b(monkeypatch)
    _LOG["fail_on"] = "uv python install"                       # provisioning unavailable
    (tmp_path / "eval.py").write_text("print('hi')\n")
    cfg = {"api_key": "x", "domain": None, "template": None}
    res = e2b_runner.run_e2b(str(tmp_path), ["eval.py"], k=1, pip_install=["numpy"],
                             python_version="3.11", cfg=cfg)
    cmds = _LOG.get("cmds", [])
    assert any(c.startswith("python ") for c in cmds)            # fell back to the sandbox python
    assert res["cost"]["python"] == "sandbox-default" and res["ran_ok"]
