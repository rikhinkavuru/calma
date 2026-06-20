"""C2: `python -m pr.init` scaffolds the two-workflow merge-gate. The generated files must honor the
same pwn-request-proof invariants as calma's own workflows (never pull_request_target; the verify half
is read-only; the comment half is workflow_run + write; no PR-controlled value lands on a run: line),
reference the PINNED composites, and refuse to clobber existing files without --force.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
from pr import init as I  # noqa: E402


def _code(text):
    """The file with `# ...` comments stripped, so invariants are checked against the workflow LOGIC,
    not the doc comments that NAME the prohibitions (e.g. the 'never pull_request_target' warning)."""
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _no_run_injection(text):
    for line in _code(text).splitlines():
        if line.strip().startswith("run:"):
            assert "${{" not in line, "run: carries a ${{ expansion (injection risk): %r" % line


def test_render_security_invariants():
    files = I.render("acme/calma", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    v, c = files[I.VERIFY_NAME], files[I.COMMENT_NAME]
    # never the pwn request (checked against the LOGIC, comments stripped)
    assert "pull_request_target" not in _code(v) and "pull_request_target" not in _code(c)
    # unprivileged half: pull_request, read-only, no write surface, PR-head checkout
    assert "pull_request:" in v and "workflow_run:" not in v
    assert "contents: read" in v
    assert "pull-requests: write" not in v and "checks: write" not in v
    assert "persist-credentials: false" in v and "head.sha" in v
    # privileged half: workflow_run + the write perms + the cancel guard, base (not PR) checkout
    assert "workflow_run:" in c and 'workflows: ["calma-verify-pr"]' in c
    assert "pull-requests: write" in c and "checks: write" in c and "contents: read" in c
    assert "conclusion != 'cancelled'" in c
    assert "persist-credentials: false" in c
    # both reference the PINNED composites from the named repo @ ref
    assert "acme/calma/.github/actions/calma-pr-review@deadbeef" in v
    assert "acme/calma/.github/actions/calma-pr-comment@deadbeef" in c
    # the steps are all `uses:` -> there is no run: line carrying a PR-controlled expansion
    _no_run_injection(v)
    _no_run_injection(c)


def test_sha_ref_is_recognized_as_pinned():
    sha = "0123456789abcdef0123456789abcdef01234567"
    assert "pinned to an immutable commit SHA" in I._pin_note("x/y", sha)
    assert "SECURITY: pin" in I._pin_note("x/y", "main")   # a mutable branch is flagged in the file


def test_write_refuses_to_clobber(tmp_path):
    d = str(tmp_path)
    w1, s1 = I.write(d, "acme/calma", "main")
    assert len(w1) == 2 and not s1
    assert os.path.isfile(os.path.join(d, I.VERIFY_NAME))
    assert os.path.isfile(os.path.join(d, I.COMMENT_NAME))
    # a second run without --force never overwrites
    w2, s2 = I.write(d, "acme/calma", "main")
    assert not w2 and len(s2) == 2
    # --force overwrites
    w3, s3 = I.write(d, "acme/calma", "main", force=True)
    assert len(w3) == 2 and not s3
