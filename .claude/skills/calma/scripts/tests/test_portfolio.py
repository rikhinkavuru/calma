"""Tests for portfolio.py - W7: the IC portfolio rollup (the at-a-glance summary + family-scope heatmap).
Pure stdlib. Run: python3 test_portfolio.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import portfolio as P  # noqa: E402

_n = _fail = 0


def expect(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


VS = [
    {"manager": "Alpha", "metric": "sharpe", "repo_verdict": "CONFIRMED",
     "family_scope": {"reproducibility": "checked", "leakage": "checked"}},
    {"manager": "Beta", "metric": "sharpe", "repo_verdict": "CONFIRMED-WITH-CAVEATS",
     "family_scope": {"reproducibility": "checked"}},
    {"manager": "Gamma", "metric": "auc", "repo_verdict": "FLAG_FOR_DECLARATION",
     "family_scope": {"reproducibility": "checked", "leakage": "flagged", "inferred-flags": "flagged"},
     "inferred_flags": [{"dimension": "leakage", "unblock": "declare the train/test split block"}]},
    {"manager": "Delta", "metric": "total_return", "repo_verdict": "REFUTED",
     "family_scope": {"reproducibility": "checked", "baseline": "checked"}},
    {"manager": "Eps", "metric": "sharpe", "repo_verdict": "INCONCLUSIVE",
     "family_scope": {"reproducibility": "FAILED", "leakage": "not-verified"}},
]

# --- summarize ---
s = P.summarize(VS)
expect(s["n"] == 5 and s["clean"] == 2, "2 of 5 mandates are clean (CONFIRMED + CAVEATS)")
expect(s["counts"]["FLAG_FOR_DECLARATION"] == 1 and s["counts"]["REFUTED"] == 1 and s["counts"]["INCONCLUSIVE"] == 1,
       "verdict counts across the book")
expect(not s["all_clean"], "the book is not all-clean (there are catches)")
ar = [a["verdict"] for a in s["action_required"]]
expect(ar == ["REFUTED", "FLAG_FOR_DECLARATION", "INCONCLUSIVE"],
       "action-required = the non-clean mandates, loudest first (REFUTED > FLAG > CAN'T-CONFIRM): %s" % ar)
expect("2 CONFIRMED clean" in s["headline"] and "FLAG_FOR_DECLARATION" in s["headline"]
       and "CAN'T-CONFIRM" in s["headline"] and "REFUTED" in s["headline"],
       "the IC one-line headline: %r" % s["headline"])
flag_row = next(a for a in s["action_required"] if a["verdict"] == "FLAG_FOR_DECLARATION")
expect(flag_row["manager"] == "Gamma" and flag_row["inferred_flags"], "the FLAG mandate carries its inferred-flags (what to declare)")

# --- family heatmap ---
h = P.family_heatmap(VS)
expect("leakage" in h["families"] and "reproducibility" in h["families"], "heatmap unions the families across mandates")
gamma = next(r for r in h["rows"] if r["manager"] == "Gamma")
expect(gamma["cells"]["leakage"] == h["legend"]["flag-for-declaration"],
       "Gamma's leakage -> 🚩 flag-for-declaration (the inferred flag overrides the family status)")
alpha = next(r for r in h["rows"] if r["manager"] == "Alpha")
expect(alpha["cells"]["leakage"] == h["legend"]["checked"], "Alpha's leakage -> ✅ checked")
eps = next(r for r in h["rows"] if r["manager"] == "Eps")
expect(eps["cells"]["reproducibility"] == h["legend"]["not-assessed"], "Eps's FAILED reproducibility -> ⛔ not-assessed")

# --- an all-clean book ---
clean = P.summarize([{"manager": "X", "repo_verdict": "CONFIRMED", "family_scope": {}},
                     {"manager": "Y", "repo_verdict": "CONFIRMED-WITH-CAVEATS", "family_scope": {}}])
expect(clean["all_clean"] and not clean["action_required"] and clean["clean"] == 2,
       "an all-clean book -> all_clean, nothing action-required")
expect(P.summarize([])["headline"] == "no mandates", "an empty book is handled")

print("portfolio: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
