#!/usr/bin/env python
"""Post (or update) a STICKY Calma validity report-card comment on the PR that triggered the workflow.

Pure stdlib (urllib). Finds an existing comment by a hidden marker and PATCHes it, else creates one — so a
re-run updates in place instead of spamming. No-ops cleanly when there's no PR context or no token."""
import json
import os
import sys
import urllib.error
import urllib.request

_MARKER = "<!-- calma-validity-check -->"
_API = "https://api.github.com"


def _pr_number(event):
    for key in ("pull_request", "issue"):
        obj = event.get(key)
        if isinstance(obj, dict) and obj.get("number"):
            return obj["number"]
    return None


def _req(method, url, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer %s" % token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "calma-validity-action",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read() or "{}")


def main():
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")            # owner/name
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not (token and repo and event_path and os.path.isfile(event_path)):
        return 0
    try:
        event = json.load(open(event_path))
    except (OSError, ValueError):
        return 0
    num = _pr_number(event)
    if not num:                                            # not a PR event → nothing to comment on
        return 0

    body_md = sys.stdin.read() if len(sys.argv) < 2 else open(sys.argv[1], errors="replace").read()
    body = _MARKER + "\n" + body_md

    base = "%s/repos/%s/issues/%d/comments" % (_API, repo, num)
    try:
        existing = _req("GET", base + "?per_page=100", token)
        mine = next((c for c in existing if _MARKER in (c.get("body") or "")), None)
        if mine:
            _req("PATCH", "%s/repos/%s/issues/comments/%d" % (_API, repo, mine["id"]), token, {"body": body})
        else:
            _req("POST", base, token, {"body": body})
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
        sys.stderr.write("calma: could not post PR comment: %s\n" % e)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
