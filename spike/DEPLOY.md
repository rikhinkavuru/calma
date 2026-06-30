# Deploy the verification backend

The dashboard (calma1.vercel.app) is just the UI. The **backend** here clones repos, orchestrates E2B
microVMs, recomputes the numbers, and runs the GitHub-App connector. It can't run on Vercel functions
(it git-clones + runs code + holds in-memory jobs past serverless limits) — it needs a real container.
This is the piece that makes "anybody can verify a repo on calma1.vercel.app" actually work end to end.

## Safety (already enforced)

`CALMA_FORCE_E2B=1` is baked into the image: every submitted repo runs in an **E2B Firecracker microVM**
(network-denied, ephemeral), never as a host subprocess. A `runner: local` request is overridden to E2B.
Do not unset this on a public deployment.

## Deploy to Fly.io

```bash
# 1. one-time: install + auth (run these yourself; auth is interactive)
brew install flyctl          # or: curl -L https://fly.io/install.sh | sh
flyctl auth login

cd spike

# 2. create the app (note: Fly's abuse filter blocks names containing "verify", hence calma-engine)
flyctl apps create calma-engine

# 3. secrets (NOT in fly.toml). The verify token must MATCH CALMA_VERIFY_TOKEN on the Vercel web project.
#    E2B vars are CALMA_E2B_* (what runner/e2b_runner.py reads), not E2B_API_KEY.
flyctl secrets set -a calma-engine \
  CALMA_VERIFY_TOKEN="$(openssl rand -hex 32)" \
  CALMA_E2B_API_KEY="<your e2b key>" \
  CALMA_E2B_ENDPOINT="e2b.dev" \
  CALMA_E2B_TEMPLATE="base" \
  CALMA_GH_APP_ID="4163291" \
  CALMA_GH_APP_SLUG="calma-verify" \
  CALMA_GH_PRIVATE_KEY="$(cat /path/to/calma-verify.pem)"

# 4. ship it (single machine — jobs are in-memory)
flyctl deploy --ha=false -a calma-engine

# 5. health check
curl -s https://calma-engine.fly.dev/api/config   # -> {"internal":false,"github":{"configured":true,...}}
```

## Point the dashboard + GitHub App at it

On the **Vercel web project** (calma1), set and redeploy:

```
CALMA_VERIFY_API_URL = https://calma-engine.fly.dev
CALMA_VERIFY_TOKEN   = <the same token you set on Fly in step 3>
```

In the **GitHub App** settings, set the webhook host to the backend:

```
Webhook URL → https://calma-engine.fly.dev/connect/github/webhook
```

(The App's Setup/Callback URL stays on the dashboard: `https://calma1.vercel.app/api/github/setup`.)

## Notes

- In-memory jobs + single instance is the MVP. Before real traffic: a durable job store + admission/rate
  limits (E2B is metered — uncapped public submissions = uncapped cost) + a bigger VM if clones are large.
- Local dev is unchanged: run `./spike/web.sh` (no CALMA_FORCE_E2B, no token) for the local operator flow.
