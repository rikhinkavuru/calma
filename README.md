# Calma

**Calma checks whether a result is actually true — by re-running the code and recomputing the number itself, instead of trusting what was reported.**

Software (and AI agents) produce numbers all day: a model's accuracy, a trading backtest's return, "I cleaned
10,000 rows," "the total is $4.2M." Most of the time it's fine. When it isn't, the failure is silent — a
number that doesn't reproduce, a leak in the data, an overfit that only shows up later. Calma re-executes the
work in a sandbox, **recomputes the headline number from the raw output files** (never the number that was
reported), and tells you whether the claim holds — with a one-command way to reproduce it.

It's an open-source [Claude Code](https://code.claude.com) skill, and also runs as a plain Python CLI. Every
number, the verdict, and even the confidence score come from deterministic scripts, **not** from a model's
opinion.

## Demo

<!-- DEMO: replace this with the recorded GIF/video, e.g. ![Calma demo](docs/demo.gif) -->
*(Demo recording coming soon.)*

Try it on a real inflated backtest that ships with this repo — one command, no setup, no network:

```
$ calma demo

re-verifying a real overfit backtest (it claimed +14,698% on BTC)...

REFUTED  (confidence 98/100)  -  the result does not hold
  - also: strategy underperforms the trivial baseline (edge -0.7422 <= 0)
  claimed +14,698%  ->  recomputed -32.4%
  reproduce: calma replay <demo-copy>/.calma/run

that was a real inflated backtest. now try your own:  calma verify <folder> "<claim>"
```

This is real output: the fixture lives at `.claude/skills/calma/assets/btc`, and `calma demo` copies
it to a temp dir, re-executes it on the held-out data, and recomputes the number
(equivalently: `calma verify .claude/skills/calma/assets/btc "+14,698% backtest"`).

You get one of these answers:

- **CONFIRMED** — it re-runs and the number checks out.
- **CONFIRMED-WITH-CAVEATS** — it holds, but narrower than claimed (and the caveat is named).
- **REFUTED** — the recomputed number contradicts the claim, with a reproduction you can run yourself.
- **MIXED** — more than one claim was checked; at least one is REFUTED while the others hold.
- **CAN'T-CONFIRM** — it can't be fully checked yet, plus a `fix:` line with the exact change to make it
  checkable (e.g. "set a fixed seed", "write predictions to a CSV"). Calma never cries wolf.

## Install

The skill is one self-contained folder with **no dependencies** (pure Python standard library,
Python 3.9 or newer).

Platforms: **macOS is first-class** (verified Seatbelt sandbox, proven by a built-in self-test);
**Linux** runs with reduced isolation and says so in the ledger (`host-not-isolated` — the stamp
never lies); **Windows is unsupported**.

As a Claude Code plugin:

```
/plugin marketplace add rikhinkavuru/calma
/plugin install calma@calma
```

That's the whole setup. The plugin installs two things:

1. **The skill** — your agent runs `calma verify` on results it produces (and you can ask for it
   any time: "verify this").
2. **The zero-touch guardrail** — a Stop hook that watches the agent's final message for checkable
   numeric claims ("accuracy is 0.91", "the backtest returned +340%"). When it finds one in a
   verifiable project, it re-executes the work and recomputes the number *before the agent finishes
   its turn*. If the number doesn't hold, the agent is stopped and handed the verdict — a wrong
   number can't be reported to you as fact. If everything checks out (or nothing is checkable),
   you never hear from it.

The guardrail is built to be invisible until the moment it isn't: precision-tuned detection (it
would rather miss than misfire), cache-first re-checks (~80ms when nothing changed), a hard time
budget, and fail-open everywhere — an error in the hook can never break your session. Cost: the
first catch costs up to 30s; repeats are cache-instant. It only auto-executes where a verified
sandbox tier is live (otherwise it skips and says so in the breadcrumb log). Opt out any
time: `CALMA_HOOK=0`, `touch .calma/hook-off`, or `.calma/config.json → {"hook": {"enabled": false}}`.
Every decision it makes is logged to `.calma/auto_history.jsonl` (see `calma stats`).

Or copy the folder into any project (works with every agent that reads SKILL.md — Claude Code, Codex,
Cursor, ...):

```bash
git clone https://github.com/rikhinkavuru/calma
cp -r calma/.claude/skills/calma  your-project/.claude/skills/
```

Or use it as a plain CLI (from the cloned repo root, matching the comment in `bin/calma`):

```bash
cd calma   # the repo you just cloned
ln -s "$(pwd)/bin/calma" /usr/local/bin/calma
calma demo
```

## Commands

```bash
calma demo                          # zero-setup: catch a bundled real inflated backtest (offline, seconds)
calma verify <folder> "<claim>"     # check a result (exit codes below)
calma verify <folder>               # no claim: checks the result reproduces (CONFIRMED scope=reproduction)
calma recipes                       # the 120 built-in metrics, grouped by family
calma verify <folder> "<claim>" --json               # machine-readable verdict (for agents/CI)
calma verify <folder> "<claim>" --check-determinism  # run twice; flaky outputs can't confirm anything
calma verify <folder> "<claim>" --timeout 300        # raise the re-execution budget (default 120s)
calma verify <folder> "<claim>" --trust third-party  # counterparty code: refuse unless a verified
                                    # container/VM tier is live (never run someone else's code unsafely)
calma teardown <folder> "<claim>" [--svg card.svg]   # shareable "claimed X -> really Y" card (+ SVG image)
calma replay <run_dir>              # re-run a saved verification; exit 0 iff the verdict reproduces
calma stats <folder>                # verification history: counts, recent catches, hook activity
calma seal <run_dir> [--publish registry/]   # one command: sign + RFC 3161 timestamp + counterparty
                                    # instructions (VERIFY-THIS.txt), optionally publish
calma attest keygen [--import ~/.ssh/id_ed25519]  # one-time signing key; after this, every verify is signed
calma attest verify <bundle> [--key pub.hex] [--replay]   # check a signed bundle, fully offline
calma attest timestamp <bundle>     # RFC 3161 trusted timestamp - makes "verified before <date>" provable
calma attest sigstore <bundle>      # lab tier: keyless countersign into the public Rekor log
calma publish <run_dir>             # append a REDACTED entry to the public catch-history registry
calma registry verify [dir]         # audit the registry chain offline: hashes, links, signatures
python3 .claude/skills/calma/scripts/run_hermetic.py doctor   # prove the sandbox works on your machine
```

Exit codes (`calma verify`):

| code | meaning |
|------|---------|
| 0 | clean — CONFIRMED / CONFIRMED-WITH-CAVEATS |
| 1 | not clean — REFUTED / MIXED / CAN'T-CONFIRM (under the default `--fail-on not-clean`) |
| 2 | bad input — missing target, malformed contract, unknown `--metric` |
| 3 | refused — execution declined (e.g. `--trust third-party` without a verified container/VM tier) |
| 4 | killed — the re-execution exceeded the `--timeout` budget |

In CI, the GitHub Action wraps the same verify:

```yaml
- uses: rikhinkavuru/calma/.github/actions/calma@main
  with:
    target: ./results
    claim: "accuracy 0.87"
    fail_on: refuted
```

Claims are natural language: `"accuracy 0.87"`, `"+14,698% backtest"`, `"$4.2M revenue"`,
`"processed 10,000 rows"` — the number and the metric are parsed from the words (`--metric` pins it
explicitly). With no claim at all, Calma still checks that the result reproduces — a clean re-run whose
number recomputes from the raw outputs reports `CONFIRMED (scope=reproduction)` and exits 0.

Verification is **incremental**: results are cached by the content hash of the code, data, contract, and
claim, so re-verifying something unchanged returns the prior verdict instantly (`--force` re-executes).
That makes it cheap enough for an agent to call in its loop after every result.

Drop a `verify.yaml` next to a result (JSON or simple YAML) to pin the contract. The contract pins **how**
to verify (entrypoint, which column is the metric, conventions) — the claim under test is always **yours**:
if your claim states a different value for the pinned metric, Calma checks *your* value; if it names a
metric the contract doesn't pin, you get CAN'T-CONFIRM with a fix line (never a verdict about a claim you
didn't make); if your text has no checkable number, the committed claim is verified and the output says so.
In CI, use the GitHub Action (`.github/actions/calma`) — `fail_on: refuted` fails the build only when a
claim actually breaks.

## What it can check

- **Does it reproduce?** Re-run → same number, or it isn't a result. (A crashed re-run can never CONFIRM —
  stale output files don't count.)
- **Does the number recompute?** The headline metric, rebuilt from the raw outputs.
- **Does it beat a basic baseline?** (e.g. buy-and-hold, or majority-class.)
- **Is it stable?** A calibrated tolerance so normal hardware/threading noise never causes a false alarm.

Built-in metrics cover **trading** (Sharpe, return, drawdown), **machine learning** (accuracy, AUC,
F1/macro/micro, PR-AUC, log-loss, MCC, calibration/ECE, Brier), **regression & forecasting** (RMSE, MAE, R²,
MAPE/sMAPE, MASE, pinball), **retrieval & LLM evals** (recall@k, NDCG, MRR, top-k, exact-match, pass@k),
**analytics** (sums, means, medians, percentiles, group-bys, distinct/null/duplicate counts, join row-loss),
**engineering** ("2.3× faster", latency p50–p99, throughput, peak memory, test coverage, error rates),
**statistics** (p-values, confidence intervals, A/B lift, chi-square, correlation, effect size), and
**business/finance** (CAGR, NPV/IRR, churn, margin, ledger reconciliation), **quant risk** (Sortino, Calmar,
VaR/CVaR, beta/alpha, information ratio), and **deeper stats/ML/analytics** (Mann-Whitney, ANOVA, Fisher exact,
KS, Cohen's κ, balanced accuracy, WER, perplexity, MAP@k, HHI, Gini, entropy…) — **120 recipes**, each validated
against the published reference implementation (scikit-learn, SciPy, NumPy, numpy-financial, statsmodels, jiwer; see
`.claude/skills/calma/references/recipes.md`). It works on programs written in **Python, R, Julia, C++, or
Rust** — Calma treats your program as a black box and does the recompute itself.

## Under the hood

`calma verify` runs a small pipeline, one script per step, so the result is auditable:

1. **Detect** the entrypoint, output files, and which column is the metric (`verify.yaml`, auto-drafted).
2. **Run** the code in a verified sandbox (macOS Seatbelt; network off). A built-in `doctor` self-test
   proves the sandbox actually blocks secret-reads and network access before the tier is claimed. On hosts
   without a verified sandbox (e.g. Linux CI) the code still runs, but the verdict is stamped
   `host-not-isolated` and a clean pass is capped at CONFIRMED-WITH-CAVEATS — the stamp never lies.
3. **Recompute** each metric from the raw outputs, the same way every time (no floating-point surprises).
4. **Compare** recomputed vs claimed, allowing for the claim's own measurement noise.
5. **Verdict** from a single deterministic function — re-checked byte-for-byte so it can't be fudged.
6. **Attest** with a content-addressed manifest (in-toto/SLSA statement + CycloneDX ML-BOM) — and, after a
   one-time `calma attest keygen`, every verify is signed into a portable DSSE bundle whose predicate is a
   VSA-style verdict statement (`github.com/rikhinkavuru/calma/verdict/v1` — bundles signed under the
   legacy `calma.dev/verdict/v1` URI remain valid: verifier + version, the contract and calibration
   hashes as policy, the verdict, the claims). The same Ed25519 key signs twice: a raw DSSE signature (the
   envelope Sigstore countersigns) and an OpenSSH SSHSIG — so a counterparty can check the signature with
   stock `ssh-keygen -Y verify` and **zero installs** (sidecar files land next to the bundle).
   `calma attest verify <bundle>` is the full offline check: both signatures, the subject digests, and a
   byte-for-byte re-derivation of every verdict label — neither a tampered bundle nor one re-signed under a
   different key with forged labels can pass. `--key` pins the expected signer; `--replay` re-executes.
   `calma attest timestamp` adds an RFC 3161 trusted timestamp (network needed only at stamping time; the
   token verifies offline forever), and `calma attest sigstore` (lab tier, needs sigstore-python)
   countersigns the same payload keylessly into the public Rekor transparency log.
7. **Publish** (opt-in): `calma publish <run_dir>` appends a redacted entry — claim, metric, claimed vs
   recomputed, verdict, content hashes; never code, never data — to a hash-chained, signed public registry
   (the catch history at `/registry`). Publish requires attest; `calma registry verify` audits the whole
   chain offline.

## Limitations

Calma proves a result is **real and reproduces** — not that it answered the *right* question. When it can't
fully verify something, it says so and tells you the fix, rather than guessing. The verified-isolation tier
ships on macOS today; on other platforms runs are honestly stamped as unisolated (a Linux tier is the top
roadmap item). Running untrusted third-party code safely needs a container/VM (planned); for now such code
is refused rather than run unsafely.

## FAQ

**Can't I just ask my agent to verify it — or to re-run the code itself?**
Asked to "double-check," a model usually re-reads its reasoning and says it looks right — that's a second
opinion, not verification. And even when an agent does re-run the code, three gaps remain: (1) the agent
*decides* whether the output matches the claim — a judgment call it can rationalize, especially about its
own work; (2) nothing stops it from "fixing" the comparison instead of the code; (3) there's no
reusable artifact — no tolerance model, no audit trail, no exit code for CI. Calma closes all three: the
diff happens under a calibrated tolerance in deterministic, unit-tested scripts, the ledger re-derives
every label byte-for-byte so a model can't author a passing verdict, and every run leaves a
content-addressed manifest — signed into a portable attestation bundle once you've made a key. Independent benchmarks back this up: agents *assessing* reproducibility score
~21% accuracy (REPRO-Bench) — judgment fails where re-execution works. The auditor can't be the auditee.

**What do people use for this problem today?**
Honestly: mostly nothing — they trust the printed number, or eyeball it. The adjacent tools solve
different problems: eval/observability platforms (LangSmith, Langfuse, Arize) trace and score with
LLM-judges; data validators (Great Expectations, Pandera) check schemas and drift; CI tests check code
paths the author thought to test. None of them re-execute the work and recompute the claimed number from
the raw outputs. In quant, independent backtest validation exists — as bespoke human consulting. That
empty cell is what Calma fills.

**Why not just put my rules / bounds / invariants in CLAUDE.md or the start of the session?**
Instructions in context are advisory and probabilistic. A model can forget them, deprioritize them, or
rationalize around them, especially late in a long session, and they only shape what gets *generated* —
they don't prove the output is correct. Calma enforces the check by *running* the code: it recomputes the
metric, compares it to the claim under a calibrated tolerance, and decides with code. Put the intent in
CLAUDE.md to guide generation; use Calma to verify the result that comes out.

**How is this different from eval / observability tools (LangSmith, Langfuse, Arize, etc.)?**
Those trace runs and score them with model-as-judge, or track drift over time. None re-execute the work
and recompute the claimed number. Calma is verification by execution to ground truth, not by judgment.

**Can the agent game the verdict?**
The label and every statistic come from deterministic, unit-tested scripts, and the ledger re-derives the
verdict byte-for-byte from its inputs — a model can't author a passing label. The one surface the producer
influences is which output column maps to the claim; a REFUTED is only allowed when that binding passed an
independent sanity check AND the claim target is unambiguous (named in the claim or pinned with --metric).
An ambiguous binding degrades to CAN'T-CONFIRM, never a verdict.

**Does it work if there's no specific number to check?**
Yes. With a claim it recomputes-and-diffs; without one it still checks that the result reproduces and that
any declared invariants hold.

**Does my code or data leave my machine?**
No. Everything runs locally; nothing is uploaded. On macOS the run is inside a verified network-off
sandbox; on hosts without one, the verdict says so explicitly instead of pretending.

**Is it only for trading/quant?**
No. It ships 120 metrics across trading, ML (classification, regression, retrieval/RAG, LLM evals),
analytics, engineering/performance, statistics, and business/finance, and treats your program as a black
box, so it works across Python, R, Julia, C++, and Rust.

**What if it can't fully verify something?**
It returns CAN'T-CONFIRM with a `fix:` line naming the exact change to make it checkable (e.g. "set a
fixed seed", "write predictions to a file"), instead of guessing. It biases toward a caveat over a false
alarm.

## Development

```bash
python3 .claude/skills/calma/scripts/tests/run_all.py     # full test suite (pure stdlib, no deps)
```

## Repository layout

```
.claude/skills/calma/    the skill — SKILL.md, scripts/, assets/, calibration/
.claude-plugin/          plugin + marketplace manifests (/plugin install calma@calma)
hooks/hooks.json         the zero-touch guardrail (Stop hook) registration
bin/calma                CLI launcher
scripts/teardowns/       the worked backtest example
registry/                the public, hash-chained catch-history registry
app/  components/        the project website (optional; not needed to use the skill)
docs/                    design specs and notes
```

## License

MIT
