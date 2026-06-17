"""P4.2 acceptance tests -- isolated, revertible repair scratch (SWE-Adept semantic-step checkpointing).

Pure git plumbing, no LLM: the suite needs no ANTHROPIC_API_KEY and no fixtures. Develops against the
bundled btc asset as a stand-in 'target'. The load-bearing invariant: the user's working tree is NEVER
mutated -- all repair edits happen on a throwaway clone, and a dead-end leaves no residue.
"""
import hashlib
import os

from edges.repair import checkpoints as CK

BTC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                   ".claude", "skills", "calma", "assets", "btc"))

_ONE_LINE_DIFF = (
    "--- a/gen_fixture.py\n"
    "+++ b/gen_fixture.py\n"
    "@@ -1,1 +1,1 @@\n"
    "-#!/usr/bin/env python3\n"
    "+#!/usr/bin/env python3  # calma-repair touch\n"
)


def _hash_tree(root, exclude=(".calma", ".git", "__pycache__", ".pytest_cache")):
    """A content hash of every file under root (sorted), skipping calma/vcs/cache noise."""
    h = hashlib.sha256()
    for dp, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in exclude)
        for n in sorted(names):
            p = os.path.join(dp, n)
            rel = os.path.relpath(p, root)
            h.update(rel.encode())
            try:
                with open(p, "rb") as fh:
                    h.update(fh.read())
            except OSError:
                pass
    return h.hexdigest()


def test_scratch_is_isolated_and_leaves_target_untouched():
    before = _hash_tree(BTC)
    scratch = CK.make_scratch(BTC)
    try:
        # the scratch is NOT under the original target
        assert not os.path.realpath(scratch).startswith(os.path.realpath(BTC) + os.sep)
        # edit + revert on the scratch
        base = CK.checkpoint(scratch)
        assert CK.apply_diff(scratch, _ONE_LINE_DIFF) is True
        CK.revert(scratch, base)
        # the ORIGINAL target is byte-identical (the user's tree was never touched)
        assert _hash_tree(BTC) == before
    finally:
        CK.cleanup_scratch(scratch)
        assert not os.path.exists(scratch)               # cleanup removes the scratch


def test_competing_hypotheses_do_not_contaminate_the_base():
    scratch = CK.make_scratch(BTC)
    try:
        base = CK.checkpoint(scratch)
        base_tree = _hash_tree(scratch)

        CK.branch_for_hypothesis(scratch, 0)
        CK.revert(scratch, base)
        assert CK.apply_diff(scratch, _ONE_LINE_DIFF) is True
        CK.revert(scratch, base)
        assert _hash_tree(scratch) == base_tree          # hyp 0 left no residue

        CK.branch_for_hypothesis(scratch, 1)
        CK.revert(scratch, base)
        assert _hash_tree(scratch) == base_tree          # base unchanged across hypotheses
    finally:
        CK.cleanup_scratch(scratch)


def test_apply_diff_empty_is_noop_and_diff_since_reports_the_real_change():
    scratch = CK.make_scratch(BTC)
    try:
        base = CK.checkpoint(scratch)
        assert CK.apply_diff(scratch, "") is False        # empty diff = no-op
        assert CK.apply_diff(scratch, "   \n  ") is False  # whitespace-only = no-op
        assert CK.apply_diff(scratch, _ONE_LINE_DIFF) is True
        applied = CK.diff_since(scratch, base)
        assert "calma-repair touch" in applied            # diff_since shows exactly the applied change
        assert "gen_fixture.py" in applied
    finally:
        CK.cleanup_scratch(scratch)
