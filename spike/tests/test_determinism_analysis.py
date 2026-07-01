"""core.determinism static analyzer: the classification bar that gates adaptive-k. The asymmetry is
load-bearing — a false 'at_risk' just wastes a re-run, a false 'deterministic' could confirm a flaky number.
So the battery leans on the dangerous direction: every unseeded / uncontrolled pattern MUST be at_risk."""
import pytest

from core import determinism as DET


def _repo(tmp_path, code, name="m.py"):
    (tmp_path / name).write_text(code)
    return str(tmp_path)


# (source, expected level) — the dangerous cases (must be at_risk) are the point.
_CASES = [
    # deterministic: every used RNG is explicitly seeded, or nothing random at all
    ("import numpy as np\nrng = np.random.default_rng(0)\nx = rng.random(5)\n", DET.DETERMINISTIC),
    ("import numpy as np\nnp.random.seed(42)\nx = np.random.rand(5)\n", DET.DETERMINISTIC),
    ("import random\nrandom.seed(1)\nx = random.random()\n", DET.DETERMINISTIC),
    ("import torch\ntorch.manual_seed(0)\nm = torch.nn.Linear(3, 1)\n", DET.DETERMINISTIC),
    ("from sklearn.model_selection import train_test_split\na = train_test_split(X, random_state=42)\n", DET.DETERMINISTIC),
    ("import lightgbm\nm = lightgbm.LGBMClassifier(random_state=42)\n", DET.DETERMINISTIC),
    ("import numpy as np\nx = np.mean([1, 2, 3])\n", DET.DETERMINISTIC),                 # pure computation
    ("def add(a, b):\n    return a + b\n", DET.DETERMINISTIC),
    # at_risk: uncontrolled randomness (the cases that must NEVER be trusted for k=1)
    ("import numpy as np\nx = np.random.rand(5)\n", DET.AT_RISK),                        # unseeded numpy
    ("import numpy as np\nrng = np.random.default_rng()\n", DET.AT_RISK),               # default_rng() no seed
    ("import numpy as np\nrng = np.random.default_rng()\nx = rng.integers(0, 2, 5)\n", DET.AT_RISK),
    ("import random\nx = random.random()\n", DET.AT_RISK),                              # unseeded stdlib random
    ("import torch\nm = torch.nn.Linear(3, 1)\n", DET.AT_RISK),                         # torch, no manual_seed
    ("from sklearn.model_selection import train_test_split\na = train_test_split(X)\n", DET.AT_RISK),  # no random_state
    ("from sklearn.ensemble import RandomForestClassifier\nm = RandomForestClassifier()\n", DET.AT_RISK),
    ("import lightgbm\nm = lightgbm.LGBMClassifier()\n", DET.AT_RISK),
    # mixed: one family seeded, another NOT → at_risk (an uncontrolled source anywhere spoils it)
    ("import numpy as np, torch\nnp.random.seed(0)\nm = torch.nn.Linear(3, 1)\n", DET.AT_RISK),
    # NON-RNG entropy: wall-clock / urandom / harness counter — "no RNG" does NOT mean deterministic here
    ("import os\nrun = int(os.environ['CALMA_RUN_INDEX'])\nx = 700 + run\n", DET.AT_RISK),   # the drift device
    ("import time\nt = time.perf_counter()\nx = 1\n", DET.AT_RISK),                          # times itself
    ("import time\nt = time.time()\n", DET.AT_RISK),
    ("import os\nx = os.urandom(4)\n", DET.AT_RISK),
    ("import secrets\nx = secrets.token_hex()\n", DET.AT_RISK),
    ("from datetime import datetime\nt = datetime.now()\n", DET.AT_RISK),
    # a seed present but ALSO a wall-clock read → still at_risk (the clock isn't controlled by the seed)
    ("import numpy as np, time\nnp.random.seed(0)\nx = np.random.rand(3)\nt = time.time()\n", DET.AT_RISK),
]


@pytest.mark.parametrize("code,expected", _CASES)
def test_classification(tmp_path, code, expected):
    got = DET.analyze(_repo(tmp_path, code))
    assert got["level"] == expected, "%r → %s (want %s): %s" % (code[:40], got["level"], expected, got["detail"])


def test_seed_and_use_in_different_files_still_deterministic(tmp_path):
    """RNG use and its seeding often live in separate files (a worker cell vs a set_seed util) — the analyzer
    scans the whole repo, so it must still see the seed."""
    (tmp_path / "seed.py").write_text("import numpy as np\nnp.random.seed(7)\n")
    (tmp_path / "work.py").write_text("import numpy as np\nx = np.random.rand(10)\n")
    assert DET.analyze(str(tmp_path))["level"] == DET.DETERMINISTIC


def test_no_source_is_unknown(tmp_path):
    assert DET.analyze(str(tmp_path))["level"] == DET.UNKNOWN        # nothing to analyze → not "deterministic"


def test_enforced_env_is_hash_and_tz_only():
    """The always-on enforced env freezes hash + tz, but must NOT pin BLAS threads (that would negate the
    multi-core template, and the residual wobble is below any reported-metric tolerance)."""
    env = DET.enforced_env()
    assert env.get("PYTHONHASHSEED") == "0" and env.get("TZ") == "UTC"
    assert not any("NUM_THREADS" in k for k in env)
