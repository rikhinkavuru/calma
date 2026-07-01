# Deploy the verification backend

The dashboard (calma1.vercel.app) is just the UI. The **backend** here clones repos, orchestrates E2B
microVMs, recomputes the numbers, and runs the GitHub-App connector. It can't run on Vercel functions
(it git-clones + runs code + holds in-memory jobs past serverless limits) — it needs a real container.
This is the piece that makes "anybody can verify a repo on calma1.vercel.app" actually work end to end.

## Safety (already enforced)

`CALMA_FORCE_E2B=1` is baked into the image: every submitted repo runs in an **E2B Firecracker microVM**
(network-denied, ephemeral), never as a host subprocess. A `runner: local` request is overridden to E2B.
Do not unset this on a public deployment.

**Crash isolation (on by default).** The heavy in-process work (discovery / leakage / diff / E2B
orchestration) runs in a disposable, resource-capped **child process** supervised by the API
(`runner/supervisor.py`), so a repo that OOMs, segfaults, hangs, or runs away kills only its own child — the
API and every other job stay up. All knobs auto-size from the container's memory; override only to tune:

| env | default | meaning |
|---|---|---|
| `CALMA_ISOLATE` | `1` | run verification in the isolated child (set `0` only for local debugging) |
| `CALMA_VERIFY_MEM_MB` | ~container×split | per-child resident-memory cap (RSS); child is killed above it |
| `CALMA_VERIFY_CONCURRENCY` | fits the box | max children at once, sized so they collectively fit (1 on the 1 GB VM) |
| `CALMA_VERIFY_CPU_SECONDS` | = wall budget | child CPU-seconds limit (runaway-loop guard) |
| `CALMA_VERIFY_WALL_SECONDS` | deep: heavy-build + k·runs (~55m); shallow: +300s | child wall-clock deadline (hang guard) — sized to fit a heavy deps install so a slow build isn't killed mid-stream |

Every job streams a timestamped e2e log (clone → build → install → run → recompute, with the sandbox's live
output): the dashboard shows it in a live console, and `GET /api/jobs/{id}/logs` returns it as plaintext.

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
  CALMA_E2B_TEMPLATE="calma-verify" \
  # ^ the pre-warmed multi-core template (8 vCPU + ML/genomics stack baked in). Build/rebuild it with
  #   `CALMA_E2B_API_KEY=… python spike/e2b_template.py` (tunable: CALMA_TEMPLATE_CPUS / _MEM_MB). Deep runs
  #   get the cores → the repo's own compute (the latency floor) runs 3-4× faster. Fall back to "base" to disable.
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
