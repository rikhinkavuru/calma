"""C4: `calma init <framework>` starter contracts. Every template VALIDATES against the contract schema
(draft_contract.validate_contract), the bindings match the engine's canonical recipe inputs, lookup is
case-insensitive + alias-aware, and init_cmd writes a verify.yaml + refuses to clobber. Pure stdlib,
offline. Run: python3 test_frameworks.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import calma as C  # noqa: E402
import draft_contract as DC  # noqa: E402
import frameworks as FW  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- every starter template validates against the contract schema ---
truth(set(FW.list_frameworks()) == {"backtrader", "vectorbt", "zipline", "pytorch", "xgboost", "sklearn",
                                    "numerai", "crunchdao"},
      "frameworks: the eight expected frameworks are present (incl. the numerai/crunchdao tournament on-ramps)")
for fw in FW.list_frameworks():
    c = FW.starter_contract(fw)
    errs = DC.validate_contract({k: v for k, v in c.items() if not k.startswith("_")})
    truth(errs == [], "frameworks: %s starter contract validates (errs=%s)" % (fw, errs))
    truth(bool(c["run"]["entrypoint"]) and bool(c["metrics"][0]["metric_id"])
          and bool(c["metrics"][0]["binding"]),
          "frameworks: %s has entrypoint + metric + binding" % fw)
    truth(c["run"].get("network") == "off", "frameworks: %s starter runs network-off" % fw)

# --- bindings match the engine's canonical recipe inputs ---
truth(FW.starter_contract("pytorch")["metrics"][0]["binding"] == {"prediction": "y_pred", "label": "y_true"},
      "frameworks: accuracy binds {prediction,label} (argmax)")
truth(FW.starter_contract("xgboost")["metrics"][0]["binding"] == {"score": "y_score", "label": "y_true"},
      "frameworks: auc binds {score,label} (roc-auc)")
truth("return" in FW.starter_contract("backtrader")["metrics"][0]["binding"],
      "frameworks: a quant framework binds {return}")

# --- ML starters carry a split skeleton so leakage can run once pointed at real files ---
truth(FW.starter_contract("sklearn").get("split") == {"train": "train.csv", "test": "test.csv"},
      "frameworks: an ML starter declares a split skeleton for the leakage check")
truth(FW.starter_contract("backtrader").get("split") is None,
      "frameworks: a quant starter has no split (row-overlap leakage is not its concern)")

# --- lookup is case-insensitive + alias-aware; unknown / non-str -> None ---
truth(FW.starter_contract("PyTorch")["metrics"][0]["metric_id"] == "accuracy", "frameworks: case-insensitive")
truth(all(FW.starter_contract(a) is not None for a in ("torch", "xgb", "scikit-learn", "bt", "vbt")),
      "frameworks: aliases resolve")
truth(FW.starter_contract("tensorflow") is None and FW.starter_contract(None) is None,
      "frameworks: an unknown framework (or non-str) -> None")
_a = FW.starter_contract("pytorch")
_a["metrics"][0]["metric_id"] = "MUTATED"
truth(FW.starter_contract("pytorch")["metrics"][0]["metric_id"] == "accuracy",
      "frameworks: starter_contract returns an independent deep copy (no shared-template mutation)")

# --- init_cmd writes a verify.yaml, refuses to clobber, errors on an unknown framework / bad target ---
d = tempfile.mkdtemp()
truth(C.init_cmd("backtrader", d) == 0, "init_cmd: writes a starter and returns 0")
dest = os.path.join(d, "verify.yaml")
truth(os.path.isfile(dest), "init_cmd: verify.yaml written")
written = json.load(open(dest))
truth("_note" not in written and written["metrics"][0]["metric_id"] == "sharpe",
      "init_cmd: the _note is stripped from the file; the contract is written")
truth(DC.validate_contract(written) == [], "init_cmd: the WRITTEN verify.yaml validates")
truth(C.init_cmd("backtrader", d) == 2, "init_cmd: refuses to clobber an existing verify.yaml")
truth(C.init_cmd("backtrader", d, force=True) == 0, "init_cmd: --force overwrites")
truth(C.init_cmd("nosuchframework", d, force=True) == 2, "init_cmd: unknown framework -> exit 2")
truth(C.init_cmd("pytorch", os.path.join(d, "does-not-exist")) == 2, "init_cmd: non-directory target -> exit 2")

print("frameworks: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
