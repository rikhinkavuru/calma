"""github_app.server - the stdlib webhook receiver: verify the HMAC signature, route the event, and (on a real
deployment) enqueue the verify+comment job on Calma's infra. REJECTS a bad/absent signature before ANY
work. Transport only - verdicts come from the engine (via the pr/ transport); no verdict-core import.

The pure functions (verify_signature / parse_command / route_event) are unit-tested offline; the
http.server Handler + the enqueue job are the live deployment surface (the actual fetch+re-execute needs
network, documented in app/README.md, not unit-tested - like the B3 workflow round-trip).
"""
import hashlib
import hmac
import http.server
import json
import os
import re
import sys
import traceback

_CMD_RE = re.compile(r"@calma\s+(full\s+review|review)\b", re.I)
_PR_ACTIONS = ("opened", "synchronize", "reopened", "ready_for_review")
_MAX_BODY = 1 << 20          # 1 MiB cap on the request body, enforced from Content-Length BEFORE the body
                             # is read into memory (these webhook payloads are far smaller) - an
                             # unauthenticated client cannot OOM the receiver with a huge Content-Length.
# only a repo OWNER / MEMBER / COLLABORATOR may trigger a (compute-spending, privileged-posting) command
# - never a drive-by commenter on a public PR. GitHub stamps comment.author_association on the event.
_ALLOWED_ASSOC = ("OWNER", "MEMBER", "COLLABORATOR")


def verify_signature(secret, body_bytes, signature_header):
    """X-Hub-Signature-256 = 'sha256=<hex>'. Constant-time HMAC-SHA256 compare. False on absent/empty
    secret, absent/malformed header, or mismatch - the webhook does NO work on a bad signature."""
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    mac = hmac.new(secret.encode("utf-8") if isinstance(secret, str) else secret, body_bytes, hashlib.sha256)
    return hmac.compare_digest("sha256=" + mac.hexdigest(), signature_header)


def parse_command(body):
    """`@calma review` -> 'review' (incremental); `@calma full review` -> 'full'; else None."""
    m = _CMD_RE.search(body or "")
    if not m:
        return None
    return "full" if "full" in m.group(1).lower() else "review"


def route_event(event_type, payload):
    """A VERIFIED webhook -> a job dict, or None (ignored). pull_request[opened/synchronize/reopened/
    ready_for_review] -> a verify job; issue_comment[created] with @calma ON A PR -> a command job."""
    if event_type == "pull_request" and payload.get("action") in _PR_ACTIONS:
        pr = payload.get("pull_request") or {}
        return {"kind": "verify", "command": "review",
                "pr_number": payload.get("number") or pr.get("number"),
                "base_sha": (pr.get("base") or {}).get("sha"),
                "head_sha": (pr.get("head") or {}).get("sha"),
                "repo": (payload.get("repository") or {}).get("full_name"),
                "installation_id": (payload.get("installation") or {}).get("id")}
    if event_type == "issue_comment" and payload.get("action") == "created":
        comment = payload.get("comment") or {}
        cmd = parse_command(comment.get("body"))
        issue = payload.get("issue") or {}
        assoc = (comment.get("author_association") or "").upper()
        # commands only on PRs (issue_comment fires for issues too), AND only from an authorized
        # association - a drive-by commenter cannot spend compute or trigger a privileged post.
        if cmd and issue.get("pull_request") and assoc in _ALLOWED_ASSOC:
            return {"kind": "command", "command": cmd, "pr_number": issue.get("number"),
                    "repo": (payload.get("repository") or {}).get("full_name"),
                    "installation_id": (payload.get("installation") or {}).get("id")}
    return None


def enqueue(job):
    """The hosted job (live deployment surface): fetch the PR head into Calma's sandbox, run the B1
    detect+verify+bundle, then the B2 review/check-run with a fresh installation token. Imports the pr/
    transport (which shells to the engine) - never the verdict core. Returns the comment result.

    NOTE: the fetch + re-execute touch the network/disk, so this is exercised on a real deployment, not
    in the unit tests (which cover the signature + routing). Kept thin + dependency-injected."""
    from pr import run_pr, comment_pr, github
    from github_app import auth
    app_id = os.environ["CALMA_APP_ID"]
    pkey = os.environ["CALMA_APP_PRIVATE_KEY"]
    workdir = os.environ.get("CALMA_WORKDIR", ".")
    token = auth.installation_token_for(app_id, pkey, job["installation_id"])
    bundle = run_pr.build_bundle(job["base_sha"], job["head_sha"], job["pr_number"], repo=workdir)
    owner, repo = job["repo"].split("/", 1)
    client = github.GitHubClient(token, owner, repo, job["pr_number"])
    # both `review` (incremental) and `full review` post: comment_pr is already idempotent + incremental
    # (same head -> nothing new; a new push -> only the delta), so there is no dry-run on this path.
    return comment_pr.run(client, bundle)


class Handler(http.server.BaseHTTPRequestHandler):
    """The webhook endpoint. The HMAC secret is read from CALMA_WEBHOOK_SECRET (or set as a class attr)."""
    secret = None
    timeout = 15        # per-request socket timeout: bound a slow-loris client on this single-threaded server

    def _secret(self):
        return self.secret or os.environ.get("CALMA_WEBHOOK_SECRET", "")

    def do_POST(self):
        delivery = self.headers.get("X-GitHub-Delivery", "?")
        try:
            length = int(self.headers.get("content-length", 0) or 0)
        except ValueError:                       # a non-integer Content-Length is a malformed request
            self.send_response(400)
            self.end_headers()
            return
        if length < 0 or length > _MAX_BODY:     # reject an oversize body BEFORE reading it (no OOM)
            self.send_response(413)
            self.end_headers()
            self.wfile.write(b"payload too large")
            return
        body = self.rfile.read(length)
        if not verify_signature(self._secret(), body, self.headers.get("X-Hub-Signature-256")):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"invalid signature")
            return
        try:
            payload = json.loads(body)
        except ValueError:
            self.send_response(400)
            self.end_headers()
            return
        job = route_event(self.headers.get("X-GitHub-Event", ""), payload)
        self.send_response(202 if job else 204)
        self.end_headers()
        if job:
            try:
                enqueue(job)
            except Exception:                 # a deployment-time failure must not crash the receiver, but
                # it MUST be visible: a swallowed job is a PR that silently never gets its gating check.
                sys.stderr.write("calma: enqueue failed (delivery %s, kind %s):\n%s\n"
                                 % (delivery, job.get("kind"), traceback.format_exc()))
                sys.stderr.flush()

    def log_message(self, fmt, *args):
        pass  # suppress default per-request access logging; the failure path above logs to stderr


def serve(host="0.0.0.0", port=8080, secret=None):
    Handler.secret = secret
    http.server.HTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve(port=int(os.environ.get("PORT", "8080")))
