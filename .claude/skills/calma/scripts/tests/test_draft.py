"""Tests for draft_contract.py: auto-draft a correct graded contract; drafted contract drives the
pipeline end-to-end; ambiguous input degrades gracefully. Pure stdlib. Run: python3 test_draft.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import draft_contract as DC  # noqa: E402
import recompute as RC  # noqa: E402
import compare as CMP  # noqa: E402
import verdict as V  # noqa: E402

BTC = os.path.join(SCR, "..", "assets", "btc")
_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- draft the BTC contract from scratch (claim provided) ---
c = DC.draft(BTC, claim=146.97697947938846)
truth(c["run"]["entrypoint"] == "gen_fixture.py", "detects entrypoint")
truth(len(c["metrics"]) == 1, "one headline metric drafted")
m = c["metrics"][0]
truth(m["metric_id"] == "total_return", "picks total_return for a return column")
truth(m["binding"] == {"return": "strat_return"}, "binds return->strat_return (not bh_return)")
truth(m["binding_status"] == "independently-bound", "grades binding independently-bound")
truth(m["headline"] and m["claim_confirmed"], "claim makes it a confirmed headline")

# --- the DRAFTED contract drives the pipeline to REFUTED end-to-end ---
tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
json.dump(c, tmp)
tmp.close()
rec = RC.recompute_contract(tmp.name, base=BTC, k=2)
diff = CMP.compare(rec, c, isolation_tier="tier0", determinism_mode="controlled-to-bit")
truth(diff["metrics"][0]["verdict"] == V.REFUTED, "drafted contract -> REFUTED end-to-end (got %s)"
      % diff["metrics"][0]["verdict"])
os.unlink(tmp.name)

# --- ambiguous input: a csv with no recognizable tag -> no metric, warning set ---
d = tempfile.mkdtemp()
with open(os.path.join(d, "random.csv"), "w") as fh:
    fh.write("foo,bar\n1.0,2.0\n3.0,4.0\n")
c2 = DC.draft(d)
truth(not c2["metrics"], "no metric drafted for untagged columns")
truth(c2["_draft_notes"]["warning"], "warning surfaced when nothing recomputable")

# --- a returns column with implausible values caps the grade ---
with open(os.path.join(d, "ret.csv"), "w") as fh:
    fh.write("returns\n50.0\n80.0\n120.0\n")  # |r| >> 1, not return-plausible
c3 = DC.draft(d, claim=1.0, metric="total_return")
truth(c3["metrics"] and c3["metrics"][0]["binding_status"] == "plausibly-bound",
      "implausible 'returns' values -> plausibly-bound, not independently-bound")


# --- benchmark-claim disambiguation (false-REFUTED guard, 2026-06-10) ---
# a claim ABOUT buy-and-hold must bind the benchmark column, never the strategy column
import tempfile as _tf
_d = _tf.mkdtemp()
os.makedirs(os.path.join(_d, "runs", "oos"))
with open(os.path.join(_d, "runs", "oos", "returns.csv"), "w") as _fh:
    _fh.write("date,strat_return,buyhold_return\n")
    for _i in range(60):
        _fh.write("2026-01-%02d,%.4f,%.4f\n" % (_i % 28 + 1, 0.001 * ((_i % 7) - 3), 0.002 * ((_i % 5) - 2)))
with open(os.path.join(_d, "noop.py"), "w") as _fh:
    _fh.write("pass\n")
truth(DC._infer_tag("buyhold_return") == "benchmark", "buyhold_return tags as benchmark")
truth(DC._infer_tag("buy_and_hold") == "benchmark", "buy_and_hold tags as benchmark")
_c1 = DC.draft(_d, claim="buy and hold returned +10%")
truth(_c1["metrics"] and _c1["metrics"][0]["binding"]["return"] == "buyhold_return",
      "a buy-and-hold claim binds the benchmark column (got %r)"
      % (_c1["metrics"][0]["binding"] if _c1["metrics"] else None))
_c2 = DC.draft(_d, claim="the backtest returned +20%")
truth(_c2["metrics"] and _c2["metrics"][0]["binding"]["return"] == "strat_return",
      "a strategy claim still binds the strategy column")
# --- WS-leakage contract surface (Step 2): optional split / keys / features auto-detect ---
# (A) a train.csv + test.csv pair -> split{train,test}; keys id/time/target; features = the rest
dA = tempfile.mkdtemp()
open(os.path.join(dA, "noop.py"), "w").write("pass\n")
for _fn in ("train.csv", "test.csv"):
    with open(os.path.join(dA, _fn), "w") as fh:
        fh.write("id,date,score,y_true,x1\n")
        for i in range(6):
            fh.write("%d,2020-01-%02d,0.%d,%d,%.2f\n" % (i, i + 1, i % 9, i % 2, i * 1.5))
cA = DC.draft(dA, claim="auc 0.9", metric="auc")
truth(cA.get("split") == {"train": "train.csv", "test": "test.csv"},
      "train.csv/test.csv pair -> split (got %r)" % cA.get("split"))
truth(cA.get("keys", {}).get("id") == "id" and cA.get("keys", {}).get("time") == "date"
      and cA.get("keys", {}).get("target") == "y_true", "keys id/time/target detected (got %r)" % cA.get("keys"))
truth(cA.get("features") == ["x1"], "features = non-key/non-output columns (got %r)" % cA.get("features"))
truth(not DC.validate_contract(cA), "a drafted split/keys/features contract validates")

# (B) *_train.csv / *_test.csv (shared stem) -> split{train,test}
dB = tempfile.mkdtemp()
for _fn in ("data_train.csv", "data_test.csv"):
    with open(os.path.join(dB, _fn), "w") as fh:
        fh.write("id,y_true,x1\n0,1,2.0\n1,0,3.0\n")
cB = DC.draft(dB)
truth(cB.get("split") == {"train": "data_train.csv", "test": "data_test.csv"},
      "*_train/*_test pair -> split (got %r)" % cB.get("split"))

# (C) a single CSV with a split/fold column -> split{file,column}
dC = tempfile.mkdtemp()
with open(os.path.join(dC, "data.csv"), "w") as fh:
    fh.write("id,fold,y_true,x1\n0,train,1,2.0\n1,test,0,3.0\n2,train,1,4.0\n")
cC = DC.draft(dC)
truth(cC.get("split") == {"file": "data.csv", "column": "fold"},
      "split/fold column -> split (got %r)" % cC.get("split"))
truth(cC.get("keys", {}).get("target") == "y_true", "target detected for a single-file split")

# (D) NOT-APPLICABLE: no split + no target -> no leakage context declared (honest abstention)
truth("split" not in c2 and "keys" not in c2 and "features" not in c2,
      "untagged single CSV -> no split/keys/features (leakage NOT-APPLICABLE)")
truth("split" not in c, "BTC (no train/test, no target) -> no split declared")
truth("keys" not in c, "BTC (time-only, no split/target) -> no leakage keys (NOT-APPLICABLE)")

# (E) validate_contract shape-checks the new optional keys (absent is fine; malformed fails loudly)
_base = {"run": {"entrypoint": "main.py"},
         "artifacts": [{"path": "x.csv", "columns": {"v": {"tag": "value"}}}], "metrics": []}
truth(not DC.validate_contract(dict(_base, split={"train": "a.csv", "test": "b.csv"},
                                    keys={"id": "id", "time": "t", "target": "y"}, features=["x1", "x2"])),
      "well-formed split/keys/features validates")
truth(not DC.validate_contract(dict(_base, split={"file": "d.csv", "column": "fold"})),
      "single-file split form validates")
truth(DC.validate_contract(dict(_base, split="nope")), "non-dict split rejected")
truth(DC.validate_contract(dict(_base, split={"train": "a.csv"})), "split without test/file rejected")
truth(DC.validate_contract(dict(_base, keys={"id": 123})), "non-string key column rejected")
truth(DC.validate_contract(dict(_base, features="x1")), "non-list features rejected")
truth(DC.validate_contract(dict(_base, features=[1, 2])), "non-string feature names rejected")

# validity surfaces: well-formed frictions / corpus validate; UNKNOWN keys are rejected (a typo'd
# friction would otherwise be silently never applied - dev-experience audit 2026-06-16)
truth(not DC.validate_contract(dict(_base, frictions={"fee_bps": 10, "slippage_bps": 5, "leverage": 2,
      "turnover_col": "t", "fill": "vwap"})), "a well-formed frictions block validates")
truth(DC.validate_contract(dict(_base, frictions={"slippage": 5})),
      "an unknown friction key (slippage vs slippage_bps) is rejected, not silently ignored")
truth(DC.validate_contract(dict(_base, frictions={"fee_bps": -1})), "a negative friction is rejected")
truth(not DC.validate_contract(dict(_base, corpus={"manifest": "c.txt", "eval_col": "p"})),
      "a well-formed corpus block validates")
truth(DC.validate_contract(dict(_base, corpus={"manifest": "c.txt", "evalcol": "p"})),
      "an unknown corpus key (evalcol vs eval_col) is rejected")

# --- conservative block auto-inference (2026-06-17): a trials matrix is auto-declared; a date column
#     and a return metric are SUGGESTED (never auto-declared); a coverage map is emitted for the human ---
dI = tempfile.mkdtemp()
open(os.path.join(dI, "noop.py"), "w").write("pass\n")
with open(os.path.join(dI, "grid_search.csv"), "w") as fh:   # a trials/grid-search matrix in the repo
    fh.write("cand_1,cand_2,cand_3\n0.01,0.02,-0.01\n0.00,0.03,0.01\n")
with open(os.path.join(dI, "returns.csv"), "w") as fh:       # a return series with a date column
    fh.write("date,strat_return\n")
    for i in range(8):
        fh.write("2026-01-%02d,%.4f\n" % (i + 1, 0.01 + 0.001 * (i % 3)))
cI = DC.draft(dI, claim="total return 0.1", metric="total_return")
truth(cI.get("trials_artifact") == "grid_search.csv",
      "a grid_search.csv is auto-detected and declared as trials_artifact (got %r)" % cI.get("trials_artifact"))
truth(not DC.validate_contract(cI), "the auto-inferred trials_artifact contract validates")
_nt = cI["_draft_notes"]
truth(any("trials matrix" in d for d in _nt.get("detected_blocks", [])),
      "the trials matrix shows up in detected_blocks (got %r)" % _nt.get("detected_blocks"))
truth(any("date column" in s for s in _nt.get("suggested_blocks", [])),
      "a date column is SUGGESTED (windows/availability), not auto-declared (got %r)" % _nt.get("suggested_blocks"))
truth("windows" not in cI and "availability" not in cI,
      "a bare date column never auto-declares a verdict-flipping windows/availability block")
truth(any("frictions" in s for s in _nt.get("suggested_blocks", [])),
      "a return-bound metric suggests a frictions block for a net-of-cost claim")
# a non-trials csv must NOT be mistaken for a trials matrix
dJ = tempfile.mkdtemp()
open(os.path.join(dJ, "noop.py"), "w").write("pass\n")
open(os.path.join(dJ, "prices.csv"), "w").write("px\n100\n101\n")
truth(DC.draft(dJ).get("trials_artifact") is None,
      "an ordinary csv is not auto-declared as a trials matrix (no false positive)")

print("draft_contract: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
