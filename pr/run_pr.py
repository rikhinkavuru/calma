"""pr.run_pr - the UNPRIVILEGED `pull_request`-job entrypoint: detect the changed verify targets, run
the engine on each IN ITS OWN network-off sandbox, and write one FindingsBundle. NO GitHub writes
(that is B2, the privileged job); no secrets; a read-only token. Transport only - the engine decides
every verdict. Inputs come from env (never the shell line, so a PR-controlled value can't be injected).
"""
import json
import os
import subprocess
import sys

# Resolve the engine, edges, and the `pr.*` transport from a TRUSTED root - this driver's OWN checkout,
# or $CALMA_ENGINE_ROOT - NEVER the PR working tree. CI runs a base-pinned copy of run_pr.py + the engine
# from here, so a PR cannot replace the verifier that grades it; only its RESULT DIRS (under `repo`,
# below) are PR-controlled. (Also lets the script run directly: without this, `python3 .../pr/run_pr.py`
# fails to import `pr`, since the parent dir is not on sys.path for a directly-run script.)
_ENGINE_ROOT = os.environ.get("CALMA_ENGINE_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ENGINE_ROOT)
from pr import bundle as B  # noqa: E402
from pr.diff_targets import changed_paths, verify_targets  # noqa: E402


def _normalize(kind, raw):
    """Normalise an engine --json into the bundle's claim shape. The A1 Report (`edges.extract`) is
    already {repo_verdict, summary, claims[], fix}; `calma.py verify` is {verdict, metrics[], ...} - map
    its metrics[] -> claims[] (numbers copied verbatim; the citation is factual, not a verdict paraphrase)."""
    if kind == "artifact":
        return {"repo_verdict": raw.get("repo_verdict"), "summary": raw.get("summary") or "",
                "isolation_tier": raw.get("isolation_tier"), "determinism_mode": raw.get("determinism_mode"),
                "claims": raw.get("claims") or [], "fix": raw.get("fix")}
    claims = []
    for m in (raw.get("metrics") or []):
        claims.append({"metric_id": m.get("metric"), "verdict": m.get("verdict"),
                       "claimed": m.get("claimed"), "recomputed": m.get("recomputed"),
                       "citation": "verify.yaml metric %s" % m.get("metric"),
                       "span": {"section": m.get("metric")}, "reason": m.get("reason")})
    return {"repo_verdict": raw.get("verdict"), "summary": raw.get("reason") or "",
            "isolation_tier": raw.get("isolation_tier"), "determinism_mode": raw.get("determinism_mode"),
            "claims": claims, "fix": raw.get("fix")}


def engine_json(target, kind, repo=".", timeout=600):
    """Run the engine SUBPROCESS for one target (NEVER imported in-process - transport only). The engine
    + edges come from the TRUSTED _ENGINE_ROOT, never from `repo` (the PR tree): contract ->
    `<_ENGINE_ROOT>/.claude/.../calma.py verify <t> --trust third-party --isolation auto` with cwd=repo;
    artifact -> `python -m edges.extract <ABS t>` with cwd=_ENGINE_ROOT (so the TRUSTED edges package -
    and the engine its bridge resolves relative to itself - runs, not the PR's copy). The PR's code still
    runs Seatbelt/bwrap/microVM-isolated. A subprocess error / unparseable output -> an INCONCLUSIVE stub."""
    if kind == "artifact":
        argv = [sys.executable, "-m", "edges.extract",
                os.path.abspath(os.path.join(repo, target)), "--json", "--mode", "fix"]
        cwd = _ENGINE_ROOT
    else:
        calma = os.path.join(_ENGINE_ROOT, ".claude", "skills", "calma", "scripts", "calma.py")
        argv = [sys.executable, calma, "verify", target, "--json",
                "--trust", "third-party", "--isolation", "auto", "--force"]
        cwd = repo
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        raw = json.loads(p.stdout)
    except (subprocess.SubprocessError, ValueError, OSError) as ex:
        return {"repo_verdict": "INCONCLUSIVE", "summary": "engine could not run: %s" % ex,
                "isolation_tier": None, "determinism_mode": None, "claims": [], "fix": None}
    ej = _normalize(kind, raw)
    # a target that could not be isolated is reported CAN'T-CONFIRM, never run unsafely / silently passed
    if ej.get("isolation_tier") == "host-not-isolated":
        ej["repo_verdict"] = "INCONCLUSIVE"
        ej["summary"] = "host could not verify a network-off sandbox - re-run on an isolating host"
    return ej


def build_bundle(base_sha, head_sha, pr_number, repo=".", cap=20, timeout=600):
    """The whole unprivileged flow as a pure function (for tests): diff -> targets -> engine -> bundle."""
    targets_meta = verify_targets(changed_paths(base_sha, head_sha, repo), repo, cap=cap)
    entries = [B.target_entry(tm["target"], tm["kind"],
                              engine_json(tm["target"], tm["kind"], repo, timeout),
                              tm["changed_files"], repo)
               for tm in targets_meta]
    return B.make_bundle(pr_number, head_sha, base_sha, entries)


def main():
    repo = os.environ.get("GITHUB_WORKSPACE") or "."
    base = os.environ.get("GITHUB_BASE_SHA", "")
    head = os.environ.get("GITHUB_HEAD_SHA", "")
    pr_number = int(os.environ.get("GITHUB_PR_NUMBER", "0") or "0")
    if not base or not head:
        sys.exit("error: set GITHUB_BASE_SHA + GITHUB_HEAD_SHA (the PR base..head range)")
    bundle = build_bundle(base, head, pr_number, repo)
    dest = os.path.join(os.environ.get("RUNNER_TEMP", repo), "calma-findings.json")
    open(dest, "w").write(B.to_json(bundle))
    nf = sum(len(t["findings"]) for t in bundle["targets"])
    print("wrote %s (%d targets, %d findings; catch=%s)"
          % (dest, len(bundle["targets"]), nf, B.has_catch(bundle)))
    # ADVISORY exit: the gate is the check-run in B2; the unprivileged job never fails on a catch.
    return 0


if __name__ == "__main__":
    sys.exit(main())
