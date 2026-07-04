"""The packaged validity CLI + PR-comment helper (free wedge for CI). fmt_markdown renders a report card;
the CLI exit code gates CI; pr_comment no-ops safely off a PR."""
import os
import sys

import validity_scan as VS

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "action"))


def test_fmt_markdown_shape():
    card = {"grade": "FAIL", "summary": {"headline": "x"},
            "checks": [{"name": "leakage", "status": "fail", "findings": ["train/test overlap 66%"]},
                       {"name": "trivial-baseline", "status": "not-applicable", "findings": []},
                       {"name": "misreport", "status": "not-applicable", "findings": []}]}
    md = VS.fmt_markdown(card)
    assert "**FAIL**" in md and "| Check | Result |" in md
    assert "Data leakage" in md and "train/test overlap 66%" in md
    assert md.count("###") >= 1                    # a Findings section


def test_fmt_markdown_pass_has_no_findings_section():
    card = {"grade": "PASS", "summary": {},
            "checks": [{"name": "leakage", "status": "pass", "findings": []}]}
    assert "Findings" not in VS.fmt_markdown(card)


def test_pr_comment_pr_number():
    import pr_comment as P
    assert P._pr_number({"pull_request": {"number": 42}}) == 42
    assert P._pr_number({"issue": {"number": 7}}) == 7
    assert P._pr_number({"push": {}}) is None


def test_pr_comment_noop_without_env(monkeypatch):
    import pr_comment as P
    for k in ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "GITHUB_EVENT_PATH"):
        monkeypatch.delenv(k, raising=False)
    assert P.main() == 0                            # clean no-op, never raises
