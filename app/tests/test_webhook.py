"""B4: the webhook receiver. HMAC verification (good/absent/mis-signed), event routing (pull_request ->
verify job; @calma full review on a PR -> a full-review command; unrelated -> ignored), command parsing,
and the live Handler round-tripping on 127.0.0.1 (a bad/absent signature -> 401 before any work). No
external network.
"""
import hashlib
import hmac
import http.server
import json
import os
import sys
import threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))
from app import server as S  # noqa: E402

SECRET = "shh-webhook-secret"


def _sign(body):
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature_good_absent_bad():
    body = b'{"hello":"world"}'
    assert S.verify_signature(SECRET, body, _sign(body)) is True
    assert S.verify_signature(SECRET, body, None) is False                 # absent
    assert S.verify_signature(SECRET, body, "sha256=deadbeef") is False    # mismatch
    assert S.verify_signature(SECRET, body, _sign(b"other")) is False      # signed a different body
    assert S.verify_signature("", body, _sign(body)) is False              # no secret configured


def test_parse_command():
    assert S.parse_command("hey @calma review please") == "review"
    assert S.parse_command("@calma full review") == "full"
    assert S.parse_command("@Calma  Full Review") == "full"                # case / spacing tolerant
    assert S.parse_command("just a normal comment") is None


def test_route_pull_request_to_verify_job():
    payload = {"action": "synchronize", "number": 7,
               "pull_request": {"base": {"sha": "base1"}, "head": {"sha": "head1"}},
               "repo": {}, "repository": {"full_name": "o/r"}, "installation": {"id": 99}}
    job = S.route_event("pull_request", payload)
    assert job and job["kind"] == "verify" and job["pr_number"] == 7
    assert job["base_sha"] == "base1" and job["head_sha"] == "head1" and job["repo"] == "o/r"
    assert job["installation_id"] == 99
    # an action we don't act on -> ignored
    assert S.route_event("pull_request", {"action": "labeled"}) is None


def test_route_issue_comment_command_only_on_prs():
    base = {"action": "created", "repository": {"full_name": "o/r"}, "installation": {"id": 1},
            "issue": {"number": 12, "pull_request": {"url": "…"}},
            "comment": {"body": "@calma full review"}}
    job = S.route_event("issue_comment", base)
    assert job and job["kind"] == "command" and job["command"] == "full" and job["pr_number"] == 12
    # the SAME comment on a plain issue (no pull_request key) -> ignored
    no_pr = dict(base, issue={"number": 12})
    assert S.route_event("issue_comment", no_pr) is None
    # an unrelated comment on a PR -> ignored
    chatter = dict(base, comment={"body": "lgtm, thanks!"})
    assert S.route_event("issue_comment", chatter) is None


def _serve():
    S.Handler.secret = SECRET
    srv = http.server.HTTPServer(("127.0.0.1", 0), S.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _post(srv, body, sig=None, event="pull_request"):
    headers = {"X-GitHub-Event": event, "content-type": "application/json"}
    if sig is not None:
        headers["X-Hub-Signature-256"] = sig
    req = urllib.request.Request("http://127.0.0.1:%d/" % srv.server_address[1],
                                 data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_live_handler_rejects_bad_signature_and_routes_good_one():
    srv = _serve()
    try:
        pr = json.dumps({"action": "opened", "number": 1,
                         "pull_request": {"base": {"sha": "b"}, "head": {"sha": "h"}},
                         "repository": {"full_name": "o/r"}, "installation": {"id": 1}}).encode()
        # a correctly-signed pull_request webhook is accepted (202) - it routes to a verify job (the
        # enqueue's real fetch fails without app creds and is swallowed; the ROUTING/auth is what's tested)
        assert _post(srv, pr, _sign(pr)) == 202
        # an unsigned / mis-signed webhook is rejected BEFORE any work
        assert _post(srv, pr, None) == 401
        assert _post(srv, pr, "sha256=deadbeef") == 401
        # a signed but unrelated event -> ignored (204), no job
        chatter = json.dumps({"action": "created", "issue": {"number": 1},
                              "comment": {"body": "hi"}}).encode()
        assert _post(srv, chatter, _sign(chatter), event="issue_comment") == 204
    finally:
        srv.shutdown()


def test_mint_jwt_with_openssl_if_available():
    """app.auth.mint_jwt produces a 3-part RS256 JWT via openssl, when openssl + a key are available
    (skipped otherwise - openssl isn't guaranteed in every CI image)."""
    import shutil
    import subprocess
    from app import auth
    if not shutil.which("openssl"):
        print("  (openssl not present - mint_jwt test skipped)")
        return
    key = subprocess.run(["openssl", "genrsa", "2048"], capture_output=True, text=True)
    if key.returncode != 0:
        print("  (openssl genrsa failed - skipped)")
        return
    jwt = auth.mint_jwt("12345", key.stdout, now=1_700_000_000)
    assert jwt.count(".") == 2 and all(jwt.split("."))      # header.payload.signature, all non-empty
