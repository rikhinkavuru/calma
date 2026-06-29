# Connect GitHub — so anyone can connect their repos

Calma uses a **GitHub App** (not OAuth) — per-repo selection, short-lived scoped tokens, webhooks for
PR checks (rebuild guide §7). The code is built (`github_app.py` + the `/connect/github*` endpoints); it
goes live once the App is registered and the server is publicly reachable.

## Two hosts (important)

The dashboard (Next, e.g. `https://calma1.vercel.app`) and the verification backend (`spike/server.py`,
the host that clones + runs repos) are **separate origins**. The install flow must land users back on the
**dashboard**, and the dashboard proxies repo/verify calls to the **backend**. So:

- **App `setup_url` / `redirect_url`** → the **dashboard** origin: `https://<dashboard>/api/github/setup`
  (records the installation, then returns to `/dashboard`). *This is the fix for the "install sent me to a
  localhost link" problem — never point setup_url at the backend/localhost.*
- **App `hook_attributes.url`** (webhooks) → the **backend** origin: `https://<backend>/connect/github/webhook`.
- The dashboard's "Connect GitHub" button is same-origin (`/api/github/connect`) and 302s to GitHub using
  the app slug — no hardcoded host.

## One-time setup (founder)

1. **Register the App** (one click): open
   [`github.com/settings/apps/new?manifest`](https://github.com/settings/apps/new?manifest), fill the
   `REPLACE_WITH_DASHBOARD_HOST` (setup/redirect) and `REPLACE_WITH_BACKEND_HOST` (webhook) placeholders in
   `app-manifest.yml`, then paste it. GitHub hands back the **App ID**, a **private key** (`.pem`), and the
   **app slug**. *(Already registered with a localhost setup_url? Just edit the App's "Setup URL" + "Callback
   URL" in its GitHub settings to `https://<dashboard>/api/github/setup` — no re-register needed.)*
2. **Backend env** (`spike/server.py`):
   ```bash
   export CALMA_GH_APP_ID=<app id>
   export CALMA_GH_PRIVATE_KEY=/path/to/app-private-key.pem   # path or the PEM string
   export CALMA_GH_APP_SLUG=<app slug>
   ```
   (No PyJWT/cryptography needed — RS256 is signed via `openssl`.)
3. **Dashboard env** (Vercel): set `NEXT_PUBLIC_GITHUB_APP_SLUG=<app slug>` (so the Connect button knows the
   install URL) and `CALMA_VERIFY_API_URL` + `CALMA_VERIFY_TOKEN` pointed at the deployed backend.
4. **Deploy the backend** somewhere reachable from Vercel (a container/VM — it clones + builds venvs +
   executes, so not Vercel functions). Until then the connect flow lands correctly but repo-listing/verify
   need the backend up.

## The flow

```
"Connect GitHub" (dashboard)  → GET /api/github/connect       → 302 github.com/apps/<slug>/installations/new
user picks repos + installs   → GitHub → GET <dashboard>/api/github/setup?installation_id=…  → recorded → /dashboard
"verify"                       → POST /api/verify {repo, installation_id}  → backend clones via a 1-hour token
list connected repos           → GET /api/github?kind=gh-repos&installation_id=…  (proxied to the backend)
```

- Tokens are **short-lived (1h) + scoped** to the selected repos; the App private key stays in a secret
  manager; no long-lived credentials are stored.
- Multi-tenant storage here is an in-memory map (`INSTALLATIONS`); production moves it to the control plane
  (`installation_id ↔ tenant`).

## Verified locally

- The RS256 JWT minting round-trips (`mint_jwt` → `openssl … -verify` → **Verified OK**).
- The endpoints are live; until the App is registered, `/connect/github` shows the setup page and
  `/api/config` reports `github.configured = false`.
