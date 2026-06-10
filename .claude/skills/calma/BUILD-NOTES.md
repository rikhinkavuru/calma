# Calma build notes

Living record of what shipped, what's in progress, decisions, and open questions. Per the runbook, the
repo stays green and runnable at every commit. Phase A (M0+M1) is buildable on this M4; M2+ needs the
repo corpus.

## Status

| Milestone | State | Notes |
|---|---|---|
| M0.0 verdict.py | **DONE, tested (27/0)** | Total pure `verdict()` over the full vector; conservative defaults; ordered false-REFUTED guards; M2-gate + controlled-to-bit carve-out. |
| M0.1 ledger + gate | **DONE, tested (12/0)** | schema + semantic `_validate()` (byte-re-derivation), strict-lattice gate, FP-aware repo verdict. BTC ledger fixture -> REFUTED / exit 1. |
| M0.2 SKILL.md + invariants | **DONE** | TOC body, version-gated description (M1 = recompute-and-diff + baseline; rest named as roadmap), 7 machine-enforced invariants. |
| M1.1 verify.yaml + draft_contract + recipes | **DONE, tested** | verify.schema.json; draft_contract.py (tag inference + graded binding); recipes: quant (Sharpe, total_return, max-drawdown) + general (accuracy, AUC-DeLong). |
| M1.2 run_hermetic | **DONE, tested** | verified Seatbelt tier with `calma doctor` positive-control (secret-read + egress BOTH blocked); process-group kill on timeout; untrusted-third-party refused (no container). |
| M1.3 recompute + compare + attest | **DONE, tested** | reference-deterministic recompute (fsum/pairwise-product/sqrt, NO transcendental/numpy); calibrated budget; shared verdict(); SBOM manifest. |
| M1.x orchestrator + report | **DONE, tested** | `calma.py verify` chains draft->run_hermetic->recompute->compare->ledger/gate->attest->progressive report. BTC -> REFUTED, honest claim -> CONFIRMED, end-to-end. 101 tests across 7 suites. |
| M2 calibration lock-gates | **DONE (Python), tested** | determinism band (coverage 0.97-0.98>=0.95, min-K 59); FP-guard corpus 0 false-REFUTED; calibration.json unlocks measured-band REFUTED; served-fraction 0.50 on a research-vetted real-repo corpus (2 flawed self-contained repos REFUTED, 2 live-data repos UNVERIFIABLE offline). Cross-language matrix still open. |
| M3 five-family + stats_engine | **deferred** | DSR/PBO validatable vs mlfinlab/pypbo vectors w/o new infra; leakage re-run + domain breadth need the corpus. |
| M4 breadth + contamination + signing | **deferred** | |

## Key decisions

- **Generalizable skill -> deep-quant CLI** (founder-confirmed). Breadth = the recompute-and-diff spine +
  trivial general recipes; DEPTH (DSR, leakage, realism) stays quant-only and becomes the CLI's core.
- **Reference transcendentals via `mpmath` at fixed precision** (correctly-rounded path) rather than
  vendoring crlibm for M1 - same guarantee class, far less build risk. Recorded as the pinned-libm choice.
- **Isolation on macOS = Tier-0 native sandbox + a verified `sandbox-exec` Seatbelt profile** with a
  positive-control credential-read self-test (`calma doctor`). Container/VM tier for untrusted third-party
  code requires a daemon (colima/Docker) not up on this host -> untrusted falls to static-only INCONCLUSIVE.
- **Tier-0 counts as a verified isolation tier** for the "REFUTED-without-a-container" rule; that rule gates
  MEASURED-BAND (nondeterministic) runs only - CONTROLLED-TO-BIT runs (the pure-stdlib BTC fixture) REFUTE.

## Open questions (-> Validation Plan blueprint S16)

- Tolerance-model constants (per-metric floors, fraud-multiple M) are placeholders until the M2 corpus
  calibrates them. Until then REFUTED only fires on CONTROLLED-TO-BIT runs with astronomic gaps (the BTC
  case). Do NOT ship measured-band REFUTED before M2.

## Test entrypoint

`python3 .claude/skills/calma/scripts/tests/run_all.py` runs every suite (pure stdlib; no pytest/numpy).

## Audit round 1 (adversarial, 2 auditors) - fixed

- **NaN-input propagation** (numeric.py): auc/accuracy/max_drawdown/DeLong now return NaN on NaN inputs
  so the recipe flags `degenerate` and the verdict degrades to INCONCLUSIVE (was: silently valid metric).
- **Path traversal** (recompute.py `_safe_join`): artifact paths that escape the contract base (abs / ..)
  are refused.
- **Determinism mis-detection** (run_hermetic.py): regex replaced with an AST scan that catches
  `import random as r`, `from random import ...`, `secrets`, `os.urandom`, numpy/torch aliases -> these
  are no longer mislabeled controlled-to-bit (closed a false-REFUTED soundness hole).
- **M2-gate soundness** (verdict.py): a REFUTED on a measured/uncontrolled BAND now requires M2
  calibration regardless of isolation tier (a container does not validate an uncalibrated band).
- **Sandbox read-scope** (run_hermetic.py): profile now denies ALL user homes (/Users) + system-secret
  dirs (keychains, /etc/ssh, /var/root), not just $HOME; `doctor` runs a probe BATTERY (raw-IP, DNS,
  curl egress + multiple secret reads) and stamps host-not-isolated on ANY leak. Honest stamp added:
  Seatbelt is host-kernel-shared, NOT escape-isolated (untrusted code still requires a container/VM,
  refused otherwise) - the process-escape-on-timeout limit is acknowledged, not hidden.
- All proxy env vars (incl no_proxy) cleared for the run phase.
- 20 new regression tests (test_audit.py). Total: 121 checks across 8 suites, all green.

## Audit round 2 (verification pass) - all round-1 fixes confirmed; 3 new fixed

- **Entrypoint path traversal** (run_hermetic.run): the entrypoint is now guarded by `_within(base,...)`
  exactly like artifact paths - an escaping entrypoint is refused (exit 2) and never read/executed on the
  host (closed a host-side read before sandboxing).
- **Dynamic-import / exec determinism evasion**: `_detect_determinism` now returns `uncontrolled` for
  `__import__`, `importlib.import_module`, `exec`/`eval`/`compile` - purity cannot be proven statically, so
  it fails safe (was: mislabeled controlled-to-bit).
- 7 new regression tests. Total: 128 checks across 8 suites, all green.

## Audit round 3 (convergence) - CONVERGED

Verdict: CONVERGED (no critical/major). Confirmed closed: entrypoint/artifact symlink-escape (realpath),
ledger REFUTED-cannot-be-clean invariant, orchestrator edge cases (no-contract / timeout / untrusted all
yield a coherent valid ledger, never a crash or exit-2). One honest tightening applied: importing a
stdlib source of run-to-run variation (time/datetime/uuid/socket/threading/multiprocessing) now downgrades
from controlled-to-bit to measured-band (fails safe). Total: 130 checks across 8 suites, all green.

## Status: M0 + M1 COMPLETE and audited. The closed build->audit->fix loop converged in 3 rounds.

Try it:  python3 .claude/skills/calma/scripts/calma.py verify .claude/skills/calma/assets/btc
Tests:   python3 .claude/skills/calma/scripts/tests/run_all.py

## M2 cross-language matrix + fraud-multiple (DONE)

- run_hermetic dispatches by entrypoint extension (Python/R/Julia/C/C++/Rust/Node) under the same verified
  Seatbelt tier; compile step for C/C++/Rust runs sandboxed too. Toolchain allowlist (~/.julia, ~/.cargo,
  ~/.rustup, ~/.npm) added so language depots are readable while secret dirs stay denied (doctor: 0 leaks).
- compare.py: fraud-multiple M=5 (calibrated) lets a fraud-grade gap REFUTE even on an UNCONTROLLED
  (non-Python) run; honest cross-language fixtures land CONFIRMED-WITH-CAVEATS. Calibrated against
  uncontrolled honest + fraud FP-guard cases (16-fixture corpus, FP=0).
- Cross-language matrix: R/Julia/C++/Rust/Python all SERVE (5 languages); Node is an honest run-gate
  failure (home traversal). Served-fraction 0.67 (6/9) across the full corpus. 12 new crosslang tests.
- The two remaining-partial M2 items from the prior handoff are now addressed: cross-language matrix
  filled; corpus grown to 9 members across 6 languages. (Live-data real repos still need per-repo
  snapshot vendoring to reach a verdict - the BTC pattern.)

## M2 vendoring shim (addresses the live-data served-fraction gate)

- scripts/calma_vendor.py: generic HTTP record/replay (patches urllib + requests), keyed by URL. RECORD
  once with network -> REPLAY offline; a cache MISS RAISES, so an offline replay is provably hermetic.
  Tested record->replay->miss (tests/test_vendor.py). calibration/VENDORING.md documents the repeatable
  recipe to turn a live-data repo into a verifiable corpus member.
- This converts "gated on vendoring each repo's data" from a blocker into a bounded, documented step.
  The one inherent per-repo task that remains: repos that print but never emit a machine-readable output
  need a one-line emit added before their headline number can be recomputed.

## Research-driven hardening

Web research (manual, not a workflow) into the AI-verification market, reproducibility-tool adoption, and
the quant/leakage literature drove these improvements:
- **Breadth for many use-cases:** added regression (RMSE/MAE/R2), classification depth (precision/recall/F1/Brier),
  and analytics (column-sum/mean, row-count) recipe families -> 15 recipes across quant/ML/DS/analytics.
- **Growth loop:** `calma teardown` emits a shareable "claimed X -> really Y + repro" card on every REFUTED.
- **Adoption UX:** SKILL.md now tells an agent to auto-invoke Calma after producing any numeric result
  (zero-install, in-workflow - the antidote to the 50%-install-fail / 21%-awareness death of repro tools).
- **Positioning:** Calma occupies the empty cell - verification by EXECUTION to ground truth - vs the
  eval/observability (judge) and data-validation (validate data) tools that never recompute the claim.
- 184 checks across 11 suites, all green.

## Audit round 4 (3 independent auditors: code/spec, fresh-user DX, startup) - fixed

The largest audit round; one true soundness blocker plus the entire first-contact UX.
- **Stale-artifact CONFIRMED (soundness blocker):** an entrypoint that crashed (exit 1) proceeded to
  recompute from pre-existing CSVs and could return CONFIRMED. New verdict guard G1b: ANY non-zero exit
  -> INCONCLUSIVE + a blocker reproducibility finding with the stderr tail. A failed re-run can never confirm.
- **Claim-target rubber-stamp:** `claim_confirmed` was simply `claim is not None`, so the REFUTED guard
  gated on nothing. Now: confirmed only when the metric is named (in the claim text or --metric) or the
  binding independently sanity-checks; a bare-number claim on an ambiguous auto-binding can never REFUTE.
- **Natural-language claims:** `verify <target> "accuracy 0.87"` / `"+14,698% backtest"` / `"$4.2M"` now
  parse (sign, %, commas, k/M/B) and infer the metric from the words; non-numeric claims exit 2 with a
  message, never a float() traceback. The README's own syntax works now (it didn't).
- **`calma replay` implemented** (was printed on every REFUTED card but didn't exist): re-runs under the
  prior contract terms and asserts the verdict + recomputed value reproduce.
- **INCONCLUSIVE actually prints the fix:** unblock text on findings + a reason->fix table; the dead
  `led.get("_diff")` render bug fixed; refusal/MANUAL/no-metric paths each carry a who-can-act unblock.
- **Honest platform stamps:** without sandbox-exec the run/install network stamps now say
  "host-default (NOT blocked)" and hermeticity "unverified" (was: hardcoded "off" - false on Linux).
- **verify.yaml accepts real YAML** (small dependency-free subset incl. flow maps) on top of JSON.
- **Entrypoint detection** broadened (train.py/pipeline.py/backtest.py + single-script fallback); ambiguous
  -> exact fix listing candidates. Fresh projects re-draft after the first run (outputs that only exist
  post-run now bind). Nonexistent/empty targets exit 2 with a clear error (no more silent INCONCLUSIVE).
- **One vocabulary + human numbers:** REFUTED (not BROKEN), CAN'T-CONFIRM display for INCONCLUSIVE;
  +14,698% -> -32.4% formatting; deterministic `verdict.confidence()` replaces the hardcoded 0.96;
  family-aware not-verified list (no DSR/PBO jargon on ML claims).
- **GitHub Action fixed** (env-indirection quoting - the old interpolation crashed on any claim and was a
  shell-injection vector) and now exercised in CI against the REFUTED fixture, on Linux.
- SKILL.md truth pass: phantom `consistency.py` step removed, consent-token prose removed (drafting is
  read-only; execution happens in the run step), "signed" -> content-addressed (signing is roadmap),
  spec path fixed. README rewritten to match real commands and real output.
- 52 new regression checks (test_dx.py). **Total: 236 checks across 12 suites, all green.**

## Recipe expansion to 50 + SOTA validation harness (2026-06-10)

The recipe library grew from 15 to 50, covering Packs 1-4 of the roadmap (the deep quant stats -
deflated Sharpe, PBO/CSCV, Harvey-Liu, MinBTL - stay out of the skill on purpose; they are the R1
paid-report engine):
- **Pack 1, engineering (8):** speedup_ratio, latency_p50/p95/p99, throughput, peak_memory,
  test_coverage, error_rate.
- **Pack 2, analytics (9):** column_median, percentile, groupby_aggregate, distinct_count,
  growth_rate, ratio_share, null_fraction, duplicate_count, join_row_loss.
- **Pack 3, ML/RAG/LLM (12):** recall_at_k, ndcg_at_k, mrr, top_k_accuracy, exact_match,
  pass_at_k, macro_f1, micro_f1, pr_auc, log_loss, mcc, ece.
- **Pack 4, statistics (6):** p_value (Welch/pooled/z), confidence_interval, lift, chi_square,
  correlation (Pearson/Spearman), effect_size (Cohen/Hedges/Glass).

What made this possible without breaking the determinism rule:
- **Deterministic transcendental kernels** in numeric.py: dlog/dexp/dlog2 (range-reduction +
  series under fsum), dlgamma (Lanczos), betainc_reg / gammainc_upper_reg (Lentz continued
  fractions), derfc, and bisection inverses for t/z critical values. Built ONLY from IEEE
  correctly-rounded primitives - no platform libm transcendentals in any recipe path, so
  bit-identical cross-platform, same guarantee as the M1 set. pass_at_k and the chi-square
  table use exact integer arithmetic before the final float ops.
- **String-typed columns:** recipe manifests declare `string_tags`; recompute keeps raw cell
  strings for those bindings (group keys, IDs, text predictions, null detection).
- **Cross-artifact bindings:** a binding value `left.csv::id` reads from a sibling artifact
  (join_row_loss, cross-file speedups).
- **SOTA validation:** calibration/gen_reference_vectors.py generates
  assets/reference_vectors.json (295 cases) from scikit-learn/SciPy/NumPy + the HumanEval
  pass@k estimator + the SQuAD normalizer + Guo et al. ECE; tests/test_recipes_sota.py
  (pure stdlib) re-runs every case through the kernels plus convention parsing, degenerate
  paths, bit-stability, and a recompute->compare e2e (REFUTED catch included). All 15
  pre-existing recipes are now also pinned to sklearn/NumPy reference values.
- **Claim-parser hardening:** the claim-number regex no longer swallows digits glued to metric
  names ("f1 0.84" parsed 1.0 before; "top-5 accuracy 0.91" parsed -5). ~50 new claim hints
  (p95, pass@1, ndcg, chi2, MoM, faster, coverage...) with order-sensitive specificity.
- **Binding grades for new tags:** durations/counts/ranks/flags/HTTP-status columns get
  independent value-plausibility checks, so true claims on sane columns CONFIRM (not CAVEAT)
  and fraudulent ones can reach REFUTED.
- Catalog: references/recipes.md. 711 checks across 13 suites, all green.
