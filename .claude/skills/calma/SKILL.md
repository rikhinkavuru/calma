---
name: calma
description: >-
  Independently verify a computational result by RE-EXECUTING it to ground truth and recomputing the
  headline number from raw outputs - then prove or break the claim. Use to check what an AI agent just
  produced (a metric, a backtest, a cleaned dataset, a "tests pass"), or as an inline guardrail an agent
  calls while it works. Recompute-and-diff against the claim + trivial-baseline edge, across domains and languages
  (quant Sharpe/return/drawdown; classification accuracy/AUC/F1/precision/recall; regression RMSE/MAE/R2;
  analytics row-count/column-sum/mean). Runs Python/R/Julia/C++/Rust as a black box. Deeper validity checks - leakage re-run, deflated-Sharpe/overfitting, realism deflators,
  contamination - are named roadmap (M3-M4), not yet delivered. Triggers: "verify", "is this result real", "did the number reproduce", "recompute this metric",
  "check this backtest/AUC/accuracy", "I processed N rows", "the total is", "before I report this".
---

# Calma - the trust layer for agentic work

Calma verifies AI-agent-produced results by **re-executing them to ground truth**. It does not read the
code and form an opinion (that is an eval tool); it **re-runs the work, recomputes the headline number
from the raw machine-readable outputs** (never the reported value), and diffs it against the claim under
a calibrated tolerance. The verdict is computed by **deterministic scripts, not the model** - so even the
agent that wrote the code cannot talk Calma out of a FAIL.

**Verdict enum (fixed vocabulary, agent-consumable):**
`CONFIRMED` / `CONFIRMED-WITH-CAVEATS` / `REFUTED` / `INCONCLUSIVE` (displayed as `CAN'T-CONFIRM`).
A multi-claim ledger where a non-headline claim breaks reports `MIXED`.

## When to invoke (agents: call this automatically)

After you produce ANY checkable result before reporting it as done - a metric (AUC/accuracy/RMSE/Sharpe),
a backtest return, a cleaned dataset ("processed 10k rows"), an aggregate ("total = $4.2M"), or a "tests
pass" claim - run Calma on it. A FAIL catches YOUR mistake before the human sees it; a CAN'T-CONFIRM tells
you the one thing to emit to make it verifiable (and prints it as a `fix:` line).

```
calma verify <target> "<claim>"     # e.g. calma verify . "accuracy 0.87"  /  "+14,698% backtest"
calma teardown <target> "<claim>"   # shareable "claimed X -> really Y" card on a break
calma replay <run_dir>              # re-run a saved verification; exit 0 iff the verdict reproduces
```

Claims are natural language: the number is parsed (signs, %, $, commas, k/M/B) and the metric is
inferred from the words ("accuracy", "AUC", "return", "rows", ...). Pass `--metric` to pin it. A bare
number with an ambiguous auto-picked metric can never produce a REFUTED - it degrades to CAN'T-CONFIRM
with the fix.

## Pipeline checklist (one script per step; the model READS outputs, never computes them)

0. **Discover + draft contract** - `scripts/draft_contract.py` -> a `verify.yaml`: entrypoint, typed+graded
   input binding, claim grounding. Drafting is read-only - nothing executes until step 2. Contracts are
   JSON or simple YAML; on a fresh project Calma re-drafts after the first run so outputs that only exist
   post-run still bind.
1. **Verified isolated run** - `scripts/run_hermetic.py` -> run + interpreter startup under ONE verified
   tier (macOS Seatbelt, proven by the `doctor` positive-control self-test). Hosts without a verified
   sandbox are stamped `host-not-isolated` and the network stamp says NOT blocked - never a silent
   verified-tier claim. A non-zero exit is a blocking finding: stale artifacts can never CONFIRM.
2. **Recompute + diff** - `scripts/recompute.py` (reference-deterministic, no transcendentals/numpy) then
   `scripts/compare.py` -> the calibrated tolerance diff; calls the shared `verdict()`.
3. **Family re-runs** - baseline edge ships now; leakage / overfitting (DSR/PBO) / realism / contamination
   are named roadmap (M3-M4), not yet delivered.
4. **Gate** - `scripts/ledger.py validate` -> the single CLEAN/NOT-CLEAN authority (strict lattice +
   findings-floor). Exit 0 clean, 1 not-clean, 2 invalid. CI: `--fail-on refuted` fails only on a break.
5. **Verdict + attestation** - `scripts/attest.py` -> a content-addressed manifest (in-toto/SLSA statement
   + CycloneDX ML-BOM; cryptographic signing is roadmap) + the strictly-progressive report (line 1 verdict
   + deterministic confidence, line 2 the one limiting thing, a `fix:` line on every CAN'T-CONFIRM).

## Machine-enforced invariants (never violate; encoded in the scripts, not prose)

1. **No statistic OR verdict label is computed by the model.** All arithmetic, the `verdict()` function,
   and the confidence score live in deterministic, unit-tested scripts. `ledger.py` re-derives every
   stored label from its `verdict_inputs` and rejects any that doesn't match byte-for-byte.
2. **Recompute ONLY from machine-readable raw outputs** (csv/parquet/json/npy/arrow) - never a notebook
   cell, rendered repr, or README number (those are claims-to-confirm).
3. **No REFUTED** under uncontrolled-and-insufficient-K determinism, a non-independently-bound input,
   resource-kill, a failed re-execution, or an unconfirmed claim target -> degrade to INCONCLUSIVE and say so.
4. **No auto-inferred trial-count N** into a printed statistic - declared/evidence-floored N only.
5. **Run + interpreter startup are untrusted-code execution behind the SAME verified tier**; untrusted
   third-party code with no container/VM tier -> refuse (static-only INCONCLUSIVE). The achieved isolation
   + determinism + network stamps are derived from the tier actually reached, never asserted.
6. **Every INCONCLUSIVE names a concrete, who-can-act unblock** (the `fix:` line); bias to CAVEAT over a
   false FAIL.
7. **Any "validity layer / five families / language-agnostic" claim carries the installed-milestone gate.**

Build status + what is real vs deferred: `BUILD-NOTES.md`. Script I/O contract:
`references/script-interfaces.md`. Full spec (repo checkout only, not shipped with the skill folder):
`docs/internal/calma-skill-blueprint.md`.
