"""P1.3 acceptance tests -- ClaimGraph -> committed verify.yaml -> engine.verify.

This edge is PURE and deterministic (measure -> metric_id is the engine's own table), so it needs NO
record/replay LLM fixtures. The "fixture" is the btc_like TARGET (gen_fixture.py + runs/oos/*.csv):
the OOS returns compound to ~ -32%, so a "+14,698%" total-return claim is REFUTED on recompute, while
accuracy (0.90) and auc (1.0) reproduce. Each test runs in a fresh tmp copy so the committed fixture
stays clean and the engine's .calma run dirs never land in the repo. engine.verify subprocesses to the
system python3, so the BTC-like runtime is available even when pytest runs under the edges venv.
"""
import os
import shutil

import pytest

from edges.extract import to_contract as TC

FIXT_TARGET = os.path.join(os.path.dirname(__file__), "fixtures", "targets", "btc_like")


# --- claim/graph builders ----------------------------------------------------------------------
def _span(quote, section, element_type="output", page=None, bbox=None):
    return {"quote": quote, "section": section, "element_type": element_type,
            "page": page, "bbox": bbox}


def _claim(measure, value_text, confidence, *, file=None, column=None, quote="",
           section="cell 0", element_type="output"):
    return {
        "value": 0.0, "value_text": value_text, "measure": measure, "subject": "",
        "claimed_provenance": {"file": file, "column": column, "cell": section,
                               "computation": None, "formula_hint": None},
        "source_span": _span(quote or value_text, section, element_type),
        "confidence": confidence,
    }


def _three_claim_graph():
    """accuracy (CONFIRMED) + auc (CONFIRMED) + total_return (REFUTED)."""
    return {"claims": [
        _claim("accuracy", "0.90", 0.90, file="preds.csv",
               quote="accuracy = 0.90", section="cell 12"),
        _claim("auc", "1.0", 0.85, file="preds.csv",
               quote="AUC: 1.0", section="cell 13"),
        _claim("total_return", "+14,698%", 0.95, file="returns.csv",
               quote="+14,698% backtest", section="cell 14", element_type="code"),
    ]}


@pytest.fixture
def btc_like(tmp_path):
    dst = os.path.join(str(tmp_path), "btc_like")
    shutil.copytree(FIXT_TARGET, dst)
    return dst


def _metric(metrics, mid):
    return next((m for m in metrics if m.get("metric") == mid or m.get("metric_id") == mid), None)


# --- acceptance tests --------------------------------------------------------------------------
def test_contract_shape_three_metrics_one_headline(btc_like):
    path = TC.to_contract(_three_claim_graph(), btc_like)
    DC = TC._dc()
    contract = DC.load_contract(path)

    mets = contract["metrics"]
    assert len(mets) == 3
    for m in mets:
        assert isinstance(m.get("binding"), dict)          # a binding (possibly empty for the engine)
        assert m.get("claimed_value") is not None
        assert m.get("claimed_precision") is not None
    assert sum(1 for m in mets if m.get("headline")) == 1  # exactly one headline
    assert DC.validate_contract(contract) == []            # no structural errors
    # never write a grade stronger than author-asserted (regrade_committed upgrades from data)
    assert all(m["binding_status"] == "author-asserted" for m in mets)
    # the literal the author wrote is preserved as claimed_value (never guessed)
    tr = next(m for m in mets if m["metric_id"] == "total_return")
    assert abs(tr["claimed_value"] - 146.98) < 0.01


def test_end_to_end_refutes_total_return(btc_like):
    graph = _three_claim_graph()
    out = TC.verify_graph(graph, btc_like)
    res = out["engine"]

    assert res["verdict"] in ("REFUTED", "MIXED")
    tr = _metric(res["metrics"], "total_return")
    assert tr is not None and tr["verdict"] == "REFUTED"
    assert abs(tr["claimed"] - 146.98) < 0.01              # the claimed +14,698%
    assert -0.40 < tr["recomputed"] < -0.25                # OOS compounds to ~ -0.32

    # The engine owns the 'fix' field; for a clean value-mismatch REFUTED it is None (the btc asset
    # itself yields None -- fix_line only fires on an unblock/recompute_error/reason-table match). We
    # assert the field is part of the contract rather than asserting a value the engine never emits.
    assert "fix" in res


def test_regrade_protects_a_misextracted_binding(btc_like):
    """The model mis-binds AUC's score to logit_score (values NOT in [0,1]). regrade_committed caps
    that binding from the data; the engine must NOT manufacture a verdict from the wrong column."""
    graph = {"claims": [
        _claim("auc", "0.95", 0.7, file="preds.csv", column="logit_score",
               quote="AUC 0.95", section="cell 9"),
    ]}
    out = TC.verify_graph(graph, btc_like)

    led_claim = out["ledger"]["claims"][0]
    assert led_claim["input_binding_status"] != "independently-bound"   # capped (plausibly-bound)

    auc = _metric(out["engine"]["metrics"], "auc")
    assert auc is not None
    assert auc["verdict"] != "REFUTED"                     # NOT a false REFUTED from a wrong column
    assert auc["verdict"] in ("INCONCLUSIVE", "CONFIRMED-WITH-CAVEATS", "CAN'T-CONFIRM")
    # the recompute on the decoy column disagrees with the claim, yet no verdict flip occurred
    assert auc["recomputed"] is not None and abs(auc["recomputed"] - 0.95) > 0.1


# --- unit coverage of the pure resolver --------------------------------------------------------
def test_resolve_metric_id_uses_the_engine_table():
    assert TC.resolve_metric_id("accuracy", "0.94") == "accuracy"
    assert TC.resolve_metric_id("total_return", "+14,698%") == "total_return"
    assert TC.resolve_metric_id("AUC", "0.91") == "auc"
    assert TC.resolve_metric_id("macro_f1", "0.88") == "macro_f1"
    assert TC.resolve_metric_id("not a metric word", "0.5") is None


def test_unresolved_measure_is_dropped_not_guessed(btc_like):
    graph = {"claims": [
        _claim("total_return", "+14,698%", 0.9, file="returns.csv",
               quote="+14,698%", section="cell 14"),
        _claim("a mystery quantity", "0.42", 0.5, file="preds.csv",
               quote="mystery 0.42", section="cell 4"),
    ]}
    path = TC.to_contract(graph, btc_like)
    contract = TC._dc().load_contract(path)
    ids = [m["metric_id"] for m in contract["metrics"]]
    assert ids == ["total_return"]                         # the unresolved claim never enters the contract
