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

print("draft_contract: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
