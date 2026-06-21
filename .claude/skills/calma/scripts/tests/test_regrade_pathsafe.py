"""Security regression (audit MAJOR): draft_contract.regrade_committed grades a COMMITTED verify.yaml's
binding from the actual data, reading artifacts[].path. A committed contract is untrusted counterparty
input, so a `../`-escaping path must NOT be read out-of-base. This proves the escape is contained (the
out-of-base file is never sampled -> the binding stays author-asserted) WHILE a legitimate in-base path is
still read and graded up (so the fix is specific containment, not "reads nothing"). Pure stdlib.
Run: python3 test_regrade_pathsafe.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import draft_contract as DC  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


_root = tempfile.mkdtemp(prefix="calma_rg_")
_base = os.path.join(_root, "base")
os.makedirs(_base)

# a clean numeric `return` column that WOULD grade up to independently-bound if it were read
_clean = "ret\n0.10\n-0.05\n0.20\n0.00\n0.05\n0.11\n-0.02\n"
# the sentinel lives OUTSIDE the contract base (a secret the verifier must never sample via `../`)
with open(os.path.join(_root, "outside.csv"), "w") as f:
    f.write(_clean)
# an identical file INSIDE the base (the legitimate control)
with open(os.path.join(_base, "inside.csv"), "w") as f:
    f.write(_clean)


def _contract(path):
    return {"run": {"entrypoint": "x"}, "artifacts": [{"path": path, "columns": {"ret": {"tag": "return"}}}],
            "metrics": [{"metric_id": "total_return", "artifact": path, "binding": {"return": "ret"},
                        "claimed_value": 0.10}]}


# escape: ../outside.csv must be CONTAINED -> never read -> binding stays author-asserted
esc = DC.regrade_committed(_contract("../outside.csv"), _base)
truth(esc["metrics"][0]["binding_status"] == "author-asserted",
      "traversal contained: a ../-escaping artifact path is NOT read out-of-base (binding stays author-asserted)")
# an absolute path to the sentinel is contained too
esc2 = DC.regrade_committed(_contract(os.path.join(_root, "outside.csv")), _base)
truth(esc2["metrics"][0]["binding_status"] == "author-asserted",
      "traversal contained: an absolute out-of-base path is NOT read")

# control: a legitimate IN-base path IS read and graded up (proves the fix is containment, not 'read nothing')
ok = DC.regrade_committed(_contract("inside.csv"), _base)
truth(ok["metrics"][0]["binding_status"] == "independently-bound",
      "in-base path still read + graded up to independently-bound (containment is specific to the escape)")

# no crash on a missing/None path
DC.regrade_committed({"run": {"entrypoint": "x"}, "artifacts": [{"path": None, "columns": {}}],
                     "metrics": []}, _base)
truth(True, "no crash on a None artifact path")

print("regrade_pathsafe: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
