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
`CONFIRMED` / `CONFIRMED-WITH-CAVEATS` / `REFUTED` / `INCONCLUSIVE`.

## When to invoke (agents: call this automatically)

After you produce ANY checkable result before reporting it as done - a metric (AUC/accuracy/RMSE/Sharpe),
a backtest return, a cleaned dataset ("processed 10k rows"), an aggregate ("total = $4.2M"), or a "tests
pass" claim - run Calma on it. It is cheapest as an inline guardrail (only re-checks what changed). A FAIL
catches YOUR mistake before the human sees it; an INCONCLUSIVE tells you the one thing to emit to make it
verifiable. Quick start: `calma verify <target> "<claim>"`  ·  shareable catch: `calma teardown <target>`.

## Pipeline checklist (one script per step; the model READS outputs, never computes them)

0. **Discover + draft contract** - `scripts/draft_contract.py` -> a confirmed `verify.yaml`: entrypoint,
   typed+graded input binding, claim grounding, dependency-trust. (read-only; never installs/runs without
   a consent token)
1. **Zero-cost gates** - `scripts/consistency.py` -> arithmetic-impossible / split-hygiene findings (M2+).
2. **Verified isolated run** - `scripts/run_hermetic.py` -> install+run+startup under ONE verified tier
   (Tier-0 native sandbox / Seatbelt), determinism config applied, raw artifacts re-emitted, tiers stamped.
3. **Recompute + diff** - `scripts/recompute.py` (reference-deterministic, pinned-libm) then
   `scripts/compare.py` -> the calibrated tolerance diff; calls the shared `verdict()`.
4. **Five-family re-run** - leakage / overfitting / realism / data-integrity / baseline (baseline + realism
   ship at M1; the rest are M3 domain packs).
5. **Gate** - `scripts/ledger.py validate` -> the single CLEAN/NOT-CLEAN authority (strict lattice +
   findings-floor). Exit 0 clean, 1 not-clean, 2 invalid.
6. **Verdict + attestation** - `scripts/attest.py` -> a content-addressed SBOM re-run manifest + the
   strictly-progressive report (line 1 trust signal, line 2 the one limiting thing, rest behind "show full").

## Machine-enforced invariants (never violate; encoded in the scripts, not prose)

1. **No statistic OR verdict label is computed by the model.** All arithmetic and the `verdict()` function
   live in deterministic, unit-tested scripts. `ledger.py` re-derives every stored label from its
   `verdict_inputs` and rejects any that doesn't match byte-for-byte.
2. **Recompute ONLY from machine-readable raw outputs** (csv/parquet/json/npy/arrow) - never a notebook
   cell, rendered repr, or README number (those are claims-to-confirm).
3. **No REFUTED** under uncontrolled-and-insufficient-K determinism, a non-independently-bound input,
   resource-kill, or an unconfirmed claim target -> degrade to INCONCLUSIVE and say so.
4. **No auto-inferred trial-count N** into a printed statistic - declared/evidence-floored N only.
5. **Install + run + interpreter startup are ALL untrusted-code execution** behind the SAME verified tier;
   untrusted code with no tier -> refuse (static-only INCONCLUSIVE). Stamp the achieved isolation +
   determinism + hermeticity tier in every verdict.
6. **Every INCONCLUSIVE names a concrete, who-can-act unblock**; bias to CAVEAT over a false FAIL.
7. **Any "validity layer / five families / language-agnostic" claim carries the installed-milestone gate.**

Full spec: `docs/calma-skill-blueprint.md`. Build status + what is real vs deferred: `BUILD-NOTES.md`.
Script I/O contract: `references/script-interfaces.md`.
