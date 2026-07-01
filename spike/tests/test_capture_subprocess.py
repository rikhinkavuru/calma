"""Capture must survive subprocess boundaries. A benchmark that runs `subprocess-per-cell` and spawns its
workers with an explicit env= (setting PYTHONHASHSEED / thread caps) drops our PYTHONPATH + CALMA_CAPTURE_OUT
— so without propagation the child computes the metric but it's captured NOWHERE (the gb_kmer hole)."""
import sys

from runner.local_runner import run_local

_CELL = "import numpy as np\nfrom sklearn.metrics import accuracy_score\n" \
        "print('acc', accuracy_score(np.array([0,1,1,0,1]), np.array([0,1,0,0,1])))\n"


def _repo(tmp_path, spawn):
    (tmp_path / "cell.py").write_text(_CELL)
    (tmp_path / "run_benchmark.py").write_text(spawn)
    return str(tmp_path)


def test_captures_across_clean_env_subprocess(tmp_path):
    """The failure mode: a child spawned with its OWN env (no PYTHONPATH/CALMA_CAPTURE_OUT) — must still
    capture, because the armed parent re-injects the capture env into subprocess children."""
    repo = _repo(tmp_path,
                 "import subprocess, sys, os\n"
                 "d = os.path.dirname(os.path.abspath(__file__))\n"
                 "for _ in range(3):\n"
                 "    subprocess.run([sys.executable, 'cell.py'], cwd=d, env={'PATH': os.environ['PATH'], 'PYTHONHASHSEED': '0'})\n")
    res = run_local(repo, ["run_benchmark.py"], k=1)
    assert res["meta"][0]["returncode"] == 0
    assert res["n_calls"][0] == 3                     # all three clean-env cells captured
    assert all(c["metric"] == "accuracy" for c in res["runs"][0])


def test_captures_across_inherited_env_subprocess(tmp_path):
    """The env=None case (child inherits os.environ) must keep working — no regression."""
    repo = _repo(tmp_path,
                 "import subprocess, sys, os\n"
                 "d = os.path.dirname(os.path.abspath(__file__))\n"
                 "subprocess.run([sys.executable, 'cell.py'], cwd=d)\n")
    res = run_local(repo, ["run_benchmark.py"], k=1)
    assert res["n_calls"][0] == 1


def test_propagation_patch_is_idempotent_and_safe():
    """Arming twice must not double-wrap subprocess.Popen, and a normal (no-capture) Popen still works."""
    import importlib
    cap = importlib.import_module("calma_capture")
    cap._OUT_PATH[0] = "/tmp/nonexistent_calma_cap"
    cap._install_subprocess_propagation()
    cap._install_subprocess_propagation()               # idempotent
    import subprocess
    assert getattr(subprocess.Popen, "__calma_env_patched__", False)
    # a plain child with no env override still runs fine
    out = subprocess.run([sys.executable, "-c", "print(2+2)"], capture_output=True, text=True)
    assert out.stdout.strip() == "4"
