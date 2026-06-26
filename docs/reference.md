# Reference

The complete command surface, generated from `calma schema` (the machine-readable spec the CLI
emits for agents). Engine version `0.13.0`.

> `calma` is the installed command. If it isn't on your PATH, substitute
> `python3 .claude/skills/calma/scripts/calma.py`. The canonical machine-readable spec is always
> `calma schema` — this page mirrors it.

- [Outcomes and verdicts](#outcomes-and-verdicts)
- [Exit codes](#exit-codes)
- [Commands](#commands)
  - [`verify`](#verify) · [`up`](#up) · [`init`](#init) · [`batch`](#batch) · [`status`](#status)
    · [`doctor`](#doctor) · [`recipes`](#recipes) · [`suggest`](#suggest) · [`demo`](#demo)
  - [`replay`](#replay) · [`report`](#report) · [`stats`](#stats) · [`teardown`](#teardown)
    · [`draft`](#draft) · [`onboard`](#onboard) · [`repair`](#repair) · [`modes`](#modes)
  - [`proof`](#proof) · [`attest`](#attest) · [`seal`](#seal) · [`publish`](#publish)
    · [`registry`](#registry) · [`schema`](#schema)
- [The `calma.toml` schema](#the-calmatoml-schema)
- [The proof bundle (run directory)](#the-proof-bundle)
- [Recipes](#recipes-catalog)

---

## Outcomes and verdicts

The terminal headline always shows one of **three outcomes**. They are a deterministic roll-up
over **six internal verdicts** (the verdict still appears in `--why`, `report.txt`, and `--json`).

| Outcome | Glyph | Meaning |
|---|---|---|
| **Confirmed** | `✓` | the number re-derives from the raw outputs and is internally sound under the stated scope |
| **Caught** | `✗` | Calma found a reason this number can't ship unchanged |
| **Can't tell** | `?` | not enough structure / determinism / isolation to decide — fail-closed, never a green pass |

The roll-up (`verdict.outcome()`, deterministic and total) maps each internal verdict to one
outcome:

| Internal verdict | Rolls up to | Meaning | Typical exit |
|---|---|---|---|
| `CONFIRMED` | **Confirmed** `✓` | reproduces and matches the claim within the calibrated budget | 0 |
| `CONFIRMED-WITH-CAVEATS` | **Confirmed** `✓` | holds, but narrower than claimed (e.g. plausibly-bound, or cross-stack numeric noise) | 0 (1 under `--fail-on caveats`) |
| `REFUTED` | **Caught** `✗` | the code recomputes a materially different number | 1 |
| `INVALIDATED` | **Caught** `✗` | the number *reproduces*, but the result is not valid (leaked / overfit / contaminated) | 1 |
| `FLAG_FOR_DECLARATION` | **Caught** `✗` | a soft validity smell fired on an undeclared scope; resolve by declaring the block | 1 |
| `INCONCLUSIVE` | **Can't tell** `?` | reproduces, but a concern can't be adjudicated, or execution was killed / refused | 1 (or 2/3/4) |
| `MIXED` *(multi-claim)* | **Caught** `✗` | at least one claim in the set is broken | 1 |

Defaults are conservative: missing information degrades toward `INCONCLUSIVE`/Can't tell, never
toward an accidental `CONFIRMED` or `REFUTED`. The exit code is consulted only to catch one case
the verdict alone misses — a clean verdict that still failed the gate on an open blocking finding
reads **Caught**, never a green pass.

---

## Exit codes

The process exit code is the gate. It is independent of the displayed outcome's color.

| Code | Name | Meaning |
|---|---|---|
| `0` | clean | Confirmed / clean — the gate passed |
| `1` | findings | Caught / findings — the gate failed (a catch, or `INCONCLUSIVE` under the default `--fail-on not-clean`) |
| `2` | invalid | invalid ledger (a stored verdict failed to re-derive) |
| `3` | refused | execution refused by the trust posture (e.g. `--trust third-party` with no verified container/VM tier live) |
| `4` | killed | the run was killed (timeout / resource budget) |

`--fail-on {not-clean,refuted,caveats}` (on `verify` and `batch`) chooses which verdicts produce
exit 1; see [`verify`](#verify).

---

## Commands

| Command | What it does |
|---|---|
| [`verify`](#verify) | re-run + recompute + diff against the claim |
| [`up`](#up) | one command: auto-detect (first run) → verify → verdict + proof; writes `calma.toml` |
| [`init`](#init) | auto-detect a result + recipe and write `calma.toml`, or scaffold a framework starter |
| [`batch`](#batch) | verify many targets at once + a summary table (CI / sprint use) |
| [`status`](#status) | is the guardrail on? hook + signing key, recent checks, last run |
| [`doctor`](#doctor) | check the install is healthy (`[✓]`/`[!]`/`[✗]` + fixes) |
| [`recipes`](#recipes) | list recipes by family, or `recipes search <term>` to find one |
| [`suggest`](#suggest) | rank the recipes a free-text ask most likely means (never verifies) |
| [`demo`](#demo) | watch Calma catch a real inflated backtest (bundled fixture, offline) |
| [`replay`](#replay) | re-run a saved verification and check it reproduces |
| [`report`](#report) | render a branded HTML report + a self-contained offline replay bundle |
| [`stats`](#stats) | summarize a target's verification history |
| [`teardown`](#teardown) | print a shareable card when a claim breaks |
| [`draft`](#draft) | generate a `verify.yaml` for a messy repo (heuristic, or `--ai`) |
| [`onboard`](#onboard) | onboard a bespoke metric from a methodology + reference vectors (CEGIS) |
| [`repair`](#repair) | propose a minimal patch for a catch and re-verify it (accepts only if it flips clean) |
| [`modes`](#modes) | show or set autonomy: verify scope + action mode |
| [`proof`](#proof) | re-verify a proof offline (one command), or show it at a glance |
| [`attest`](#attest) | sign a run into a portable bundle, or verify one offline |
| [`seal`](#seal) | the whole proof chain: sign + RFC-3161 timestamp + counterparty instructions |
| [`publish`](#publish) | append a redacted entry to the public catch-history registry |
| [`registry`](#registry) | audit the catch-history registry chain offline |
| [`schema`](#schema) | emit the machine-readable CLI spec (for agents) |

### `verify`

```
calma verify [target] [claim_text] [options]
```

Re-execute the code in a network-off sandbox, recompute the headline metric from the raw outputs,
and diff it against the claim under a calibrated tolerance. `target` defaults to `.`; the claim is
optional (without one, Calma reproduces the result and reports the recomputed value).

| Flag | Values | Description |
|---|---|---|
| `--claim CLAIM` | | the claim to check (same as the positional `claim_text`), e.g. `"accuracy 0.87"` |
| `--metric METRIC` | recipe id | force a recipe, e.g. `sharpe` (browse with `calma recipes`) |
| `--run-id RUN_ID` | | name of the run dir under `<target>/.calma/` (default `run`) |
| `--fail-on` | `not-clean` (default) · `refuted` · `caveats` | process exit policy (see [exit codes](#exit-codes)) |
| `--trust` | `own-code` (default) · `third-party` | `third-party` auto-escalates to a container tier and **refuses** (exit 3) if no verified container/VM tier is live |
| `--isolation` | `auto` · `seatbelt` · `bwrap` · `docker` · `e2b` · `firecracker` | isolation backend; explicit choices fail loud if unavailable (never a silent host fallback) |
| `--timeout SECONDS` | `[1, 86400]`, default `120` | re-execution wall-clock budget; overrun kills the run (exit 4) |
| `--force` | | re-execute even if code, data, and claim are unchanged since the last run |
| `--restore` | | restore + pin the repo's declared deps into `<target>/.calma_venv` first (network in this phase only; the run stays network-denied) |
| `--check-determinism` | | re-execute twice and require identical artifacts (catches flaky results) |
| `--mode` | `ask` (default) · `suggest` · `auto` | autonomy for follow-on *actions* only; the verdict is always deterministic |
| `--json` | | print a machine-readable verdict object instead of the report |
| `--why` | | expand the full "not verified" scope list (every undeclared validity family) |
| `--offline` | | auto mode only: skip the one network step (the RFC-3161 timestamp) |
| `--run-only` | | debug: recompute + show the binding and the gap, **no verdict, no gate** (always exit 0) |
| `--cross-engine` | | recompute each metric through an independent second kernel and diff (additive; never changes the verdict) |
| `--emit-otel [ENDPOINT]` | | emit the verdict as a standard OpenTelemetry GenAI evaluation span |
| `--otel-dual BACKENDS` | `braintrust,langsmith` | with `--emit-otel`, also emit native attrs for backends that don't read `gen_ai.*` yet |

### `up`

```
calma up [target] [--claim CLAIM] [--metric METRIC] [--yes]
```

The one-command path. On the first run it auto-detects the result and recipe, verifies, emits a
proof, and writes a committed `calma.toml`; later runs re-verify against that `calma.toml`.
`target` defaults to `.`. `--claim` / `--metric` override `calma.toml`; `--yes` accepts the
auto-detected recipe without prompting (agents / CI).

### `init`

```
calma init [framework] [target] [--list] [--yes] [--force]
```

Omit `framework` to **auto-detect** the result + recipe and write `calma.toml`. Or name a
framework to scaffold a `verify.yaml` starter: `backtrader` · `vectorbt` · `zipline` · `pytorch`
· `xgboost` · `sklearn` (aliases `torch`, `xgb`, `scikit-learn`). `target` defaults to `.`.
`--list` prints the frameworks; `--yes` skips the prompt; `--force` overwrites an existing config.

### `batch`

```
calma batch [targets ...] [--manifest TSV] [--fail-on POLICY] [--timeout S] [--force] [--json]
```

Verify many targets and print one summary table. `targets` are dirs (each with a committed
contract) or globs like `'runs/*'`. `--manifest` is a TSV of `path<TAB>claim<TAB>[metric]` rows
(with `#` comments) for targets without a committed contract. `--fail-on` applies across all
targets (exit 1 if any fails).

### `status`

```
calma status [target] [--json]
```

Is the guardrail on? Shows the Stop hook, the signing key, engine + Python version, the active
`calma.toml`, a 7-day tally (checks · outcomes), a shipped tally, and the last run. `target`
defaults to `.`.

### `doctor`

```
calma doctor [--fix] [--json]
```

Health checks with a `[✓]`/`[!]`/`[✗]` line and a fix for each. `--fix` applies the safe
auto-fixes (e.g. generate a local signing key).

### `recipes`

```
calma recipes [term ...] [--json]
```

List every recipe grouped by family, or `calma recipes search <term>` to find one by meaning.
`--json` prints `{family: [metric ids]}` (or the search hits).

### `suggest`

```
calma suggest <text> [-k N] [--json]
```

Rank the recipes a free-text ask most likely means (suggestion only — never verifies). `-k`/
`--top` sets how many candidates to show (default 5).

### `demo`

```
calma demo [--keep]
```

Re-verify a bundled real overfit backtest (offline, a few seconds) and watch it get caught.
`--keep` retains the temp copy of the fixture and prints its path.

### `replay`

```
calma replay <run_dir>
```

Re-run a saved verification (the `.calma/<run-id>` dir printed on the original verdict) and check
it reproduces the same verdict and recomputed value.

### `report`

```
calma report <run_dir> [--out PATH] [--no-pdf] [--no-sign]
```

Render a branded HTML report (prints to PDF) plus a self-contained, fully-offline replay bundle.
`--out` sets the HTML path (default `<run_dir>/report.html`); `--no-pdf` skips the
headless-browser PDF attempt; `--no-sign` skips signing (integrity hashes then come from files,
not a verifiable bundle).

### `stats`

```
calma stats <target> [--json]
```

Summarize a target's `.calma` verification history.

### `teardown`

```
calma teardown <target> [claim_text] [--claim C] [--metric M] [--force] [--svg PATH]
```

Print a shareable card when a claim breaks. `--svg` also writes the card as a dark SVG image.

### `draft`

```
calma draft <target> [--ai] [--budget N] [--model TIER] [--force] [--json]
```

Generate a `verify.yaml` for a messy repo. Heuristic by default; `--ai` adds the LLM drafter +
counterexample repair loop (needs the edges deps + an API key; falls back to the heuristic if
unavailable). `--budget` caps the model draft+repair rounds (default 3).

### `onboard`

```
calma onboard --metric-id ID --family FAM --methodology TEXT --vectors JSON [options]
```

Onboard a **bespoke** metric (no published oracle) from a methodology + reference vectors: an LLM
proposes the recipe, the deterministic gate admits it only if it reproduces every reference vector
and satisfies the declared invariants (needs the edges deps + an API key). `--family` is one of
`quant|classification|regression|analytics|engineering|retrieval|llm-eval|stats|finance|forecasting`.
`--methodology` and `--vectors` accept `@path` or inline; `--metamorphic-hint` (repeatable) adds
an invariant; `--budget` caps CEGIS attempts (default 6). See [`extending.md`](extending.md).

### `repair`

```
calma repair <run_dir> [--budget N] [--model TIER] [--apply] [--json]
```

For a `REFUTED` / `INVALIDATED` run, an LLM proposes a minimal patch and Calma re-verifies the
patched code from scratch — it accepts the fix **only** if the recompute flips the verdict to
clean (needs the edges deps + an API key). Your files are untouched unless you pass `--apply`.
`--budget` caps the diagnosis hypotheses (default 4).

### `modes`

```
calma modes [--verify SCOPE] [--mode MODE] [--global] [--dir DIR] [--json]
```

Show or set autonomy. `--verify` sets the verify **scope** (`off` · `headline` · `all`) — how
aggressively the zero-touch hook auto-verifies. `--mode` sets the **action mode** (`ask` ·
`suggest` · `auto`) — what Calma does after a catch (seal / timestamp / restore). `--global`
writes to `~/.calma/config.json` (everywhere) instead of `./.calma/config.json`. The verdict is
always deterministic; the mode governs only follow-on actions.

### `proof`

```
calma proof <verify|show> ...
```

The proof is the product — re-verify one offline, or show it at a glance.

**`calma proof verify <path> [--key KEY] [--replay] [--json]`** — the one-command, cosign-style
offline re-verify. `path` accepts a proof bundle file, a run dir, or a project dir, and needs no
network and no trust in Calma's servers: it checks both signatures (DSSE + SSHSIG), every content
hash, and re-derives every verdict label byte-for-byte from its stored inputs, printing a checklist
that ends in the verdict (`ATTESTATION VERIFIED …`) and exiting 0 when the bundle is authentic and
clean. `--key` pins the expected signing key (file path or hex); `--replay` also re-executes the
run and re-derives the number.

**`calma proof show [run_dir] [--json]`** — the proof at a glance (`run_dir` defaults to `.`): the
3-outcome verdict, claimed vs recomputed, the signing key, the data-authenticity ceiling, the
re-verify command, plus a shareable `https://trycalma.ai/proof?...` permalink and an embeddable
badge — `![verified by calma](https://trycalma.ai/badge?...)` — both rendered from the verdict
metadata in the URL (no raw data leaves). The [trycalma.ai/proof](https://trycalma.ai/proof)
permalink page and the badge endpoint are served by the web app.

### `attest`

```
calma attest <keygen|sign|sigstore|timestamp|verify> ...
```

Sign a run into a portable bundle, or verify one offline. `calma attest keygen` generates a local
Ed25519 signing key; `calma attest verify <bundle> [--replay]` checks both signatures, every hash,
and re-derives the verdict byte-for-byte (`--replay` also re-executes). See
[the proof bundle](#the-proof-bundle).

### `seal`

```
calma seal <run_dir> [--no-timestamp] [--publish REGISTRY] [--note TEXT] [--key FILE]
           [--evidence DIR] [--rekor URL] [--rekor-optional] [...]
```

The whole proof chain in one command: sign + RFC-3161 timestamp + counterparty instructions,
optionally publishing a redacted registry entry. `--no-timestamp` skips the one network step;
`--evidence DIR` also exports an allocator evidence bundle (verified result + input lineage +
runtime digests + replay, mapped to GIPS-2026 / ODD); `--rekor URL` logs each entry to a Sigstore
Rekor transparency log (fail-closed unless `--rekor-optional`).

### `publish`

```
calma publish [run_dir] [--registry DIR] [--engagement ID] [--open ID] [--note TEXT] [--rekor URL] [...]
```

Append a **redacted** entry (claim / verdict / gap only — never code or data) to the public
catch-history registry. `--open ID` publishes an engagement-opened entry at contract signing, so
a later missing outcome is visible (the clinical-trial property).

### `registry`

```
calma registry <proof|site|verify|verify-proof> ...
```

Audit the catch-history registry chain offline. `calma registry verify` re-walks the hash-chained
log; `calma registry proof` emits a self-contained `.proof` bundle (inclusion proof + signed
checkpoint + witness cosignatures) that re-verifies years later with no Calma server;
`calma registry verify-proof` checks such a bundle.

### `schema`

```
calma schema [--json]
```

Emit the machine-readable CLI spec — every command, flag, the three outcomes, and the exit codes
— so an agent never has to parse `--help`.

---

## The `calma.toml` schema

`calma.toml` is the committed config `calma up` / `calma init` write so the next run is a bare
`calma verify`. It is a single `[verify]` table:

```toml
[verify]
target = "."                 # folder containing the code and its outputs
metric = "accuracy"          # a recipe id (omit to auto-detect) — browse: calma recipes search <term>
claim  = "accuracy 0.80"     # the headline number to check
# tol  = 0.01                # optional: override the calibrated tolerance for this metric
```

Edit any field; delete the file to start over. `--claim` / `--metric` on the command line
override it.

For deeper control — the entrypoint, column bindings, conventions, and the validity blocks
(`split` / `trials` / `frictions` / `corpus` / `universe` / `embargo` / `simulation_assumptions`)
— Calma reads a `verify.yaml`. Don't hand-write it: `calma draft <repo>` or
`calma init <framework>` generates a runnable one. Most validity checks activate only when their
block is declared; the thin-input plausibility family is the exception (it flags from the series
alone, soft-only).

---

## The proof bundle

Every verdict writes a run directory (default `.calma/run`). Its key files:

| File | Contents |
|---|---|
| `ledger.json` | the verdict ledger — keys `schema`, `claims`, `findings`, `scope`, `repo_verdict`, `target`; every label re-derives byte-for-byte from its stored `verdict_inputs` |
| `recompute.json` | the recomputed value(s) and the per-metric terms |
| `diff.json` | claimed vs recomputed, the gap, and the calibrated budget |
| `verify.yaml` | the contract used for this run (how to run, what to bind) |
| `report.txt` | the full text verdict (always carries the complete "not verified" list) |
| `attestation.bundle.json` | the signed attestation — keys `schema`, `envelope` (DSSE), `ssh` (SSHSIG), `verification` |
| `attestation.payload.json` | the signed verdict bytes |
| `attestation.sig.sshsig` | the OpenSSH SSHSIG signature |
| `attestation.allowed_signers` | the signer's public key (ships with the bundle — proves integrity, not identity) |
| `VERIFY-THIS.txt` | the two offline-verification recipes (CLI and zero-install OpenSSH), with the exact keyid line |
| `replay/` | a self-contained, portable replay bundle — `sh replay/replay.sh` re-derives the verdict fully offline with no Calma server |
| `report.html` | written by `calma report` — a branded report that prints to PDF |

Re-verify any bundle **offline** with one command — `calma proof verify .calma/run` (or point it
at the bundle file or the project dir) — or `calma proof show .` to see it at a glance with a
shareable permalink and an embeddable badge. The lower-level `calma attest verify` and zero-install
OpenSSH paths are in [how-to.md → Verify a proof offline](how-to.md#verify-a-proof-offline).

---

## Recipes catalog

`calma recipes` → **628 metrics across 16 families**, each validated against byte-reproducible
reference vectors (597 of 628 are independently verified Tier-1):

| Family | Count | Family | Count |
|---|---|---|---|
| stats | 124 | quant | 91 |
| analytics | 88 | classification | 82 |
| finance | 47 | regression | 34 |
| forecasting | 30 | engineering | 29 |
| credit | 28 | derivatives | 16 |
| retrieval | 14 | llm-eval | 12 |
| liquidity | 10 | portfolio | 9 |
| execution | 7 | exposure | 7 |

Black-box over Python, R, Julia, C++, and Rust. Search by meaning with
`calma recipes search <term>`; force one with `--metric <id>`.
