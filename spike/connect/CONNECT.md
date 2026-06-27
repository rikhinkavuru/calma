# Connect GitHub — so anyone can connect their repos

Calma uses a **GitHub App** (not OAuth) — per-repo selection, short-lived scoped tokens, webhooks for
PR checks (rebuild guide §7). The code is built (`github_app.py` + the `/connect/github*` endpoints); it
goes live once the App is registered and the server is publicly reachable.

## One-time setup (founder)

1. **Register the App** (one click): open
   [`github.com/settings/apps/new?manifest`](https://github.com/settings/apps/new?manifest), set the
   `hook_attributes.url` / `setup_url` / `redirect_url` in `app-manifest.yml` to your public host, then
   paste the manifest. GitHub creates the App and hands back:
   - **App ID**, a generated **private key** (`.pem`), and the **app slug** (the `name`, slugified).
2. **Set env + restart:**
   ```bash
   export CALMA_GH_APP_ID=<app id>
   export CALMA_GH_PRIVATE_KEY=/path/to/app-private-key.pem   # path or the PEM string
   export CALMA_GH_APP_SLUG=<app slug>
   ./spike/web.sh
   ```
   (No PyJWT/cryptography needed — RS256 is signed via `openssl`.)
3. **Public host for webhooks/redirects:** the App's `setup_url` must reach this server. Locally use a
   tunnel (`cloudflared tunnel --url http://localhost:8787` or ngrok); in prod, the deployed URL.

## The flow (already wired)

```
user clicks "Connect GitHub"  → GET /connect/github          → redirect to github.com/apps/<slug>/installations/new
user picks repos + installs   → GitHub → GET /connect/github/setup?installation_id=…  → stored
"verify"                       → POST /api/verify {repo, installation_id}  → clone via a 1-hour installation token
list a tenant's repos          → GET /api/gh/repos?installation_id=…
```

- Tokens are **short-lived (1h) + scoped** to the selected repos; the App private key stays in a secret
  manager; no long-lived credentials are stored.
- Multi-tenant storage here is an in-memory map (`INSTALLATIONS`); production moves it to the control plane
  (`installation_id ↔ tenant`).

## Verified locally

- The RS256 JWT minting round-trips (`mint_jwt` → `openssl … -verify` → **Verified OK**).
- The endpoints are live; until the App is registered, `/connect/github` shows the setup page and
  `/api/config` reports `github.configured = false`.
