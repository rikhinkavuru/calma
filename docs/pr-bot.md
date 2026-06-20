# Calma PR-review bot — adopter guide

The deterministic verifier as a GitHub PR check (the CodeRabbit-shaped sibling of the MCP server). On a
PR it re-executes the changed result dirs/notebooks **in the engine's network-off sandbox**, recomputes
every headline number from raw outputs, and posts the verdicts **inline** + a gating **check-run**. Every
verdict and number is the engine's, copied verbatim — the bot is a transport (`pr/`), it imports no
verdict core (firewall test).

## The two-workflow security model (do not shortcut it)

A PR from a fork carries attacker-controlled code, and Calma's whole job is to **re-execute it**. The
only safe shape is GitHub Security Lab's **pwn-request-proof two-workflow pattern**:

1. **`.github/workflows/calma-verify-pr.yml`** — trigger `pull_request`, `permissions: { contents: read }`
   only, **no secrets**. A fork PR here gets a read-only token, so re-executing its code is safe; the
   engine *also* sandboxes it (`--trust third-party --isolation auto` → Seatbelt/bwrap/microVM,
   network-off). It checks out the PR **head** with `persist-credentials: false`, runs `pr/run_pr.py`
   (diff → targets → verify → bundle), uploads the **`calma-findings`** artifact, and **posts nothing**.
2. **`.github/workflows/calma-comment-pr.yml`** — trigger `workflow_run` on the first workflow completing,
   runs **privileged** (`pull-requests: write`, `checks: write`, `contents: read`) in the *base* repo's
   trusted context. It downloads the artifact, **treats it as untrusted data** (schema-validate, never
   execute, never shell-interpolate a field), and runs `pr/comment_pr.py` to post the review + summary +
   check-run.

**Never** use `pull_request_target` + a head checkout (the pwn request). **Never** interpolate
`${{ github.event.* }}` into a `run:` shell — PR context reaches the scripts through `env:` only.
`.github/workflows/codeql-actions.yml` runs CodeQL (`languages: actions`) as a guardrail for exactly
these two failure modes.

### Gate integrity — bind the comment job, and (for the strongest guarantee) pin the engine

The split above stops a fork PR from stealing secrets, but it does **not** by itself make the findings
artifact *authentic*: the unprivileged job runs the PR's code, and — when the engine is vendored into
the repo — the **engine itself from the PR checkout**. Two controls follow:

- The privileged comment job passes the **trusted** head SHA as `CALMA_EXPECTED_HEAD`
  (`${{ github.event.workflow_run.head_sha }}`), and `pr/comment_pr.py` **refuses any bundle whose
  `head_sha` differs** — and never trusts the artifact's own `pr_number`/`head_sha` for routing. This
  stops a forged or cross-PR bundle from posting a check-run/review onto another commit or PR. (Pinning
  every `actions/*` to a commit SHA closes the action-tag-mutation vector on the same privileged job.)
- A PR must not be able to forge its **own** green check by editing the vendored engine, so the verify job
  runs a **trusted, base-pinned engine**: `pr/run_pr.py` resolves the engine, `edges`, and the `pr.*`
  transport from its own checkout (`_ENGINE_ROOT`), and `calma-verify-pr.yml` checks the engine out at the
  PR **base** (`path: .calma-engine`) and runs *that* copy against the PR's result dirs. Adopters get the
  same property either way: check the engine out at the PR base as shown, or reference the reusable action
  by an **immutable commit SHA** (so `$GITHUB_ACTION_PATH` is the pinned engine, not the PR's copy). Signing
  the bundle in the trusted verify step is available as optional defense-in-depth.

## Adopt it

**One command** — no vendoring of `pr/` or the engine:

```bash
python -m pr.init --ref <calma-commit-sha>   # writes .github/workflows/calma-{verify,comment}-pr.yml
git add .github/workflows && git commit -m "add the Calma merge-gate"
# then mark the `calma` check Required in branch protection (Settings -> Branches)
```

The two generated workflows `uses:` the pinned composite actions — `calma-pr-review` (the UNPRIVILEGED
detect+verify+bundle half) and `calma-pr-comment` (the PRIVILEGED review + gating-check-run half) — so the
**pinned action SHA is the base-pin**: a PR cannot swap the engine that grades it, because the engine is
fetched from the immutable calma `@ref`, not the PR head. Pin `--ref` to a commit SHA (a mutable branch
lets the engine change under you; `pr.init` warns when you pass one). For a hosted variant where your LLM
keys never touch the customer repo, see the GitHub App (`app/`, B4). (Manual path, as calma's own CI uses:
copy `pr/` + the two workflow files and run `run_pr.py` / `comment_pr.py` directly.)

What gets verified: a changed result dir with a committed `verify.yaml` (a `contract` target); a changed
`.ipynb`/`.csv` under a runnable dir (an `artifact` target, drafted by `python -m edges.extract`); or a
changed **ML/backtest framework run** — MLflow `mlruns/`, Weights & Biases `wandb/`, Ray Tune
`ray_results/`, or a `wandb-summary.json` / `result.json` / `progress.csv` — under a dir with a runnable
entrypoint (`train.py` / `backtest.py` / `strategy.py` / …). A `REFUTED`/`INVALIDATED`/`MIXED` target ⇒ a
failing `calma` check-run + a line-anchored inline comment ("cell 5 says +14,698% → recomputes to
−31.6%"); a clean PR ⇒ a passing check + a one-line summary. Re-pushing is incremental + idempotent (no
duplicate comments; fixed catches resolve).

## Manual end-to-end verification (BLOCKED in offline CI — requires a live repo or `act`)

The unit suites (`pr/tests`, run with the engine venv: `python -m pytest pr -q`) cover the bundle, the
rendering, and the commenter against a **mock** GitHub client — no network, no token. The full
workflow round-trip needs a live GitHub repo (or [`act`](https://github.com/nektos/act)) and a token, so
it is **not** part of the automated tests. To verify by hand:

1. On a sandbox repo, open a PR that commits a deliberately-`REFUTED` result dir (a `verify.yaml`
   claiming a number the data contradicts — e.g. copy `.claude/skills/calma/assets/btc`).
2. Confirm **calma-verify-pr** runs on the fork PR with a read-only token and uploads `calma-findings`
   (it must post nothing and hold no secrets).
3. Confirm **calma-comment-pr** then posts one batched inline review + a summary comment + a **failing**
   `calma` check-run; push a fix and confirm the comment resolves and the check goes green.
4. Confirm CodeQL Actions reports no `UntrustedCheckout` / script-injection finding.

Keep secrets out of any committed test fixture.
