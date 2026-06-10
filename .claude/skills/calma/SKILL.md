---
name: calma
description: >-
  Independently verify a computational result by RE-EXECUTING it to ground truth and recomputing the
  headline number from raw outputs - then prove or break the claim. Use to check what an AI agent just
  produced (a metric, a backtest, a cleaned dataset, a "tests pass"), or as an inline guardrail an agent
  calls while it works. Recompute-and-diff against the claim + trivial-baseline edge, across domains and languages:
  120 SOTA-validated recipes - trading (Sharpe/return/drawdown), classification (accuracy/AUC/F1/macro-micro-F1/
  PR-AUC/log-loss/MCC/ECE/Brier), regression (RMSE/MAE/R2), analytics (sum/mean/median/percentile/groupby/
  distinct/nulls/duplicates/growth/share/join-loss), engineering ("2.3x faster"/latency p50-p99/throughput/
  peak-memory/coverage/error-rate), retrieval+LLM evals (recall@k/NDCG/MRR/top-k/exact-match/pass@k),
  statistics (p-value/CI/lift/chi-square/Mann-Whitney/ANOVA/Fisher-exact/correlation/effect-size), quant risk
  (Sortino/Calmar/VaR/CVaR/beta/alpha/IR), finance (CAGR/NPV/IRR/churn/margin/reconciliation), and forecasting
  (MAPE/sMAPE/WAPE/MASE/pinball). Runs Python/R/Julia/C++/Rust as a black box.
  Deeper validity checks - leakage re-run, deflated-Sharpe/overfitting, realism deflators,
  contamination - are named roadmap (M3-M4), not yet delivered. Triggers: "verify", "is this result real", "did the number reproduce", "recompute this metric",
  "check this backtest/AUC/accuracy/p95/speedup/pass@k", "I processed N rows", "the total is", "the experiment was significant", "before I report this".
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
you the one thing to emit to make it verifiable (and prints it as a `fix:` line). Inline use is cheap:
verification is cached by the content hash of code+data+contract+claim, so re-checking anything unchanged
returns the prior verdict in milliseconds (`--force` re-executes).

```
calma verify <target> "<claim>"     # e.g. calma verify . "accuracy 0.87"  /  "+14,698% backtest"
calma verify <target> "<claim>" --json                # machine-readable verdict (agents: use this)
calma verify <target> "<claim>" --check-determinism   # re-execute twice; FLAKY outputs -> INCONCLUSIVE
calma teardown <target> "<claim>" [--svg card.svg]    # shareable "claimed X -> really Y" card on a break
calma replay <run_dir>              # re-run a saved verification; exit 0 iff the verdict reproduces
calma stats <target>                # verification history: counts + recent catches
calma attest keygen [--import ~/.ssh/id_ed25519]   # one-time key; after this every verify auto-signs
calma attest verify <bundle> [--key pub] [--replay]   # counterparty: check a bundle offline
calma attest timestamp <bundle>     # RFC 3161 trusted timestamp (the one networked step; verifies offline)
calma attest sigstore <bundle>      # lab tier: keyless countersign into the public Rekor log
calma publish <run_dir> [--registry DIR] [--engagement ID]   # REDACTED entry -> the public catch history
calma publish --open <engagement-id>                         # log an engagement at contract signing
calma registry verify [dir]         # audit the registry chain offline (hashes + links + signatures)
```

Agents: prefer `--json` - it returns `{verdict, clean, confidence, claimed, recomputed, reason, fix,
cached, run_dir}` so you branch on the verdict without parsing prose.

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
   + CycloneDX ML-BOM) and, once `calma attest keygen` has run, a SIGNED DSSE bundle on every verify whose
   predicate is the VSA-style `calma.dev/verdict/v1` (verifier+version, contract+calibration hashes as
   policy, verdict, claims). The same Ed25519 key signs twice: raw DSSE (Sigstore-countersignable) and an
   OpenSSH SSHSIG (namespace `calma-attest@v1`) with sidecar files, so the counterparty can verify with
   stock `ssh-keygen -Y verify` and zero installs - or run `calma attest verify <bundle>` for the full
   offline check (both signatures + byte-for-byte verdict re-derivation; `--key` pins the signer,
   `--replay` re-executes). Layer 1: `calma attest timestamp` (RFC 3161, anti-backdating, offline-verifiable).
   Layer 2 (lab): `calma attest sigstore` -> public Rekor log entry. Then the strictly-progressive report
   (line 1 verdict + deterministic confidence, line 2 the one limiting thing, a `fix:` line on every
   CAN'T-CONFIRM).
6. **Publish (opt-in)** - `scripts/registry.py` -> `calma publish <run_dir>` appends a REDACTED entry
   (claim/metric/claimed-vs-recomputed/verdict/content-hashes; NEVER code or data - whitelist enforced at
   append AND audit) to the hash-chained, SSHSIG-signed public catch history. Publish requires a verified
   attestation bundle. `calma registry verify` audits the chain offline; a missing outcome for an opened
   engagement is structurally visible (clinical-trial property).
7. **Recipe compiler (new recipes only)** - the model DRAFTS offline under
   `references/recipe-draft.schema.json` (a DSL program over existing kernels + a named oracle +
   metamorphic relations + edge behaviour); `scripts/compiler.py admit` is the deterministic gate
   (differential vs the oracle in the reference venv, metamorphic suite, degeneracy, bit-stability;
   failures return counterexamples - CEGIS). Pass -> frozen under a content hash in
   `assets/compiled_recipes.json` with `set_maturity: compiled-validated`; the loader re-validates the
   hash so a tampered asset fails closed. Verify-time NEVER consults a model: compiled, validated,
   frozen - never improvised.

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
`references/script-interfaces.md`. The full 120-recipe catalog (binding tags, conventions, data
layouts, reference implementations each is validated against): `references/recipes.md`. Full spec
(repo checkout only, not shipped with the skill folder): `docs/internal/calma-skill-blueprint.md`.
