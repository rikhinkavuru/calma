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
