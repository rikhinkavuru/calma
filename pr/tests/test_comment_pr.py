"""B2: the privileged commenter, against a MOCK GitHub client (records calls; no network). ONE batched
review per run, idempotent (same head -> nothing new), incremental (a new push comments only the delta;
a vanished catch is resolved), and the check-run conclusion is a pure function of the engine verdicts.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))
from pr import comment_pr as C  # noqa: E402
from pr import render as R  # noqa: E402


class MockGitHub:
    def __init__(self, comments=None, summary=None, threads=None):
        self.calls = []
        self._comments = comments or []   # existing bot inline comments (carry calma:fp markers)
        self._summary = summary           # existing summary comment {id, body} or None
        self._threads = threads or []
        self.reviews = []

    def list_bot_review_comments(self):
        return list(self._comments)

    def find_summary_comment(self):
        return self._summary

    def create_review(self, commit_id, event, body, comments):
        self.calls.append(("create_review", len(comments)))
        self.reviews.append({"commit_id": commit_id, "event": event, "comments": comments})
        return {"id": 100}

    def create_summary_comment(self, body):
        self.calls.append(("create_summary", None))
        return {"id": 9, "body": body}

    def update_summary_comment(self, comment_id, body):
        self.calls.append(("update_summary", comment_id))
        return {"id": comment_id, "body": body}

    def create_check_run(self, head_sha, conclusion, output):
        self.calls.append(("check_run", conclusion))
        return {"id": 5}

    def review_threads(self):
        return list(self._threads)

    def resolve_thread(self, thread_id):
        self.calls.append(("resolve", thread_id))
        return {}

    def names(self):
        return [c[0] for c in self.calls]


def _finding(verdict, fp, **kw):
    base = {"metric_id": "total_return", "verdict": verdict, "claimed": 1.47, "recomputed": -0.32,
            "citation": "cell 5 says 147.0x → recomputes to −31.6% [notebook cell 5]",
            "reason": "differs beyond budget", "file": "report.ipynb", "line": 12, "fingerprint": fp}
    base.update(kw)
    return base


def _bundle(repo_verdict, findings, head="h1"):
    return {"schema": "calma/pr-findings@1", "pr_number": 7, "head_sha": head, "base_sha": "b",
            "targets": [{"target": "results/btc", "kind": "contract", "repo_verdict": repo_verdict,
                         "summary": "s", "isolation_tier": "seatbelt-verified",
                         "determinism_mode": "controlled-to-bit", "findings": findings,
                         "fix": "report the net return"}]}


def test_one_refuted_one_confirmed_posts_one_inline_and_failing_check():
    gh = MockGitHub()
    b = _bundle("MIXED", [_finding("REFUTED", "aa"), _finding("CONFIRMED", "bb")])
    res = C.run(gh, b)
    assert res["ok"]
    # exactly ONE create_review, carrying exactly ONE inline comment (the REFUTED)
    assert gh.names().count("create_review") == 1
    assert len(gh.reviews) == 1 and len(gh.reviews[0]["comments"]) == 1
    assert "calma:fp=aa" in gh.reviews[0]["comments"][0]["body"]
    assert "create_summary" in gh.names()
    assert ("check_run", "failure") in gh.calls


def test_idempotent_rerun_posts_nothing_new():
    # the REFUTED comment already exists (its fp marker present) -> no new review
    existing = [{"body": "**REFUTED** … calma:fp=aa"}]
    gh = MockGitHub(comments=existing, summary={"id": 9, "body": "old " + R.SUMMARY_MARK})
    res = C.run(gh, _bundle("REFUTED", [_finding("REFUTED", "aa")]))
    assert res["new_findings"] == 0
    assert gh.names().count("create_review") == 0          # idempotent: nothing new to post
    assert "update_summary" in gh.names()                  # the summary is PATCHed in place, not re-created
    assert ("check_run", "failure") in gh.calls


def test_incremental_only_the_new_comment():
    # fp=aa already posted; a new push adds fp=cc -> a review with ONLY the new comment
    gh = MockGitHub(comments=[{"body": "calma:fp=aa"}])
    b = _bundle("MIXED", [_finding("REFUTED", "aa"), _finding("REFUTED", "cc")], head="h2")
    C.run(gh, b)
    assert gh.names().count("create_review") == 1
    bodies = [c["body"] for c in gh.reviews[0]["comments"]]
    assert len(bodies) == 1 and "calma:fp=cc" in bodies[0]


def test_resolve_on_fix():
    # a thread for fp=gone exists; the new bundle no longer contains it -> resolveReviewThread
    gh = MockGitHub(threads=[{"id": "PRRT_1", "isResolved": False, "fingerprints": ["gone"]},
                             {"id": "PRRT_2", "isResolved": False, "fingerprints": ["aa"]}])
    C.run(gh, _bundle("REFUTED", [_finding("REFUTED", "aa")]))
    assert ("resolve", "PRRT_1") in gh.calls               # the vanished catch is resolved
    assert ("resolve", "PRRT_2") not in gh.calls           # the still-present one is left alone


def test_invalidated_phrasing_and_cant_confirm_neutral():
    gh = MockGitHub()
    C.run(gh, _bundle("INVALIDATED", [_finding("INVALIDATED", "ii", citation="held-out claim violated")]))
    assert "reproduces, but not a valid result" in gh.reviews[0]["comments"][0]["body"]
    assert ("check_run", "failure") in gh.calls
    gh2 = MockGitHub()
    C.run(gh2, _bundle("INCONCLUSIVE", [_finding("INCONCLUSIVE", "nn", file=None, line=None)]))
    assert ("check_run", "neutral") in gh2.calls


def test_bundle_is_data_never_executed_or_shell_interpolated():
    # a malicious citation/reason is rendered as TEXT (inside a markdown comment), never executed
    gh = MockGitHub()
    evil = _finding("REFUTED", "ev", citation="$(rm -rf /) `whoami` ${HOME}", reason="; drop table")
    C.run(gh, _bundle("REFUTED", [evil]))
    body = gh.reviews[0]["comments"][0]["body"]
    assert "$(rm -rf /)" in body                            # present as literal text, not expanded
    assert "calma:fp=ev" in body
