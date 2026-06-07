"""Regression tests for the adversarial-audit fixes. Pure stdlib. Run: python3 test_audit.py
Covers: NaN-input propagation, AST determinism detection (regex-evasion), path-traversal rejection,
M2-gate soundness (measured-band needs M2 regardless of isolation tier), broadened doctor.
"""
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import numeric as N  # noqa: E402
import recipes as R  # noqa: E402
import recompute as RC  # noqa: E402
import run_hermetic as H  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def isnan(x):
    return isinstance(x, float) and x != x


# 1) NaN inputs -> NaN metric -> recipe degenerate=True (was: silently valid)
nan = float("nan")
truth(isnan(N.auc([0.6, nan, 0.3], [1, 0, 0])), "auc with NaN score -> NaN")
truth(isnan(N.accuracy([1, nan, 1], [1, 0, 1])), "accuracy with NaN pred -> NaN")
truth(isnan(N.max_drawdown([0.1, nan, 0.2])), "max_drawdown with NaN -> NaN")
truth(isnan(N.auc_delong_se([0.6, 0.7, nan, 0.3], [1, 1, 0, 0])), "delong SE with NaN -> NaN")
truth(R.get("accuracy")({"p": [1, nan], "y": [1, 0]}, {"prediction": "p", "label": "y"})["degenerate"],
      "recipe marks NaN result degenerate")

# NaN flows to INCONCLUSIVE through the pipeline (never a verdict)
import compare as CMP  # noqa: E402
d = tempfile.mkdtemp()
os.makedirs(os.path.join(d, "runs"))
with open(os.path.join(d, "r.csv"), "w") as fh:
    fh.write("strat_return\n0.1\nnan\n0.2\n")
contract = {"run": {"entrypoint": "x"}, "artifacts": [{"path": "r.csv",
            "columns": {"strat_return": {"tag": "return", "na_policy": "error"}}}],
            "metrics": [{"metric_id": "total_return", "artifact": "r.csv",
                         "binding": {"return": "strat_return"}, "claimed_value": 5.0,
                         "headline": True, "binding_status": "independently-bound", "claim_confirmed": True}]}
# write contract, then recompute via the real loader
import json  # noqa: E402
cpath = os.path.join(d, "verify.yaml")
json.dump(contract, open(cpath, "w"))
rec = RC.recompute_contract(cpath, base=d, k=1)
diff = CMP.compare(rec, contract, isolation_tier="tier0", determinism_mode="controlled-to-bit")
truth(diff["metrics"][0]["verdict"] == V.INCONCLUSIVE, "NaN in artifact -> INCONCLUSIVE, not a verdict")

# 2) AST determinism detection catches regex-evading nondeterminism
def det(src):
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
    f.write(src)
    f.close()
    mode = H._detect_determinism(f.name)[0]
    os.unlink(f.name)
    return mode


truth(det("import csv, json\nprint(1)\n") == "controlled-to-bit", "pure stdlib -> controlled-to-bit")
truth(det("import random as r\nprint(r.random())\n") != "controlled-to-bit", "aliased random caught")
truth(det("from random import random\nprint(random())\n") != "controlled-to-bit", "from-import random caught")
truth(det("import secrets\nprint(secrets.randbelow(9))\n") != "controlled-to-bit", "secrets caught")
truth(det("import os\nprint(os.urandom(4))\n") != "controlled-to-bit", "os.urandom caught")
truth(det("import numpy as np\nprint(np.zeros(3))\n") == "uncontrolled" or det("import numpy as np\n") == "measured-band",
      "numpy -> not controlled-to-bit")
truth(det("import torch\n") == "uncontrolled", "torch -> uncontrolled")

# 3) path-traversal rejection
truth(os.path.realpath(H.os.path.join("/x", "y")) is not None, "sanity")
try:
    RC._safe_join("/tmp/base", "../../etc/hosts")
    truth(False, "traversal path should raise")
except ValueError:
    truth(True, "recompute rejects .. traversal")
try:
    RC._safe_join("/tmp/base", "/etc/passwd")
    truth(False, "absolute escape should raise")
except ValueError:
    truth(True, "recompute rejects absolute escape")
truth(RC._safe_join("/tmp", "sub/ok.csv").endswith("sub/ok.csv"), "valid relative path allowed")

# 4) M2-gate: a measured-band run with a container but NO M2 calibration -> INCONCLUSIVE (not REFUTED)
big = {"gap": 147.0, "effective_budget": 0.05, "claim_outside_ci": True, "claim_confirmed_target": True,
       "binding_status": "independently-bound", "container_present": True, "isolation_tier": "seatbelt-verified",
       "determinism_mode": "measured-band", "band_coverage_ok": True, "sufficient_k": True, "m2_calibrated": False}
truth(V.verdict(big) == V.INCONCLUSIVE, "measured-band + container + no M2 -> INCONCLUSIVE")
big2 = dict(big, m2_calibrated=True)
truth(V.verdict(big2) == V.REFUTED, "measured-band + M2-calibrated -> REFUTED")

# 5) broadened doctor: no leaks across the probe battery (when sandbox-exec present)
doc = H.doctor(os.path.join(SCR, "..", "assets", "btc"))
if doc["sandbox_exec"]:
    truth(doc["leaks"] == [], "doctor battery: zero leaks (egress+secret all blocked)")

print("audit-fixes: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
