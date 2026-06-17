"""pr.run_pr - the UNPRIVILEGED `pull_request`-job entrypoint: detect the changed verify targets, run
the engine on each IN ITS OWN network-off sandbox, and write one FindingsBundle. NO GitHub writes
(that is B2, the privileged job); no secrets; a read-only token. Transport only - the engine decides
every verdict. Inputs come from env (never the shell line, so a PR-controlled value can't be injected).
"""
import json
import os
import subprocess
import sys

from pr import bundle as B
from pr.diff_targets import changed_paths, verify_targets


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
    """Run the engine SUBPROCESS for one target (NEVER imported in-process - transport only). artifact ->
    `python -m edges.extract <t> --json --mode fix`; contract -> `calma.py verify <t> --json --trust
    third-party --isolation auto` so untrusted PR code stays Seatbelt/bwrap/microVM-isolated even here.
    A subprocess error / unparseable output -> a CAN'T-CONFIRM stub (never a silent pass)."""
    if kind == "artifact":
        argv = [sys.executable, "-m", "edges.extract", target, "--json", "--mode", "fix"]
    else:
        calma = os.path.join(repo, ".claude", "skills", "calma", "scripts", "calma.py")
        argv = [sys.executable, calma, "verify", target, "--json",
                "--trust", "third-party", "--isolation", "auto", "--force"]
    try:
        p = subprocess.run(argv, cwd=repo, capture_output=True, text=True, timeout=timeout)
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
