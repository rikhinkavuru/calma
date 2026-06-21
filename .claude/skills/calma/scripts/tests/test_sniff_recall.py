"""CR1/CR2 regression corpora for the zero-touch sniffer.

  recall  - the 12-phrasing probe set (incl. the 3 the autonomy probe caught MISSING:
            bare-decimal return, the "94% accurate" adjective, the literal `total_return 0.35`)
            must all BIND, and every emitted claim must re-parse to the same metric+value.
  precision - the false-positive traps must stay at ZERO fires, so recall was not bought with
            precision (this corpus + recall are the permanent guard the plan calls for).
  near-miss - a result-shaped number next to a metric word that misses only a soft gate is
            surfaced as a near-miss (CR1's visible "couldn't bind" signal); hard non-claims aren't.
  coverage - the hook coverage line tells the truth about 1-of-N (CR2).

Pure stdlib, offline. Run: python3 test_sniff_recall.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import sniff_claims as SN  # noqa: E402
import draft_contract as DC  # noqa: E402
import hook_stop as HK  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- RECALL: 12 phrasings, all must bind; the last 3 are the probe's documented misses ---
RECALL = [
    ("final accuracy is 0.91", "accuracy", 0.91),
    ("AUC 0.94 on the holdout", "auc", 0.94),
    ("the model hit an F1 of 0.88", "f1", 0.88),
    ("RMSE: 12.4", "rmse", 12.4),
    ("sharpe came in at 1.8", "sharpe", 1.8),
    ("Done! The backtest returned +19,971% over the period.", "total_return", 199.71),
    ("the portfolio returned 23%", "total_return", 0.23),
    ("recall@10 was 0.72", "recall_at_k", 0.72),
    ("p95 latency 120ms", "latency_p95", 120.0),
    ("the strategy total return is 0.35", "total_return", 0.35),     # (a) bare-decimal return
    ("the model is 94% accurate", "accuracy", 0.94),                 # (b) adjective form
    ("total_return 0.35", "total_return", 0.35),                     # (c) literal snake_case
]
bound = 0
for text, want_metric, want_value in RECALL:
    cands = SN.sniff(text)
    hit = next((c for c in cands if c["metric"] == want_metric), None)
    if hit is None:
        truth(False, "recall: %r should bind %s" % (text, want_metric))
        continue
    bound += 1
    truth(abs(hit["value"] - want_value) < 1e-6,
          "recall: %r value %s == %s" % (text, hit["value"], want_value))
    # round-trip: the emitted claim string re-parses to the same metric + value
    pv, ph = DC.parse_claim(hit["claim"])
    truth(ph == want_metric and pv is not None and abs(pv - want_value) < 1e-6,
          "round-trip: claim %r -> (%s, %s)" % (hit["claim"], pv, ph))
truth(bound == len(RECALL), "recall: all %d phrasings bind (%d did)" % (len(RECALL), bound))

# --- PRECISION: the trap corpus must stay silent (0 fires) ---
NEGATIVES = [
    "set the toxiproxy latency to 500ms",
    "the CSS margin is 8px",
    "I refactored 5% of the commits",
    "precision is 0.001 after rounding floats",
    "the return code is 0",
    "exact match on 5 byte-identical files",
    "we should target accuracy 0.95 next",
    "baseline accuracy was 0.80",
    "is the accuracy 0.9?",
    "the function returns 5 items",
    "python 3.14 with 12 tests",
    "the summary is 100% accurate",        # colloquial adjective, no ML subject
    "my answer is 95% accurate",
    "the function return is 0.5",          # bare 'return', no finance subject
]
fires = [t for t in NEGATIVES if SN.sniff(t)]
truth(not fires, "precision: trap corpus stays silent (fired on: %s)" % fires)

# --- NEAR-MISS: soft-gate misses are surfaced; hard non-claims are not ---
_, near = SN.sniff("the function return is 0.5", with_near=True)
truth(any(n["reason"] == "no-finance-subject" and n["value"] == "0.5" for n in near),
      "near-miss: bare 'return 0.5' (no finance subject) is a near-miss")
_, near2 = SN.sniff("accuracy 7.3", with_near=True)
truth(any(n["metric"] == "accuracy" for n in near2),
      "near-miss: an out-of-range accuracy is a near-miss")
_, near3 = SN.sniff("precision is 0.001 after rounding floats", with_near=True)
truth(near3 == [], "near-miss: a domain-denied number is NOT a near-miss (no nag)")
_, near4 = SN.sniff("python 3.14 with 12 tests", with_near=True)
truth(near4 == [], "near-miss: a version/count number is NOT a near-miss")
# a bound claim suppresses a duplicate near-miss for the same value
claims5, near5 = SN.sniff("the strategy total return is 0.35", with_near=True)
truth(claims5 and not any(n["value_key"] == 0.35 and n["metric"] == "total_return"
                          for n in near5),
      "near-miss: a value that BOUND is not also reported as a near-miss")

# --- COVERAGE LINE (CR2): honest 1-of-N + the all-checked phrasing ---
tally = {"verdicts": {"CONFIRMED": 1}, "timeout": 0, "error": 0}
line_headline = HK._coverage_line(tally, 120, detected=4, max_claims=1)
truth("1 of 4" in line_headline and "CALMA_VERIFY=all" in line_headline,
      "coverage: headline mode says '1 of 4' + points at CALMA_VERIFY=all")
line_all = HK._coverage_line(tally, 120, detected=1, max_claims=1)
truth("of " not in line_all and "checked 1 number this turn" in line_all,
      "coverage: detected==checked keeps the plain phrasing")
line_scope_all = HK._coverage_line({"verdicts": {"CONFIRMED": 4}, "timeout": 0, "error": 0},
                                   120, detected=4, max_claims=5)
truth("CALMA_VERIFY=all" not in line_scope_all,
      "coverage: when the budget covered everything, no upsell")

# --- NEAR-MISS LINE shape ---
nl = HK._near_miss_line([{"value": "0.35", "term": "return", "metric": "total_return"}])
truth("couldn't auto-verify" in nl and "0.35" in nl and "calma verify" in nl,
      "near-miss line names the number + the next step")

print("sniff-recall (CR1/CR2): %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
