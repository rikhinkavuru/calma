"""The corpus intake rubric as a hard CI gate (guide §A.2).

The corpus is a MEASUREMENT INSTRUMENT for a verifier, so its shape must itself be auditable: every repo
declares domain/tier/split/license/commit_date, and the corpus must be describable as a distribution
(n per domain × tier) — not an opportunistic list. A repo that slips in without a `meta` block, or with an
out-of-vocabulary tier, breaks the build here rather than silently skewing the scorecard.
"""
import corpus  # noqa: E402  (spike root on sys.path via conftest)


def test_every_repo_conforms_to_the_intake_rubric():
    errs = corpus.validate()
    assert errs == [], "corpus intake violations:\n  " + "\n  ".join(errs)


def test_corpus_is_describable_as_a_distribution():
    d = corpus.distribution()
    assert d["n"] >= 10
    # not an 'iris trap' of a single tier: at least the trivial floor + the adversarial proof both present.
    assert d["by_tier"].get("T1", 0) > 0, d["by_tier"]
    assert d["by_tier"].get("T4", 0) > 0, "a corpus with no T4 negatives cannot prove FCR=0"


def test_t4_negatives_span_the_verdict_taxonomy():
    """The T4 tier's job is to continuously falsify FCR=0, so its graded negatives must exercise MORE than one
    failure mode (a corpus that only tests REFUTED can't catch an INVALIDATED false-confirm)."""
    t4_expects = {claim.get("expect") for _n, m, claim in corpus.graded_claims() if m["tier"] == "T4"}
    # every graded T4 claim is a NON-confirm expectation (a positive-confirm graded T4 would be a mislabel)
    assert t4_expects and t4_expects.issubset(set(corpus.NON_CONFIRM_EXPECTS)), t4_expects
    assert len(t4_expects) >= 2, "T4 must span multiple failure modes, saw only %s" % t4_expects


def test_dev_test_split_is_present():
    """Anti-overfit hygiene (guide §A.5): a locked `test` slice must exist so heuristics can't be tuned on
    everything. (Small now; grows with the corpus.)"""
    d = corpus.distribution()
    assert d["by_split"].get("dev", 0) > 0
    assert "test" in d["by_split"], "no locked test split — every repo is tunable-against (overfit risk)"
