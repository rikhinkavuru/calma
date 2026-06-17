# Calma

[calma1.vercel.app](https://calma1.vercel.app/) · `v0.10.0` · MIT · pure Python stdlib

**Independently verify a computational result by re-executing it to ground truth and recomputing the headline number from the raw outputs — then prove or break the claim.**

Calma is an open-source verifier for numbers that matter. Point it at a result — a backtest's Sharpe, a model's accuracy, a "2.3× faster" benchmark, a cleaned dataset, an LLM eval — and it **re-runs the code in a network-off sandbox, recomputes the metric from the raw output files (never the reported number), and diffs it against the claim** under a calibrated tolerance. The verdict comes from a single deterministic function, not a language model. If the number is real, Calma confirms it with a signed, replayable proof. If it isn't, Calma breaks it and shows you exactly where.

> "SOC 2 for backtests." The auditor can't be the auditee — Calma re-derives every label byte-for-byte, so a stamp can't be faked, even by Calma.

```
$ calma verify ./my-backtest "Sharpe 2.6"
  REFUTED — confidence 0.81
  claimed 2.6 → the code recomputes 0.4 over runs/returns.csv
  re-executed under seatbelt-verified isolation, controlled-to-bit
  fix:  the headline uses 252-day annualization on weekly returns; recompute with the right convention
  replay:  calma replay ./my-backtest/.calma/run     # re-derive this verdict offline, byte-for-byte
```

---

## Why

Every dashboard, paper, and pitch deck reports a number. Almost none of them can be independently checked without trusting whoever produced it. AI agents make this worse: they now generate the backtests, the evals, and the "tests pass" — and they are confidently wrong at scale. The expensive failures (a fund allocates on an inflated Sharpe; a team ships a model that leaked its test set) come from a number that was **technically reproducible but not valid**.

Calma is built around one act almost no one else does: **recompute the claimed number from the raw outputs, and separately check that the result is sound.** Those are two different questions, and Calma answers both.

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
   ┌─────────┐   recompute the headline metric from those raw files with one of 623 SOTA recipes
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
| **CAN'T-CONFIRM** | not enough structure / determinism / isolation to decide — always carries a concrete `fix:` |
| **MIXED** | multi-claim, at least one broken |

Defaults are conservative: missing information degrades toward CAN'T-CONFIRM, never toward an accidental CONFIRMED or REFUTED.

### The validity layer — 10 families → INVALIDATED

Reproducibility (the number recomputes) is *not* validity (the result is sound). Calma ships a real, integrated validity layer — pure-stdlib, bit-stable, each detector only ever **degrades** a verdict, and `INVALIDATED` fires only under a scope-guard (when the claim positively asserts the clean property the data violates):

| Family | Catches |
|---|---|
| **Leakage** | row / id / temporal look-ahead / target leakage + a leakage-corrected re-run |
| **Overfitting** | Deflated Sharpe (Bailey–López de Prado) + PBO via CSCV; N is never guessed |
| **Execution realism** | fees / slippage / borrow / financing + Almgren √ market-impact + net-of-friction re-run + capacity |
| **Contamination** | exact eval-in-corpus (sha256) + near-duplicate MinHash/LSH |
| **Backtest soundness** | omitted costs (gross-sold-as-net), cherry-picked window, survivorship universe |
| **Point-in-time / look-ahead** | point-in-time membership / attrition + availability-date checks + a +1-period-lag probe |
| **Data-snooping** | study-wide multiple-testing — Bonferroni / Holm / BHY + the Harvey-Liu-Zhu Sharpe haircut (t > 3.0) |
| **Regime / walk-forward** | in-sample → out-of-sample edge collapse, corroborated by a two-sample KS regime shift |
| **Model-process leakage** | featurization fit on train+test, validation-reuse / selection-on-test |
| **Distributional shift** | covariate / target shift between train and test (KS + PSI) |

### Breadth

`calma recipes` → **623 metrics across 16 families**, each validated against byte-reproducible reference vectors: trading (Sharpe/Sortino/Calmar/VaR/CVaR), classification (accuracy/AUC/F1/log-loss/ECE/Brier), regression (RMSE/MAE/R²), analytics (sum/mean/percentile/groupby/join-loss), engineering ("2.3× faster"/p50–p99/throughput/coverage), retrieval & LLM evals (recall@k/NDCG/MRR/pass@k/exact-match), statistics (p-value/CI/effect-size), derivatives (Black-Scholes + Greeks/IV), credit, rates, fund & LP (TVPI/DPI/KS-PME), forecasting (MAPE/sMAPE/MASE/pinball), and more. Black-box over **Python, R, Julia, C++, Rust**.

### Isolation & attestation

Verified network-off own-code tiers — **Seatbelt** (macOS) and **bubblewrap** (Linux) — each self-tested (a planted secret-read and an egress attempt must both fail), plus a network-denied **Docker** tier and a **remote Firecracker microVM** (`--isolation e2b`, vendor-neutral: E2B cloud or self-hosted, egress denied in-guest) for untrusted counterparty code on a Docker-less host. Every catch ships a proof object: a hash-chained public registry, **DSSE + OpenSSH SSHSIG dual-signing** (zero-install verify), an RFC-3161 timestamp, and an optional Sigstore/Rekor transparency log with offline-verifiable inclusion proofs. Pure Python stdlib, no third-party runtime dependencies.

---

## Surfaces — the engine, everywhere

Calma is one deterministic engine behind five surfaces. *AI proposes, determinism disposes.* Each surface is a thin transport that calls the engine as a black-box subprocess and never re-implements a verdict (enforced by firewall tests).

- **Claude Code skill / inline agent guardrail** — a Stop hook catches numeric claims before an agent reports them; the agent's own work gets verified mid-loop.
- **CLI** — `calma verify`, `recipes`, `suggest`, `replay`, `doctor`, `seal`, `registry verify`.
- **MCP server** (`python -m calma_mcp`) — the deterministic verifier callable from *any* MCP host (Cursor, Codex CLI, Windsurf, Claude Desktop, CI bots).
- **A1 artifact pipeline** (`python -m edges.extract`) — point it at a notebook / PDF / CSV and it verifies *every* number, each catch tied to its source span ("cell 14 says 0.94 → recomputes to 0.71").
- **PR-review bot** (`pr/` + a hosted GitHub App in `app/`) — re-runs `calma verify` on a PR's changed result-dirs in the engine's sandbox and posts the verdicts inline + a gating check-run, built on the pwn-request-proof two-workflow pattern.

### The AI edges (intelligence around a deterministic core)

LLMs are used only where they can't fake a verdict: **extracting** claims from messy artifacts, **drafting** verify contracts for repos that ship none (the heuristic always disposes), **synthesizing** new recipes via CEGIS (draft → admit → counterexample → re-draft; data has the final say), and **auto-repairing** a broken result then re-verifying with an anti-test-hacking gate. The `edges/` package is firewalled off from the pure-stdlib core.

---

## The benchmark

`benchmark/` ships a 129-case corpus (synthetic + external UCI/sklearn + real-world) scored on two axes (NASEM 2019):

- **Reproducibility** — does the headline number recompute? Calma **100%** catch / 0 false-confirm / 0 false-alarm vs an LLM-as-judge ~82% and trust-the-number 0%.
- **Validity** — the cell where the number *reproduces* but the result is invalid: Calma **100%** (it INVALIDATES the 12 tagged leaked / overfit / survivorship / shift cases) vs a recompute-only method's **0%**.

A fourth `agent-with-exec` arm (a frontier agent with a `run_python` tool, sandboxed identically) measures the *honest* differences once an agent can execute: verdict-instability (Calma 0 by construction), a pass^k consistency curve, agreement-with-Calma, cost, and the validity blind spot — across ≥2 model families, every counted run network-off-isolated, every transcript published.

---

## Quickstart

```bash
# install the CLI (pure stdlib; no runtime deps)
./install.sh                      # or: pip install -e . from the repo

# verify a result directory (auto-drafts a contract, or reads a committed verify.yaml)
calma verify ./result "accuracy 0.94" --metric accuracy --json

# see the catalog, get a recipe suggestion, replay a sealed verdict offline
calma recipes
calma suggest ./result
calma replay ./result/.calma/run

# prove the sandbox actually isolates on this host
python3 .claude/skills/calma/scripts/run_hermetic.py doctor
```

A `verify.yaml` pins *how* to verify (entrypoint, column bindings, conventions, and any validity blocks — `split` / `trials` / `frictions` / `corpus` / `universe` / `study` / `windows` / `pipeline`). Validity checks activate only when their block is declared — Calma never guesses a scope.

---

## Architecture & guarantees

```
.claude/skills/calma/scripts/   the deterministic engine (pure stdlib): verdict · ledger · compare ·
                                recompute · numeric · 10 *_checks.py validity families · run_hermetic
edges/                          the AI edges (extract / draft / synth / repair) — firewalled from core
mcp/                            the host-agnostic MCP server (transport)
pr/  ·  app/                    the PR-review bot (CI) + the hosted GitHub App (transport)
benchmark/                      the 129-case corpus + the 4-arm comparison + scoring
```

- **The verdict is one function**, re-derived byte-for-byte at the gate — non-gameable.
- **Pure stdlib, fully offline, code never leaves your machine.** The honest answer to "where is our data processed?" is *"on your machine, network-off."*
- **Every transport is firewalled** — `mcp/`, `pr/`, `app/` import no verdict core; the validity detectors import no model.
- **Tested:** 39 core suites / 0 failed (pure stdlib) + 147 transport tests; 623 recipes against reference vectors.

## Status & docs

`v0.10.0`. Real and tested. See [`CHANGELOG.md`](CHANGELOG.md), the [PR-bot adopter guide](docs/pr-bot.md), and the [GitHub App guide](app/README.md).

## License

MIT. Calma is pure Python stdlib at runtime — no copyleft exposure, no third-party supply chain.
