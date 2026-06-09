# Calma

**Calma checks whether a result is actually true — by re-running the code and recomputing the number itself, instead of trusting what was reported.**

Software (and AI agents) produce numbers all day: a model's accuracy, a trading backtest's return, "I cleaned
10,000 rows," "the total is $4.2M." Most of the time it's fine. When it isn't, the failure is silent — a
number that doesn't reproduce, a leak in the data, an overfit that only shows up later. Calma re-executes the
work in a sandbox, **recomputes the headline number from the raw output files** (never the number that was
reported), and tells you whether the claim holds — with a one-command way to reproduce it.

It's an open-source [Claude Code](https://code.claude.com) skill, and also runs as a plain Python CLI. Every
number and the final verdict come from deterministic scripts, **not** from a model's opinion.

## Demo

<!-- DEMO: replace this with the recorded GIF/video, e.g. ![Calma demo](docs/demo.gif) -->
*(Demo recording coming soon.)*

Here's the kind of result it produces — a real backtest claiming +14,698% that falls apart out-of-sample:

```
$ calma verify ./btc-backtest  "+14,698% backtest"

  BROKEN  (96/100)  -  the result does not hold
   claimed +14,698%   ->   recomputed -32%  (re-ran the code on the held-out data)
   why:  best of 100 in-sample tries; loses to simply buying and holding
   reproduce:  calma replay ./.calma/run
```

You get one of three answers:

- **CONFIRMED** — it re-runs and the number checks out.
- **REFUTED** — the recomputed number contradicts the claim (with a reproduction you can run yourself).
- **CAN'T-CONFIRM** — it can't be fully checked yet (e.g. no fixed seed, or no output file), plus the exact
  fix to make it checkable. Calma never cries wolf.

## Install

The skill is one self-contained folder with **no dependencies** (pure Python standard library).

```bash
git clone https://github.com/rikhinkavuru/calma
cp -r calma/.claude/skills/calma  your-project/.claude/skills/
```

In Claude Code it's then available as the `calma` skill. Or run it directly:

```bash
python3 your-project/.claude/skills/calma/scripts/calma.py verify <folder> "<claim>"
```

## What it can check

- **Does it reproduce?** Re-run → same number, or it isn't a result.
- **Does the number recompute?** The headline metric, rebuilt from the raw outputs.
- **Does it beat a basic baseline?** (e.g. buy-and-hold, or majority-class.)
- **Is it stable?** A calibrated tolerance so normal hardware/threading noise never causes a false alarm.

Built-in metrics cover **trading** (Sharpe, return, drawdown), **machine learning** (accuracy, AUC, F1,
precision, recall, Brier), **regression** (RMSE, MAE, R²), and **data/analytics** (sums, means, row counts).
No specific number to check? It still verifies that the result reproduces. It works on programs written in
**Python, R, Julia, C++, or Rust** — Calma treats your program as a black box and does the recompute itself.

## Commands

```bash
calma verify <folder> "<claim>"     # check a result        (exit 0 = clean, 1 = not clean, 2 = invalid)
calma teardown <folder> "<claim>"   # print a shareable "claimed X, really Y" card when something breaks
python3 .../scripts/run_hermetic.py doctor   # check the sandbox is working on your machine
```

Drop a `verify.yaml` next to a result and re-runs only re-check what changed. There's a GitHub Action
(`.github/actions/calma`) to use it as a CI check.

## Under the hood

`calma verify` runs a small pipeline, one script per step, so the result is auditable:

1. **Detect** the entrypoint, output files, and which column is the metric (`verify.yaml`).
2. **Run** the code in a verified sandbox (macOS Seatbelt; network off), re-emitting the raw outputs. A
   built-in `doctor` self-test proves the sandbox actually blocks secret-reads and network access.
3. **Recompute** each metric from the raw outputs, the same way every time (no floating-point surprises).
4. **Compare** recomputed vs claimed, allowing for the claim's own measurement noise.
5. **Verdict** from a single deterministic function — re-checked byte-for-byte so it can't be fudged.
6. **Attest** with a signed manifest (in-toto/SLSA + CycloneDX ML-BOM) for audit trails.

## Limitations

Calma proves a result is **real and reproduces** — not that it answered the *right* question. When it can't
fully verify something, it says so and tells you the fix, rather than guessing. Running untrusted third-party
code safely needs a container/VM (planned); for now such code is refused rather than run unsafely.

## Development

```bash
python3 .claude/skills/calma/scripts/tests/run_all.py     # full test suite (pure stdlib, no deps)
```

## Repository layout

```
.claude/skills/calma/   the skill — SKILL.md, scripts/, assets/, calibration/
scripts/teardowns/      the worked backtest example
app/  components/        a small project website (optional; not needed to use the skill)
docs/                    design specs and notes
```

## License

MIT
