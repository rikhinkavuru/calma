---
name: calma
description: >-
  Independently verify a computational result by RE-EXECUTING it to ground truth and recomputing the
  headline number from raw outputs - then prove or break the claim. Use to check what an AI agent just
  produced (a metric, a backtest, a cleaned dataset, a "tests pass"), or as an inline guardrail an agent
  calls while it works. Recompute-and-diff against the claim + trivial-baseline edge, across domains and languages:
  623 SOTA-validated recipes - trading (Sharpe/return/drawdown), classification (accuracy/AUC/F1/macro-micro-F1/
  PR-AUC/log-loss/MCC/ECE/Brier), regression (RMSE/MAE/R2), analytics (sum/mean/median/percentile/groupby/
  distinct/nulls/duplicates/growth/share/join-loss), engineering ("2.3x faster"/latency p50-p99/throughput/
  peak-memory/coverage/error-rate), retrieval+LLM evals (recall@k/NDCG/MRR/top-k/exact-match/pass@k),
  statistics (p-value/CI/lift/chi-square/Mann-Whitney/ANOVA/Fisher-exact/correlation/effect-size), quant risk
  (Sortino/Calmar/VaR/CVaR/beta/alpha/IR + ES backtests/Acerbi-Szekely/Hill tail index), derivatives
  (Black-Scholes price + Greeks/implied vol), credit (expected loss/Altman-Z/Merton/Basel-ASRF), rates
  (duration/convexity/DV01/Z-spread), fund & LP (TVPI/DPI/RVPI/KS-PME), attribution (Brinson/active share),
  liquidity & execution (Amihud/Roll/Kyle/implementation-shortfall), finance
  (CAGR/NPV/IRR/churn/margin/reconciliation), and forecasting (MAPE/sMAPE/WAPE/MASE/pinball/Nash-Sutcliffe).
  Runs Python/R/Julia/C++/Rust as a black box.
  Validity checks - data leakage (train/test row/id/temporal overlap + target leakage, with a
  leakage-corrected re-run), overfitting (Deflated Sharpe + PBO/CSCV), execution-realism deflators
  (transaction cost / slippage / borrow / square-root market impact, with a friction-deflated re-run)
  and eval/benchmark contamination (corpus hash overlap + near-duplicate minhash) - are DELIVERED,
  producing the INVALIDATED verdict ("the number reproduces, but the result is invalid"). Triggers:
  "verify", "is this result real", "did the number reproduce", "recompute this metric",
  "check this backtest/AUC/accuracy/p95/speedup/pass@k", "I processed N rows", "the total is", "the experiment was significant", "before I report this".
---

# Calma - the trust layer for agentic work

Calma verifies AI-agent-produced results by **re-executing them to ground truth**. It does not read the
code and form an opinion (that is an eval tool); it **re-runs the work, recomputes the headline number
from the raw machine-readable outputs** (never the reported value), and diffs it against the claim under
a calibrated tolerance. The verdict is computed by **deterministic scripts, not the model** - so even the
agent that wrote the code cannot talk Calma out of a FAIL.

**Verdict enum (fixed vocabulary, agent-consumable):**
`CONFIRMED` / `CONFIRMED-WITH-CAVEATS` / `REFUTED` / `INVALIDATED` / `INCONCLUSIVE` (displayed as `CAN'T-CONFIRM`).
A multi-claim ledger where a non-headline claim breaks reports `MIXED`.

## When to invoke (agents: call this automatically)

After you produce ANY checkable result before reporting it as done - a metric (AUC/accuracy/RMSE/Sharpe),
a backtest return, a cleaned dataset ("processed 10k rows"), an aggregate ("total = $4.2M"), or a "tests
pass" claim - run Calma on it. A FAIL catches YOUR mistake before the human sees it; a CAN'T-CONFIRM tells
you the one thing to emit to make it verifiable (and prints it as a `fix:` line). Inline use is cheap:
verification is cached by the content hash of code+data+contract+claim, so re-checking anything unchanged
returns the prior verdict in milliseconds (`--force` re-executes).

```
calma demo                          # zero-setup demo: catches a bundled real inflated backtest (offline)
calma verify <target> "<claim>"     # e.g. calma verify . "accuracy 0.87"  /  "+14,698% backtest"
calma verify <target>               # no claim: checks the result reproduces (CONFIRMED scope=reproduction)
calma verify <target> "<claim>" --json                # machine-readable verdict (agents: use this)
calma verify <target> "<claim>" --check-determinism   # re-execute twice; FLAKY outputs -> INCONCLUSIVE
calma verify <target> "<claim>" --mode auto           # autonomy: ask (default) | suggest | auto. mode
                                                      # governs follow-on ACTIONS only (seal/timestamp on a
                                                      # catch; retry a missing dep with --restore) - NEVER the
                                                      # verdict, which is always deterministic. Outward actions
                                                      # (publish) need an explicit opt-in even in auto. Also
                                                      # CALMA_MODE / .calma/config.json {"mode"}; logged to auto_history.jsonl
calma verify <target> "<claim>" --timeout 300         # raise the re-execution budget (default 120s)
calma verify <target> "<claim>" --trust third-party   # counterparty code: auto-escalates to the
                                                      # container tier (refuses exit 3 if none is live)
calma verify <target> "<claim>" --isolation docker    # run in a network-denied Linux container
                                                      # (auto|seatbelt|bwrap|docker|firecracker; fails loud if unavailable)
calma verify <target> "<claim>" --isolation bwrap     # native Linux own-code tier (bubblewrap, no
                                                      # daemon); auto picks it on Linux, Seatbelt on macOS
calma verify <target> "<claim>" --restore             # restore + PIN the repo's declared deps into
                                                      # .calma_venv before the run (network used in this phase only)
calma batch <dir>... | --manifest m.tsv   # verify MANY results in one run -> one summary table + roll-up exit
calma recipes                       # all 623 metric ids, grouped by family (for --metric)
calma suggest "<free-text ask>"     # unclear what to verify? rank the likely recipes (suggestion only)
calma teardown <target> "<claim>" [--svg card.svg]    # shareable "claimed X -> really Y" card on a break
calma replay <run_dir>              # re-run a saved verification; exit 0 iff the verdict reproduces
calma report <run_dir> [--out f.html] [--no-pdf]   # branded HTML report (prints to PDF) + an offline replay bundle
calma stats <target>                # verification history: counts + recent catches
calma seal <run_dir> [--publish REGISTRY_DIR --note "..."]   # ONE command: sign + RFC 3161 timestamp
                                    # + VERIFY-THIS.txt counterparty instructions (+ optional publish)
calma attest keygen [--import ~/.ssh/id_ed25519]   # one-time key; after this every verify auto-signs
calma attest verify <bundle> [--key pub] [--replay]   # counterparty: check a bundle offline
calma attest timestamp <bundle>     # RFC 3161 trusted timestamp (the one networked step; verifies offline)
calma attest sigstore <bundle>      # lab tier: keyless countersign into the public Rekor log
calma publish <run_dir> [--registry DIR] [--engagement ID]   # REDACTED entry -> the public catch history
calma publish --open <engagement-id>                         # log an engagement at contract signing
calma registry verify [dir]         # audit the registry chain offline (hashes + links + signatures)
```

## How to report a verdict (agents: follow this format)

After running `calma verify`, report in THIS order - the user should never need another command:

1. **The verdict line**: verdict + claimed vs recomputed (from the `--json` output).
2. **On REFUTED: diagnose the cause.** Read the producing code and name the exact line/choice
   that made the claimed number wrong (e.g. "line 71 prints the in-sample grid-search winner,
   not the held-out result"). Calma proves the gap; you explain it.
3. **The honest number**, stated plainly ("the real held-out return is +168%").
4. **The proof object**: run `calma seal <run_dir>` (signs + timestamps + writes
   VERIFY-THIS.txt). Tell the user: "the signed, timestamped verdict is in <run_dir> -
   VERIFY-THIS.txt inside has the exact commands a counterparty runs, including a
   zero-install OpenSSH check." NEVER make the user type signature commands by hand.
5. If the user wants it on the public record: `calma seal <run_dir> --publish <registry_dir>`,
   then a signed git commit + push makes the site's /registry page update itself.
6. **On CAN'T-CONFIRM because it's UNCLEAR what to verify** (an `f-no-metric` finding, or a
   bad `--metric`): the verdict carries a `suggestions` list / a "Did you mean..." line.
   Surface those candidates and ASK THE USER to pick one (re-run with `--metric <id>`) or to
   say which number they computed. Do this automatically - never guess a metric to force a
   verdict, and never make the user invoke `calma suggest` themselves. (In a batch, only the
   genuinely-ambiguous targets reach this branch; clearly-bound ones verify silently as usual.)
   YOU are the best ranker here: `calma suggest` is a deterministic lexical fallback for headless
   use, but in this conversation use your OWN understanding of what the user described to map it
   to the right `metric_id`(s) - treat the `suggestions` list as a recall aid, not the answer, and
   it's fine to propose a recipe it missed (e.g. "your wealth-inequality number → `gini_coefficient`")
   as long as you confirm with the user before pinning it. Still never auto-verify against a guess.

Agents: prefer `--json` - it returns `{verdict, clean, gate_exit, confidence, claimed, recomputed,
reason, fix, cached, note, run_dir, metric, metrics[], isolation_tier, determinism_mode}` so you
branch on the verdict without parsing prose (`metrics[]` carries every claim in a multi-metric run).

## The zero-touch guardrail (installed automatically with the plugin)

The plugin registers a **Stop hook** (`scripts/hook_stop.py`): when an agent's final message
contains a checkable numeric claim (precision-tuned detector, `scripts/sniff_claims.py`) in a
verifiable project, the claim is auto-verified before the turn ends. On a definitive
REFUTED/MIXED the stop is **blocked** and the verdict is injected back; on everything else the
hook is completely silent. Fail-open by construction: any error, timeout, or ambiguity means
silence, never a broken session.

**Agents: if your stop is blocked with a calma verdict, that is the hook.** Do not argue with
it or restate the refuted number - follow the reporting contract above (diagnose the cause in
the producing code, state the honest recomputed number, offer the seal). The same break never
blocks twice while code+data are unchanged; fixing the code re-verifies fresh.

Controls: env `CALMA_HOOK=0` (kill switch) · `touch .calma/hook-off` (per-project or `~/.calma`)
· `.calma/config.json` `{"hook": {"enabled": false, "timeout_s": 30, "max_claims": 1}}`.
Every hook decision (fired, skipped, error) is breadcrumbed to `.calma/auto_history.jsonl`
and summarized by `calma stats` - the seed of a future claims-as-code manifest.

Claims are natural language: the number is parsed (signs, %, $, commas, k/M/B) and the metric is
inferred from the words ("accuracy", "AUC", "return", "rows", ...). Pass `--metric` to pin it. A bare
number with an ambiguous auto-picked metric can never produce a REFUTED - it degrades to CAN'T-CONFIRM
with the fix.

A committed `verify.yaml` pins **how** to verify (entrypoint, bindings, conventions) - never WHAT the
user claimed. If the claim states a different value for the pinned metric, the USER's value is verified
(announced as a `note:`); a claim about a metric the contract doesn't pin is CAN'T-CONFIRM with a fix
line, never a verdict about an unclaimed metric; claim text with no checkable number verifies the
committed claim and says so in the report and `--json` (`note`).

## Pipeline checklist (one script per step; the model READS outputs, never computes them)

0. **Discover + draft contract** - `scripts/draft_contract.py` -> a `verify.yaml`: entrypoint, typed+graded
   input binding, claim grounding. Drafting is read-only - nothing executes until step 2. Contracts are
   JSON or simple YAML; on a fresh project Calma re-drafts after the first run so outputs that only exist
   post-run still bind.
1. **Verified isolated run** - `scripts/run_hermetic.py` -> run + interpreter startup under ONE verified
   no-daemon own-code tier (macOS Seatbelt OR Linux bubblewrap, proven by the same `doctor` positive-
   control self-test). Hosts without a verified sandbox are stamped `host-not-isolated` and the network
   stamp says NOT blocked - never a silent verified-tier claim. A non-zero exit is a blocking finding:
   stale artifacts can never CONFIRM.
2. **Recompute + diff** - `scripts/recompute.py` (reference-deterministic, no transcendentals/numpy) then
   `scripts/compare.py` -> the calibrated tolerance diff; calls the shared `verdict()`.
3. **Family re-runs** - baseline edge, data-leakage (row/id/temporal/target, with a leakage-corrected
   re-run), overfitting (Deflated Sharpe + PBO/CSCV), execution-realism deflators (cost/slippage/borrow/
   square-root market impact, with a friction-deflated re-run) and eval/benchmark contamination (corpus
   hash overlap + near-duplicate minhash) all ship now -> the INVALIDATED verdict.
4. **Gate** - `scripts/ledger.py validate` -> the single CLEAN/NOT-CLEAN authority (strict lattice +
   findings-floor). Exit 0 clean, 1 not-clean, 2 invalid. CI: `--fail-on refuted` fails only on a break.
5. **Verdict + attestation** - `scripts/attest.py` -> a content-addressed manifest (in-toto/SLSA statement
   + CycloneDX ML-BOM) and, once `calma attest keygen` has run, a SIGNED DSSE bundle on every verify whose
   predicate is the VSA-style `github.com/rikhinkavuru/calma/verdict/v1` (verifier+version,
   contract+calibration hashes as
   policy, verdict, claims; legacy-URI bundles still verify - see script-interfaces.md). The same
   Ed25519 key signs twice: raw DSSE (Sigstore-countersignable) and an
   OpenSSH SSHSIG (namespace `calma-attest@v1`) with sidecar files, so the counterparty can verify with
   stock `ssh-keygen -Y verify` and zero installs - or run `calma attest verify <bundle>` for the full
   offline check (both signatures + byte-for-byte verdict re-derivation; `--key` pins the signer,
   `--replay` re-executes). Layer 1: `calma attest timestamp` (RFC 3161, offline-verifiable). Its
   anti-backdating guarantee holds ONLY once the TSA's CA chain verifies; a structural-only token (no CA
   embedded / openssl absent) is reported UNVERIFIED ("date self-asserted, not proven") and does not prove
   the date. Layer 2 (lab): `calma attest sigstore` -> public Rekor log entry. Then the strictly-progressive report
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
   **Adding recipes (this compiler path OR hand-registering a pack in `recipes.py`, how the 623
   shipped): follow the "Definition of done for a NEW recipe" checklist at the top of
   `references/recipes.md`** - it is not done at "computes the right number." Every recipe also
   needs a `assets/recipe_descriptions.json` entry (a description + >=2 aliases, INCLUDING plain
   conceptual paraphrases - that is what carries `calma suggest`'s paraphrase recall) and, when it
   has a common spoken name, a claim-routing hint. `tests/test_suggest.py` fails closed if a
   registered recipe has no enrichment, so a future pack can't silently ship un-suggestable.

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

Script I/O contract:
`references/script-interfaces.md`. The recipe-catalog reference (binding tags, conventions, data
layouts, reference implementations - representative families; `calma recipes` lists all 623 ids):
`references/recipes.md`.
