"""B2: rendering - every verdict word + number copied from the engine, INVALIDATED phrased distinctly,
the check-run conclusion a pure function of the verdicts. No network."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))
from pr import render as R  # noqa: E402


def _finding(verdict, **kw):
    base = {"metric_id": "total_return", "verdict": verdict, "claimed": 1.47, "recomputed": -0.316,
            "citation": "cell 5 says 147.0x → recomputes to −31.6% [notebook cell 5]",
            "reason": "recomputed value differs beyond the calibrated budget",
            "file": "report.ipynb", "line": 12, "fingerprint": "ab12cd34"}
    base.update(kw)
    return base


def _bundle(targets):
    return {"schema": "calma/pr-findings@1", "pr_number": 7, "head_sha": "h", "base_sha": "b",
            "targets": targets}


def _target(verdict, findings, **kw):
    t = {"target": "results/btc", "kind": "contract", "repo_verdict": verdict, "summary": "1 refuted",
         "isolation_tier": "seatbelt-verified", "determinism_mode": "controlled-to-bit",
         "findings": findings, "fix": "report the net-of-cost return"}
    t.update(kw)
    return t


def test_inline_body_copies_engine_words():
    body = R.inline_body(_finding("REFUTED"), "seatbelt-verified")
    assert "**REFUTED**" in body
    assert "recomputes to −31.6%" in body                 # the citation is verbatim
    assert "claimed 1.47 → recomputed -0.316" in body
    assert "Reason: recomputed value differs" in body
    assert "seatbelt-verified isolation" in body
    assert "calma:fp=ab12cd34" in body                    # the idempotency marker


def test_invalidated_reads_distinctly():
    body = R.inline_body(_finding("INVALIDATED", citation="survivorship-free claim violated"))
    assert "**INVALIDATED**" in body and "reproduces, but not a valid result" in body


def test_flag_for_declaration_reads_distinctly_and_is_a_catch():
    body = R.inline_body(_finding("FLAG_FOR_DECLARATION", citation="inferred train/test split, 28% row overlap"))
    assert "**FLAG_FOR_DECLARATION**" in body and "declare the named block to resolve" in body
    assert R.is_catch(_finding("FLAG_FOR_DECLARATION")) is True


def test_check_conclusion_is_pure_function_of_verdicts():
    assert R.check_conclusion(_bundle([_target("REFUTED", [_finding("REFUTED")])])) == "failure"
    assert R.check_conclusion(_bundle([_target("INVALIDATED", [_finding("INVALIDATED")])])) == "failure"
    # a FLAG_FOR_DECLARATION blocks the merge gate (CANONICAL §3: it maps to a failing check conclusion)
    assert R.check_conclusion(_bundle([_target("FLAG_FOR_DECLARATION",
                                               [_finding("FLAG_FOR_DECLARATION")])])) == "failure"
    assert R.check_conclusion(_bundle([_target("INCONCLUSIVE", [])])) == "neutral"
    assert R.check_conclusion(_bundle([_target("CONFIRMED", [])])) == "success"


def test_review_comments_only_catches_with_a_line():
    b = _bundle([_target("MIXED", [
        _finding("REFUTED", fingerprint="aa"),
        _finding("CONFIRMED", fingerprint="bb"),          # not a catch -> no inline
        _finding("REFUTED", fingerprint="cc", file=None, line=None)])])   # no anchor -> summary, not inline
    cs = R.review_comments(b)
    assert len(cs) == 1 and cs[0]["fingerprint"] == "aa" and cs[0]["side"] == "RIGHT"
    # the only_fingerprints filter (incremental): nothing new -> no comments
    assert R.review_comments(b, only_fingerprints=set()) == []


def test_summary_has_table_fix_and_marker():
    body = R.summary_body(_bundle([_target("REFUTED", [_finding("REFUTED")])]))
    assert "| target | verdict | catches |" in body and "`results/btc`" in body and "REFUTED" in body
    assert "**Fix:**" in body and "calma:summary" in body and "seatbelt-verified" in body
