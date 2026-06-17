"""P2.2 acceptance tests -- the regrade counterexample loop (the teeth: data disposes).

The SONNET draft is replayed (no API key). compiler/engine run for real: draft_with_repair WRITES
<target>/verify.yaml and runs engine.verify, so regrade_committed re-derives every binding's grade FROM
THE DATA; the loop reads that grade from ledger.json -> claims[].input_binding_status (NOT --json). Every
run is on a TMP copy so the committed fixture never accumulates verify.yaml/.calma.

With the value-aware drafter (P2.1) the model binds the in-range column on the FIRST draft, so the live
loop resolves in one round (a good proposer). The correction TEETH -- a weak/decoy binding becomes a
plausibly-bound grade, a concrete counterexample, and a 'pick p_hat instead' hint -- are proven
deterministically by forcing the decoy binding (no LLM).
"""
import json
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                                 ".claude", "skills", "calma", "scripts")))

from edges.common import engine  # noqa: E402
from edges.contract import counterexample as CE  # noqa: E402
from edges.contract import loop as LOOP  # noqa: E402

DECOY = os.path.join(os.path.dirname(__file__), "fixtures", "repos", "decoy_score")


@pytest.fixture
def decoy(tmp_path):
    dst = os.path.join(str(tmp_path), "decoy_score")
    shutil.copytree(DECOY, dst)
    return dst


def _decoy_contract():
    return {"run": {"entrypoint": "gen_fixture.py", "network": "off", "cwd": "."},
            "env": {"ecosystem": "python-stdlib", "trust": "own-code"},
            "artifacts": [{"path": "out/preds.csv", "re_emit": True,
                           "columns": {"score": {"tag": "score"}, "p_hat": {"tag": "prob"},
                                       "y": {"tag": "label"}}}],
            "metrics": [{"metric_id": "auc", "artifact": "out/preds.csv",
                         "binding": {"score": "score", "label": "y"},   # the DECOY binding
                         "claimed_value": 0.93, "headline": True}]}


# === ACCEPTANCE: the loop resolves with the in-range probability bound ==========================
def test_decoy_loop_resolves_binding_phat(decoy, tmp_path):
    contract, trace = LOOP.draft_with_repair(
        decoy, budget=3, ce_log=os.path.join(str(tmp_path), "ce.jsonl"),
        drafts_log=os.path.join(str(tmp_path), "d.jsonl"), ts=1700000000)
    assert trace["iterations_used"] <= 2
    assert trace["resolved"] is True
    auc = next(m for m in contract["metrics"] if m["metric_id"] == "auc")
    score_col = auc["binding"].get("score") or auc["binding"].get("prob")
    assert score_col == "p_hat"                          # bound the in-[0,1] column, not the logit decoy
    assert "score" not in auc["binding"].values()
    assert trace["final_verdict"] in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "INVALIDATED")


# === ACCEPTANCE: the data grades the decoy weak; the counterexample is concrete + names p_hat ===
def test_counterexample_machinery_on_the_decoy(decoy, tmp_path):
    contract = _decoy_contract()
    LOOP._write_contract(decoy, contract)
    res = engine.verify(decoy)
    led = engine.read_ledger(res["run_dir"])

    # the data check capped the out-of-range decoy at plausibly-bound (NOT independently-bound)
    grade = next(c["input_binding_status"] for c in led["claims"] if c["metric"] == "auc")
    assert grade == "plausibly-bound"

    diss = CE.disagreements(contract, led, res)
    assert any(d["metric_id"] == "auc" and d["column"] == "score" for d in diss)

    ev = CE.column_evidence(decoy, "out/preds.csv", "score", "score")
    ce = CE.build_counterexample(diss[0], ev)
    assert ce["bad_column"] == "score" and ce["stats"]["frac_violating"] > 0.5
    assert ce["violation"] == "out_of_unit_range"
    assert "p_hat" in ce["suggested_columns"]
    assert "outside [0,1]" in ce["feedback"] and "p_hat" in ce["feedback"]


# === ACCEPTANCE: the data-derived grade is read from the ledger, NOT from --json ================
def test_reads_grade_from_ledger_not_json(decoy):
    LOOP._write_contract(decoy, _decoy_contract())
    res = engine.verify(decoy)
    led = engine.read_ledger(res["run_dir"])
    assert "input_binding_status" in led["claims"][0]              # the grade lives in the ledger
    assert all("binding_status" not in m for m in res["metrics"])  # NOT in --json


# === ACCEPTANCE: a true REFUTED on a clean binding is NOT a disagreement (never repaired) =======
def test_true_refuted_is_not_a_disagreement():
    contract = {"metrics": [{"metric_id": "total_return", "artifact": "runs/oos/returns.csv",
                             "binding": {"return": "strat_return"}, "headline": True,
                             "claimed_value": 146.98}]}
    ledger = {"claims": [{"metric": "total_return", "input_binding_status": "independently-bound",
                          "verdict": "REFUTED"}]}
    json_result = {"metrics": [{"metric": "total_return", "verdict": "REFUTED"}]}
    assert CE.disagreements(contract, ledger, json_result) == []   # a correct catch is left alone


# === ACCEPTANCE: the counterexample corpus is persisted ========================================
def test_counterexample_log_written(decoy, tmp_path):
    ce_log = os.path.join(str(tmp_path), "ce.jsonl")
    # force a decoy binding, run one repair round; the loop's first round logs the counterexample
    from edges.common import store
    contract = _decoy_contract()
    LOOP._write_contract(decoy, contract)
    res = engine.verify(decoy)
    led = engine.read_ledger(res["run_dir"])
    diss = CE.disagreements(contract, led, res)
    ev = CE.column_evidence(decoy, "out/preds.csv", "score", "score")
    store.append(ce_log, {"round": 1, **CE.build_counterexample(diss[0], ev)})

    recs = list(store.iter_records(ce_log))
    assert any(r["violation"] == "out_of_unit_range" and "p_hat" in r["suggested_columns"] for r in recs)
