"""Isolated, revertible repair scratch (SWE-Adept semantic-step checkpointing). NEVER operate on the
user's working branch: make_scratch() copies the target into a throwaway git working tree, and every
checkpoint/branch/revert/apply happens there. The accepted patch is returned to the orchestrator as a
unified diff; the scratch is deleted on cleanup."""
import os
import shutil
import subprocess
import tempfile


def _git(repo, *args, check=True):
    """Run git in `repo` non-interactively; return CompletedProcess. Pins an identity + disables hooks/
    prompts so a repair can never trip an interactive flow or run repo hooks."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0",
               GIT_AUTHOR_NAME="calma-repair", GIT_AUTHOR_EMAIL="repair@calma.local",
               GIT_COMMITTER_NAME="calma-repair", GIT_COMMITTER_EMAIL="repair@calma.local")
    return subprocess.run(["git", "-C", repo, "-c", "core.hooksPath=/dev/null", *args],
                          capture_output=True, text=True, env=env, check=check)


def make_scratch(target):
    """A disposable copy of `target` as its own git repo, so repair edits never reach the user's tree.
    copytree(target) into a temp dir and `git init` it. Returns the scratch path. The scratch EXCLUDES
    .calma run state (a fresh verify writes its own) and vcs/cache noise so the first verify starts clean."""
    scratch_root = tempfile.mkdtemp(prefix="calma-repair-")
    scratch = os.path.join(scratch_root, os.path.basename(os.path.realpath(target)) or "target")
    shutil.copytree(target, scratch,
                    ignore=shutil.ignore_patterns(".calma", ".calma_venv", ".calma_httpcache",
                                                  ".git", "__pycache__", ".pytest_cache"))
    _git(scratch, "init", "-q")
    _git(scratch, "add", "-A")
    _git(scratch, "commit", "-q", "-m", "calma-repair: scratch baseline", check=False)
    return scratch


def checkpoint(repo):
    """Return a ref (the current HEAD sha) to revert to. Commits any pending state first so the
    checkpoint is a real, restorable tree (semantic-step boundary)."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "calma-repair: checkpoint", "--allow-empty", check=False)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def branch_for_hypothesis(repo, i):
    """Create + switch to an isolated branch for hypothesis i (one branch per hypothesis, SWE-Adept).
    Returns the branch name."""
    name = "hyp-%d" % i
    _git(repo, "checkout", "-q", "-B", name)
    return name


def revert(repo, ref):
    """Hard-reset the scratch tree back to `ref` and wipe untracked cruft -- a dead-end leaves NO
    residue (clean slate for the next hypothesis), including any .calma the verify wrote."""
    _git(repo, "checkout", "-q", "-f", ref)
    _git(repo, "reset", "-q", "--hard", ref)
    _git(repo, "clean", "-xffdq", check=False)


def apply_diff(repo, unified_diff):
    """Apply a unified diff to the scratch tree. Returns True iff it applied cleanly. An empty/whitespace
    diff is a NO-OP -> return False (the orchestrator treats 'nothing applied' as a non-fix).

    LLM-emitted diffs routinely carry slightly-wrong @@ line numbers/counts, so we escalate through
    increasingly tolerant appliers: strict git apply -> 3way -> --recount, then GNU `patch` with fuzz
    (matches on context, not line numbers). The hunk CONTENT still has to match, so this widens what
    applies without letting a bogus patch through."""
    if not unified_diff or not unified_diff.strip():
        return False
    for extra in (["--whitespace=nowarn"], ["--3way", "--whitespace=nowarn"],
                  ["--recount", "--whitespace=nowarn"]):
        p = subprocess.run(["git", "-C", repo, "apply", *extra, "-"],
                           input=unified_diff, text=True, capture_output=True)
        if p.returncode == 0:
            return True
    # last resort: GNU patch tolerates line-number drift via context fuzz (try -p1 then -p0).
    for strip in ("-p1", "-p0"):
        p = subprocess.run(["patch", strip, "--fuzz=3", "--no-backup-if-mismatch", "-s",
                            "-d", repo], input=unified_diff, text=True, capture_output=True)
        if p.returncode == 0:
            return True
    return False


def diff_since(repo, ref):
    """The unified diff of the scratch tree vs `ref` (what the hypothesis actually changed) -- used by
    the reviewers to inspect the REAL applied change, not just the model's proposed text."""
    _git(repo, "add", "-A")
    return _git(repo, "diff", ref, check=False).stdout


def cleanup_scratch(repo):
    """Delete the scratch root. Idempotent; never raises."""
    root = os.path.dirname(os.path.realpath(repo))
    shutil.rmtree(root, ignore_errors=True)
