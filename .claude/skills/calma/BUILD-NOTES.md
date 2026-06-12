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

## Recipe expansion to 59 + SOTA validation harness (2026-06-10)

The recipe library grew from 15 to 59, covering Packs 1-6 of the roadmap (the deep quant stats -
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
- **Pack 5, finance (6):** cagr, npv, irr (deterministic bisection), churn_rate (churn/retention),
  margin_pct, reconciliation_total (cross-artifact ledger diff).
- **Pack 6, forecasting (3):** mape (mape/smape), mase (seasonal m=), pinball_loss (q=).

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
  assets/reference_vectors.json (312 cases) from scikit-learn/SciPy/NumPy + the HumanEval
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
- Catalog: references/recipes.md. Pack 5/6 references: numpy-financial (npv/irr), sklearn
  (MAPE, pinball), Hyndman & Koehler (MASE). 756 checks across 13 suites, all green.

## Recipe expansion to 118 (2026-06-10, second wave)

Packs 7-11 double the library (59 -> 118) without touching the determinism rules:
- **Pack 7, quant risk & relative performance (13):** volatility, downside_deviation, sortino,
  calmar, value_at_risk, cvar, win_rate, profit_factor, omega_ratio, beta, alpha,
  information_ratio, tracking_error. Conventions documented (target-0 full-sample Sortino,
  loss-positive VaR/CVaR, rf=0 simple alpha); periods parsed from "monthly/weekly/daily" claims.
- **Pack 8, classification & regression depth II (17):** balanced_accuracy, cohen_kappa,
  specificity, fbeta (beta from "F2"/"F0.5"), jaccard, weighted_f1, ks_statistic, gini_norm,
  msle/rmsle, medae, max_error, explained_variance, wape, forecast_bias, adjusted_r2
  (predictor count required), nrmse, durbin_watson.
- **Pack 9, analytics & engineering II (13):** column_min/max/std, iqr, outlier_count (Tukey),
  mode_share, gini_coefficient, hhi, entropy (bits/nats), latency_p90, apdex (t required),
  uptime_pct, cache_hit_rate.
- **Pack 10, statistical tests II (12):** mann_whitney (tie+continuity-corrected asymptotic),
  ks_test (classical Kolmogorov asymptotic, documented), anova (F via the deterministic
  incomplete beta), proportion_z, fisher_exact (exact two-sided via integer combinatorics,
  scipy semantics incl. its relative-tolerance gate), odds_ratio (sample/Haldane),
  relative_risk, cramers_v, skewness, kurtosis, jarque_bera, autocorrelation.
- **Pack 11, retrieval/LLM II (4):** precision_at_k, map_at_k (min(R,k) denominator,
  documented), perplexity (from raw per-token logprobs), wer/cer (exact Levenshtein DP).

Reference corpus grew to 385 vectors; new references: statsmodels (durbin_watson,
proportions_ztest, acf), jiwer (WER/CER), scipy.stats (mannwhitneyu, f_oneway, fisher_exact,
skew/kurtosis/jarque_bera, iqr, entropy, ks_2samp, kstwobign), sklearn (balanced_accuracy,
kappa, fbeta, jaccard, weighted F1, MSLE, medae, max_error, explained_variance). ~50 new
claim hints with collision-ordering tests ("balanced accuracy" before "accuracy", "cache hit"
before "hit rate", "median absolute error" before "median"...); new `benchmark` column tag;
convention inference for VaR levels, F-beta, lags, Apdex T, predictor counts, and
monthly/weekly/daily annualization.

## Attestation chain: Ed25519-signed DSSE bundles (2026-06-10)

Signing is no longer roadmap. Next-work item 1 from the handoff shipped:

- **ed25519.py** - pure-stdlib RFC 8032 Ed25519 (reference algorithm over Python big ints; strict
  verify rejects the malleated s+L form). Same no-deps rule as the numeric kernels; EdDSA is
  deterministic, so same key + same ledger -> byte-identical bundle. Pinned to the RFC section 7.1
  test vectors (fetched from the spec, not memory) in tests/test_attest.py.
- **Bundle format** (attest.py) - a DSSE envelope (PAE-signed, payloadType
  application/vnd.in-toto+json) over an in-toto Statement v1 whose predicate embeds the FULL
  ledger + manifest; subject digest = sha256 of the canonical ledger JSON. DSSE is the envelope
  Sigstore countersigns, so the later Sigstore step is "append to envelope.signatures" - the
  signed payload bytes never change. keyid = sha256(raw pubkey). Keys live at ~/.calma/keys/
  (CALMA_KEY_DIR overrides; seed file 0600).
- **CLI** - `calma attest keygen` (one-time), `calma attest sign <run_dir>`, and the counterparty
  side `calma attest verify <bundle> [--key pub] [--replay]`, fully offline. Once a key exists,
  **every `calma verify` auto-signs** its run dir (failure to sign never breaks a verification).
- **Verification has teeth beyond the signature**: verify_bundle re-derives every verdict label
  byte-for-byte via ledger.validate_obj, checks the subject digest against the canonical embedded
  ledger, cross-checks the manifest root hash, and binds the statement verdict to the ledger's
  repo_verdict. The adversarial case that matters - forge the labels AND re-sign under your own
  key, embedded in the bundle - passes the signature check and dies at ledger-rederive. A pinned
  --key kills the re-signing itself. A REFUTED bundle verifies (the verdict is the payload, not
  the pass condition).
- **test_attest.py**: 43 checks - RFC vectors, PAE bytes, keygen permissions, auto-sign on a real
  REFUTED fixture run, deterministic re-sign, pinned-key pass/fail, six tamper shapes (in-place
  payload edit, forged-labels-re-signed, statement/ledger verdict split, subject-digest swap,
  manifest hash swap, garbage payloads), clean-run bundle, error paths. **14 suites, ~1010 checks,
  all green.** Dogfooded through the real CLI: true claim CONFIRMED + signed, inflated claim
  REFUTED + signed, hand-tampered bundle FAILS at the signature, --replay reproduces.
- Copy upgraded now that it's true: Features card "Signed, forensic attestation", lab Report step
  ("signed attestation bundle ... checks offline"), README under-the-hood step 6 + commands,
  SKILL.md step 5 + commands, script-interfaces.md bundle section. calma 0.3.0 -> 0.4.0 (the
  version is part of the cache fingerprint, so old cache entries invalidate - intended).

## Attestation chain completed to spec + catch history + recipe compiler (2026-06-10, calma 0.5.0)

The remaining two roadmap items shipped, and the attestation chain was brought to the full
in-toto/Sigstore-stack design (three layers, each optional on top of the last):

**Attestation upgrades (Layer 0-2):**
- **VSA-shaped predicate** - predicateType is now `https://calma.dev/verdict/v1`, modeled on the
  SLSA Verification Summary Attestation: `verifier` {id, engine, version}, `timeVerified`,
  `policy` {contract hash + calibration.json + reference_vectors.json hashes}, `verdict`, a
  `claims` summary - plus the full embedded ledger+manifest that give re-derivation teeth.
  verify_bundle gains `claims-binding` (summary must equal derived-from-ledger; no split possible)
  and still accepts @1 bundles/legacy predicates.
- **SSHSIG (sshsig.py, pure stdlib)** - every bundle is signed TWICE with the same Ed25519 key:
  raw DSSE (Sigstore-countersignable) and an OpenSSH SSHSIG (PROTOCOL.sshsig, namespace
  `calma-attest@v1`). Sidecar files mean a counterparty verifies with stock
  `ssh-keygen -Y verify` and ZERO installs - the crypto library is the OS. Interop tested both
  directions against the system ssh-keygen. Mix-and-match (DSSE key != SSH key) and
  ssh-block-stripping both fail closed. `keygen --import ~/.ssh/id_ed25519` adopts an existing
  unencrypted OpenSSH identity (openssh-key-v1 parsed pure-stdlib).
- **RFC 3161 trusted timestamps (rfc3161.py, Layer 1)** - `calma attest timestamp <bundle>`
  builds the DER TimeStampReq pure-stdlib, POSTs to freetsa.org (the ONLY networked step),
  embeds the token + TSA CA cert; verification is offline forever: TSTInfo parsed pure-stdlib
  (imprint must be sha256 of THIS bundle's DSSE signature - a lifted token dies), full chain
  via `openssl ts -verify` when openssl exists, honestly "structural only" when not. Tested
  against a locally-built openssl TSA (no network in tests) + live freetsa interop verified.
- **Sigstore Layer 2 (sigstore_l2.py, lab tier)** - `calma attest sigstore <bundle>` keyless-
  countersigns the SAME payload bytes via sigstore-python (OIDC -> Fulcio -> Rekor) into a
  standard Sigstore bundle. Optional dependency; missing install = exact instructions.

**Catch history (registry.py) - next-work item 2, SHIPPED:**
- `calma publish <run_dir>` -> a REDACTED entry (claim/metric/claimed-vs-recomputed/verdict/
  content hashes; never code or data - ALLOWED_FIELDS whitelist enforced at append AND audit)
  derived from a VERIFIED attestation bundle (publish requires attest). Hash chain (entry embeds
  prev sha256, id = sha256(canonical)), every entry SSHSIG-signed, HEAD.json signed too so tail
  truncation breaks the audit. `calma publish --open <id>` logs engagements at contract signing
  (the clinical-trial property: a missing outcome is structurally visible).
  `calma registry verify` audits everything offline. Tamper matrix tested: edit, edit+rehash,
  drop-middle, truncate-tail, reorder, foreign-key-rebuild (pinned), redaction leaks.
- `registry/` lives at the repo root (README + entries), rendered statically at `/registry`
  (new page, site design language, graceful empty state, open engagements surfaced). Lab page
  links it; Features card copy upgraded to "signed + trusted-timestamped + OpenSSH-verifiable".

**Recipe compiler (dsl.py + compiler.py) - next-work item 3, SHIPPED:**
- **DSL**: JSON expression trees over whitelisted numeric.py kernels (col/lit/call/op/zip/len),
  typed bottom-up, no loops/recursion -> total by construction, MAX_DEPTH 16 / MAX_NODES 256
  (DoS-safe). Interpreter degrades to NaN, never raises on numeric content; programs are
  content-hashed (sha256 of canonical JSON).
- **Admission gate (CEGIS)**: structural -> differential vs the NAMED oracle in the reference
  venv over LCG datasets (rel tol 1e-9) -> metamorphic relations (permutation/scale/shift/
  duplicate/bounds) -> degeneracy (empty/single/constant/NaN: degrade, never raise, never inf)
  -> bit-stability double-run. Failures print structured counterexamples - the drafting model's
  repair feedback. The gate proved itself live: the first cv draft declared duplicate-invariance,
  which is FALSE under ddof=1, and the gate returned exact counterexamples; draft repaired,
  re-admitted. Oracle modules allowlisted (numpy/scipy/sklearn/statsmodels/math/statistics);
  `subprocess.*` etc. rejected structurally.
- **Frozen + registered**: assets/compiled_recipes.json holds program + sha256 + pinned vectors
  + admission metadata; recipes.py loads at import RE-VALIDATING the hash (tampered assets are
  skipped with a warning - fails closed); set_maturity "compiled-validated"; claim hints insert
  BEFORE the generic hint tail ("standard error of the mean" can never bind column_mean).
  Draft contract: model-side schema at references/recipe-draft.schema.json.
- **Two real recipes admitted through the real gate**: `sem` (scipy.stats.sem) and
  `coefficient_of_variation` (scipy.stats.variation) - registry is now 120. Verified end-to-end
  through the CLI: a true SEM claim CONFIRMS via the compiled recipe, an inflated one cannot.
- Verify-time never consults a model. Compiled, validated, frozen - never improvised.

**Suite: 16 suites, ~1117 checks, all green** (new: test_registry.py 24, test_compiler.py 45,
test_attest.py 43->69). Site builds static incl. /registry. Dogfooded the whole chain through
the real CLI: keygen -> verify (compiled recipe, CONFIRMED) -> attest verify (11 checks OK) ->
stock ssh-keygen verify -> freetsa timestamp -> offline chain-verified re-verify -> publish
(opened engagement + outcome + a REFUTED catch) -> registry verify -> replay reproduces.
calma 0.4.0 -> 0.5.0.

## 2026-06-11 - the zero-touch guardrail (calma 0.6.0)

**Stop hook (hook_stop.py + sniff_claims.py + hooks/hooks.json) - SHIPPED:**
- **Claim sniffer**: precision-first detector over the agent's final message. Curated STRONG
  vocabulary (subset of CLAIM_METRIC_HINTS - generic words like total/mean/rows are deliberately
  absent), CONDITIONAL terms gated by strengtheners (coverage needs %, latency needs ms, faster
  needs x, correlation needs |v|<=1), @k families, latency percentiles, and exactly one analytics
  template ("processed N rows"). Claim syntax enforced (connector-word gap only), non-claims
  rejected structurally (versions, dates, years, line/port/exit refs, counted units, negation,
  questions, hypotheticals/targets, baselines, code fences/inline code/quotes/URLs/paths),
  values gated by per-family plausibility ([0,1]-bounded metrics; bare 1<v<=100 is
  percent-ambiguous -> silence). Emitted claims round-trip through parse_claim to the same
  value (test-enforced) and metric ids map into the engine's own hint table (closure
  test-enforced). The contract: a missed claim costs nothing; a false fire is a release blocker.
- **Stop hook**: fail-open everywhere (any error/timeout/malformed input -> exit 0 silent),
  stop_hook_active short-circuit (one verification round per stop, never loops), never-nag
  (informed-state + cache: the same break never blocks twice while code+data unchanged),
  preflight (verify.yaml or .calma/cache.json or entrypoint+CSV; .calma alone is NOT evidence -
  the hook's own breadcrumbs create it), no-shell subprocess (argv only - transcript text can
  never inject), process-group kill on timeout budget (default 30s, config-clamped 5..300),
  blocks ONLY on REFUTED/MIXED with the SKILL.md reporting contract injected; CONFIRMED /
  CAN'T-CONFIRM / unbindable / error are silent breadcrumbs in .calma/auto_history.jsonl
  (surfaced by calma stats; the seed of claims-as-code). Kill switches: CALMA_HOOK=0,
  .calma/hook-off (project or ~), config {"hook":{"enabled":false}}.
- **Suite: test_sniff.py (283 checks: fire corpus, silent-trap corpus, round-trip, vocabulary
  closure) + test_hook.py (39 checks: BTC catch end-to-end through a real subprocess, never-nag,
  all kill switches, fail-open paths incl. hung-entrypoint kill, transcript tail-read, sidechain
  filtering, preflight). 18 suites, ~1467 checks, all green.**
- Adversarially stress-tested by a multi-agent attack round (6 corpus lenses x ~30 realistic
  messages each + 3 code-attack reviewers + independent re-verification of every finding);
  confirmed findings fixed and regression-tested below.

**Stress-test results (270 cases tested, 83 reported, 12 confirmed false fires, 0 code-attack
findings survived verification).** Every confirmed bug was a precision failure on realistic
engineering chatter - exactly the contract's release-blocker class. Root causes and fixes:
- **Config-assignment shape** ("I set the toxiproxy latency to 500ms", "set the section margin
  to 4%"): a knob being turned is not a result being measured. New guard: assignment
  verb+determiner before the term ("set the", "capped the", "configured a"; the determiner
  distinguishes assignment from the noun in "test set") AND a bare "to" in the term->number gap
  -> reject. "Latency dropped to 80ms" (no assignment verb) still fires - pinned in the suite.
- **Fabricated values** ("injected latency to 250ms"): injected/simulated/artificial/induced
  immediately before the term -> reject.
- **The `returned` alias was too loose** ("the disk usage probe returned 92%"): probes, checks,
  and functions all "return" percentages. Verb aliases now additionally require a finance-shaped
  subject in the sentence (strategy/portfolio/backtest/fund/trade/...); "the strategy returned
  23%" still fires.
- **Missing counted units**: results/matches/events/duplicates/errors/warnings and money units
  (cents/dollars/usd/...) added to _UNIT_AFTER. Kills "Perplexity gave 5 results" (the search
  product), "R2 at 0.4 cents per GB" (the object store), "tracking error was 3 duplicate events"
  (an analytics bug).
- **Domain collisions** -> per-term _CONTEXT_DENY lists: "precision" in rounding/tolerance/
  float-comparison sentences (0.01-precision money rounding lives exactly inside the pct_or_01
  window - the strengthener selects FOR the collision); "churn" in diff/rename/PR/review
  chatter; "exact match" next to byte/file/artifact/checksum/sbom vocabulary; "margin" in
  CSS/layout/viewport sentences.
- **Log loss is never a percentage**: "0.4% log loss" is SRE chatter about lost log lines, not
  cross-entropy -> % suffix on log_loss rejects unconditionally; "log loss is 0.41" unaffected.
- All 12 attack texts pinned verbatim as silent-trap regressions + 3 boundary fire cases pinned
  so the new guards can't silently overreach. **test_sniff.py 283 -> 304 checks; 18 suites,
  ~1488 checks, all green.** Engine __version__ 0.5.0 -> 0.6.0 (matches the plugin manifests;
  the version is part of the cache fingerprint, so stale cache entries invalidate - intended).

## 2026-06-11 - UX audit round 5: the claim is the user's, never the contract's (calma 0.6.x)

**P0-1 claim substitution (the big one).** A committed `verify.yaml` used to silently verify ITS
claim regardless of what the user typed (`calma verify ./btc "Sharpe is 2.1"` returned a REFUTED
about total_return). New `_reconcile_claim()` gate in `calma.py`, applied before cache/run:
- (a) user claim names the same metric and the same value *numerically, within the claim's own
  reported precision* (never string equality) -> proceed, no warning. This also kills the false
  "your claim differs" note for "+14,698% backtest" vs 146.977 (P1-6).
- (b) user names a metric (claim text or --metric) the contract does not pin -> INCONCLUSIVE
  (CAN'T-CONFIRM) with `fix: add a <metric> metric to verify.yaml, or move/remove verify.yaml`.
  Never a verdict about a claim the user didn't make.
- (c) same metric, different value -> **the USER's value is verified**. Design choice, documented:
  the contract pins bindings/conventions (the anti-gaming surface), not the claim value;
  `claim_confirmed` still requires the metric to be NAMED in the claim or --metric, so an unnamed
  value override can never manufacture a REFUTED. Other pinned claims are demoted to
  reproduction-only for that run so no verdict is shown about a claim the user didn't make.
  The committed file is never rewritten; the override is announced as a `note:` in the report
  and in `--json` ("note").
- (d) claim text with no checkable number -> the committed claim is verified, prominently noted
  in human output and `--json`.
Also: a convention cap can no longer absorb a SIGN FLIP (compare.py: conventions rescale, they
never flip sign) - found while dogfooding (c), where "+50% return" vs -32.4% had slipped to
CONFIRMED-WITH-CAVEATS through the conv-cap.

**P0-2 `calma demo`.** Copies the bundled real overfit BTC fixture (assets/btc, minus .calma) to
a temp dir, runs the full pipeline offline (~0.3s), prints the verdict card + "that was a real
inflated backtest. now try your own". README quickstart now shows `calma demo` (literally
runnable) and names the real fixture path.

**P1 fixes.** Bare `calma` / `calma help` print full help + a 3-line start-here hint (exit 0).
The exit line is human: `[exit 1 (CAN'T-CONFIRM) - see --fail-on for the exit policy]` replaces
"[gate exit N - INCONCLUSIVE]" (internal enum + --json unchanged; `report.display()` maps).
No-claim mode (`calma verify <dir>`): a clean re-run whose metric recomputes from raw outputs is
now CONFIRMED/CAVEATS "(scope=reproduction)" with exit 0 - via a new `no_claim_reproduced`
verdict_inputs field set ONLY when no metric in the whole contract carries a claim (a numberless
metric next to claimed ones stays INCONCLUSIVE; verdict() stays the single pure function and
ledger re-derivation is unchanged). `verify.yaml` with `artifacts: []` next to recomputable
outputs names verify.yaml as the cause in the fix line; malformed contracts now print a minimal
copy-pasteable verify.yaml. README symlink install matches bin/calma:3 verbatim and is
cwd-explicit. MIXED documented in the README verdict list.

**P2s.** `calma recipes` (120 ids grouped by family, --json too); --metric help references it
instead of dumping 120 ids; argparse help filled for teardown positionals/--run-id/stats --json;
reproduce hints echo the actual invocation style (`_invocation()`: "python3 .../calma.py replay"
when run as a script, "calma replay" via the wrapper); teardown's internal re-verify is counted
separately in `calma stats` ("teardown re-checks: N, not counted"); `calma publish` of a
non-REFUTED run prints an honest "not a catch" notice; `calma attest verify` failure appends
"next: ask the producer to re-run `calma seal` and resend the bundle"; stats' hook-activity
summary verified present in human output.

**Tests.** test_dx.py 62 -> 96 checks: regression coverage for P0-1(a)-(d) (true claim CONFIRMS
against an inflated committed value; wrong claim REFUTES against the USER's value; mismatched
metric and --metric conflict block with the fix; unparseable claim notes the substitution in
report + --json), P1-6 numeric-precision match on the real BTC contract, no-claim reproduction
(exit 0 + scope=reproduction), empty-artifacts fix line, malformed-contract example snippet,
bare/help/recipes/demo CLI surfaces, human exit-line vocabulary, _invocation() echo, and stats
teardown separation. Full suite: 18 suites, 0 failures.

## 2026-06-11 - security/product audit round 6: cache collision, sandbox self-state, trust posture, predicate URIs (0.6.1)

**P0 cache collision (calma.py).** The verify cache mapped fingerprint -> {run_id, repo_verdict},
but run_id defaults to "run" for every CLI verify, and the run dir is overwritten per verification -
so verify A (REFUTED), verify B (CONFIRMED, same run dir), re-verify A served B's CONFIRMED ledger
as A's cached verdict. Fixed: `_store_cache` now pins the exact ledger bytes (`ledger_sha256`) the
entry was derived from; `_cached_result` rejects the hit (falls through to a fresh run) when the run
dir's ledger hash no longer matches, AND when the cached repo_verdict disagrees with the ledger on
disk. cache.json writes are atomic (temp + os.replace). Regression: the exact A/B/A scenario plus
the tampered-cached-verdict case in test_dx.py.

**P0 predicate URI migration (attest.py).** calma.dev is owned by a stranger - every emitted URI is
now GitHub-rooted (`https://github.com/rikhinkavuru/calma/verdict/v1`, `.../attestation/verification/v1`,
`.../skill` for verifier/builder ids; recipe-draft.schema.json `$id` likewise). The legacy calma.dev
URIs stay in PREDICATE_TYPES_ACCEPTED forever, and claims-binding is enforced on BOTH verdict/v1
shapes - so v1 bundles signed under the old URI (including the genesis registry entry and the btc
test bundle) keep verifying. Confirmed: `registry verify registry/` exit 0; `attest verify` passes
on the pre-migration btc fixture bundle. README/SKILL.md/script-interfaces.md prose updated with the
old-bundles-remain-valid note.

**P1-1 sandbox self-state write (run_hermetic.py).** The Seatbelt profile allowed
`(allow file-write* (subpath base))` and `.calma` lives inside base - code under test could plant
cache.json/ledgers and forge verdict state. A `(deny file-write* (subpath "<base>/.calma"))` now
comes AFTER the allow (Seatbelt is last-match-wins). Verified the verifier itself never writes
.calma DURING the sandboxed child run (all .calma writes happen in the parent, after H.run returns).
Real probe in test_hermetic.py: overwrite cache.json + plant a ledger both DENIED, base stays
writable, pre-existing cache bytes untouched.

**P1-2 trust posture (calma.py + run_hermetic.py).** `calma verify --trust {own-code,third-party}`
(default own-code). third-party tightens the posture AT RUNTIME (`trust_override` into H.run - the
contract file is never rewritten; drafted contracts keep `trust: own-code`): no verified container/VM
tier -> refuse to execute, INCONCLUSIVE with the posture named in the fix line, CLI exit 3. A
one-line first-run notice per target dir (marker in .calma/, stderr only, never repeated): "calma
re-executes this project's code in a sandbox (tier: X) - pass --trust third-party for counterparty
code".

**P1-3 hook isolation gate (hook_stop.py).** The Stop hook now (a) creates NO .calma dir (no
breadcrumbs) before the verifiable-target gate passes - a metric mention in an unrelated repo leaves
nothing behind; (b) requires a VERIFIED sandbox tier before auto-executing: run_hermetic doctor,
cached in hook state with a 24h TTL; no verified tier -> skip with a "no-verified-sandbox"
breadcrumb; `{"hook": {"force_unverified": true}}` overrides. (c) The child verify's --timeout is
capped at 30s regardless of the CLI's 120s default.

**P1-4 timeout.** `calma verify --timeout SECONDS` (default 120; `run.timeout` in verify.yaml
honored when the flag is absent; clamped to [1, 86400]); plumbed into run_hermetic for both the main
run and the determinism re-run. The killed fix line names the flag: "raise it with --timeout SECONDS
(or run.timeout in verify.yaml)". CLI exit 4 on a killed run, exit 3 on a refusal (both in the
README exit-code table).

**P2s.** Python floor: `sys.version_info >= (3, 9)` checked at the top of main() with a clear error
(features used floor at 3.8 - math.comb/walrus - but 3.8 is EOL; 3.9 is the supported floor, stated
in the README install section). Env whitelist into the sandbox: only PATH/HOME/LANG/LC_*/TMPDIR/
PYTHON* plus contract `env.passthrough` names reach the child - parent secrets are stripped
(documented in the module docstring + verify.schema.json; probed in test_hermetic.py). Atomic writes
for registry entries + HEAD.json (registry.py) alongside cache.json. `calma seal` catches ValueError
from RFC 3161 response parsing (a malformed TSA reply defers the timestamp instead of tracebacking
mid-seal). stderr/stdout tails are $HOME-redacted (`~`) before they can enter ledgers or bundles.
README: exit-code table (0-4), 6-line GitHub Action example, platform statement (macOS first-class /
Linux reduced-and-says-so / Windows unsupported), hook cost line ("first catch costs up to 30s;
repeats are cache-instant"). compiler.py reference venv: `$CALMA_REF_VENV` first, then the /tmp
default with a multi-user world-writable warning. Version 0.6.1 across calma.py, plugin.json,
marketplace.json.

**Tests.** test_dx.py 96 -> 121 checks (A/B/A cache collision + tamper rejection, trust refusal +
exit 3 + drafted-contract-untouched, timeout flag/contract/default + exit 4 + fix-line naming,
first-run notice once-only, $HOME redaction); test_hermetic.py 9 -> 16 (the .calma write-deny probe
under the real sandbox, env whitelist + passthrough); test_hook.py 39 -> 43 (no-litter gate,
no-verified-sandbox skip + force_unverified override + TTL re-probe); test_attest.py 73 -> 78
(GitHub-rooted predicate, legacy-URI fixture bundle still verifies with claims-binding enforced).
Full suite: 18 suites, 0 failures. Dogfood: A/B/A reproduced-then-fixed on a /tmp copy of
assets/btc; `registry verify registry/` exit 0; `attest verify` on the pre-migration btc bundle
passes; `calma demo` still catches the inflated backtest.

## Served-fraction corpus to 9/9 (2026-06-12)

The real-repo + cross-language served-fraction corpus went from **6/9 → 9/9** (`served_fraction = 1.0`;
REFUTED 3, CONFIRMED 2, CONFIRMED-WITH-CAVEATS 4; zero false-confirms, zero false-REFUTEs). Three general
engine fixes + two newly-vendored real repos, not corpus-specific hacks. Regenerate the artifact with
`calibration/regen_served_fraction.py` (records the full corpus; needs toolchains + network for restore).

- **Node served (isolation fix).** Node's CJS loader `lstat`s `/Users` while realpath-resolving the
  entrypoint; the blanket `(deny file-read* (subpath "/Users"))` rejected it (EPERM → run-gate fail).
  `run_hermetic._profile` now emits `(allow file-read-metadata <literal ancestor>...)` for the EXACT
  ancestor chain of the run base (`_ancestors`). Metadata-only (lstat/stat/readlink) lets any runtime
  resolve its script; directory listing and file-content reads under `/Users` stay denied. Doctor still
  proves zero secret-reads + zero egress; an adversarial probe (test_hermetic.py) confirms lstat passes
  while `listdir`/`open` are denied. Node added to test_crosslang.py CASES.
- **Restore/run interpreter consistency.** A Python repo whose deps are restored into `<base>/.calma_venv`
  now RUNS under that venv (`_venv_python`), not the host interpreter — otherwise a dep-heavy repo silently
  fails the run gate (can't import what restore installed). Run result carries `interpreter: restored-venv|host`.
- **Whole-program determinism.** `_detect_determinism(entry, base)` now scans EVERY `.py` under the program
  tree (excl. `.calma*`/`.calma_venv`/`__pycache__`), not just the entry file, so a thin entrypoint over
  numpy-using local modules is honestly `measured-band` (was wrongly `controlled-to-bit`). Scientific stack
  (pandas/scipy/sklearn/statsmodels) added to the RNG/non-bit set. Whole-tree only when `base` is given;
  a bare single-file call stays single-file (so callers in shared dirs aren't tarred by neighbors).
- **Two vendored real repos** under `assets/corpus/<name>/` (each with `VENDORED.md` provenance + re-record
  recipe). (1) `momentum-strategy` (sh-mukherjee, MIT, yfinance) — frozen `vendored_prices.csv` snapshot,
  unchanged signals→risk→backtest compute path, pinned deps (cp313 wheels), `total_return = -2.76%` →
  CONFIRMED. (2) `btc-sma-crossover` (HilmiSamdya/btc-sma-backtest, MIT) — the upstream SMA-crossover+TP/SL
  strategy driven by BTC-USD OHLC fetched from Coinbase via the `calma_vendor` HTTP record/replay shim
  (recorded once, replayed offline, hermetic), `total_profit = 19024.77` via `column_sum` → CONFIRMED. This
  replaces the retired `Erfaniaa/crypto-backtester` (deleted upstream + binance HTTP 451 = unreproducible).
- **calma_vendor shim hardening.** record now forwards request **headers** (Coinbase 403s without a
  User-Agent), honors requests **`params`** (folds the querystring into the cache key + fetch, so paged GETs
  don't alias), and patches **`requests.Session.request`** (covers `requests.Session()` and ccxt, what real
  repos actually use — not just the module-level helpers). The shim is vendored alongside btc-sma-crossover
  (self-contained under network-off isolation) with a byte-identical drift guard in test_vendor.py.

**Tests.** test_hermetic.py 16 → 25 (metadata-ancestor profile structure + sandbox boundary probe: lstat
allowed, listdir/read denied; venv-aware interpreter selection); test_vendor.py 2 → 8 (params keying +
differing-params MISS, Session replay, drift guard); test_crosslang.py +node; test_m2.py +btc-sma-crossover
offline shim replay. Full suite green under both Homebrew python3.13 and system python3.14: 18 suites, 0 failures.
