"""The metric×domain×tier scorecard (guide §A.4): the intake matrix renders, per-cell outcome aggregation is
correct, and the FCR cell is a hard gate that catches a planted false-confirm."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "optimize"))

import scorecard  # noqa: E402


def test_intake_matrix_renders_with_tiers():
    m = scorecard.corpus_matrix()
    md = scorecard.render(m, None)
    assert "domain \\ tier" in md and "T4" in md
    assert m["n"] >= 10


def _results():
    """A synthetic run_spike results dict spanning two cells, incl. one deliberate false-confirm."""
    return {"repos": [
        {"name": "a", "meta": {"domain": "finance", "tier": "T3"}, "ran": True, "n_calls": [1, 1],
         "claims": [{"verdict": "CONFIRMED", "expect": "CONFIRMED", "match": True, "bound": True,
                     "false_confirm": False}]},
        {"name": "b", "meta": {"domain": "finance", "tier": "T4"}, "ran": True, "n_calls": [1],
         "claims": [{"verdict": "INVALIDATED", "expect": "INVALIDATED", "match": True, "bound": True,
                     "false_confirm": False}]},
        {"name": "c", "meta": {"domain": "ml", "tier": "T1"}, "ran": False, "n_calls": [],
         "claims": [{"verdict": "INCONCLUSIVE", "expect": None, "match": True, "bound": False,
                     "false_confirm": False}]},
    ]}


def test_score_results_aggregates_per_cell():
    cells = scorecard.score_results(_results())
    fin_t3 = cells[("finance", "T3")]
    assert fin_t3["repos"] == 1 and fin_t3["ran"] == 1 and fin_t3["captured"] == 1
    assert fin_t3["bound"] == 1 and fin_t3["graded"] == 1 and fin_t3["matches"] == 1
    assert fin_t3["verdicts"]["CONFIRMED"] == 1
    ml_t1 = cells[("ml", "T1")]
    assert ml_t1["ran"] == 0 and ml_t1["captured"] == 0
    assert scorecard.fcr_breaches(cells) == []          # clean corpus → no breach


def test_fcr_gate_catches_a_planted_false_confirm():
    res = _results()
    res["repos"][1]["claims"][0].update(verdict="CONFIRMED", false_confirm=True)  # T4 negative wrongly confirmed
    cells = scorecard.score_results(res)
    breaches = scorecard.fcr_breaches(cells)
    assert breaches and breaches[0]["cell"] == "finance/T4" and breaches[0]["false_confirms"] == 1
    md = scorecard.render(scorecard.corpus_matrix(), cells)
    assert "❌ FAIL" in md                                 # the gate visibly fails in the report
