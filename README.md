# Calma

**Verify a computational result by re-running it and recomputing the number from the raw outputs.**

Calma is an open-source [Claude Code](https://code.claude.com) skill (and a standalone Python toolkit). Point
it at a result — a metric, a backtest, a cleaned dataset, an aggregate — and it re-executes the code in an
isolated sandbox, recomputes the headline number from the machine-readable outputs (never the number that was
reported), and tells you whether the claim holds. The verdict is computed by deterministic scripts, not by a
model's opinion.

```
$ calma verify ./btc-backtest  "+14,698% backtest"

  BROKEN  (96/100)  -  the result does not hold
   claimed 146.98  ->  recomputed -0.32
   why: winner of 100 in-sample param combos; loses to buy-and-hold out-of-sample
   reproduce: calma replay ./.calma/run
   scope: re-ran the code · recomputed from the out-of-sample trade log · isolation: seatbelt-verified
```

If a result reproduces, you get `CONFIRMED`. If the recomputed number contradicts the claim, you get `REFUTED`
with a one-command reproduction. If it can't be fully verified (nondeterminism, a missing seed, no
machine-readable output), you get `CAN'T-CONFIRM` and the exact fix — never a false alarm.

## Install

Calma is a self-contained skill under `.claude/skills/calma/` with **no Python dependencies** (pure stdlib).

```bash
# into a Claude Code project:
git clone https://github.com/rikhinkavuru/calma
cp -r calma/.claude/skills/calma  your-project/.claude/skills/

# then in Claude Code it's discoverable as the `calma` skill, or run the CLI directly:
python3 your-project/.claude/skills/calma/scripts/calma.py verify <target> "<claim>"
```

## What it checks

- **Reproduces?** Re-run → same number, or it isn't a result.
- **Recomputes?** The headline metric, rebuilt from the raw outputs — never the reported value.
- **Beats the baseline?** A trivial baseline (buy-and-hold, majority-class) recomputed from the same data.
- **Holds under nondeterminism?** A calibrated tolerance band so GPU/threading noise never causes a false break.

Metric recipes ship for **quant** (Sharpe, total-return, max-drawdown), **classification** (accuracy, AUC,
F1, precision, recall, Brier), **regression** (RMSE, MAE, R²), and **analytics** (column sum/mean, row count).
No stated number? It still verifies reproducibility + invariants. Works on programs written in **Python, R,
Julia, C++, and Rust** — Calma runs them as a black box and recomputes in its own reference layer.

## How it works

`calma verify` runs a six-step pipeline, one script per step (the model reads outputs, never computes them):

1. **draft_contract** — auto-detects the entrypoint, output files, and a graded column binding (`verify.yaml`).
2. **run_hermetic** — runs install + entrypoint under a verified isolation tier (macOS Seatbelt; network off),
   re-emitting the raw artifacts. A `doctor` self-test proves the sandbox blocks secret reads and egress.
3. **recompute** — recomputes each metric from the raw outputs on a reference-deterministic path
   (correctly-rounded ops, no transcendentals, no numpy).
4. **compare** — diffs recomputed vs claimed under a calibrated tolerance + the claim's own sampling error.
5. **ledger / gate** — a strict pass/fail gate; every verdict label is re-derived byte-for-byte from its inputs.
6. **attest** — a content-addressed manifest plus in-toto/SLSA and CycloneDX ML-BOM attestations.

## Usage

```bash
calma verify <dir> "<claim>"     # verify a result; exit 0 clean / 1 not-clean / 2 invalid
calma teardown <dir> "<claim>"   # print a shareable "claimed X -> really Y + repro" card on a REFUTED
python3 .../run_hermetic.py doctor   # check the isolation tier on your host
```

A `verify.yaml` contract can be committed next to a result so re-runs and CI only re-check what changed.
Use it as a CI gate with the included GitHub Action (`.github/actions/calma`).

## Limitations

Calma proves a result is **real and reproduces** — not that it solved the *right* problem. When it can't
fully verify (nondeterminism without a seed, un-emitted outputs, code that needs live data), it returns
CAN'T-CONFIRM with the fix, and biases to a caveat over a false break. Untrusted third-party code requires a
container/VM tier; on a host with only the Seatbelt tier, such code is refused rather than run unsafely.

## Development

```bash
python3 .claude/skills/calma/scripts/tests/run_all.py     # full suite, pure stdlib, no deps
```

## Repository layout

```
.claude/skills/calma/   the skill — SKILL.md, scripts/, assets/, references/, calibration/
scripts/teardowns/      the worked BTC example fixture
app/ components/         a small Next.js project website (optional; not needed to use the skill)
docs/                    project planning + design specs (internal/)
```

## License

MIT.
