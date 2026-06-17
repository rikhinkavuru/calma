# Calma GitHub App (hosted PR bot)

The hosted variant of the PR-review bot (B4). The customer installs the App; their PR code is fetched
and re-executed in **Calma's** network-off sandbox, so the LLM/signing keys never touch the customer
repo, and Calma posts as a distinct app identity (which can create check-runs — App-only). For the
self-hosted-in-CI path (no App, secrets stay in the customer's own Actions), use the two workflows in
`docs/pr-bot.md` instead.

Transport only, like `pr/` and `mcp/`: every verdict is the engine's. `app/` imports the `pr/` transport
(which shells to the engine) and never the verdict core (`app/tests/test_firewall.py`).

## App manifest (permissions + events)

Create a GitHub App with the **least-privilege** permissions:

- **Pull requests:** Read & write (the inline review + summary comment)
- **Checks:** Read & write (the gating check-run, App-only-creatable)
- **Contents:** Read (fetch the PR head to re-execute)

Subscribe to events: **Pull request** (`opened`, `synchronize`, `reopened`, `ready_for_review`) and
**Issue comment** (`created`, for the `@calma review` / `@calma full review` command interface — PR
comments arrive as `issue_comment`). Set a **webhook secret** (HMAC, mandatory).

## Run

```bash
export CALMA_WEBHOOK_SECRET=…        # the webhook HMAC secret (X-Hub-Signature-256 is verified)
export CALMA_APP_ID=…                # the GitHub App id
export CALMA_APP_PRIVATE_KEY="$(cat calma-app.private-key.pem)"   # RS256 (signed via openssl)
export CALMA_WORKDIR=/srv/checkout   # where the App fetches the PR head before re-executing
python3 -m app.server                # listens on $PORT (default 8080)
```

## How it works

1. **`app/server.py`** verifies the `X-Hub-Signature-256` HMAC **before any work** (a bad/absent
   signature → `401`), parses the event, and routes it: a `pull_request` action → a verify job; an
   `issue_comment` with `@calma review` / `@calma full review` **on a PR** → a command job; anything else
   is ignored (`204`).
2. **`app/auth.py`** mints a short-lived **RS256 JWT** (signed with the app private key via `openssl`, no
   third-party crypto dep) and exchanges it for a 1-hour **installation token**.
3. The job runs the same B1 (detect + verify + bundle, in Calma's network-off sandbox) and B2 (one
   batched inline review + summary + gating check-run) logic as the CI path, with that token.

## Tested vs not

`app/tests` (run with the engine venv) cover the **HMAC verification** (good/bad/absent signature →
401), **event routing**, and **command parsing** offline (the live `Handler` round-trips on
`127.0.0.1`). The actual **fetch + re-execute of a customer PR** touches network/disk, so it is exercised
on a real deployment, not in the unit tests (the same honest boundary as the B3 workflow round-trip).
Secrets live on Calma's infra and are never committed.
