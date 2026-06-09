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

This is real output — a backtest that claimed +14,698% on BTC, re-executed on the held-out data:

```
$ calma verify ./btc-backtest "+14,698% backtest"

REFUTED  (confidence 98/100)  -  the result does not hold
  - also: strategy underperforms the trivial baseline (edge -0.7422 <= 0)
  claimed +14,698%  ->  recomputed -32.4%
  reproduce: calma replay ./btc-backtest/.calma/run
```

You get one of four answers:

- **CONFIRMED** — it re-runs and the number checks out.
- **CONFIRMED-WITH-CAVEATS** — it holds, but narrower than claimed (and the caveat is named).
- **REFUTED** — the recomputed number contradicts the claim, with a reproduction you can run yourself.
- **CAN'T-CONFIRM** — it can't be fully checked yet, plus a `fix:` line with the exact change to make it
  checkable (e.g. "set a fixed seed", "write predictions to a CSV"). Calma never cries wolf.

## Install

The skill is one self-contained folder with **no dependencies** (pure Python standard library).

As a Claude Code plugin:

```
/plugin marketplace add rikhinkavuru/calma
/plugin install calma@calma
```

Or copy the folder into any project (works with every agent that reads SKILL.md — Claude Code, Codex,
Cursor, ...):

```bash
git clone https://github.com/rikhinkavuru/calma
cp -r calma/.claude/skills/calma  your-project/.claude/skills/
```

Or use it as a plain CLI:

```bash
ln -s "$(pwd)/calma/bin/calma" /usr/local/bin/calma
calma verify <folder> "<claim>"
```

## Commands

```bash
calma verify <folder> "<claim>"     # check a result   (exit 0 = clean, 1 = not clean, 2 = bad input)
calma teardown <folder> "<claim>"   # print a shareable "claimed X -> really Y" card when something breaks
calma replay <run_dir>              # re-run a saved verification; exit 0 iff the verdict reproduces
python3 .claude/skills/calma/scripts/run_hermetic.py doctor   # prove the sandbox works on your machine
```

Claims are natural language: `"accuracy 0.87"`, `"+14,698% backtest"`, `"$4.2M revenue"`,
`"processed 10,000 rows"` — the number and the metric are parsed from the words (`--metric` pins it
explicitly). With no claim at all, Calma still checks that the result reproduces.

Drop a `verify.yaml` next to a result (JSON or simple YAML) to pin the contract. In CI, use the GitHub
Action (`.github/actions/calma`) — `fail_on: refuted` fails the build only when a claim actually breaks.

## What it can check

- **Does it reproduce?** Re-run → same number, or it isn't a result. (A crashed re-run can never CONFIRM —
  stale output files don't count.)
- **Does the number recompute?** The headline metric, rebuilt from the raw outputs.
- **Does it beat a basic baseline?** (e.g. buy-and-hold, or majority-class.)
- **Is it stable?** A calibrated tolerance so normal hardware/threading noise never causes a false alarm.

Built-in metrics cover **trading** (Sharpe, return, drawdown), **machine learning** (accuracy, AUC, F1,
precision, recall, Brier), **regression** (RMSE, MAE, R²), and **data/analytics** (sums, means, row counts) —
15 recipes. It works on programs written in **Python, R, Julia, C++, or Rust** — Calma treats your program
as a black box and does the recompute itself.

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
6. **Attest** with a content-addressed manifest (in-toto/SLSA statement + CycloneDX ML-BOM) for audit
   trails; cryptographic signing is on the roadmap.

## Limitations

Calma proves a result is **real and reproduces** — not that it answered the *right* question. When it can't
fully verify something, it says so and tells you the fix, rather than guessing. The verified-isolation tier
ships on macOS today; on other platforms runs are honestly stamped as unisolated (a Linux tier is the top
roadmap item). Running untrusted third-party code safely needs a container/VM (planned); for now such code
is refused rather than run unsafely.

## FAQ

**How is this different from just asking my agent to double-check its own work?**
The agent that produced the result is the worst judge of it: it re-reads its own reasoning, tends to
rationalize, and never actually re-runs anything. "Looks right" is a second opinion, not verification.
Calma re-executes the code and recomputes the number from the raw outputs, and the verdict comes from
deterministic scripts, not a model. Even the agent that wrote the code can't talk Calma out of a FAIL.

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
No. It ships metrics for trading, ML (classification + regression), and analytics, and treats your program
as a black box, so it works across Python, R, Julia, C++, and Rust.

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
bin/calma                CLI launcher
scripts/teardowns/       the worked backtest example
app/  components/        a small project website (optional; not needed to use the skill)
docs/                    design specs and notes
```

## License

MIT
