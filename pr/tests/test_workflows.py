"""B3: the two workflows + the composite action honor the pwn-request-proof security model. Text-based
(no PyYAML dependency) but it asserts the load-bearing invariants: never pull_request_target, the
unprivileged half is read-only, the privileged half is workflow_run + write, and NO PR-controlled value
is shell-interpolated (every ${{ github.event / inputs }} is an env/with/if mapping, never a run: line).
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
GH = os.path.normpath(os.path.join(HERE, "..", "..", ".github"))
VERIFY = os.path.join(GH, "workflows", "calma-verify-pr.yml")
COMMENT = os.path.join(GH, "workflows", "calma-comment-pr.yml")
ACTION = os.path.join(GH, "actions", "calma-pr-review", "action.yml")
DANGER = ("${{ github.event", "${{ inputs.", "${{ github.head_ref", "${{ steps.")


def _read(p):
    assert os.path.isfile(p), "missing workflow file: %s" % p
    return open(p, encoding="utf-8").read()


def _code(text):
    """The file with YAML `# ...` comments removed (none of our values contain a literal #), so the
    invariants are checked against the workflow LOGIC, not the doc comments that NAME the prohibitions."""
    out = []
    for line in text.splitlines():
        i = line.find("#")
        out.append(line if i < 0 else line[:i])
    return "\n".join(out)


def _no_shell_injection(text):
    """No PR-controlled expansion ever lands on a `run:` shell line; each appears only as a YAML mapping
    value (env/with) or an `if:` guard - the script-injection guard CodeQL Actions also enforces."""
    for line in _code(text).splitlines():
        s = line.strip()
        if s.startswith("run:"):
            assert "${{" not in line, "run: line carries a ${{ expansion (injection risk): %r" % line
        if any(d in line for d in DANGER):
            key = s.split(":", 1)[0].replace("-", "").replace(".", "").replace("_", "")
            ok = (":" in s and key.isalnum()) or s.startswith("if:")
            assert ok, "a PR-controlled expansion is not an env/with/if mapping: %r" % line


def test_no_pull_request_target_anywhere():
    for p in (VERIFY, COMMENT, ACTION):
        assert "pull_request_target" not in _code(_read(p)), p   # the pwn request - never allowed


def test_unprivileged_verify_is_read_only_and_persist_credentials_false():
    t = _read(VERIFY)
    code = _code(t)
    assert "pull_request:" in code and "workflow_run:" not in code
    assert "contents: read" in code
    assert "pull-requests: write" not in code and "checks: write" not in code   # no write surface here
    assert "persist-credentials: false" in code
    assert "head.sha" in code                                                    # checks out the PR head
    _no_shell_injection(t)


def test_privileged_comment_is_workflow_run_and_least_privilege():
    t = _read(COMMENT)
    assert "workflow_run:" in t and 'workflows: ["calma-verify-pr"]' in t
    assert "pull-requests: write" in t and "checks: write" in t and "contents: read" in t
    assert "conclusion != 'cancelled'" in t                                # the guard
    assert "persist-credentials: false" in t                              # checks out the BASE bot code
    _no_shell_injection(t)


def test_action_uses_env_indirection():
    t = _read(ACTION)
    assert "using: \"composite\"" in t or "using: composite" in t
    _no_shell_injection(t)
    # the inputs reach the script via env, and the run line references the action path, not an input
    assert "run_pr.py" in t and "$GITHUB_ACTION_PATH" in t
