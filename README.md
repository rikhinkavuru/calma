# Calma

[calma1.vercel.app](https://calma1.vercel.app/) · `v0.12.0` · MIT · pure Python stdlib

**An automatic guardrail for AI-generated results: Calma re-runs your agent's work, recomputes the numbers it reported, and blocks the wrong ones before they ship.**

> **Everyone else reads the diff or trusts the score. Calma re-runs the work and recomputes the number** — from the raw output files, never the number your agent reported. A diff review and an LLM-judge both reason *about* a result; Calma re-derives it. There's no score left to game.

Calma is an open-source verifier for numbers that matter. Point it at a result — a backtest's Sharpe, a model's accuracy, a "2.3× faster" benchmark, a cleaned dataset, an LLM eval — and it **re-runs the code in a network-off sandbox, recomputes the metric from the raw output files (never the reported number), and diffs it against the claim** under a calibrated tolerance. The verdict comes from a single deterministic function, not a language model. If the number is real, Calma confirms it with a signed, replayable proof. If it isn't, Calma breaks it and shows you exactly where.

> The verdict is computed by deterministic code, not a model — so it's a guardrail you can't talk your way past, even when it's checking your own agent's work. Calma re-derives every label byte-for-byte, so a stamp can't be faked, even by Calma.

**By default it's zero-touch — you type nothing.** Installed as a Claude Code hook (or the MCP tool in Cursor/Codex), Calma auto-verifies the numbers your agent computes *before you ever see them*, and blocks a wrong one so it can't be reported as fact:

```
# an agent finishes a task and is about to report a number — the Stop hook fires automatically:
  ⓧ calma caught a number: REFUTED — claimed Sharpe 2.6, the code recomputes 0.4
    the agent must now report the honest 0.4 and diagnose the cause, not the inflated 2.6
```

Or run it explicitly — from the CLI, CI, or a PR check:

```
$ calma verify ./my-backtest "Sharpe 2.6"
  REFUTED — confidence 0.81
  claimed 2.6 → the code recomputes 0.4 over runs/returns.csv
  re-executed under seatbelt-verified isolation, controlled-to-bit
  fix:  the headline uses 252-day annualization on weekly returns; recompute with the right convention
  replay:  calma replay ./my-backtest/.calma/run     # re-derive this verdict offline, byte-for-byte
```

---

## Contents

- [What's in this repo](#whats-in-this-repo)
- [Why recompute](#why)
- [How it works](#how-it-works) — verdict · validity layer · breadth · cross-engine · isolation
- [Surfaces — the engine, everywhere](#surfaces--the-engine-everywhere)
- [Hosted API & dashboard](#hosted-api--dashboard)
- [The benchmark](#the-benchmark)
- [Quickstart](#quickstart)
- [Architecture & design properties](#architecture--design-properties)
- [Limitations](#limitations)
- [Develop](#develop)
- [Status & docs](#status--docs) · [License](#license)

---

## What's in this repo

One deterministic engine and the surfaces that wrap it:

- **The engine + the `calma` CLI/skill** — `.claude/skills/calma/` (pure stdlib) and the pip-installable `src/calma` facade.
- **The website + hosted console** — a Next.js app (`app/`, `components/`) serving the marketing site and a logged-in `/dashboard` product UI, deployed at [calma1.vercel.app](https://calma1.vercel.app/).
- **The control-plane API** — `control_plane/` (FastAPI) + `api/` (the Vercel Python entry) backing the console's verifications, tenants, and API keys.
- **The transports** — the MCP server (`mcp/`), the PR-review bot (`pr/`), and the hosted GitHub App (`github_app/`).
- **The benchmark** — `benchmark/`, the reproducible 117-case head-to-head corpus.

---

## Why

Every dashboard, paper, and pitch deck reports a number. Almost none of them can be independently checked without trusting whoever produced it. AI agents make this worse: they now generate the backtests, the evals, and the "tests pass" — and they are confidently wrong at scale. The expensive failures (a team ships a model that leaked its test set; a fund allocates on an inflated Sharpe) come from a number that was **technically reproducible but not valid**.

Calma is built around one act almost no one else does: **recompute the claimed number from the raw outputs, and separately check that the result is sound.** Those are two different questions, and Calma answers both.

**Why recompute, instead of reading the diff or trusting the score?** Because a score is the thing that gets gamed. In 2026 a UC Berkeley team built an agent that scored **~100% on six major agentic benchmarks** — SWE-bench, WebArena, GAIA — *without solving a single task*: on SWE-bench it dropped a `conftest.py` that makes the grader report every test as passing; on WebArena it read the gold answer straight off a `file://` URL ([Wang et al., 2026](https://www.rdworldonline.com/how-a-berkeley-team-broke-8-major-ai-benchmarks-six-of-them-hit-100-without-solving-a-single-task/)). The score was perfect; the work was never done. Reading the diff doesn't catch that, and neither does asking a model whether the result *looks* right — on [Calma's own head-to-head benchmark](benchmark/), an LLM-as-judge **silently confirmed 14 wrong numbers** and caught only ~82% of cases, while trusting the reported number caught **0 of 77**. Calma re-executes the work and recomputes the number from the raw output files, so there is no score left to game.

---

## How it works

```
  artifact + claim
        │
        ▼
   ┌─────────┐   draft or load a verify.yaml contract (how to run, what to bind)
   │ contract│
   └────┬────┘
        ▼
   ┌─────────┐   re-execute the entrypoint in a NETWORK-OFF sandbox (Seatbelt / bubblewrap /
   │ run     │   Docker / remote Firecracker microVM), re-emitting the raw output files.
   └────┬────┘   A planted secret-read AND a network-connect must FAIL, proven by an in-sandbox self-test.
        ▼
   ┌─────────┐   recompute the headline metric from those raw files with one of 628 SOTA recipes
   │recompute│   (Python / R / Julia / C++ / Rust, run as a black box) — never the reported number.
   └────┬────┘
        ▼
   ┌─────────┐   diff recomputed vs claimed under a CALIBRATED tolerance (BLAS/reduction-order noise is a
   │ verdict │   caveat, not a refutation), then run the validity layer, then derive ONE deterministic label.
   └────┬────┘
        ▼
   ┌─────────┐   a hash-chained ledger + a signed, offline-verifiable attestation (DSSE + OpenSSH
   │ attest  │   SSHSIG, RFC-3161 timestamp, optional Sigstore/Rekor transparency log).
   └─────────┘
```

### The verdict is deterministic and non-gameable

One total pure function (`verdict.py`) maps a fully-specified input vector to one label. It is imported by **both** the emitter and the gate, which re-derives every label byte-for-byte — so a hand-edited or model-authored verdict cannot pass.

| Verdict | Meaning |
|---|---|
| **CONFIRMED** | the number reproduces and matches the claim within the calibrated budget |
| **CONFIRMED-WITH-CAVEATS** | it holds, but narrower than claimed (e.g. only plausibly-bound, or cross-stack numeric noise) |
| **REFUTED** | the code recomputes a materially different number — heavily guarded (independent binding, controlled determinism, claim outside the CI) |
| **INVALIDATED** | the number *reproduces*, but the result is not valid (leaked / overfit / survivorship-biased / contaminated) |
| **CAN'T-CONFIRM** | not enough structure / determinism / isolation to decide — always carries a concrete `fix:` and a structured `needs:` (exactly what to provide to resolve it) |
| **MIXED** | multi-claim, at least one broken |

Defaults are conservative: missing information degrades toward CAN'T-CONFIRM, never toward an accidental CONFIRMED or REFUTED.

### The validity layer — 13 families

Reproducibility (the number recomputes) is *not* validity (the result is sound). Calma ships a real, integrated validity layer — pure-stdlib, bit-stable, each detector only ever **degrades** a verdict, and `INVALIDATED` fires only under a scope-guard (when the claim positively asserts the clean property the data violates):

| Family | Catches |
|---|---|
| **Leakage** | row / id / temporal look-ahead / target leakage + a leakage-corrected re-run |
| **Overfitting** | Deflated Sharpe (Bailey–López de Prado) + PBO via CSCV + the deflated-**AUC** selection-overfit haircut; N is never guessed |
| **Execution realism** | fees / slippage / borrow / financing + Almgren √ market-impact + net-of-friction re-run + capacity |
| **Contamination** | exact eval-in-corpus (sha256) + near-duplicate MinHash/LSH |
| **Backtest soundness** | omitted costs (gross-sold-as-net), cherry-picked window, survivorship universe |
| **Point-in-time / look-ahead** | point-in-time membership / attrition + availability-date checks + a +1-period-lag probe |
| **Data-snooping** | study-wide multiple-testing — Bonferroni / Holm / BHY + the Harvey-Liu-Zhu Sharpe haircut (t > 3.0) |
| **Regime / walk-forward** | in-sample → out-of-sample edge collapse, corroborated by a two-sample KS regime shift |
| **Model-process leakage** | featurization fit on train+test, validation-reuse / selection-on-test |
| **Distributional shift** | covariate / target shift between train and test (KS + PSI) |
| **Era-embargo / purged-CV** *(tournament)* | train↔validation windows too close for the target's forward horizon (Numerai's published 8-era/20-day, 16-era/60-day purge; the López de Prado purge+embargo form) + the leading-era CORR inflation premium |
| **Risk-sim assumptions** *(Chaos / Gauntlet)* | per-block invariants of a DeFi risk simulation: ≤1 liquidation/account/block, a VaR labeled p99 that is really the p95 of the loss vector, calibration-window look-ahead, the close-factor bound |
| **Statistical plausibility** *(thin-input)* | fires with **no declared block**, SOFT-only (→ CAVEATS, never INVALIDATED): implausibly-high Sharpe, a too-smooth (serial-correlation) curve, and a **regime-drift** non-stationarity smell off the return series; plus an **undeclared-split leakage** smell (an inferred train/test split + real row overlap) and a **train/test loss-gap** overfit smell off ML artifacts — each names the exact block to declare for the authoritative verdict |

### Two catches that survive every other gate

A number can clear every check you already run — dbt tests, Pandera schemas, snapshot diffs, an LLM-eval harness — and still be wrong, because all of those confirm a number is *internally consistent*, not *correct*. Two of Calma's catches target exactly that blind spot, and both fire on a number that **recomputes perfectly**:

- **The trivial-baseline edge** (a diff-time guard, not one of the validity families above). A model card reports 92% accuracy and recomputes to 92% — but if 92% of the rows are one class, predicting the majority every time scores the same. The headline is real, reproducible, and worthless. Calma recomputes the trivial baseline next to the claim and flags a number that doesn't beat it.
- **Eval contamination** (the *Contamination* family above). A "zero-shot held-out" benchmark scores 0.92 and recomputes to 0.92 — but Calma hashes the eval items against the declared corpus (exact sha256 + near-duplicate MinHash/LSH) and finds 40% already in pretraining, so the *held-out* claim is **INVALIDATED**. The number is genuine; the held-out framing isn't. The entire eval-tooling category checks for none of this.

### Breadth

`calma recipes` → **628 metrics across 16 families**, each validated against byte-reproducible reference vectors: trading (Sharpe/Sortino/Calmar/VaR/CVaR), classification (accuracy/AUC/F1/log-loss/ECE/Brier), regression (RMSE/MAE/R²), analytics (sum/mean/percentile/groupby/join-loss), engineering ("2.3× faster"/p50–p99/throughput/coverage), retrieval & LLM evals (recall@k/NDCG/MRR/pass@k/exact-match), statistics (p-value/CI/effect-size), derivatives (Black-Scholes + Greeks/IV), credit, rates, fund & LP (TVPI/DPI/KS-PME), forecasting (MAPE/sMAPE/MASE/pinball), and more. Black-box over **Python, R, Julia, C++, Rust**.

### Cross-engine correctness

A 2026 study found **no backtest engine publishes cross-engine correctness** — every single-engine number carries *unquantified implementation uncertainty* (accumulation order, annualization, an off-by-one — and nobody checks the metric against a second implementation). `calma verify --cross-engine` recomputes the headline metric through a **second, independently-written kernel** (a different algorithm and reduction order from the primary — e.g. a sequential product vs a pairwise product tree, Welford variance vs two-pass) and **diffs the two under the calibrated tolerance**. Agreement to 1e-9 is evidence the number is implementation-robust; a divergence is flagged as an implementation-dependent metric to reconcile. The check is additive — it never changes the verdict — and reports which external stacks (R / Julia / Node) the host could use as an even stronger second engine.

### Isolation & attestation

Verified network-off own-code tiers — **Seatbelt** (macOS) and **bubblewrap** (Linux) — each self-tested (a planted secret-read and an egress attempt must both fail), plus a network-denied **Docker** tier and a **remote Firecracker microVM** (`--isolation e2b`, vendor-neutral: E2B cloud or self-hosted, egress denied in-guest) for untrusted counterparty code on a Docker-less host. Every catch ships a proof object: a hash-chained public registry, **DSSE + OpenSSH SSHSIG dual-signing** (zero-install verify), an RFC-3161 timestamp, an optional Sigstore/Rekor transparency log, and **calma's own RFC 6962 transparency log** emitting self-contained **`.proof` bundles** (`calma registry proof`) that re-verify **offline** — an inclusion proof + a signed checkpoint + external-witness cosignatures, so a published catch re-verifies years later with no calma server. Pure Python stdlib, no third-party runtime dependencies.

---

## Surfaces — the engine, everywhere

Calma is one deterministic engine behind a handful of surfaces. *AI proposes, determinism disposes.* Each surface is a thin transport that calls the engine as a black-box subprocess and never re-implements a verdict (enforced by firewall tests).

- **Claude Code skill / inline agent guardrail** — a Stop hook catches numeric claims before an agent reports them; the agent's own work gets verified mid-loop.
- **CLI** — `calma verify`, `draft` (point it at a messy repo → a runnable `verify.yaml`), `recipes`, `suggest`, `modes`, `replay`, `doctor`, `seal`, `registry verify`.
- **MCP server** (`python -m calma_mcp`) — the deterministic verifier callable from *any* MCP host (Cursor, Codex CLI, Windsurf, Claude Desktop, CI bots).
- **A1 artifact pipeline** (`python -m edges.extract`) — point it at a notebook / PDF / CSV and it verifies *every* number, each catch tied to its source span ("cell 14 says 0.94 → recomputes to 0.71").
- **The merge gate — *block the merge on a wrong number*** (`pr/` + a hosted GitHub App in `github_app/`) — re-runs `calma verify` on a PR's changed result-dirs in the engine's network-off sandbox and posts the verdicts inline. But the SKU is the **gating check-run**: a pure function of the engine's verdicts (`failure` on any REFUTED / INVALIDATED / MIXED, `neutral` on CAN'T-CONFIRM, `success` otherwise) that you mark **required** in branch protection. A comment-bot posts an LLM opinion you can dismiss; this is a **blocking correctness gate** — *prove your own numbers before you ship.* Built on the pwn-request-proof two-workflow pattern.
- **The hosted console** (`/dashboard`) — a logged-in product UI on the Next.js site (WorkOS AuthKit), backed by the control-plane API (`control_plane/` + `api/`): submit a bundle, list / inspect verifications, and manage API keys. See [`DASHBOARD.md`](DASHBOARD.md).

### Autonomy — two axes you control (a mode changes what Calma *does*, never what it *decides*)

| Axis | Values | Controls |
|---|---|---|
| **Verify scope** — how aggressively the zero-touch hook auto-verifies | `off` · `headline` (default) · `all` (every checkable claim this turn) | env `CALMA_VERIFY` · `.calma/config.json {"verify": …}` |
| **Action mode** — what it does *after* a check (seal / timestamp / restore-retry) | `ask` (default) · `suggest` · `auto` | env `CALMA_MODE` · `--mode` · `.calma/config.json {"mode": …}` |

Choose them with one command — `calma modes` shows the current state and the choices; `calma modes --verify all --mode auto` sets them (this project), `--global` sets them everywhere. A break (REFUTED/MIXED/INVALIDATED) blocks at any scope; outward actions (publish/send) need a standing opt-in even in `auto`. For *every number in a notebook/report*, the A1 pipeline (`python -m edges.extract`) verifies them all in one shot. Every decision is breadcrumbed to `.calma/auto_history.jsonl` and summarized by `calma stats`.

### The AI edges (intelligence around a deterministic core)

LLMs are used only where they can't fake a verdict: **extracting** claims from messy artifacts, **drafting** verify contracts for repos that ship none (the heuristic always disposes), **synthesizing** new recipes via CEGIS (draft → admit → counterexample → re-draft; data has the final say), and **auto-repairing** a broken result then re-verifying with an anti-test-hacking gate. The `edges/` package is firewalled off from the pure-stdlib core.

---

## Hosted API & dashboard

Beyond the OSS engine, this repo contains the **hosted product** — verification-as-a-service for teams whose output is numbers. The engine stays the same; this wraps it in a multi-tenant API and a logged-in UI.

- **Control-plane API** — `control_plane/` (FastAPI), deployed as a Vercel Python / Fluid-Compute function (`api/index.py` + `api.vercel.json`), backed by **Postgres** (Supabase, per-tenant row-level security) and **Cloudflare R2** object storage. Endpoints: `POST /v1/verifications` (submit a bundle), `GET /v1/verifications/{id}[/result|/proof]`, `GET /v1/verifications` (list), `POST /v1/uploads` (presigned R2 PUT), `POST|GET|DELETE /v1/keys` (API-key admin), `POST /internal/provision` (first-party tenant provisioning). Bearer **API-key** auth (`calma_sk_<env>_…`, SHA-256-hashed, constant-time verify), idempotency keys, and an immutable hash-chained `audit_log`.
- **Execution** — on submit, the API stages the bundle + data from R2 into a workdir and runs the **same engine** as a subprocess (`calma verify --json`), then persists the run + verdict + artifacts. Set `CALMA_EXEC_ISOLATION=e2b` to execute untrusted code in a network-denied **E2B Firecracker microVM** (the host self-proves egress is denied before stamping the tier). Recompute always happens host-side, outside the sandbox.
- **Dashboard** (`app/dashboard/`, `lib/`) — a logged-in console behind **WorkOS AuthKit**: submit a verification, list and inspect verdicts (claimed vs recomputed, the validity results, the execution tier, the evidence bundle), and create / revoke API keys. The dashboard talks to the API first-party with a service token that never reaches the browser (`lib/calma.ts` is `server-only`). See [`DASHBOARD.md`](DASHBOARD.md) and [`control_plane/README.md`](control_plane/README.md).

The end-to-end path is real and tested (sign-up → key → upload → submit → execute → verdict → proof). **Not yet wired:** a worker queue (execution is currently synchronous/inline), usage **billing/metering** (Stripe — the schema columns exist, the logic doesn't), hosted **verdict signing** (the local CLI `calma seal` signs; the hosted path stores the evidence JSON unsigned for now), and SSO/SCIM.

## The benchmark

`benchmark/` ships a 117-case corpus (synthetic + external UCI/sklearn + real-world) scored on two axes (NASEM 2019):

- **Reproducibility** — does the headline number recompute? Calma **100%** catch (77/77) / 0 false-confirm / 0 false-alarm vs an LLM-as-judge **~82%** (63/77, with 14 silent false-confirms and 12 false alarms) and trust-the-number **0%** (0/77).
- **Validity** — the cell where the number *reproduces* but the result is invalid: Calma **100%** (it INVALIDATES the tagged leaked / overfit / survivorship / shift cases) vs a recompute-only method's **0%**.

A fourth `agent-with-exec` arm (a frontier agent with a `run_python` tool, sandboxed identically) measures the *honest* differences once an agent can execute: verdict-instability (Calma 0 by construction), a pass^k consistency curve, agreement-with-Calma, cost, and the validity blind spot — across ≥2 model families, every counted run network-off-isolated, every transcript published. See [`benchmark/README.md`](benchmark/README.md).

---

## Quickstart

```bash
# install the CLI (pure stdlib; no runtime deps) — see docs/install.md for all paths
pip install calma                 # or: ./install.sh (symlink) · pip install 'calma[parquet]' for .parquet

# verify a result directory (auto-drafts a contract, or reads a committed verify.yaml)
calma verify ./result "accuracy 0.94" --metric accuracy --json
#   the verdict ends with a one-line "not verified" summary; add --why for the full scope list

# REFUTED? let an LLM propose a fix — Calma re-verifies the patched code and accepts it ONLY if the
# recompute flips the verdict to clean (your files are untouched unless you pass --apply)
calma repair ./result/.calma/run            # needs the edges deps + an API key

# see the catalog, get a recipe suggestion, replay a sealed verdict offline
calma recipes
calma suggest ./result
calma replay ./result/.calma/run

# prove the sandbox actually isolates on this host
python3 .claude/skills/calma/scripts/run_hermetic.py doctor

# watch a real inflated backtest get caught, zero setup
make demo
```

A `verify.yaml` pins *how* to verify (entrypoint, column bindings, conventions, and any validity blocks — `split` / `trials` / `frictions` / `corpus` / `universe` / `study` / `windows` / `pipeline`). Most validity checks activate only when their block is declared — Calma never guesses a scope that could flip a verdict; the exception is the thin-input plausibility family, which flags from the series alone. Don't write it by hand: `calma draft <repo>` points Calma at a messy repo and writes a runnable `verify.yaml`, auto-detecting the safe blocks (split, trials) and *suggesting* the rest.

### Running the website locally

```bash
npm install
npm run dev          # http://localhost:3000  (marketing site + /dashboard console)
```

The console additionally needs the control-plane API and WorkOS env — see [`DASHBOARD.md`](DASHBOARD.md) and [`control_plane/README.md`](control_plane/README.md).

---

## Architecture & design properties

```
.claude/skills/calma/scripts/   the deterministic engine (pure stdlib): verdict · ledger · compare ·
                                recompute · numeric · validity families · run_hermetic
src/calma/                      the thin pip-installable facade (a client of the one engine, not a fork)
edges/                          the AI edges (extract / draft / synth / repair) — firewalled from core
mcp/                            the host-agnostic MCP server (transport)
pr/  ·  github_app/             the PR-review bot (CI) + the hosted GitHub App (transport)
app/  ·  components/  ·  lib/    the Next.js website (marketing) + the logged-in /dashboard console
control_plane/  ·  api/         the FastAPI control plane + its Vercel Python entry (verifications/tenants/keys)
registry/                       the hash-chained public catch registry served by the site
benchmark/                      the 117-case corpus + the 4-arm comparison + scoring
```

- **The verdict is one function**, re-derived byte-for-byte at the gate — non-gameable.
- **Pure stdlib; offline by default — your code and data never leave your machine.** The honest answer to "where is our data processed?" is *"on your machine, network-off."* (Optional tiers you turn on explicitly — a remote microVM for untrusted code, an RFC-3161 timestamp, a Rekor log — make a network call, and the ledger records exactly which.)
- **Every transport is firewalled** — `mcp/`, `pr/`, `github_app/` import no verdict core; the validity detectors import no model.
- **Tested:** 71 core suites / 0 failed (pure stdlib) + the MCP + PR transport suites; one command runs all three — `make test-all`; 628 recipes against reference vectors.

## Limitations

Read these before you rely on a verdict.

- **Reproducible is not the same as right.** A `CONFIRMED` verdict means the headline number **re-derives from the raw outputs and is internally sound under the stated scope** — it is *not* a guarantee of real-world correctness, future performance, model soundness, or investment merit, and it is **not investment advice**. A program that deterministically fabricates its own raw outputs will reproduce; calma checks the number against the outputs, not the outputs against reality.
- **Validity depth scales with what you declare.** The leakage / overfitting / survivorship / look-ahead / regime / era-embargo / risk-sim families run when you point calma at the split, trials, frictions, universe, embargo, or simulation_assumptions they need. A thin-input result with nothing declared gets the *soft* plausibility-smell layer only (it degrades a number to `CONFIRMED-WITH-CAVEATS`, never `INVALIDATED`). Missing information degrades toward `CAN'T-CONFIRM`, never toward an accidental `CONFIRMED`/`REFUTED`.
- **Coverage is honest, not total.** Some assumptions are not checkable from one output log (e.g. a risk sim's one-of-n non-collusion); calma reports those as out-of-scope rather than asserting them. The per-verdict ledger lists exactly what was and was not checked. On the recipe side, **597 of 628 recipes (95.1%) are independently verified (Tier-1)** — against the live framework number, the official numerai-tools, or a frozen vector generated from numpy/scipy/sklearn — with a `make eval` gate that won't let that ratio regress (`benchmark/coverage_report.py`); the remaining 31 are honestly listed, not hidden.
- **Isolation varies by host.** A verified sandbox is used where available; on other hosts re-execution runs with reduced isolation and **the ledger records the tier it actually achieved**. Treat third-party code accordingly.

## Develop

The core is pure Python stdlib — no virtualenv needed to run or test it.

```bash
make test         # the core suite (pure stdlib): 71 suites, 0 failures
make test-all     # every layer: core + MCP + PR transports (bootstraps ~/.calma venvs if missing)
make eval         # the standing eval net: core suite + framework golden vectors + recompute baseline + determinism
make demo         # watch a real inflated backtest get caught (offline, zero setup)
make benchmark    # synthetic-only quick track (the full 117-case run is in benchmark/README.md → "Reproduce")
```

The engine lives in `.claude/skills/calma/scripts/` and imports nothing outside the standard library. The intelligence layers (`edges/`) and the transports (`mcp/`, `pr/`, `github_app/`) are **firewalled** from it — a test fails if any of them imports the verdict core, and the validity detectors import no model. Run the core suite under the **system** `python3` (running it inside an edges venv produces false failures). See [`docs/extending.md`](docs/extending.md) to add a recipe or a validity family.

## Status & docs

`v0.12.0`. Real and tested. See [`CHANGELOG.md`](CHANGELOG.md), the [install guide](docs/install.md), the [extending guide](docs/extending.md), the [supported frameworks](docs/frameworks.md), the [PR-bot adopter guide](docs/pr-bot.md), the [GitHub App guide](github_app/README.md), the [console/auth guide](DASHBOARD.md), and the [security policy](SECURITY.md).

## License

MIT. Calma is pure Python stdlib at runtime — no copyleft exposure, no third-party supply chain.
