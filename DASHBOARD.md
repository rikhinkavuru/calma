# Calma console (dashboard) + auth

A logged-in product UI at `/dashboard` on the Next.js site, sitting on the verifications API
(`control_plane/api`). Built P2-M5. List / detail / submit / API-keys, with WorkOS login.

## Run locally
```bash
# 1. the API (control plane)
~/.calma/cp-venv/bin/uvicorn control_plane.api.app:app --host 127.0.0.1 --port 8000

# 2. the dashboard (Next.js) — reads .env
npm run dev          # http://localhost:3000/dashboard
```

## Auth
- **Production:** WorkOS AuthKit. `lib/session.ts` calls `withAuth()`, then provisions/looks up the Calma
  tenant for the WorkOS user via `POST /internal/provision`. **One operator step to enable real login:**
  register the redirect URI in the WorkOS dashboard (Redirects):
  - dev:  `http://localhost:3000/callback`
  - prod: `https://calma1.vercel.app/callback`
  and confirm `WORKOS_API_KEY` / `WORKOS_CLIENT_ID` / `WORKOS_COOKIE_PASSWORD` / `NEXT_PUBLIC_WORKOS_REDIRECT_URI` in `.env`.
- **Local dev without the interactive flow:** set `DASHBOARD_DEV_TENANT_ID=<tenant uuid>` in `.env`
  (a "DEV SESSION" pill shows in the nav). Mint a tenant with
  `~/.calma/cp-venv/bin/python -m control_plane.api.bootstrap init --org "Dev" --slug dev`.

## How the dashboard talks to the API (first-party)
The dashboard is a trusted first party: server components / server actions call the FastAPI API with
`X-Calma-Service-Token` (= `CALMA_SERVICE_TOKEN`) + `X-Calma-Tenant-Id` (the session's tenant). The service
token never reaches the browser (`lib/calma.ts` is `server-only`). Submit uploads the bundle to R2 via a
presigned PUT **server-side** (no browser CORS), then calls the engine.

## Files
```
lib/calma.ts            server-side API client (service token)
lib/session.ts          WorkOS session + dev fallback -> { user, tenantId }
app/callback/route.ts   WorkOS OAuth callback
app/dashboard/          layout (auth gate) · page (list) · v/[id] · submit · keys · Nav/Badge · actions.ts
```

## Deploy (Vercel)
The control-plane API ships as a **Vercel Python (Fluid Compute) function** in its own project, separate
from the Next.js site so the engine (`.claude/skills/calma/scripts/**`) bundles cleanly from the repo root.

```
api/index.py        ASGI entry — exposes the FastAPI `app`; pins CALMA_ENGINE_PYTHON=sys.executable
requirements.txt    fastapi · psycopg[binary] · boto3 · e2b   (the engine itself stays pure-stdlib)
api.vercel.json     @vercel/python build; routes /* -> the ASGI app; includeFiles bundles control_plane + engine
```

Deploy the API as a **second project** off this repo (don't link it to the Next `calma` project):
```bash
vercel link --project calma-api --yes               # links THIS dir to a new project (.vercel is gitignored)
vercel deploy --local-config api.vercel.json --yes  # preview; add --prod to promote
```
Then on the dashboard (`calma`) project set `CALMA_API_URL=https://<calma-api-domain>` + `CALMA_SERVICE_TOKEN`
and redeploy. Set every secret with `vercel env` (never the committed repo) — DB / R2 / WorkOS / service token.

### Dashboard (the `calma` project = calma1.vercel.app)
The Next.js site (marketing + `/dashboard`) deploys to the existing **`calma`** project. Live now via a
CLI deploy from this branch's working tree (the dashboard code isn't on `main` yet — a future push to `main`
that lacks it would revert calma1 to marketing-only, so **merge this branch to `main` to make it durable**).

Production env on `calma`: `WORKOS_CLIENT_ID` · `WORKOS_API_KEY` · `WORKOS_COOKIE_PASSWORD` ·
`NEXT_PUBLIC_WORKOS_REDIRECT_URI=https://calma1.vercel.app/callback` · `CALMA_API_URL` (the calma-api URL) ·
`CALMA_SERVICE_TOKEN`. Do **not** set `DASHBOARD_DEV_TENANT_ID` in production (it bypasses login).

Auth: `middleware.ts` (authkitMiddleware, scoped to `/dashboard` + `/callback`) + `app/callback/route.ts`
(`handleAuth`) + the layout's Server-Action sign-in. WorkOS redirect URIs must be registered (done):
`https://calma1.vercel.app/callback` (prod) + `http://localhost:3000/callback` (dev).

To redeploy the dashboard via CLI you need a **`.vercelignore`** (NOT committed — it would break the
calma-api deploy, which needs `api/`). It must exclude `.env` (a `.vercelignore` REPLACES `.gitignore`, so
Next would otherwise load the local `.env` into prod) plus the Python/engine dirs so `api/*.py` isn't built
as a function:
```
.env
.env.*
api/  requirements.txt  api.vercel.json  control_plane/  .claude/  benchmark/  edges/  mcp/  pr/
*.py  pyproject.toml  Dockerfile  Makefile  .next/  node_modules/
```
Then: `vercel link --project calma --yes` · `vercel deploy --prod`.

### Hosted execution (E2B)
Untrusted-code submissions need a verified isolation tier. On the dev Mac that's seatbelt; on Vercel (no local
sandbox) set **`CALMA_EXEC_ISOLATION=e2b`** so the API runs the engine with `--isolation e2b`, booting a
network-denied **Firecracker microVM** (E2B). Recompute always happens host-side, outside the sandbox. Required
E2B env: `CALMA_E2B_API_KEY`, `CALMA_E2B_ENDPOINT` (e.g. `e2b.dev`), `CALMA_E2B_TEMPLATE` (e.g. `base`). The
engine's in-VM probe proves egress is denied (fail-closed) before stamping `e2b-firecracker`.
