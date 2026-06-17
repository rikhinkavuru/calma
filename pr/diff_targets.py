"""pr.diff_targets - a PR's base..head diff -> the verifiable TARGET DIRS the engine can re-execute.
Pure git + path logic; NO engine import (the bot is a transport - verdicts come from the engine).
"""
import os
import subprocess
import sys

# a changed file of these kinds (under a runnable dir with NO committed verify.yaml) -> an A1
# `edges.extract` ARTIFACT target (draft a contract from the artifact, then verify every number).
_ARTIFACT_EXTS = (".ipynb", ".pdf")
_DATA_EXTS = (".csv", ".tsv", ".parquet", ".json")
# a dir is runnable (edges.extract can draft+run it) when it ships one of these entrypoints.
_ENTRYPOINTS = ("gen.py", "gen_fixture.py", "main.py", "run.py")


def changed_paths(base_sha, head_sha, repo="."):
    """Files the PR introduces: `git diff --name-only --diff-filter=ACMR base...head` (THREE dots =
    the merge-base..head range, so unrelated changes already on the base don't count). [] on error."""
    r = subprocess.run(["git", "-C", repo, "diff", "--name-only", "--diff-filter=ACMR",
                        "%s...%s" % (base_sha, head_sha)], capture_output=True, text=True)
    if r.returncode != 0:
        return []
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _has(repo, dirpath, name):
    return os.path.isfile(os.path.join(repo, dirpath, name))


def _ancestor_with(repo, start_dir, pred):
    """Walk up from start_dir (repo-relative) to the repo root; first dir satisfying pred, or None."""
    d = start_dir or "."
    while True:
        if pred(d):
            return d
        if d in ("", "."):
            return None
        nd = os.path.dirname(d)
        if nd == d:
            return None
        d = nd or "."


def verify_targets(changed, repo=".", cap=20):
    """Map changed files -> verifiable target dirs. Rules (each documented):
      - a changed/added verify.yaml -> its dir is a 'contract' target (a committed contract).
      - a changed file under a dir (or ancestor) that HAS a verify.yaml -> that dir, 'contract'
        (re-verify on a data change, e.g. runs/**/*.csv).
      - else a changed .ipynb/.pdf/.csv under a dir (or ancestor) with a runnable entrypoint but NO
        verify.yaml -> that dir, 'artifact' (edges.extract drafts + verifies every number).
    Dedup to dirs; cap to `cap` (a giant PR must not fan out unbounded - the overflow is reported on
    stderr, never silently dropped). Returns [{target, kind, changed_files:[...]}]."""
    targets = {}
    for p in changed:
        d0 = os.path.dirname(p) or "."
        if os.path.basename(p) == "verify.yaml":
            tdir, kind = d0, "contract"
        else:
            cdir = _ancestor_with(repo, d0, lambda dd: _has(repo, dd, "verify.yaml"))
            if cdir is not None:
                tdir, kind = cdir, "contract"
            elif p.lower().endswith(_ARTIFACT_EXTS + _DATA_EXTS):
                adir = _ancestor_with(repo, d0, lambda dd: any(_has(repo, dd, e) for e in _ENTRYPOINTS))
                tdir, kind = (adir, "artifact") if adir is not None else (None, None)
            else:
                tdir = None
        if not tdir:
            continue
        t = targets.setdefault(tdir, {"target": tdir, "kind": kind, "changed_files": []})
        t["changed_files"].append(p)
        # a verify.yaml in the dir wins: a 'contract' classification is authoritative over 'artifact'
        if kind == "contract":
            t["kind"] = "contract"
    ordered = sorted(targets.values(), key=lambda t: t["target"])
    if len(ordered) > cap:
        print("pr.diff_targets: capping %d targets to %d (dropping %s)"
              % (len(ordered), cap, [t["target"] for t in ordered[cap:]]), file=sys.stderr)
    return ordered[:cap]
