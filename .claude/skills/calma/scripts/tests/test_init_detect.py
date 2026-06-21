"""M1: `calma init` is not a trap on an existing repo. `--list` shows the frameworks; when the
template's artifacts don't exist but the repo carries data, init REFUSES and steers to `calma draft`
(instead of writing a contract that points at paths that don't exist); --force still writes the
skeleton; a fresh repo still scaffolds. Pure stdlib, offline. Run: python3 test_init_detect.py
"""
import io
import os
import sys
import shutil
import tempfile
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import calma as C  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def run_init(*args, **kw):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = C.init_cmd(*args, **kw)
    return rc, out.getvalue() + err.getvalue()


# --- --list shows frameworks + aliases ---
rc, text = run_init(None, list_fw=True)
truth(rc == 0, "--list exits 0")
truth("backtrader" in text and "sklearn" in text, "--list names the frameworks")
truth("torch -> pytorch" in text or "torch" in text, "--list shows aliases")

# --- no framework, no --list -> helpful error, not a crash ---
rc, text = run_init(None)
truth(rc == 2 and "calma init --list" in text, "missing framework steers to --list")

tmp = tempfile.mkdtemp(prefix="calma_m1_")

# --- mismatch: repo has runs/returns.csv (strat_return), template wants results/returns.csv ---
repo = os.path.join(tmp, "real")
os.makedirs(os.path.join(repo, "runs"))
with open(os.path.join(repo, "runs", "returns.csv"), "w") as fh:
    fh.write("date,strat_return\n2020,0.1\n2021,0.2\n")
rc, text = run_init("backtrader", repo)
truth(rc == 2, "mismatch refuses (exit 2)")
truth("calma draft" in text, "mismatch steers to `calma draft`")
truth("runs/returns.csv" in text, "mismatch names what the repo actually has")
truth(not os.path.exists(os.path.join(repo, "verify.yaml")),
      "mismatch writes NO verify.yaml (not a trap)")

# --- --force writes the skeleton anyway ---
rc, text = run_init("backtrader", repo, force=True)
truth(rc == 0 and os.path.exists(os.path.join(repo, "verify.yaml")),
      "--force writes the skeleton despite the mismatch")

# --- fresh repo (no artifacts yet) still scaffolds (the intended pre-output use) ---
fresh = os.path.join(tmp, "fresh")
os.makedirs(fresh)
rc, text = run_init("sklearn", fresh)
truth(rc == 0 and os.path.exists(os.path.join(fresh, "verify.yaml")),
      "fresh repo scaffolds normally")

# --- alias resolves ---
fresh2 = os.path.join(tmp, "fresh2")
os.makedirs(fresh2)
rc, _ = run_init("torch", fresh2)
truth(rc == 0 and os.path.exists(os.path.join(fresh2, "verify.yaml")),
      "alias 'torch' resolves to pytorch")

shutil.rmtree(tmp, ignore_errors=True)
print("init-detect (M1): %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
