"""pr.comment_pr - the PRIVILEGED workflow_run entrypoint: consume the FindingsBundle (as UNTRUSTED
DATA - parse, never execute, never shell-interpolate) and post ONE batched inline review + a single
updated summary comment + a gating check-run, idempotently + incrementally. The only code that holds a
write token. No engine import; the check-run conclusion is a pure function of the engine verdicts.
"""
import json
import os
import re

from pr import bundle as B
from pr import render as R

_FP_RE = re.compile(r"calma:fp=([0-9a-fA-F]+)")


def _fps_in(comments):
    out = set()
    for c in comments or []:
        for m in _FP_RE.finditer(c.get("body") or ""):
            out.add(m.group(1))
    return out


def run(client, bundle, dry_run=False):
    """Post the review + summary + check-run for `bundle` via `client` (a real GitHub client or a mock).
    Idempotent: re-running on the same head posts NOTHING new (fingerprints already present). Incremental:
    a new push comments only on the delta; a catch that no longer reproduces has its thread resolved.
    Returns {ok, new_findings, actions}."""
    errs = B.validate(bundle)
    if errs:
        return {"ok": False, "errors": errs}
    head = bundle["head_sha"]
    existing_fps = _fps_in(client.list_bot_review_comments())
    all_fps = R.all_catch_fingerprints(bundle)
    new_fps = {fp for fp in all_fps if fp not in existing_fps}
    actions = {"review": None, "summary": None, "check_run": None, "resolved": []}

    # (1) ONE batched review carrying only the NEW inline findings (never one POST per comment)
    new_comments = R.review_comments(bundle, only_fingerprints=new_fps)
    if new_comments:
        payload = [{k: c[k] for k in ("path", "line", "side", "body")} for c in new_comments]
        actions["review"] = (client.create_review(commit_id=head, event="COMMENT", body="", comments=payload)
                             if not dry_run else {"dry_run": len(payload)})

    # (2) the single summary comment - PATCH in place (find by the hidden marker), else create once
    body = R.summary_body(bundle)
    if not dry_run:
        existing = client.find_summary_comment()
        actions["summary"] = (client.update_summary_comment(existing["id"], body) if existing
                              else client.create_summary_comment(body))

    # (3) the gating check-run - conclusion is a pure function of the engine verdicts
    if not dry_run:
        actions["check_run"] = client.create_check_run(
            head_sha=head, conclusion=R.check_conclusion(bundle), output=R.check_output(bundle))

    # (4) resolve-on-fix: a thread whose fingerprint is no longer among the bundle's catches is resolved
    for th in client.review_threads():
        if th.get("isResolved"):
            continue
        th_fps = set(th.get("fingerprints") or [])
        if th_fps and not (th_fps & all_fps):
            if not dry_run:
                client.resolve_thread(th["id"])
            actions["resolved"].append(th["id"])
    return {"ok": True, "new_findings": len(new_fps), "conclusion": R.check_conclusion(bundle),
            "actions": actions}


def main():
    """The workflow_run job entrypoint: build the real GitHub client from the least-privilege env, read
    the artifact bundle (untrusted data), and post."""
    from pr.github import GitHubClient
    token = os.environ["GITHUB_TOKEN"]
    owner, repo = os.environ["GITHUB_REPOSITORY"].split("/", 1)
    bundle = B.from_json(open(os.environ.get("CALMA_BUNDLE", "calma-findings.json")).read())
    pr_number = bundle.get("pr_number") or int(os.environ.get("GITHUB_PR_NUMBER", "0") or "0")
    result = run(GitHubClient(token, owner, repo, pr_number), bundle)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
