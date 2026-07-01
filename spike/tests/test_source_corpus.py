"""The automated corpus-sourcing pipeline (guide §A.6, P4). The network stages are gated/best-effort; the
PURE core — cheap filters, freshness classification, Stage-5 stub emission, graceful offline degradation —
is the testable surface and must be exactly right (it decides what enters the measurement instrument).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "optimize"))

import source_corpus as SC  # noqa: E402


def test_cheap_filter_accepts_a_good_candidate():
    repo = {"license": "MIT", "size_kb": 1200,
            "readme": "Our model reaches 96.67% accuracy on the test set."}
    ok, reasons = SC.cheap_filter(repo)
    assert ok, reasons


def test_cheap_filter_rejects_nonpermissive_license_oversize_and_no_number():
    assert not SC.cheap_filter({"license": "GPL-3.0", "size_kb": 100, "readme": "acc 0.99"})[0]
    assert not SC.cheap_filter({"license": "MIT", "size_kb": 9_000_000, "readme": "acc 0.99"})[0]
    # a README with no metric-word+number pair is cut before spending LLM tokens
    assert not SC.cheap_filter({"license": "MIT", "size_kb": 100, "readme": "a nice project, see docs"})[0]


def test_has_reported_number_needs_metric_word_and_a_number():
    assert SC.has_reported_number("Sharpe ratio of 1.83 over the backtest")
    assert SC.has_reported_number("BLEU = 34.20 on WMT")
    assert not SC.has_reported_number("version 2.0.1 released today")     # a version number, no metric word
    assert not SC.has_reported_number("high accuracy achieved")           # a metric word, no number


def test_freshness_post_cutoff_classification():
    assert SC.is_post_cutoff("2026-03-01", cutoff="2025-10-01") is True
    assert SC.is_post_cutoff("2024-01-01", cutoff="2025-10-01") is False
    assert SC.is_post_cutoff("unknown") is False                          # conservative on unknown dates


def test_stage5_stub_is_a_valid_corpus_entry():
    import corpus as CORP  # noqa: E402  (spike root on sys.path via conftest)
    repo = {"name": "owner__repo", "url": "https://github.com/owner/repo.git", "commit": "abc123",
            "domain": "finance", "license": "MIT", "commit_date": "2026-02-15"}
    stub = SC.repos_yaml_stub(repo, tier="T2", split="test")
    # the stub must pass the same intake rubric a hand-authored entry does (guide §A.2)
    errs = CORP.validate([stub])
    assert errs == [], errs
    assert stub["meta"]["post_cutoff"] is True and stub["discover"] is True


def test_pipeline_degrades_gracefully_offline(monkeypatch):
    """With no GITHUB_TOKEN the search no-ops → an empty, well-formed queue (never an error)."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    res = SC.run(domains=["finance"], per_query=5)
    assert res["stats"]["searched"] == 0 and res["stage5_queue"] == []


def test_github_search_gated_without_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert SC.github_search("topic:quant-finance language:python") == []
