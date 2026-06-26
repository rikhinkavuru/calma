# Tutorial — catch your first wrong number in 5 minutes

This is a single, linear walk-through. Copy each block in order. By the end you will have
watched Calma break a real inflated backtest, verified a number of your own, and re-derived
the proof offline — without leaving this page.

> **What Calma does:** it re-runs the code in a network-off sandbox, recomputes the headline
> number *from the raw output files* (never the number that was reported), and diffs it against
> your claim. The verdict comes from a deterministic function, not a language model.

---

## 0. Install (about 30 seconds)

The core is pure Python standard library — no virtualenv, no runtime dependencies. The
guaranteed path is a clone plus a symlink:

```bash
git clone https://github.com/rikhinkavuru/calma
cd calma
make install        # symlinks the `calma` command onto your PATH — no pip, no venv
```

Confirm it works:

```bash
calma doctor
```

```
calma doctor
  [✓] engine        calma 0.13.0
  [✓] runtime       Python 3.14.5
  [✓] stop-hook     wired (hooks.json -> hook_stop.py)
  [✓] guardrail     active
  [!] signing-key   no local signing key (proofs still emit; signing is optional defense-in-depth)
       ↳ calma attest keygen   # generate a local Ed25519 signing key

0 issue(s), 1 warning(s) - see the fix lines above.  (run `calma doctor --fix` to auto-fix what's safe)
```

One `[!]` warning about a signing key is expected and harmless — proofs still emit unsigned;
signing is optional defense-in-depth.

> **Other ways to get the command.** `pip install calma` (the library + CLI) once it is on
> PyPI, `uvx calma verify ...` for a zero-install run, or the Claude Code plugin (`/plugin
> marketplace add rikhinkavuru/calma`) for the zero-touch hook. If `calma` is not yet on your
> PATH, substitute `python3 .claude/skills/calma/scripts/calma.py` for `calma` everywhere
> below — the behavior is identical.

---

## 1. Watch a real catch (about 5 seconds)

Before verifying anything of your own, see Calma break a number. The `demo` command re-runs a
bundled, real overfit backtest that claimed a **+14,698%** return on BTC:

```bash
calma demo
```

```
re-verifying a real overfit backtest (it claimed +14,698% on BTC)...

✗ Caught  total_return 147.0x (+14,698%) claimed → recomputed -32.4%  (Δ -147.3x (-14,730%))  (confidence 98/100)
  the result does not hold
  - also: strategy underperforms the trivial baseline (edge -0.7422 <= 0)
  reproduce: calma replay <tmp>/btc-backtest/.calma/run
  scope: reproducibility, recomputation, baseline, plausibility | isolation: seatbelt-verified |
      determinism: controlled-to-bit (bit-exact)
  not verified: 12 deeper checks not run (data leakage, model-process leakage, covariate/target
      distribution shift, +9 more) - declare the relevant block, or re-run with --why / --json
  not attested: input-data authenticity (Calma recomputes the declared output, not whether the
      upstream input data is authentic / untampered)
```

Calma re-executed the backtest, recomputed the return from the raw equity curve, and found the
real number is **−32.4%**. The headline was off by 147×. It also notes the strategy doesn't beat
a trivial baseline. That is the whole product in one command: re-run the work, recompute the
number, break the wrong one.

---

## 2. Make a number of your own

Now verify something you control. Create a tiny project — a "model" that writes its raw
predictions to a CSV, plus an honest claim about its accuracy.

```bash
mkdir -p ~/calma-first && cd ~/calma-first
```

Create `model.py` (copy the whole block):

```bash
cat > model.py <<'PY'
# model.py — writes the raw predictions; Calma recomputes accuracy from this file,
# not from any number we print. 8 of 10 rows are correct → accuracy 0.80.
import csv

rows = [
    # y_true, y_pred
    (1, 1), (0, 0), (1, 1), (1, 0), (0, 0),
    (1, 1), (0, 1), (1, 1), (0, 0), (1, 1),
]
with open("predictions.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["y_true", "y_pred"])
    w.writerows(rows)
print("wrote predictions.csv (10 rows)")
PY
```

You don't need to run `model.py` yourself — Calma re-executes it inside the sandbox. The claim
you'll check is **`accuracy 0.80`**.

---

## 3. Verify it with one command

`calma up` is the one-command path: on the first run it auto-detects the result and the recipe,
re-executes the code, recomputes the number, diffs it against your claim, writes a committed
`calma.toml`, and emits a proof.

```bash
calma up --claim "accuracy 0.80"
```

```
✓ Confirmed  accuracy 0.8  (claimed 0.8 · recomputed 0.8 · Δ 0)  (confidence 95/100)
  reproduces and recomputes to the claim
  - recomputed value matches the claim within the calibrated budget
  verified by re-execution (isolation: seatbelt-verified, determinism: controlled-to-bit (bit-exact))
  not verified: 6 deeper checks not run (model-process leakage, covariate/target distribution
      shift, overfitting / deflated-Sharpe / PBO, +3 more) - declare the relevant block, or
      re-run with --why / --json for the full list
  not attested: input-data authenticity (Calma recomputes the declared output, not whether the
      upstream input data is authentic / untampered)

[exit 0 (CONFIRMED) · verified in 0.2s]
→ wrote calma.toml  (next time, just run `calma verify`)
```

**`✓ Confirmed`** is the headline. Calma re-ran `model.py` in a verified network-off sandbox,
recomputed accuracy from `predictions.csv` (it got `0.8`), and matched it to your claim within
the calibrated tolerance.

Read the honest fine print:

- **`not verified: 6 deeper checks not run`** — Calma confirmed the number *reproduces*, but it
  did not assess leakage, overfitting, or distribution shift, because you declared no scope for
  them. Reproducible is not the same as valid; Calma never pretends to check what you didn't
  give it.
- **`not attested: input-data authenticity`** — Calma proves the recompute, not that the
  upstream input data is authentic or that the result is semantically correct. This ceiling is
  printed on every verdict on purpose.

The `calma.toml` it wrote pins how to re-check this result, so the next run is bare `calma verify`:

```bash
cat calma.toml
```

```toml
# calma.toml - committed so `calma verify` (no args) re-checks this result.
# Calma re-executes the code in a network-off sandbox and recomputes the headline number from
# the raw output files (never the reported number), then proves or breaks the claim.
# Edit any field; delete the file to start over. Docs: https://trycalma.ai/docs
#
# detected: recipe 'accuracy' (auto-detected by `calma up`)

[verify]
target = "."
metric = "accuracy"  # recipe id - browse with `calma recipes search <term>`
claim  = "accuracy 0.80"  # the headline number to check
```

---

## 4. Read and share the proof

Every verdict leaves a run directory at `.calma/run` containing a signed, replayable proof. See
it at a glance — with a shareable permalink and an embeddable badge:

```bash
calma proof show .
```

```
calma proof  ·  ✓ Confirmed
  accuracy: claimed 0.8 · recomputed 0.8
  signed by:   ebf722e19cf7016d…b573bfb82f (offline-verifiable)
  ceiling:     proves the recompute, NOT input-data authenticity or semantic correctness
  re-verify offline:  calma proof verify .
  share:       https://trycalma.ai/proof?outcome=Confirmed&metric=accuracy&claimed=0.8&recomputed=0.8&keyid=ebf722e19cf7016d…
  badge:       ![verified by calma](https://trycalma.ai/badge?outcome=Confirmed&label=accuracy+0.8)
```

(Your keyid will differ.) Paste the `badge:` markdown into a README for a live "verified by
calma" badge; the `share:` link opens the proof on the
[trycalma.ai/proof](https://trycalma.ai/proof) permalink page — both render from the verdict
metadata in the URL, so no raw data leaves.

Anyone can re-derive the verdict **offline** — no Calma server, no network — from the project dir,
the run dir, or the bundle file:

```bash
calma proof verify .
```

```
ATTESTATION VERIFIED  -  calma-first
  signature        OK  (ed25519, keyid ebf722e19cf7016d)
  ssh-signature    OK  (verifiable with ssh-keygen -Y verify (namespace calma-attest@v1))
  ledger-rederive  OK  (all verdict labels re-derive; gate clean)
  verdict          CONFIRMED
  the bundle is authentically signed and every verdict label re-derives from its stored inputs
```

It checks both signatures and re-derives every verdict label byte-for-byte from its stored
inputs. For a branded HTML report plus a portable, fully-offline replay bundle you can hand to
anyone, run `calma report .calma/run` (then `sh .calma/run/replay/replay.sh` re-derives the
verdict with zero dependencies). The zero-install OpenSSH signature check is in
[how-to.md → Verify a proof offline](how-to.md#verify-a-proof-offline).

---

## 5. Now break it (10 seconds)

Confirm the gate actually bites. Re-run with an inflated claim:

```bash
calma verify . "accuracy 0.95"
```

```
✗ Caught  accuracy 0.95 claimed → recomputed 0.8  (Δ -0.15)  (confidence 98/100)
  the result does not hold
  reproduce: calma replay .calma/run
  scope: reproducibility, recomputation, leakage | isolation: seatbelt-verified | determinism:
      controlled-to-bit (bit-exact)
  not verified: 6 deeper checks not run (model-process leakage, covariate/target distribution
      shift, overfitting / deflated-Sharpe / PBO, +3 more) - declare the relevant block, or
      re-run with --why / --json for the full list
  not attested: input-data authenticity (Calma recomputes the declared output, not whether the
      upstream input data is authentic / untampered)

[exit 1 (REFUTED) - claim refuted (the catch; --fail-on sets exit behavior)]
  → calma teardown .   a shareable card of this catch
```

The headline flips to **`✗ Caught`** and the process exits **1** — the same non-zero code that
fails a CI job or blocks a Stop hook. The number Calma recomputed (`0.8`) never moved; only the
claim was wrong, and Calma caught it from the raw outputs.

---

## What you just learned

| Step | Command | Outcome |
|---|---|---|
| See a real catch | `calma demo` | `✗ Caught` — a +14,698% backtest recomputed to −32% |
| Verify your own number | `calma up --claim "accuracy 0.80"` | `✓ Confirmed`, wrote `calma.toml` |
| Re-derive offline | `calma proof verify .` | `ATTESTATION VERIFIED` |
| Prove the gate bites | `calma verify . "accuracy 0.95"` | `✗ Caught`, exit 1 |

Three outcomes roll up every verdict: **`✓ Confirmed`**, **`✗ Caught`**, **`? Can't tell`**.
The exit code follows: `0` clean, `1` a catch (or findings), `2`/`3`/`4` for an invalid ledger,
a refused run, or a killed run.

## Where to go next

- **[How-to guides](how-to.md)** — install the zero-touch Claude Code hook, wire the CI / PR
  gate, add a custom recipe, run non-interactively in CI.
- **[Reference](reference.md)** — every command and flag, the verdict semantics, exit codes, the
  `calma.toml` schema, the proof-bundle fields.
- **[Explanation](explanation.md)** — why recompute beats re-reading the number, the validity
  families, the data-authenticity ceiling, and the threat model.
