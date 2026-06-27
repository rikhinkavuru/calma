"""calma.spike.connect.github_app — the GitHub App connector (rebuild guide §7): anyone connects their repos.

A GitHub App (not an OAuth App) gives per-repo selection, short-lived scoped tokens, and webhooks. Flow:
  1. user clicks Connect → /connect/github → redirect to github.com/apps/<slug>/installations/new
  2. they pick repos → install → GitHub redirects to /connect/github/setup?installation_id=…
  3. we store installation_id ↔ tenant
  4. to act: mint a short RS256 JWT from the App private key → exchange for a 1-hour installation token →
     list / clone the selected repos with it.

Stdlib + openssl only (RS256 via `openssl dgst -sha256 -sign` — no PyJWT/cryptography dependency). Tokens
are short-lived + scoped to the selected repos; the App private key lives in a secret manager. Lifted from
the previous engine's proven auth.

Config (env): CALMA_GH_APP_ID, CALMA_GH_PRIVATE_KEY (a PEM string or a path to one), CALMA_GH_APP_SLUG.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
import urllib.request

_API = "https://api.github.com"


def _private_key() -> str:
    v = os.environ.get("CALMA_GH_PRIVATE_KEY", "")
    if v and os.path.isfile(v):
        return open(v).read()
    return v if "PRIVATE KEY" in v else ""


def configured() -> bool:
    return bool(os.environ.get("CALMA_GH_APP_ID") and _private_key() and os.environ.get("CALMA_GH_APP_SLUG"))


def install_url() -> str:
    return "https://github.com/apps/%s/installations/new" % os.environ.get("CALMA_GH_APP_SLUG", "")


def _b64url(b: bytes) -> bytes:
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def mint_jwt(app_id, private_key_pem, now=None) -> str:
    """A GitHub App JWT (RS256), signed with the App private key via openssl. iat backdated 60s for skew,
    exp +9min (< GitHub's 10-min cap). `now` injectable for tests."""
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


def installation_token(jwt, installation_id, api=_API) -> str:
    """Exchange the App JWT for a 1-hour installation token (scoped to the install's selected repos)."""
    req = urllib.request.Request(
        "%s/app/installations/%s/access_tokens" % (api, installation_id), data=b"", method="POST",
        headers={"authorization": "Bearer " + jwt, "accept": "application/vnd.github+json",
                 "x-github-api-version": "2022-11-28", "user-agent": "calma"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - fixed api.github.com host
        return json.loads(r.read()).get("token")


def installation_token_for(installation_id) -> str:
    """Mint the JWT from env + exchange it for the installation token."""
    return installation_token(mint_jwt(os.environ["CALMA_GH_APP_ID"], _private_key()), installation_id)


def list_installation_repos(token) -> list[dict]:
    """The repos this installation granted access to (the user's selected repos)."""
    req = urllib.request.Request(
        "%s/installation/repositories?per_page=100" % _API,
        headers={"authorization": "token " + token, "accept": "application/vnd.github+json",
                 "user-agent": "calma"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        data = json.loads(r.read())
    return [{"name": x["name"], "slug": x["full_name"],
             "visibility": "private" if x.get("private") else "public",
             "description": x.get("description") or "", "language": (x.get("language") or "")}
            for x in data.get("repositories", [])]


def clone_url(token, full_name) -> str:
    """An authed clone URL using the short-lived installation token."""
    return "https://x-access-token:%s@github.com/%s.git" % (token, full_name)
