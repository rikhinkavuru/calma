"""The rebuilt stop-hook guardrail. The load-bearing property: intake is fail-closed — a bare number in a
message with no producing artifact in the repo is INCOMPLETE, never REFUTED (the old hook's bug). It still
catches a real committed-prediction misreport."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hook"))

import hook_stop as H


def test_bare_number_in_message_is_not_refuted(tmp_path):
    # a repo with no committed data/predictions; the message brags a number -> guardrail must NOT refute it.
    (tmp_path / "README.md").write_text("notes\n")
    card = H.evaluate("Final test accuracy: 0.89 — great result!", str(tmp_path))
    assert card is not None and card["grade"] != "FAIL", card


def test_message_with_no_metric_is_a_noop(tmp_path):
    assert H.evaluate("All done, shipped the feature.", str(tmp_path)) is None


def test_no_repo_is_a_noop():
    assert H.evaluate("accuracy 0.99", "/nonexistent/path/xyz") is None


def test_real_committed_misreport_is_caught(tmp_path):
    # predictions give accuracy 0.5; the message claims 95% -> a real catch through the hook.
    (tmp_path / "results").mkdir()
    rows = "".join("%d,0\n" % (i % 2) for i in range(10))
    (tmp_path / "results" / "predictions.csv").write_text("y_true,y_pred\n" + rows)
    card = H.evaluate("We reach a test accuracy of 95% on the benchmark.", str(tmp_path))
    assert card is not None and card["grade"] == "FAIL", card
    assert any(c["name"] == "misreport" and c["status"] == "fail" for c in card["checks"])
