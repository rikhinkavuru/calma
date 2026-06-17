"""pr.github - a tiny stdlib GitHub REST + GraphQL client (urllib) for the privileged comment job:
batched reviews, the summary comment upsert, the check-run, and resolve-on-fix via GraphQL review
threads (REST does not expose the PRRT_ thread id). Rate-limit hygiene (honor Retry-After / back off).
No engine import. The identity is the workflow_run job's GITHUB_TOKEN (an installation token scoped to
the repo, least-privilege: pull-requests:write, checks:write, contents:read).
"""
import json
import re
import time
import urllib.error
import urllib.request

_API = "https://api.github.com"
_BOT_MARK = "calma:fp="            # only OUR inline comments carry this - scopes list_bot_review_comments
_SUMMARY_MARK = "calma:summary"


class GitHubClient:
    def __init__(self, token, owner, repo, pr_number, api=_API):
        self.token, self.owner, self.repo, self.pr, self.api = token, owner, repo, pr_number, api

    def _req(self, method, path, body=None, graphql=False):
        url = (self.api + "/graphql") if graphql else (self.api + path)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "authorization": "Bearer " + self.token, "accept": "application/vnd.github+json",
            "x-github-api-version": "2022-11-28", "content-type": "application/json",
            "user-agent": "calma-pr-bot"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                # primary/secondary rate limit: honor Retry-After, else exponential back off, then re-raise
                if e.code in (403, 429) and attempt < 3:
                    time.sleep(int(e.headers.get("Retry-After") or (2 ** attempt)))
                    continue
                raise
        return {}

    def _paged(self, path):
        out, page = [], 1
        while True:
            sep = "&" if "?" in path else "?"
            cs = self._req("GET", "%s%sper_page=100&page=%d" % (path, sep, page))
            if not isinstance(cs, list) or not cs:
                break
            out += cs
            if len(cs) < 100:
                break
            page += 1
        return out

    def list_bot_review_comments(self):
        return [c for c in self._paged("/repos/%s/%s/pulls/%d/comments" % (self.owner, self.repo, self.pr))
                if _BOT_MARK in (c.get("body") or "")]

    def find_summary_comment(self):
        for c in self._paged("/repos/%s/%s/issues/%d/comments" % (self.owner, self.repo, self.pr)):
            if _SUMMARY_MARK in (c.get("body") or ""):
                return c
        return None

    def create_review(self, commit_id, event, body, comments):
        # ONE batched review carrying every NEW inline comment (the content-creation secondary limit is
        # 80/min + 500/hr - per-comment posting throttles on any real PR).
        return self._req("POST", "/repos/%s/%s/pulls/%d/reviews" % (self.owner, self.repo, self.pr),
                         {"commit_id": commit_id, "event": event, "body": body, "comments": comments})

    def create_summary_comment(self, body):
        return self._req("POST", "/repos/%s/%s/issues/%d/comments" % (self.owner, self.repo, self.pr),
                         {"body": body})

    def update_summary_comment(self, comment_id, body):
        return self._req("PATCH", "/repos/%s/%s/issues/comments/%s" % (self.owner, self.repo, comment_id),
                         {"body": body})

    def create_check_run(self, head_sha, conclusion, output):
        out = {"title": output.get("title", "calma"), "summary": output.get("summary", "")}
        anns = output.get("annotations") or []
        if anns:
            out["annotations"] = anns[:50]   # GitHub caps at 50/request; PATCH to append more
        return self._req("POST", "/repos/%s/%s/check-runs" % (self.owner, self.repo),
                         {"name": "calma", "head_sha": head_sha, "status": "completed",
                          "conclusion": conclusion, "output": out})

    def review_threads(self):
        q = ("query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n)"
             "{reviewThreads(first:100){nodes{id isResolved isOutdated comments(first:50){nodes{body}}}}}}}")
        d = self._req("POST", "", {"query": q, "variables": {"o": self.owner, "r": self.repo, "n": self.pr}},
                      graphql=True)
        nodes = (((((d or {}).get("data") or {}).get("repository") or {}).get("pullRequest") or {})
                 .get("reviewThreads") or {}).get("nodes") or []
        out = []
        for th in nodes:
            fps = set()
            for c in (th.get("comments") or {}).get("nodes", []):
                fps |= {m.group(1) for m in re.finditer(r"calma:fp=([0-9a-fA-F]+)", c.get("body") or "")}
            out.append({"id": th.get("id"), "isResolved": th.get("isResolved"), "fingerprints": list(fps)})
        return out

    def resolve_thread(self, thread_id):
        q = "mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{id isResolved}}}"
        return self._req("POST", "", {"query": q, "variables": {"id": thread_id}}, graphql=True)
