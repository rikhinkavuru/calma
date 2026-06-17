"""app.auth - GitHub App authentication (stdlib + openssl): mint a short-lived RS256 JWT signed with
the app private key, exchange it for a 1-hour installation token. No third-party crypto dependency -
RS256 is delegated to `openssl dgst -sha256 -sign` (the same shell-out the README documents). No engine
import.
"""
import base64
import json
import os
import subprocess
import tempfile
import time
import urllib.request

_API = "https://api.github.com"


def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def mint_jwt(app_id, private_key_pem, now=None):
    """A GitHub App JWT (RS256): base64url(header).base64url(payload).base64url(signature), the signature
    an RSA-SHA256 over `header.payload` made with the app private key (via openssl). `now` (unix seconds)
    is injectable for deterministic tests. iat is backdated 60s for clock skew; exp is +9min (<10min cap)."""
    now = int(now if now is not None else time.time())
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(json.dumps({"iat": now - 60, "exp": now + 540, "iss": str(app_id)},
                                 separators=(",", ":")).encode())
    signing_input = header + b"." + payload
    kf = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
    try:
        kf.write(private_key_pem)
        kf.close()
        p = subprocess.run(["openssl", "dgst", "-sha256", "-sign", kf.name],
                           input=signing_input, capture_output=True)
        if p.returncode != 0 or not p.stdout:
            raise RuntimeError("openssl RS256 sign failed: %s" % p.stderr.decode("utf-8", "replace")[:200])
        sig = _b64url(p.stdout)
    finally:
        os.unlink(kf.name)
    return (signing_input + b"." + sig).decode("ascii")


def installation_token(jwt, installation_id, api=_API):
    """Exchange the app JWT for a 1-hour installation token: POST /app/installations/{id}/access_tokens.
    Check-run creation is App-only; this token carries the App's permissions on the install."""
    req = urllib.request.Request(
        "%s/app/installations/%s/access_tokens" % (api, installation_id), data=b"", method="POST",
        headers={"authorization": "Bearer " + jwt, "accept": "application/vnd.github+json",
                 "x-github-api-version": "2022-11-28", "user-agent": "calma-pr-bot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read()).get("token")


def installation_token_for(app_id, private_key_pem, installation_id, api=_API):
    """Convenience: mint the JWT + exchange it in one call."""
    return installation_token(mint_jwt(app_id, private_key_pem), installation_id, api)
