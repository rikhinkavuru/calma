# Deploying the Calma Merge-Gate (GitHub App)

Status: the receiver + auth + the `pr/` engine transport are built and unit-tested. What remains before a
**hosted** deployment is (1) you register the App, and (2) the execution path is routed through the
control-plane's E2B microVM (see **Security**, below). Until both are done, use the **GitHub Action path**
(§B) which is deployable today with no hosting and no untrusted-code-on-Calma's-infra risk.

## A. Hosted GitHub App (the SaaS gate)

### Step 1 — register the App (you, ~2 min)
1. Set `hook_attributes.url` in `app-manifest.yml` to the deployed webhook URL (from Step 2).
2. Go to `https://github.com/settings/apps/new?manifest` (personal) or
   `https://github.com/organizations/<org>/settings/apps/new?manifest` (org), submit `app-manifest.yml`.
3. GitHub returns **App ID**, a generated **private key (.pem)**, and a **webhook secret**. Keep them secret.
4. Hand me: `CALMA_APP_ID`, `CALMA_APP_PRIVATE_KEY` (the .pem contents), `CALMA_WEBHOOK_SECRET`, and a test repo
   to install on. I set them as deployment secrets (never committed) and finish wiring + verify.

### Step 2 — the webhook receiver
`github_app/server.py` is the reference receiver (stdlib `http.server`): it verifies the `X-Hub-Signature-256`
HMAC, rejects bad/absent signatures before any work, caps the body at 1 MiB, and routes
`pull_request` + authorized `issue_comment` events to a verify job. Hosted, it needs a serverless adapter
(an ASGI/handler entry like `api/index.py`) + the env secrets above.

### Step 3 — verify (me, once registered)
Install on the test repo, open a PR with a wrong number, confirm the required Check Run goes **failure**
(merge blocked) and flips to **success** when the number is corrected.

### Security (the blocker that makes this a build, not a config)
`server.py::enqueue` currently runs the PR's code via the engine **inline, on a local workdir** — correct for
the CI/self-host model (§B), WRONG for a hosted App that runs *other people's* PR code on Calma's infra.
The hosted enqueue MUST: respond `202` immediately, enqueue async, then in a worker **clone the PR head with
the installation token and run it inside the control-plane's E2B microVM** (network-off, never cross-tenant)
— exactly like `POST /v1/verifications`. Routing through the existing control-plane execution is the secure
deployment; running the engine inline in the webhook is a sandbox-escape surface. Do not flip the App
`public` until this path is audited.

## B. GitHub Action path (deployable today, no hosting, no new attack surface)

For the customer's **own** repo, the gate runs in their CI — no Calma hosting, and the code is the customer's
own (no untrusted-third-party-on-our-infra problem). Reuses `pr/` + the BASE-pinned trusted engine
(`.calma-engine` / `_ENGINE_ROOT`, the H1 hardening). Ship a published Action + a workflow snippet:

```yaml
# .github/workflows/calma.yml — block the merge on a wrong number
name: calma
on: [pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pipx install calma          # or pin the engine ref
      - run: calma verify . --json --fail-on refuted   # non-zero exit fails the required check
```

This is the fastest "block the merge on a wrong number" with zero hosting. Recommended first SKU; the hosted
App (§A) is the no-CI-config upgrade.
