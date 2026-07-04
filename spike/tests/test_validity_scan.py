"""validity_scan — the no-reproduction report card (the GTM validity wedge). Grades a repo on leakage /
trivial-baseline / committed-predictions misreport WITHOUT running it. Fail-closed: nothing to check is
INCOMPLETE, never a false PASS or a false verdict."""
import os

import validity_scan as VS

FIX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def test_committed_leakage_fails(tmp_path):
    (tmp_path / "data_train.csv").write_text("seq,label\nAAAA,0\nBBBB,1\nCCCC,0\nEEEE,1\n")
    (tmp_path / "data_test.csv").write_text("seq,label\nAAAA,0\nBBBB,1\nDDDD,0\n")   # AAAA,BBBB leaked
    card = VS.scan(str(tmp_path))
    assert card["grade"] == "FAIL", card
    leak = next(c for c in card["checks"] if c["name"] == "leakage")
    assert leak["status"] == "fail" and leak["findings"]


def test_committed_prediction_misreport_fails(tmp_path):
    (tmp_path / "results").mkdir()
    # predictions give accuracy 0.5 (y_pred all 0 on balanced labels); README claims 95%
    rows = "".join("%d,0\n" % (i % 2) for i in range(10))
    (tmp_path / "results" / "predictions.csv").write_text("y_true,y_pred\n" + rows)
    (tmp_path / "README.md").write_text("Test accuracy: 95%\n")
    card = VS.scan(str(tmp_path))
    assert card["grade"] == "FAIL", card
    mis = next(c for c in card["checks"] if c["name"] == "misreport")
    assert mis["status"] == "fail" and mis["findings"]


def test_honest_committed_predictions_pass():
    # the committed_preds fixture reports numbers that match its predictions.csv -> clean bill
    card = VS.scan(os.path.join(FIX, "committed_preds"))
    assert card["grade"] == "PASS", card
    assert not any(c["status"] == "fail" for c in card["checks"])


def test_nothing_to_check_is_incomplete(tmp_path):
    # a repo with only prose and no committed data/predictions -> honest INCOMPLETE, not a false PASS
    (tmp_path / "README.md").write_text("A project. No data or predictions committed.\n")
    card = VS.scan(str(tmp_path))
    assert card["grade"] == "INCOMPLETE", card


def test_bare_external_claim_is_not_refuted(tmp_path):
    # a claim handed in (as a stop-hook would) with no committed artifact behind it must not become a
    # misreport FAIL — you can't refute a number nothing produced.
    (tmp_path / "README.md").write_text("notes only\n")
    card = VS.scan(str(tmp_path), claims=[{"metric": "accuracy", "value": "0.89", "id": "hook"}])
    assert card["grade"] != "FAIL", card
    mis = next(c for c in card["checks"] if c["name"] == "misreport")
    assert mis["status"] != "fail"
