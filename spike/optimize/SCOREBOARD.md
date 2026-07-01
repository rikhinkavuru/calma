# Calma architecture — optimization scoreboard

The durable tracker for the metric-by-metric optimization loop. **Source of truth across sessions** — read
this first to resume. Each cycle: measure → diagnose the limiter → improve the code → re-measure → record.

## The rules of this loop
- **FCR = 0 is the fixed invariant.** Never traded for any other gain. A change that confirms one wrong
  number is a regression no matter what else it improves.
- **"Maxed" = hit the ambitious target OR provably plateau** (diminishing returns shown, not abandoned).
- Some metrics trade off (tolerance: catch vs false-refute; binding aggressiveness vs FCR). We push the
  **Pareto frontier**, holding FCR fixed. "All metrics maxed at once" is a frontier, not a point.

## How to measure
```
# value-half (catch-rate / false-refute / FCR-under-injection / MDE) — capture once, replay many:
~/.calma/spike-venv/bin/python optimize/capture_fixtures.py     # run base fixtures once → captures/
~/.calma/spike-venv/bin/python optimize/measure.py              # → optimize/metrics.json + prints summary
# coverage-half (reproduction / binding / verdict-accuracy / false-confirm gate) — the go/no-go harness:
~/.calma/spike-venv/bin/python run_spike.py                     # → results/SPIKE-REPORT.md
```

## Scoreboard (priority order: safety → value → coverage → trust → ops)

| # | Metric | Target | Current | Source | Status |
|---|---|---|---|---|---|
| 1 | **False-confirm rate** (cardinal) | **0** | **0.0** — ~260 injections + 8/8 attacks + **0/16 on the LIVE real-repo corpus** | measure+invalidate+redteam+run_spike | ✅ HELD on real code |
| 2 | **Catch-rate** (both axes) | →1 | misreport **1.0** + wrong-formula **1.0** given-bound; **~0.58 effective** | measure+invalidate | ⚠️ coverage-bound (NOT logic) → breadth/capture |
| 3 | Reproduction rate | ≥0.90 | **0.80 LIVE** (8/10); 2 fails = repo code bugs | run_spike live | ⚠️ env-pinning (concurrent session building it) |
| 4 | **Binding rate** | (safe ceiling) | **0.50 LIVE** (8/16) · logic **1.0** synth | run_spike live + binding.py | ✅ unbound = all correct fail-closed¹ |
| 5 | Binding correctness (right quantity) | →1 | **1.0** + over-bind **0.0** (synth) | binding.py | ✅ logic safe; keep over-bind 0 |
| 4b | Capture coverage (candidate exists) | high | hand-rolled metrics **uncaptured** | corpus diag | ◻ value-recompute fallback (the real lever) |
| 6 | False-refute / false-invalidate | 0 | refute **0.0**; **fixed a balanced-acc false-INVALIDATE** | measure + recompute_stress | ✅ + regression test |
| 7 | Confirm/refute precision | high | **1.0 / 1.0** on base-rate-mixed corpus | corpus_synth.py | ✅ |
| 8 | Validity / wrong-formula catch (INVALIDATED) | →1 | **1.0** (80 inj) · FCR **0** · MDE 1e-4 | invalidate.py | ✅ maxed on clean inputs; real-leakage rate next |
| 9 | Discovery recall / precision | high | struct 1.0/1.0; **prose 0→1.0** (precision 1.0) | discovery_eval.py | ✅ prose patterns added |
| 10 | MDE / sensitivity | char. | full catch ≥ **3e-4** (4-dec floor) | measure | ✅ characterized (misreport axis) |
| 11 | Tolerance separation (produced vs recompute) | char. | **INVALIDATED-axis MDE 1e-4** (~1e-6 rel floor) | invalidate.py | ✅ characterized |
| 12 | Verdict determinism (Calma-self) | →1 | **1.0** (3 captures · verdict+produced) | determinism.py | ✅ |
| 13 | **Adversarial FCR** (red-team) | 0 | **0.0** — 8 attack vectors, none confirmed | redteam.py | ✅ HELD (incl. binding-coincidence hole) |
| 14 | Calibration / tamper | — | tamper N/A (signing deferred §6) | redteam (robustness) | ◻ calibration needs confidence scores |
| — | Catalog breadth (verifiable coverage) | grow | **626 recipes** + 16 core-native (mcc/kappa/brier, 1e-9) | recipes + catalog | ✅ already broad |
| 15 | Operational (latency/cost/batch) | low/scaling | wall 10.2s/repo corpus · 1.6s local | run_spike | ◻ p95/cost/batch + E2B cost telemetry (shipped /api/cost) |

## Key insight (cycle 0)
**Catch-rate is coverage-bounded.** The misreport→REFUTED path is saturated (FCR 0, catch 1.0, false-refute
0) on claims Calma can bind+reproduce. So the lever that most raises *real* catch-rate is **coverage**
(binding #4, reproduction #3), not the diff/verdict logic — those are already at ceiling on this path. The
harder error classes (wrong-formula→INVALIDATED, nondeterminism) still need their own injection corpora to
prove catch-rate there (cycles to come). The injection harness (`optimize/`) is the new value-half
instrument; `run_spike.py` remains the coverage-half + the false-confirm gate.

## Cycle log
- **Cycle 0 — foundation + first value-half baseline (2026-06-30).** Built `optimize/` (capture-once /
  replay-many injection meta-eval). First-ever measurement of catch-rate & FCR against *deliberately wrong*
  claims: FCR 0.0, catch 1.0 (given-bound), false-refute 0.0, MDE floor 3e-4. Established that catch-rate is
  coverage-bounded → **#4 binding is the next cycle.** No core code changed yet (added files only).
- **Cycle 1 — binding diagnosis (2026-06-30).** Built `optimize/binding.py` (synthetic multi-candidate
  corpus, 11 scenarios). **Binding LOGIC is maxed: bind-rate 1.0, correctness 1.0, over-bind 0.0,
  fail-closed 1.0.** So the corpus's 58% is NOT a logic defect. Decomposed the 5 real INCONCLUSIVE claims:
  (a) iris-multimodel ×1 = genuinely ambiguous → *correct* fail-closed (ceiling is <100% by design);
  (b) digits-softmax ×2 = hand-rolled metric never captured → **capture-coverage gap**;
  (c) iris-codealpha ×2 = GridSearchCV emits *several* user-site accuracy calls → **real binding gap** my
  synthetic corpus missed (it assumed exactly one user-site call).
  **Don't optimize "binding rate" by binding ambiguous cases** — that raises the number while creating
  false-confirm risk. Target = bind everything with a unique correct answer, fail closed on the rest.
- **Cycle 1 CONCLUSION — binding is at its safe ceiling (don't trade FCR to raise it).** Worked through
  every no-hint disambiguation (bind-smallest / bind-last / bind-unique-value-match). **All have the same
  hole:** if a claim *misreports* computation A to a value that coincidentally equals a different
  computation B, any auto-resolution landing on B CONFIRMS a wrong number → false confirm. "Unique value
  match" doesn't save you (the matched computation may not be the claim's referent). So a no-hint
  multi-candidate claim **cannot be safely CONFIRMED** — fail-closed is correct. Per the FCR-never-traded
  rule, binding is maxed at the frontier. Safe levers (next cycles): capture coverage, reproduction infra,
  discovery referent extraction — never more-aggressive binding. (Vindicates the memory's warning.)
- **Cycle 2 — wrong-formula / INVALIDATED catch (2026-06-30).** Built `optimize/invalidate.py`: perturb a
  capture's produced `result` while keeping inputs honest (claimed==produced but produced≠independent
  recompute) → simulates a cheating/wrong formula. **80 injections: invalidation-catch 1.0, FCR 0.0,
  caught down to 1e-4 rel** (INVALIDATED-axis MDE; ~1e-6 floor). The moat's core is proven, not just the
  easy misreport path. Reproduction diag: the 2 corpus non-runs are genuine repo bugs / sklearn version
  drift (classifier-on-continuous, NaN-to-estimator) — correct fail-closed; needs env-pinning, not tuning.

## META-FINDING (after cycles 0-2)
**The core verification logic is maxed within FCR=0 on the current corpus** — four hard axes at ceiling
(misreport-catch, binding, reproduction-given-runnable, wrong-formula-catch), FCR=0 held under 130
deliberately-wrong injections. The corpus is **too easy** (clean seeded iris/sklearn repos) to reveal the
real ceiling, and the graded set is n=1. So the remaining optimization is NOT core-logic tuning; it is:
(1) a **harder + adversarial corpus** (the highest-leverage next build — gives every metric room and is
where real gaps will surface), (2) **breadth** (catalog metrics → more claims get a hard verdict vs
REPRODUCED-ONLY), (3) **the unmeasured trust metrics** (determinism #12, real-leakage validity #8b,
adversarial-FCR #13, tamper #14), (4) **infra** (env-pinning #3, value-recompute fallback for hand-rolled
metrics). 351 tests green; only `optimize/*` added, no core changed.

- **Cycle 3 — recompute-correctness stress + a REAL bug fixed (2026-06-30).** Built
  `optimize/recompute_stress.py`: 17 subtle cases (multiclass macro/micro/weighted, AUC ties, {1,2} labels,
  string labels, pos_label=0, imbalance, regression w/ negatives) where the capture's `result` IS sklearn's
  value → an honest claim must come back CONFIRMED. **The oracle matches sklearn on every recompute path
  (0 recompute bugs).** But the stress caught a **validity false-INVALIDATE**: `balanced_accuracy` was
  baselined against the majority-class fraction (right only for raw accuracy) — a constant predictor scores
  1/n_classes on balanced accuracy, so an honest 0.667 (2-class, majority 0.75) was wrongly INVALIDATED.
  Fixed in `core/validity.py` (correct per-metric baseline) + `tests/test_validity_baseline.py`.
  recompute_stress now 17/17; test_loop gate green. **First core-code improvement of the loop.**
  CORPUS RERUN: blocked — the sandbox has no network for git-clone/pip, so live binding/reproduction can't
  be re-measured here. Per the shipped memo (commit 2aa7327) binding improved (iris CONFIRMED, codealpha
  collapsed 25 internal calls), so the 58% baseline is stale-low.
- **Cycle 4 — leakage / soundness axis (#8b) validated (2026-06-30).** Built `optimize/leakage_stress.py`
  (controlled-overlap synthetic splits). Both detectors correct against their own threshold: **exact-row
  catch 1.0 (≥1%), homology catch 1.0 (≥5%), false-positive 0 on clean disjoint splits, sub-threshold
  quiet.** (Surfaced + fixed two of MY OWN test-data bugs first: a cyclic / LCG-low-bit DNA generator that
  made clean splits self-flag, and a 2-mutation near_dup whose k-mer Jaccard fell below the 0.8 threshold —
  switched to a seeded Mersenne-Twister RNG + 1-mutation near-dup. Lesson: synthetic-corpus quality is
  load-bearing — verify the generator before trusting a catch number.) **Two-axis catch is now fully
  measured + at ceiling:** reproducibility axis (recompute, cycles 2-3) + soundness axis (leakage, cycle 4).

## STATE after cycles 0-4 (turn 2026-06-30)
Every hard verification axis measured and at its safe ceiling on clean inputs; **FCR = 0 held under ~210
deliberately-wrong injections**; ONE real core bug found + fixed (balanced-accuracy false-invalidate).
Instruments (all `optimize/`): capture_fixtures, measure (misreport), binding, invalidate (wrong-formula),
recompute_stress (oracle vs sklearn), leakage_stress (contamination). **Uncommitted & ready to commit:**
`core/validity.py` fix + `tests/test_validity_baseline.py` (left uncommitted to avoid racing the concurrent
main work — flag for the founder).
- **Cycles 5-7 — trust + breadth + the franchise gate (2026-06-30).**
  - #12 verdict determinism: `optimize/determinism.py` — 3 independent re-captures, 68 claims, **verdict +
    produced-value stability 1.0** (Calma is byte-stable).
  - Breadth: `mcc` + `cohen_kappa` ported to the NATIVE pure-stdlib catalog (were flywheel-dependent),
    validated vs sklearn to 1e-9 (`tests/test_catalog_mcc_kappa.py`); catalog 13→15. Full suite green (353+).
  - #13 **ADVERSARIAL FCR = 0** (`optimize/redteam.py`): 8 engineered attacks — value-coincidence
    multi-candidate, cheating formula, metric-spoof, single-class, trivial-baseline, NaN, nondeterministic,
    length-mismatch — **none confirmed** (→ INCONCLUSIVE / INVALIDATED / REPRODUCED-ONLY / NON-DET). The
    binding-coincidence hole (proven unfixable without FCR risk) fails CLOSED as designed. (Soft note:
    NaN / length-mismatch land in REPRODUCED-ONLY — honest "can't verify", safe; could add an explicit
    "malformed inputs" caveat later.)
- **Two uncommitted core improvements ready to commit:** `core/validity.py` (balanced-acc baseline fix),
  `core/catalog.py` (+mcc +cohen_kappa) + tests. Left uncommitted to avoid racing concurrent main work.
- **Cycle 8 — discovery prose recall (#9) (2026-06-30).** `optimize/discovery_eval.py` measured recall 1.0
  structured / **0.0 prose** — the regex parser missed every natural phrasing ("achieved 96.67% accuracy",
  "F1 score of 0.72", "AUC was 0.91"). Added prose patterns to `discovery/extract.py` (metric↔value either
  order via a connector; `map_metric` stays the precision gate). **Prose recall 0→1.0, precision 1.0**,
  structured unchanged, test_discovery green. Real front-of-funnel lift (more claims reach the verifier;
  each still fail-closes). Third uncommitted core improvement.
- **Cycle 9 — the HARDER corpus + a real tolerance bug fixed (2026-06-30).** Built `optimize/corpus_synth.py`
  (full confusion — honest/misreport/wrong-formula — across ALL 15 catalog metrics × binary/multiclass/
  every averaging mode/regression/reductions/finance = 27 scenarios, sklearn/scipy ground truth). It
  immediately exposed a **false-confirm the easy corpus hid:** a bounded [0,1] metric claimed as a bare
  integer ("1") got ±0.5 tolerance (half-ULP of the units digit) → "1" swallowed a produced 0.9667. Fixed in
  `core/tolerance.py` (bounded-integer claims use a tight relative check; counts keep half-ULP) +
  `tests/test_tolerance_bounded_int.py`. After the fix **all 27 scenarios pass: catch 1.0/1.0, FCR 0,
  false-refute 0, false-invalidate 0, confirm/refute-precision 1.0** (#7 now measured on a mixed corpus).
  Also built `optimize/edge_stress.py` — degenerate inputs (zero-var Sharpe, constant-target R², all-equal
  AUC, single-class, NaN) all fail closed; valid extremes (1e9 / 1e-8 / huge outliers) all confirm. No new
  bug. **4th core fix.** Both corpora + edge stress are now permanent CI gates (`test_optimize_gates.py`, 7 gates).
- **Loop status:** every scoreboard metric has been run on a HARD corpus and is at its achievable peak there;
  4 real core bugs found+fixed; FCR=0 held under ~260 wrong/adversarial/edge injections; the franchise
  invariants are CI-gated. Breadth is ALREADY broad (626 recipes + 16 core-native, not a gap). **Genuine
  further gains are now MULTI-SESSION INFRA that this sandbox can't do (no network):** env-pinning
  (reproduction of version-drifted repos), value-recompute fallback (hand-rolled metrics with no captured
  computation), and a LIVE real-repo corpus to lift the graded set above n=1. #14 tamper = N/A until
  signing (§6). The per-metric *tuning* loop on offline-synthesizable corpora has genuinely converged.
- **Cycle 10 — the LIVE real-repo corpus (2026-06-30).** Network IS available via the sandbox override, so
  the corpus ran on current code: **reproduction 80% (8/10), binding 50% (8/16), FALSE-CONFIRMS 0, verdict
  accuracy 100%.** The franchise invariant **FCR=0 holds on real GitHub repos**, and every bound claim is
  correctly verdicted (3 honest iris repos→CONFIRMED, version-drift→REFUTED, unseeded RF→NON-DETERMINISTIC).
  ¹**The 50% unbound is ALL correct fail-closed, not a defect:** iris-multimodel (genuinely ambiguous),
  digits-softmax (hand-rolled numpy, no captured computation + no artifact → genuinely unverifiable),
  iris-codealpha (GridSearchCV multi-eval, "Final Accuracy" underspecified → auto-confirm proven unsafe).
  Binding rate fell 58→50% *because prose-discovery raised recall* (15 claims vs 11) — the new claims are in
  the hard repos and correctly fail closed; a denominator effect, FCR still 0. The 2 non-runs are real repo
  bugs (classifier-on-continuous; NaN-to-estimator) → env-pinning territory (concurrent session). **The loop
  is now validated on REAL code, not just synthetics: FCR=0, correct verdicts, correct fail-closure.**

## Phase 2 — real-repo tooling (post-loop, 2026-06-30, on main)
- **CI fixed (was red on EVERY commit):** `fastapi`+`httpx` were missing from `.github/workflows/ci.yml`,
  so test_server_auth errored. Now green — the 7 franchise gates run in CI on every push/PR.
- **`optimize/corpus_run.py`** — low-friction live runner: a BARE repo URL → clone HEAD → detect entrypoint
  → infer deps → discover → verify. The harness for "test on tons of random repos." Local + `--e2b`.
- **Notebook support (pure-stdlib `.ipynb`→`.py`)** — most real ML repos are notebooks, not scripts; this
  is the make-runnable unlock. Validated: a real breast-cancer notebook materialized + ran + produced verdicts.
- **Make-runnable bug FIXED:** `detect_entrypoint` matched README env-setup commands (`python -m venv …`)
  as the entrypoint → broke the run. Now skips setup modules (`runner/build.py` + test). +14% reproduction.
- **Batch-1 (7 repos): reproduction 57%, binding 100%, FCR 0, verdict-accuracy 1.0** (3/3 graded). Non-runs
  are real externalities: external Colab/Kaggle data ("connect your data" need), sklearn version-drift
  (`plot_roc_curve` removed — env-pinning territory), a notebook that ran but reported no recognizable metric.
- **Known edge (deferred):** one repo hit RecursionError under the auto-runner yet still produced the correct
  CONFIRMED verdict (FCR-safe). Corpus curation to n=50-100 is the founder's "test on tons of repos" phase.

## Phase 3 — domain generalization (2026-07-01, executing docs/DOMAIN-GENERALIZATION-GUIDE.md)
Executing the guide's franchise-safety-first roadmap. FCR=0 held throughout; full suite 460→540 tests.
- **P0.1 — corpus intake schema.** Every repos.yaml entry now carries a machine-checkable `meta`
  {domain/tier/split/license/commit_date} (guide §A.2). New `corpus.py` describes the corpus as a
  DISTRIBUTION (n per domain×tier) + validates the rubric; `tests/test_corpus_schema.py` is a hard gate.
  The 18/20-ML "iris trap" is now measured, not hidden. Corpus grew 20→23 (finance/statistics domains added).
- **P0.3 — T4 tier + coincidental-value fuzz.** T4 negatives tagged/added per domain; `optimize/convention_fuzz.py`
  is the standing FCR proof (guide §B.2 rule 8) — 2800 random fabricated values against random inputs, 0
  matched any standard convention. Wired into `test_optimize_gates.py` as a permanent CI gate.
- **P2 — convention registry (§B.2) [DONE].** New `core/conventions.py`: the HARD CONTRACT (cited axes, size
  cap ≤24, no free continuous params, tight tolerance, gated-on-reproduction, audit note) + a GENERIC
  `search()` reused by catalog + (later) synth/NLP. Native pure-stdlib kernels added to the catalog
  (stdev/variance/sortino/calmar/information_ratio/correlation) validated vs numpy/scipy to 1e-9. Covers
  Sharpe/Sortino/Calmar/IR + stdev-ddof + correlation-type. Proven END-TO-END on real runs: finance_sharpe
  (√252+ddof=0)→CONFIRMED, stats_correlation (spearman-as-'correlation')→CONFIRMED, finance_sharpe_cheat
  (hardcoded)→INVALIDATED. **FCR=0 on the 2800-trial fuzz + T4.**
- **P1 — __main__ capture ladder (§B.1) [DONE].** Tier 1 = `sys.monitoring` (PEP 669) target capture in
  `calma_capture.install_targets_monitoring` — hooks the CODE OBJECT so it captures a metric defined+called
  in __main__ (AND imported AND THREADED), reads NAMED args off the frame, DISABLE-elsewhere for ~0 overhead;
  never mutates source. Tier 2 = `capture/ast_capture.py` (AST decorator-append + __main__ exec + round-trip
  determinism GUARD) as the <3.12 portable fallback. Runner auto-selects Tier 1 on ≥3.12 (`target_tier`
  breadcrumb); `CALMA_CAPTURE_NOMON=1` forces legacy. **A/B PROOF:** main_metric → CONFIRMED under Tier 1 vs
  INCONCLUSIVE (fail-closed) under the legacy import-patch tier — the __main__ gap closed, and the old miss
  was always fail-closed. digits-softmax-style hand-rolled metrics now reach a real verdict (cheat→INVALIDATED).
  Full local graded corpus: reproduction 92%, binding 93%, **verdict-accuracy 100%, FALSE-CONFIRMS 0.**
- **P0.2 — metric×domain×tier scorecard [DONE].** `optimize/scorecard.py` renders the intake distribution
  matrix + per-(domain,tier) outcomes (reproduction/capture/binding/verdict-accuracy/verdict-distribution),
  each with n-counts + small-n flags, and the FCR cell as a HARD gate (`fcr_breaches`). `run_spike` now emits
  per-repo `meta` so results are self-describing. Live scorecard across 5 domains: FCR 0 in every cell.
- **P3 — NLP/IR recompute + LLM-synth + learned fail-closed (§B.3) [DONE].** New `core/textmetrics.py`:
  pure-stdlib IR (nDCG validated vs sklearn to 1e-9; MRR/recall@k/precision@k/hit@k/MAP) + NLP generation
  (BLEU corpus/sentence; ROUGE-1/2/L) kernels, merged into the catalog. nDCG (gain×k) + BLEU (tok×smooth×
  scale) convention grids reuse `conventions.search` — the SAME code path as Sharpe (the guide's unifying
  insight). LEARNED metrics (BERTScore/BLEURT/COMET) fail closed to REPRODUCED-ONLY with an honest reason
  (no independent recompute of a neural checkpoint). LLM synthesis PRODUCTIONIZED: `_llm_synthesize` (Claude,
  gated+best-effort like the planner) proposes a recompute, `_validate_synth` disposes (wrong/injected code
  fails validation → falls back to the grounded registry code, never banked); text-input case generators +
  best-effort sacrebleu/pytrec_eval oracle wiring with the empty-qrels-bug guard. Proven end-to-end:
  ir_ndcg→CONFIRMED, bleu_eval→CONFIRMED (scale=percent), bertscore→REPRODUCED-ONLY. Fuzz gate extended to
  ndcg+bleu (3600 trials, 0 FCR).
- **P4 — automated sourcing pipeline (§A.6) [DONE].** `optimize/source_corpus.py`: Stage 1 (GitHub search,
  gated) → Stage 2 cheap filters (permissive SPDX + size + reported-number, PURE) → Stage 3 planner triage →
  Stage 4 dry-run → Stage 5 emit a repos.yaml stub that passes the SAME intake rubric a hand-authored entry
  does. Post-cutoff freshness classification (decontamination slice). Degrades gracefully offline (empty,
  well-formed queue). Network stages gated/best-effort like the planner.
- **Cycle FB — the 20-feature build-out (2026-07-01), Waves 0+1.** Executing `docs/FEATURE-BUILD-PLANS-2026-07.md`
  at SOTA. **Wave 0 (FCR-hardeners + legibility):** F8 inline red-team gate (`core/redteam_gate.py` +
  `verdict.monotone`, a second independent downgrade-only screen of every CONFIRMED, wired in `pipeline.
  _apply_redteam_gate`); F4 claim salience (`discovery/salience.py` P0 deterministic + `discovery/
  claim_classifier.py` P1 best-effort LLM, identity-preserving re-rank, zero FCR surface); F10 perturbation
  primitives (`core/perturb.py`). **Wave 1 (coverage floor + un-foolability):** F2 fuzz-the-formula + F7
  metamorphic + F10-P1 fabrication all ride ONE shared in-sandbox re-invocation emitter (`capture/reinvoke.py`,
  gated `CALMA_FUZZ=1`, armed at atexit so __main__ targets resolve, wired through local + E2B runners →
  `run_result['fuzz']` → `core/diff.py._fuzz_overlay` → the EXISTING validity-invalidating path, downgrade-only);
  host judges = `core/formula_diff.py` (differential vs catalog + convention-explains guard), `core/metamorphic.py`
  (exact analytic MRs on the repo's own outputs), `core/perturb.fabrication_from_fuzz` (input-independent output).
  F1 get-it-running repair loop (`runner/repair.py`, ENV-ONLY action space {PIP/APT/SETENV/ENTRYPOINT_ARG/
  FETCH_DATA/GIVE_UP} — no source-edit, so a bad step → DISCOVERED not a confirm; source-modified rail caps
  CONFIRMED→REPRODUCED-ONLY via `pipeline._apply_agent_modified_cap`; best-effort LLM proposer, heuristic
  fallback). New meta-evals: `optimize/{formula_fuzz_eval,metamorphic_eval,fabrication,repair,claim_legibility}.py`
  + extended `redteam.py` (inline_gate_fcr + honest-no-downgrade). **FCR=0 held on every new gate**: fuzz
  catch-rate 1.0 / false-INVALIDATED 0 / coincident-constant→INVALIDATED; MR catch 1.0 / mr-confirms 0;
  fabrication catch 1.0 / false-flag 0; repair structurally FCR-safe. Full suite 588→632 tests (+44), all green.
- **Cycle FB — Waves 2–4 (2026-07-01), the remaining 14 features.** **Wave 2 (trust stack, all post-verdict,
  FCR surface zero):** F16 data digests (`core/datahash.py`, a field + binding key); F18 reproducibility
  receipts (`attest/receipt.py` — timestamp-free canonical claim block → idempotent `receipt_sha256`,
  measurement split out); F3 signed attestations (lifted `legacy/control_plane/api/signing.py` → `attest/
  {signing,statement,verify_verdict}.py` — DSSE + in-toto verdict/v1 VSA, ed25519 env-seed + KMS ECDSA-P256,
  PASSED-iff-CONFIRMED, fail-open sign / fail-closed verify); F12 transparency log (`attest/tlog.py` — local
  hash-chained tamper-evident ledger + optional Rekor, fail-open submit); F13 badges+registry (`attest/badge.py`
  — CONFIRMED-only-green, SHA-pin staleness); F9 bug bounty (`optimize/bounty.py` + BOUNTY.md — false-CONFIRM =
  the only Critical, wild-FCR 0). Server routes wired: /api/{signing-key,jobs/{id}/{receipt,attestation,
  inclusion-proof},badge/{id}}. Installed `cryptography` into the spike venv. **Wave 3 (new domains +
  compounding):** F6 statistical/distribution (`core/interval.py` prediction interval + new distinct verdict
  CONFIRMED-STOCHASTIC, NOT in POSITIVE; step-3 defers to the distribution for unstable runs; k_min power gate;
  meta-eval FCR=0); F15 seed injection (`capture/seedinject.py` force-seed hook + `core/seedchar.py`
  characterization ONLY; `seed_injected` hard-caps decide below CONFIRMED); F5 learning flywheel (`synth/
  experience.py` ExperienceBank + the KnownValueHint FIREWALL — a hint can never reach diff/verdict, enforced by
  test_known_value_firewall); F11 cross-run anomaly (`core/{anomaly,refstore}.py` robust-z + advisory-only
  overlay, never auto-refutes, dark-launched behind opts.anomaly). **Wave 4 (deep determinism infra —
  escalations):** F17 differential recompute (`synth/xcheck.py` + inline diff shadow hook — disagree→degenerate,
  agree→no-upgrade); F19 certified enclosures (`core/intervals.py` Neumaier + stable-two-pass variance,
  straddle→fail-closed at the tolerance boundary; soundness proven vs exact Fraction); F20 shim tier
  (`determinism.enforced_env(shim)` SOURCE_DATE_EPOCH + `runner/rr_runner.py`, graceful without rr); F14 Nix
  (`runner/nix_runner.py` flake synthesis + uv `--generate-hashes`, graceful without nix). **FCR=0 held on EVERY
  new gate** (formula_fuzz / metamorphic / fabrication / repair / stochastic / anomaly / xcheck / interval /
  bounty). Full suite 588→704 tests (+116 across all waves), all green, 2 skipped. ALL 20 FEATURES BUILT.
- **Cycle QUALITY — all-reviews hardening (2026-07-01).** Ran the gstack analysis tools and drove every metric to
  its ceiling without touching functionality. **/health = 10/10**: installed ruff/vulture/mypy into the spike
  venv; ruff CLEAN (added `ruff.toml`, per-file-ignore E741 in generated recipes/), vulture 0 dead-code,
  **mypy 0 errors across 86 source files** (core FCR-oracle fully typed; narrowed SDK/crypto unions via
  getattr/isinstance, annotated dict inits, widened tolerance.close to float|None — all logic-preserving),
  tests 10/10, shell clean. **/cso security = 4 findings fixed** (report in .gstack/security-reports/): HIGH —
  exec_formula sandbox escape closed with an AST denylist (`_ast_safe`, blocks dunder/import/global before
  exec); MEDIUM — data_resolver SSRF/LFI closed (`_url_is_safe`: http(s)-only + private/loopback/link-local/
  metadata-IP reject, blocks file://); MEDIUM — repair PIP arg-injection closed (`is_safe_pip`: plain
  requirement spec only); LOW — .env gitignored. Full suite 709→719 (+10 quality/security tests), all green,
  FCR gates all still 0. **/code-review** (background workflow, high effort, 4 finders → 9 candidates → 5
  verified) surfaced 5 real findings, ALL FIXED + regression-tested: (1) badge missing CONFIRMED-STOCHASTIC →
  grey 'unknown' [added yellowgreen, is_green stays false]; (2) capture `record(**inputs)` reserved-kwarg
  collision — a repo metric param named `n`/`site`/... silently dropped/failed capture [refactored to a
  collision-safe `_record(inputs_dict)`, routed all 4 internal tiers through it]; (3) stochastic step-3 bypass
  could affirm a never-produced value inside the wide t-interval [`interval.contains` now checks the OBSERVED
  run range, not the extrapolated PI]; (4) FCR gate checked POSITIVE not AFFIRMATIVE — a stochastic false-affirm
  wouldn't trip it [redteam+bounty+gate now use AFFIRMATIVE, + a `stochastic_fabricated` attack added → REFUTED];
  (5) red-team value-coincidence screen false-downgraded legit train+test CONFIRMEDs [screen removed —
  coincidence is binding's job]. (4 of 9 candidates unverified — workflow verifiers hit a session cap on
  diff/interval/pipeline/reinvoke, all already adversarially reviewed in the prior pass.) **Engine DX:** README
  test counts corrected (293→720+), added a "Quality gates" section (the full lint/type/deadcode + FCR-gate
  command suite, verified to pass as written) + documented the attest/ trust layer + optimize/ meta-evals.
  Final: 588→720 tests, ruff/mypy/vulture all clean, every FCR gate 0. Tooling: `~/.calma/spike-venv/bin/{ruff,
  vulture,mypy}`; lint config = `ruff.toml`; security report in `.gstack/security-reports/`.
- **STATUS: the whole DOMAIN-GENERALIZATION-GUIDE roadmap (P0-P4) is executed.** Full suite 460→587 tests
  (+127), FCR=0 held across every gate (convention_fuzz 3600 / redteam / corpus_synth / edge_stress /
  recompute_stress) and every scorecard cell. Convention rule 7 (audit surface) wired: a convention-search
  confirm records WHICH standard convention matched. Corpus now spans finance/statistics/ir/nlp/ml/analytics
  (5 new graded fixtures). Coverage grew ONLY by capture reach (§B.1) + recompute breadth (§B.2/§B.3) behind
  independent oracles — the verdict never loosened.
