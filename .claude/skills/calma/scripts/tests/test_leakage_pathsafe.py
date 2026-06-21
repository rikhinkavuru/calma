"""L1: leakage_checks._load_split contains contract-supplied split paths to the base dir, so an
untrusted/counterparty verify.yaml with `split.train: ../../etc/passwd` (or any traversal) is
refused - never a read outside the base. The B1 undeclared-split smell rides the same guarded reader.
One shared guard (pathsafe). Pure stdlib, offline. Run: python3 test_leakage_pathsafe.py
"""
import os
import sys
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import pathsafe as PS  # noqa: E402
import leakage_checks as LC  # noqa: E402
import plausibility_checks as PLC  # noqa: E402
import backtest_checks as BC  # noqa: E402
import overfitting_checks as OC  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- the shared guard ---
tmp = tempfile.mkdtemp(prefix="calma_l1_")
base = os.path.join(tmp, "base")
os.makedirs(base)
open(os.path.join(base, "ok.csv"), "w").write("a\n1\n")
# a secret OUTSIDE the base that must never be reachable
secret = os.path.join(tmp, "secret.txt")
open(secret, "w").write("TOPSECRET")

truth(PS.safe_join(base, "ok.csv") == os.path.realpath(os.path.join(base, "ok.csv")),
      "safe_join: in-base path resolves")
for evil in ["../secret.txt", "../../etc/passwd", "/etc/passwd", "sub/../../secret.txt"]:
    try:
        PS.safe_join(base, evil)
        truth(False, "safe_join must reject %r" % evil)
    except ValueError:
        truth(True, "safe_join rejects %r" % evil)
truth(PS.is_contained(base, "ok.csv") and not PS.is_contained(base, "../secret.txt"),
      "is_contained mirrors safe_join")

# --- _load_split: a traversal split path reads NOTHING outside base ---
d = LC._load_split({"split": {"train": "../secret.txt", "test": "ok.csv"}}, base)
truth(d is None, "_load_split refuses a ../ traversal split.train (returns None)")
d2 = LC._load_split({"split": {"file": "../../etc/passwd", "column": "x"}}, base)
truth(d2 is None, "_load_split refuses a traversal single-file split")

# --- a LEGITIMATE in-base two-file split still loads ---
open(os.path.join(base, "train.csv"), "w").write("id,y\n1,0\n2,1\n")
open(os.path.join(base, "test.csv"), "w").write("id,y\n3,0\n4,1\n")
d3 = LC._load_split({"split": {"train": "train.csv", "test": "test.csv"}}, base)
truth(d3 is not None and d3.get("train") and d3.get("test"),
      "_load_split still loads a legitimate in-base split")

# --- delegation: plausibility_checks._safe_join is the same guard now ---
try:
    PLC._safe_join(base, "../secret.txt")
    truth(False, "PLC._safe_join must reject traversal")
except ValueError:
    truth(True, "plausibility_checks._safe_join delegates to the shared guard")

# --- B1 inferred-split smell can't be coerced into an out-of-base read ---
# (artifacts named train/test with traversal would still be contained by the same _load_split guard)
contract_b1 = {"artifacts": [{"path": "../secret.txt", "columns": {}}]}
res = PLC.check_undeclared_split_leak(contract_b1, base)
truth(res is None, "B1 undeclared-split smell never reads outside base via inferred paths")

# --- SEC-1: the OTHER artifact readers (target-leakage, backtest, overfitting) are contained too ---
open(os.path.join(base, "secret2.csv"), "w").write("target,feat\n1,1\n0,0\n")
# leakage target-leakage table: a traversal artifact carrying the target column reads NOTHING
trav = {"keys": {"target": "target"},
        "artifacts": [{"path": "../secret.txt", "columns": {"target": {}}}]}
hdr, rows = LC._target_table(None, trav, base)
truth(hdr == [] and rows == [], "SEC-1: leakage _target_table refuses a traversal artifact path")
# backtest artifact path: traversal -> "" (read as missing, never out of base)
truth(BC._artifact_path(base, {"artifact": "../../etc/passwd"}) == "",
      "SEC-1: backtest _artifact_path contains a traversal artifact")
truth(BC._artifact_path(base, {"artifact": "ok.csv"}).endswith("ok.csv"),
      "SEC-1: backtest _artifact_path still resolves an in-base artifact")
# overfitting returns/trials: traversal -> None
truth(OC._returns({"metrics": [{"headline": True, "binding": {"return": "r"},
                                "artifact": "../secret.txt"}]}, base) is None,
      "SEC-1: overfitting _returns contains a traversal artifact")
truth(OC._trials_stats({}, base, "../../etc/passwd") is None,
      "SEC-1: overfitting _trials_stats contains a traversal artifact")

shutil.rmtree(tmp, ignore_errors=True)
print("leakage-pathsafe (L1): %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
