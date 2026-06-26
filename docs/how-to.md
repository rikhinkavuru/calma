# How-to guides

Task-focused recipes for people who already know what Calma is. Each section is independent —
jump to the one you need. New to Calma? Start with the
[tutorial](tutorial-catch-your-first-wrong-number.md).

> Throughout, `calma` is the installed command (`make install`, `pip install calma`, or
> `uvx calma`). If it isn't on your PATH, substitute `python3 .claude/skills/calma/scripts/calma.py`.

- [Install Calma as a Claude Code Stop-hook](#install-as-a-stop-hook)
- [Silence or turn off the hook](#silence-or-turn-off-the-hook)
- [Wire a CI / PR merge gate](#wire-a-ci--pr-merge-gate)
- [Verify a proof offline](#verify-a-proof-offline)
- [Commit a `calma.toml` so the next run is bare `calma verify`](#commit-a-calmatoml)
- [Run non-interactively in CI or from an agent](#run-non-interactively)
- [Find the right recipe](#find-the-right-recipe)
- [Check that the guardrail is on — `status` and `doctor`](#check-the-guardrail)
- [Verify many results at once](#verify-many-results-at-once)
- [Add a custom recipe or validity family](#add-a-custom-recipe)

---

## Install as a Stop-hook

Calma's zero-touch mode runs as a Claude Code **Stop hook**: when an agent's final message
contains a checkable numeric claim, Calma re-executes the work, recomputes the number, and
blocks the stop only on a definitive catch (`REFUTED` / `INVALIDATED` / `MIXED`) — so a wrong
number is never reported as fact. It is silent and fail-open otherwise.

Install it as a Claude Code plugin (this wires the hook and the MCP tool):

```bash
# in Claude Code:
/plugin marketplace add rikhinkavuru/calma
```

Confirm it's live:

```bash
calma status
```

```
calma status
  guardrail   [✓] stop-hook active
  ...
```

The hook is defined in `hooks/hooks.json` and runs `hook_stop.py` with a 90-second timeout. To
control how aggressively it auto-verifies, set the **verify scope**:

```bash
calma modes --verify headline   # default: just the headline number this turn
calma modes --verify all        # every checkable claim in the turn
calma modes --verify off        # disable auto-verification
calma modes --global --verify all   # write the choice to ~/.calma/config.json (everywhere)
```

---

## Silence or turn off the hook

The hook prints one status line per run. Silence just that line, or disable the hook entirely:

```bash
export CALMA_QUIET=1     # keep the guardrail, drop the per-run line
export CALMA_VERIFY=off  # don't auto-verify (scope off)
export CALMA_HOOK=0      # disable the Stop hook completely
touch .calma/hook-off    # per-project opt-out (no env var needed)
```

A break still blocks at any scope above `off`; outward actions (publish/send) always need a
standing opt-in. `calma status` shows `per-run line quiet (CALMA_QUIET=1)` when silenced.

---

## Wire a CI / PR merge gate

Calma's exit code is the gate. Run `calma verify` in CI; a catch exits non-zero and fails the
job. Commit a [`calma.toml`](#commit-a-calmatoml) so the command needs no arguments:

```yaml
# .github/workflows/verify.yml
name: verify numbers
on: [pull_request]
jobs:
  calma:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install calma
      - run: calma verify --fail-on not-clean   # exit 1 on a catch or an INCONCLUSIVE
```

Tune the exit policy with `--fail-on`:

| `--fail-on` | Fails (exit 1) on |
|---|---|
| `not-clean` *(default)* | any catch **and** `INCONCLUSIVE` |
| `refuted` | only a definitive catch (`REFUTED` / `INVALIDATED` / `MIXED`) |
| `caveats` | stricter — even a clean `CONFIRMED-WITH-CAVEATS` fails |

For a richer PR experience — inline verdict comments plus a **required, blocking check-run** you
mark required in branch protection — use the PR bot and the hosted GitHub App. See
[`pr-bot.md`](pr-bot.md) and [`github_app/README.md`](../github_app/README.md). The check-run is
a pure function of the engine's verdicts: `failure` on any `REFUTED` / `INVALIDATED` / `MIXED`,
`neutral` on `CAN'T-CONFIRM`, `success` otherwise.

---

## Verify a proof offline

The proof is the product. Every run leaves a signed bundle that re-verifies with **no Calma
server and no network**. One command re-derives the verdict — point it at a project dir, a run
dir, or a bundle file:

```bash
calma proof verify .
```

```
ATTESTATION VERIFIED  -  my-project
  schema           OK
  signature        OK  (ed25519, keyid ebf722e19cf7016d)
  ssh-signature    OK  (verifiable with ssh-keygen -Y verify (namespace calma-attest@v1))
  ledger-rederive  OK  (all verdict labels re-derive; gate clean)
  verdict          CONFIRMED
  the bundle is authentically signed and every verdict label re-derives from its stored inputs
```

It checks both signatures (DSSE + SSHSIG), every content hash, and re-derives every verdict label
byte-for-byte from its stored inputs, exiting 0 when the bundle is authentic and clean. Pin the
expected signer with `--key <file|hex>`; add `--replay` to also re-execute the run.

Show the proof at a glance — the verdict, claimed vs recomputed, the signing key, the
data-authenticity ceiling, a re-verify command, plus a shareable permalink and an embeddable badge:

```bash
calma proof show .
```

```
calma proof  ·  ✓ Confirmed
  accuracy: claimed 0.8 · recomputed 0.8
  signed by:   ebf722e19cf7016d…b573bfb82f (offline-verifiable)
  ceiling:     proves the recompute, NOT input-data authenticity or semantic correctness
  re-verify offline:  calma proof verify .
  share:       https://trycalma.ai/proof?outcome=Confirmed&metric=accuracy&claimed=0.8&recomputed=0.8&keyid=…
  badge:       ![verified by calma](https://trycalma.ai/badge?outcome=Confirmed&label=accuracy+0.8)
```

Paste the `badge:` markdown into a README for a live "verified by calma" badge; the `share:` link
opens the proof on the [trycalma.ai/proof](https://trycalma.ai/proof) permalink page. Both render
from the verdict metadata in the URL — no raw data leaves.

### Lower-level paths

`calma proof verify` wraps these — reach for one when you need the underlying primitive:

- **Zero-install signature check** (stock OpenSSH ≥ 8.0, already on every Mac/Linux box; no Calma
  at all). From inside the run directory:

  ```bash
  ssh-keygen -Y verify -f attestation.allowed_signers \
    -I calma-<keyid> -n calma-attest@v1 \
    -s attestation.sig.sshsig < attestation.payload.json
  ```

  Prints `Good "calma-attest@v1" signature ...` if the verdict bytes are authentic. The exact
  `-I calma-<keyid>` line is printed in the bundle's `VERIFY-THIS.txt`.
- **`calma attest verify <bundle> [--replay]`** — the bundle-file primitive `proof verify` calls.
- **`calma registry verify-proof <proof>`** — verify a published `.proof` transparency bundle
  (inclusion proof + signed checkpoint); `calma registry verify` re-walks the redacted public log.

> The signing key ships *inside* the bundle, so a bare signature check proves **integrity, not
> identity**. To prove identity, obtain the signer's public key from a channel you trust and pin
> it with `calma proof verify --key`, or compare the keyid.

---

## Commit a `calma.toml`

`calma.toml` is the committed config that pins *how* to re-check a result. Write it by
auto-detection, then commit it — every later run is a bare `calma verify`:

```bash
calma init --yes        # auto-detect the result + recipe, write calma.toml (no prompt)
```

```
Detected: recipe 'accuracy' (classification) on predictions.csv  [label=y_true, prediction=y_pred]
→ wrote calma.toml
  verify it now:          calma up
  add a number to check:  set  claim = "accuracy=<value>"  in calma.toml
```

Edit the `[verify]` table to set the claim and any forced recipe:

```toml
[verify]
target = "."
metric = "accuracy"          # a recipe id — browse with `calma recipes search <term>`
claim  = "accuracy 0.80"     # the headline number to check
# tol  = 0.01                # optional: override the calibrated tolerance
```

Then:

```bash
calma verify     # reads calma.toml; no arguments needed
```

For *how to run and what to bind* beyond the headline — entrypoint, column bindings,
conventions, and validity blocks (`split` / `trials` / `frictions` / `corpus` / `universe` /
`embargo` / `simulation_assumptions`) — Calma uses a `verify.yaml`. Generate one for a messy
repo with `calma draft <repo>` (heuristic) or `calma init <framework>` (a starter skeleton).

---

## Run non-interactively

Agents and CI must never block on a prompt. Pass `--yes` so the auto-detected recipe is accepted
silently:

```bash
calma init --yes                       # write calma.toml, no prompt
calma up --yes --claim "accuracy 0.80" # first-run auto-detect + verify + proof, no prompt
calma verify --json                    # machine-readable verdict object on stdout
```

`--json` is available on `verify`, `batch`, `status`, `doctor`, `recipes`, `suggest`, `stats`,
and more. For the full agent-facing spec without parsing `--help`, emit the machine-readable
schema:

```bash
calma schema      # the JSON spec of every command, flag, the 3 outcomes, and exit codes
```

---

## Find the right recipe

Calma ships **628 recipes across 16 families**. Search by meaning:

```bash
calma recipes search "sharpe ratio"
```

```
recipes matching 'sharpe ratio':
  sharpe                     quant        Excess return per unit of total volatility.
  adjusted_sharpe_ratio      quant        Sharpe ratio penalized for negative skew and excess kurtosis
  modified_sharpe_ratio      quant        Sharpe-style ratio using modified (Cornish-Fisher) VaR ...
  probabilistic_sharpe_ratio quant        Probability that the true Sharpe ratio exceeds a benchmark
  deflated_sharpe            quant        Probability the strategy's true Sharpe beats the multiple-...
  ...
  use one:  calma verify <folder> "<claim>" --metric <id>
```

List every recipe grouped by family with bare `calma recipes`. Not sure what your number is
called? `calma suggest "my risk-adjusted return looked strong"` ranks the likely recipes
(suggestion only — it never verifies). Force one with `--metric <id>`.

---

## Check the guardrail

`calma status` answers "is the guardrail on?" at a glance — the hook, the signing key, a 7-day
tally, and the last run:

```bash
calma status
```

```
calma status
  guardrail   [✓] stop-hook active
  signing     no local signing key (proofs still emit; signing is optional defense-in-depth)
  engine      calma 0.13.0 · Python 3.14
  project     .  (calma.toml: accuracy)
  last 7 days 3 checks  ·  3 Confirmed
  shipped     0 numbers caught before shipping  ·  0 shipped unverified
  last run    Confirmed accuracy 0.8  ·  10s ago
  → calma doctor   full health check (+ --fix)
```

`calma doctor` runs deeper health checks and prints a fix line for each issue. Apply the safe
auto-fixes (e.g. generate a signing key) with `--fix`:

```bash
calma doctor --fix
```

---

## Verify many results at once

For a whole sprint or a batch of runs, `calma batch` verifies many targets and prints one
summary table. Either point it at directories that each carry a committed `verify.yaml`/
`calma.toml`, or pass a TSV manifest of `path<TAB>claim<TAB>[metric]` rows:

```bash
calma batch 'runs/*'                       # every dir under runs/ with a committed contract
calma batch --manifest claims.tsv          # path  TAB  claim  TAB  [metric] per row
calma batch --manifest claims.tsv --fail-on not-clean --json
```

The exit policy applies across all targets (exit 1 if any fails).

---

## Add a custom recipe

A new metric or a firm-specific validity check is a small, eval-gated contribution to the
pure-stdlib engine — never a fork. The full contract (golden vector + a test + `make eval` stays
green), the recipe decorator, the bespoke-metric CEGIS onboarding path (`calma onboard`), and
the 3-function validity-family protocol are documented in **[`extending.md`](extending.md)**.
