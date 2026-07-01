# Calma — Domain-Generalization Guide

**A SOTA methodology for (A) building a multi-domain evaluation corpus that measures and drives verification
quality per domain, and (B) closing the three honest capture/recompute limits — while holding the sacred
invariant FCR = 0 (zero false-confirms).**

Date: 2026-07-01 · Audience: Calma engineering · Status: research-backed design doc, not yet implemented.

> Anchors in this repo: capture shim `spike/capture/calma_capture.py`; trusted recompute
> `spike/core/catalog.py` + `spike/core/diff.py`; convention grid `catalog.CONVENTIONS`; synth flywheel
> `spike/synth/formula.py` + `spike/synth/store.py`; AI planner `spike/planner.py`; corpus `spike/repos.yaml`;
> runners `spike/runner/local_runner.py` + `spike/runner/e2b_runner.py`. The Phase-0 go/no-go
> (`spike/results/GO-NO-GO-corpus-2026-06-29.md`) is the baseline this guide grows from.

---

## Executive summary

Calma today is proven on one narrow slice — CPU-only sklearn classification (iris, breast-cancer) — where
reproduction ran at 80%, binding at 58%, and false-confirms at **0/12**
(`spike/results/GO-NO-GO-corpus-2026-06-29.md`). The bet holds on unauthored code, and every failure fails
*closed*. The task now is to make that bet hold across finance/quant, statistics/econometrics,
information-retrieval / LLM-evals, NLP generation, deep learning, and genomics — and to *measure* it per
domain so we can drive each frontier without ever risking the franchise.

Two workstreams:

- **Part A — the corpus.** Adopt the construction discipline of the strongest execution-based benchmarks
  (SWE-bench and its automated descendants, ResearchCodeBench, the ML Reproducibility Challenge, NCBench):
  central-claim focus, difficulty stratification, freshness-based decontamination, held-out + adversarial
  splits, and an automated sourcing pipeline where GitHub search proposes and the AI planner triages. Grow
  from ~10 ML repos to ~180 repos across six domains in four phases, tracking a fixed per-domain scorecard
  (reproduction / capture / binding / verdict-accuracy / **FCR=0** / verdict distribution).

- **Part B — the limits.** (1) Close the `__main__` capture gap with a three-tier capture ladder led by
  `sys.monitoring` (PEP 669) and an AST-rewrite fallback, run under `runpy.run_path(run_name="__main__")` —
  no repo-source mutation, near-zero overhead, cannot change the numbers. (2) Generalize convention-search
  from a Sharpe special-case into a small, *cited*, size-capped convention registry spanning the finance and
  statistics grids, with FCR-safety enforced by keeping grids to documented-standard settings and tight
  tolerances. (3) Productionize the LLM-synthesized-recompute path behind the existing validation oracle
  (`_validate_synth`), extend it to NLP generation metrics via the reference libraries as oracles + a
  tokenization/smoothing convention search, and **fail closed to REPRODUCED-ONLY** for learned/embedding
  metrics (BERTScore/BLEURT/COMET) that cannot be independently recomputed.

The through-line: **coverage grows by adding capture reach + recompute breadth, never by loosening the
verdict.** Every new domain, convention, and synthesized formula is gated by an independent oracle, and the
corpus's adversarial/negative split is the standing proof that FCR stays 0.

---

# Part A — The multi-domain evaluation corpus

## A.1 What SOTA execution-based corpora teach us

Calma's corpus is not an ML *training* set; it is a **measurement instrument for a verifier**. The closest
prior art is execution-based benchmark construction, and five lessons transfer directly.

**1. A handful of popular repos is a distributional trap.** SWE-bench's influence came with a warning: its
original design leaned on ~12 popular Python libraries, and follow-up work shows that measuring on so few,
popularity-selected repos produces a *distributional mismatch* — "the measured performance may not be
representative of real-world scenarios" — with up to **60% lower agent success** once you broaden to
hundreds of repos with lower-quality issue descriptions and higher fix complexity
([Automated Benchmark Generation for Repository-Level Coding Tasks / SetUpAgent](https://proceedings.mlr.press/v267/vergopoulos25a.html)).
Calma's iris-heavy corpus is exactly this trap in miniature: seeded `load_iris` + LogisticRegression is the
*easiest* possible verification target (tiny, deterministic, one library call). Our 58% binding number is
optimistic precisely because the corpus is easy.

**2. Automate sourcing; filter with an LLM judge; keep humans for the oracle.** The scalable benchmarks all
converged on the same pipeline shape — programmatic sourcing → automated environment synthesis → oracle
extraction → LLM-judge quality filter. SWE-rebench harvests 21k+ tasks via an interactive setup agent and
"filters unsound instances using an ensemble of LLM judges, validated against human-verified annotations"
([SWE-rebench](https://arxiv.org/pdf/2505.20411)); SWE-Bench++ turns live PRs into "reproducible,
execution-based tasks via four stages: programmatic sourcing, environment synthesis, test oracle extraction,
and quality assurance" across 11 languages
([SWE-Bench++](https://arxiv.org/html/2512.17419)); daVinci-Env / SetUpAgent build the environment with an
*iterative* agent that "inspects the repository to infer dependencies, Python constraints, and test entry
points ... then executes and validates ... and refines the artifacts by providing concise failure diagnoses
and repeating the loop" ([daVinci-Env](https://arxiv.org/pdf/2603.13023v2)). **Calma already owns three of
the four stages** — `planner.py` is the environment-synthesis agent, `discovery` is oracle (claim)
extraction, and the runner is the execution harness. The missing piece is the *sourcing + triage* front
door (§A.6).

**3. Freshness is the decontamination lever.** ResearchCodeBench dates every repo's first/last commit
against model knowledge cutoffs and reports a "contamination-safe subset" — "thirteen of the twenty
repositories began after the latest known model cutoff ... strong evidence that the majority of tasks were
unseen during pretraining" ([ResearchCodeBench](https://researchcodebench.github.io/)). This matters for
Calma because the planner is an LLM: if the corpus repo predates the planner model's cutoff, the planner may
"know" the entrypoint/deps from memorization rather than from reading the repo, inflating reproduction rate.
Pin every corpus repo to a commit SHA (we already do in `repos.yaml`) *and* record its commit date; maintain
a **post-cutoff held-out slice** the planner has provably never seen (§A.5).

**4. Reproducibility is not binary; score the central claim, per-claim.** The ML Reproducibility Challenge's
hardest-won lesson: "whenever we talk about a paper to be reproducible, the expectation is this binary
property — yes or no. However, the reality is way more nuanced" — so from 2020 they scoped the challenge to
the *central claim* and introduced a structured Reproducibility Summary
([Announcing MLRC 2023](https://reproml.org/blog/announcing_mlrc2023/);
[MLRC 2020 report](https://doi.org/10.5281/zenodo.4833117)). Calma's seven-way verdict
(CONFIRMED / REFUTED / INVALIDATED / REPRODUCED-ONLY / NON-DETERMINISTIC / INCONCLUSIVE / DISCOVERED) is
already this nuanced view mechanized. The corpus must therefore be labeled *per claim*, not per repo — which
`repos.yaml` supports (`claims:` with a per-claim `expect`).

**5. Continuous, stratified re-evaluation is the maintenance model.** In genomics, NCBench is "implemented as
a continuously re-evaluated open-source repository" that reports recall/precision "stratified by read
depth/coverage category," relying only on GitHub Actions + Zenodo
([NCBench, F1000Research](https://f1000research.com/articles/12-1125);
[PubMed](https://pubmed.ncbi.nlm.nih.gov/39345270/)). The takeaway for Calma: the corpus is a living CI
asset, re-run on every engine change, with results *stratified by domain and difficulty* — not a one-shot
spreadsheet.

## A.2 Selection criteria (the intake rubric)

Every candidate repo is scored on these axes before admission. Encode them as machine-checkable fields on
each `repos.yaml` entry so intake is auditable and the corpus is describable as a distribution, not a list.

| Axis | What to require | Why it matters for a *verifier* corpus |
|---|---|---|
| **Self-containedness** | Data is bundled, synthesized in-repo, a library dataset (`load_*`), or fetched from one stable public URL. No private data, no auth, no >1GB downloads. | Non-self-contained repos test our data-connect plumbing, not our verify logic. Keep them to a small, tagged `data-connect` sub-track. SWE-bench-style corpora bundle everything into a reproducible image for exactly this reason ([SWE-bench](https://github.com/SWE-bench/SWE-bench)). |
| **Determinism** | Prefer seeded/deterministic. But *deliberately include* unseeded repos (RandomForest w/o `random_state`) — they are the NON-DETERMINISTIC verdict's test cases (e.g. current `breast-cancer-rf`). | The verifier must *detect* non-determinism, so the corpus needs both. Determinism is a per-claim label, not an admission filter. |
| **Dependency weight** | Tag `light` (stdlib+numpy), `medium` (sklearn/pandas/scipy), `heavy` (torch/tf/transformers), `native` (R/Julia/C++, compiled genomics tools). | Dep weight is the dominant driver of reproduction cost and failure. Stratify metrics by it so a low genomics reproduction rate isn't blamed on verify logic when it's really an install failure. |
| **Licensing** | Record SPDX license. Prefer permissive (MIT/BSD/Apache-2.0). **Never redistribute repo contents**; store only `{url, commit_sha}` and clone at run time. | SWE-bench itself is MIT but *mirrors* task repos rather than absorbing them; benchmark *tooling* license ≠ underlying repo license ([SWE-bench collection](https://github.com/swe-bench/SWE-bench/blob/main/swebench/collect/README.md)). Reference-by-SHA keeps us clean of derivative-distribution issues ([Stop Uploading Test Data in Plain Text](https://arxiv.org/html/2305.10160v2)). |
| **Claim density** | ≥1 machine-extractable reported number (README %, printed line, committed `results.json`/table). Prefer 2–5 claims/repo. | Claim density is throughput: one clone yields N verify tests. But avoid *only* high-density repos — GridSearchCV repos emit 30+ per-fold numbers (`iris-codealpha`) that are ambiguity stress-tests, not easy wins. |
| **Domain coverage** | Tag the domain + metric family. Enforce a *target distribution* (§A.6), not opportunistic collection. | Prevents the iris trap. The corpus should be describable as "N per domain × M difficulty tiers." |
| **Difficulty stratification** | Assign a tier `T1..T4` at intake (below) and, later, an *empirical* difficulty from measured outcomes. | ResearchCodeBench defines a HARD subset as "the bottom 50% by aggregate pass rate" ([ResearchCodeBench](https://proceedings.neurips.cc/paper_files/paper/2025/file/cd0d0a873cc3e601c76f46dccc3d4c5f-Paper-Datasets_and_Benchmarks_Track.pdf)). We want the analog: a HARD slice that keeps the engine honest. |

**Difficulty tiers (a priori, refined by measurement):**

- **T1 — trivial:** single library metric call, seeded, light deps, one printed number (today's iris repos).
  *Purpose: regression floor. Must stay ~100%.*
- **T2 — standard:** custom metric function (planner "target"), or `.score()`-style, or a committed
  predictions artifact; medium deps. *Purpose: the real product surface — drives binding + capture.*
- **T3 — hard:** multi-candidate metrics (GridSearchCV, multi-model scripts), hand-rolled numeric metrics
  with no library call, convention-sensitive metrics (Sharpe), `__main__`-defined metrics, subprocess-per-cell.
  *Purpose: the honest-limits frontier (Part B).*
- **T4 — adversarial / negative:** deliberately fabricated, leaked, trivial-baseline, or non-deterministic
  claims where the *correct* verdict is REFUTED / INVALIDATED / NON-DETERMINISTIC / INCONCLUSIVE.
  *Purpose: the standing FCR=0 proof. A false CONFIRM here is a P0 regression.*

## A.3 Per-domain playbook

For each domain: where to source, the canonical metrics (what our catalog/recipes must recompute), and what
makes verification *hard* — i.e. which Part-B capability it exercises.

### Finance / quant
- **Sources:** GitHub topics `quant-finance`, `backtesting`, `algorithmic-trading`; single-file
  strategy/backtest demos; libraries' own example scripts (`quantstats`, `pyfolio`, `empyrical`, `vectorbt`,
  `bt`, `ffn`). Prefer repos with a synthetic or bundled price series so they're self-contained.
- **Canonical metrics:** Sharpe, Sortino, Calmar, Information ratio, max drawdown, CAGR, volatility, alpha,
  beta, VaR/CVaR, Treynor, Omega. (Many already in `recipes/`.)
- **What's hard — and this is the crux:** these are **convention-sensitive** (§B.2). The same returns series
  yields a Sharpe of 0.8 or 12.7 depending on annualization (√252 vs none) and ddof (0 vs 1), and the repo's
  choice "is buried in its own code (`* np.sqrt(252)`, `np.std` default ddof=0) and isn't captured"
  (`catalog.py` comment). A single-convention recompute *falsely disagrees* with a correct number. Finance
  is the domain that forces convention-search to grow up. It's also heavily `__main__`-defined (a
  `sharpe_ratio(returns)` helper in the script) → forces §B.1.

### Statistics / econometrics
- **Sources:** `statsmodels` examples, `scipy.stats` demos, textbook-companion repos (regression, hypothesis
  testing, A/B analysis), econometrics course repos.
- **Canonical metrics:** p-values, t/F/chi-square statistics, confidence intervals, effect sizes (Cohen's d),
  correlations (Pearson/Spearman/Kendall), R²/adjusted-R², OLS coefficients, ANOVA tables, Mann-Whitney/
  Fisher-exact.
- **What's hard:** the **ddof / sample-vs-population** split — "the classic numpy (`ddof=0`) vs pandas
  (`ddof=1`) discrepancy" — plus one/two-tailed p-value conventions, and correlation *type* ambiguity
  (a repo says "correlation = 0.83"; is it Pearson or Spearman?). Spearman is already in the synth registry
  (`formula.py` `_SPEARMAN`, validated vs `scipy.stats.spearmanr`); the general lesson is that many stats
  metrics need a *type/convention* disambiguation, not just a formula.

### Information retrieval / LLM-evals
- **Sources:** `pytrec_eval`, `ranx`, `ir_measures`, `beir`, `pyserini`, `ragas`, LLM-eval harness repos;
  RAG/retrieval demo repos that print nDCG/MRR/recall@k. Reference truth: TREC-style qrels.
- **Canonical metrics:** nDCG@k, MRR, MAP, recall@k, precision@k, Hit@k, R-precision; LLM-eval: pass@k,
  exact-match, F1 (SQuAD-style), win-rate.
- **What's hard:** the **reference-implementation divergence**. `trec_eval` is the community standard;
  `ranx` states "the metrics have been tested against TREC Eval for correctness"
  ([ranx](https://amenra.github.io/ranx/)) and `pytrec_eval` exists explicitly "to stop the cultivation of
  custom implementations of IR evaluation measures" ([pytrec_eval](https://github.com/cvangysel/pytrec_eval)).
  There are *multiple* nDCG formulas (Järvelin vs Burges log-discount) and k-cutoff conventions
  (`ndcg_cut` at k ∈ {5,10,15,20,30,100,...}), plus real bugs — e.g. an empty-qrels query makes
  `pytrec_eval` return **NDCG > 1**
  ([pytrec_eval #57](https://github.com/cvangysel/pytrec_eval/issues/57)). So IR needs a *reference-library
  oracle* (validate our recompute against `pytrec_eval`/`ranx`) plus a small convention grid over the nDCG
  variant + k. This is the same machinery as §B.2/§B.3.

### NLP generation
- **Sources:** `sacrebleu`, HuggingFace `evaluate`, `rouge-score`, `nltk` translate/summarization examples;
  MT/summarization demo repos reporting BLEU/ROUGE.
- **Canonical metrics:** BLEU / sacreBLEU, ROUGE-{1,2,L}, METEOR, chrF/chrF++, TER; embedding/learned:
  BERTScore, BLEURT, COMET.
- **What's hard:** these are **not pure functions of numeric arrays** — they depend on tokenization, casing,
  smoothing, n-gram order, stemming, and (for learned metrics) an exact model checkpoint. "BLEU scores can
  vary greatly depending on which parameters are used ... especially when different tokenization and
  normalization techniques are used" ([HF evaluate BLEU](https://github.com/huggingface/evaluate/blob/main/metrics/bleu/README.md)),
  which is why sacreBLEU emits a reproducibility signature like
  `BLEU|nrefs:1|case:mixed|eff:no|tok:13a|smooth:exp|version:2.0.0`
  ([sacrebleu](https://github.com/mjpost/sacrebleu)). This is the domain that forces §B.3 (LLM-synth +
  convention search over tok/smooth) and the "fail closed on learned metrics" rule.

### Deep learning
- **Sources:** PyTorch/Keras example repos, small CNN/MLP training demos with a reported test accuracy/loss,
  fine-tuning tutorials. Keep to CPU-runnable or small-GPU; use CPU wheels (`build.cpu_pip_args` already
  swaps `torch` → CPU wheel).
- **Canonical metrics:** accuracy, top-k accuracy, F1, AUROC, perplexity, loss values, mAP (detection).
- **What's hard:** **non-determinism and cost.** GPU nondeterminism (cuDNN, atomic adds), dataloader
  shuffling without seeds, and long/ heavy installs. Most DL claims will land NON-DETERMINISTIC or
  REPRODUCED-ONLY, and that is the *correct* verdict — the corpus must reward the engine for saying so, not
  penalize it. This domain primarily stresses reproduction + the determinism gate + heavy-build handling
  (already partly addressed: adaptive-k, uv installer, CPU wheels).

### Genomics / bioinformatics
- **Sources:** `scikit-bio`, `biopython`, `pysam` example scripts; small variant-calling-eval or
  expression-analysis demos; **nf-core** pipelines for the truth-set methodology (as a design reference,
  not necessarily runnable in our tier).
- **Canonical metrics:** precision/recall/F1 over variant sets (TP/FP/FN vs a truth set), AUROC/AUPRC for
  classifiers, sensitivity/specificity, concordance; stratified by region/coverage.
- **What's hard:** **truth-set matching semantics and stratification.** In variant calling, "precision and
  recall" hinge on *how a called variant is matched to a truth variant* (RTG `vcfeval` normalization,
  atomization, region intersection) — NCBench reports two different TP counts (`TPquery` vs `TPtruth`)
  because "the same variant in the truthset [may be] predicted multiple times"
  ([NCBench](https://f1000research.com/articles/12-1125)) — and GA4GH best practice is to stratify by genomic
  context ([nf-core/variantbenchmarking usage](https://github.com/nf-core/variantbenchmarking/blob/1.5.0/docs/usage.md)).
  Even undergraduates running the *same* SEQC2 data get wildly different precision/recall due to
  environment/install heterogeneity
  ([PLOS Comp Bio 2025](https://journals.plos.org/ploscompbiol/article?id=10.1371%2Fjournal.pcbi.1013552)).
  For Calma this means genomics is a **native-deps + non-trivial-matching** domain: start with the
  numeric-metric-from-a-committed-predictions-file cases (recompute precision/recall from a committed
  TP/FP/FN or a predictions CSV via `core/artifacts.py`), and treat full pipeline reproduction as a later,
  tagged sub-track.

## A.4 The per-domain scorecard (what to track, and the one line that can never move)

Extend `spike/optimize/SCOREBOARD.md` into a **matrix: metric × domain × difficulty tier.** For each cell:

1. **Reproduction rate** — fraction of repos whose entrypoint ran and produced the claimed number's context.
   (Floor target ≥ 60%; stratify by dep-weight so install failures are visible.)
2. **Capture rate** — fraction of *ran* claims where the metric computation was intercepted (inputs
   recorded). This is the number §B.1 moves.
3. **Binding rate** — fraction of captured claims unambiguously bound to *the* headline computation. This is
   the number §B.1's disambiguation + auto-binding moves (58% baseline).
4. **Verdict accuracy** — on the hand-graded subset, fraction where Calma's verdict == the graded truth.
5. **False-confirm count — MUST BE 0.** Across every claim whose graded truth is *not* CONFIRMED, the number
   Calma marks CONFIRMED. **This is a hard gate, per-domain and global. A single false-confirm anywhere is a
   P0 that blocks release.** It is not a rate to optimize; it is an invariant.
6. **Verdict distribution** — the histogram of the seven verdicts per domain. A healthy corpus produces a
   *spread*; if a domain is 100% REPRODUCED-ONLY, our recompute catalog doesn't cover it yet (a coverage
   signal, not a bug).

Report each cell as `n = <count>` alongside the rate — MLRC's discipline of never collapsing to a single
pass/fail applies to *our* reporting too. Small-n cells (verdict accuracy at n=1 today) get a confidence
caveat and a "grow this" flag.

**Why FCR is modeled as an invariant, not a metric:** every other number trades off against effort and
coverage; FCR does not trade off against anything. The architecture already enforces this structurally — the
verdict comes from an *independent* recompute + three-way diff, the binder refuses (INCONCLUSIVE) rather than
guess, and `catalog._degenerate` fails closed. The corpus's job is to *continuously falsify* the claim that
FCR=0, via the T4 adversarial split (§A.5).

## A.5 Avoiding corpus overfit

A verifier that is tuned until it's green on a fixed corpus has learned the corpus, not verification. Four
defenses, borrowed from the contamination literature:

**1. Held-out split.** Partition every domain into `dev` (engine authors see failures, tune against them)
and `test` (locked; only run on release candidates; failures are never used to tune). Never let a heuristic
be written against a `test` repo. This is the basic anti-overfit hygiene the LLM-eval community now treats as
mandatory ([Stop Uploading Test Data in Plain Text](https://arxiv.org/html/2305.10160v2)).

**2. Post-cutoff freshness slice.** Because the planner is an LLM, maintain a slice of repos whose commit
date is *after* the planner model's knowledge cutoff, so the planner cannot have memorized their
entrypoint/deps. Compare reproduction rate on pre- vs post-cutoff repos; a large gap means the planner is
leaning on memorization (as ResearchCodeBench found: "all models suffer a consistent drop" on the
contamination-safe subset ([ResearchCodeBench](https://researchcodebench.github.io/))). This is Calma's
analog of decontamination — and note the broader warning that *soft* (semantic) contamination evades n-gram
filters, so freshness-by-date is the robust lever, not string-dedup
([Soft Contamination Means Benchmarks Test Shallow Generalization](https://arxiv.org/pdf/2602.12413)).

**3. Adversarial / negative examples (the FCR proof).** The T4 tier must be large and *diverse* — for every
domain, hand-construct claims that are:
   - **Fabricated** (a plausible-but-wrong number the code never produces) → expect REFUTED.
   - **Leaked** (a real number computed on a train/test-contaminated split) → expect INVALIDATED (the
     validity overlay in `diff.py`/`core.validity` already does this for committed splits).
   - **Trivial-baseline** (accuracy == majority-class rate; Sharpe of a buy-and-hold) → expect INVALIDATED.
   - **Convention-mismatched** (a *correct* Sharpe under √252 that our default recompute disagrees with) →
     expect CONFIRMED *only after convention-search* — this doubles as the §B.2 test.
   - **Non-deterministic** (unseeded) → expect NON-DETERMINISTIC.
   - **Coincidental** (a fabricated value that happens to equal a standard-convention output on the specific
     inputs) → expect REFUTED; this is the sharpest FCR test for §B.2, and must be fuzzed, not hand-picked.
   The synthetic fixtures in `repos.yaml` (`misreported`, `trivial_baseline`, `custom_metric_invalid`,
   `nondeterministic`, `two_splits`) are the seed of this tier — grow them to *per-domain* negatives.

**4. Refresh cadence.** Add a fresh cohort each quarter (new post-cutoff repos), retire/flag repos that
break (upstream force-push, dependency yank), and re-run the *whole* corpus on every engine change as CI —
the NCBench continuous model ([NCBench](https://pubmed.ncbi.nlm.nih.gov/39345270/)). Track metric *deltas*
per release; a drop in any cell is a regression, a rise in FCR is a P0.

## A.6 The phased growth plan (~10 → ~180 repos)

**Sourcing pipeline (automate stage 1, keep humans for the oracle):**

```
GitHub/Exa search  ──►  cheap pre-filters  ──►  AI-planner triage  ──►  dry-run  ──►  human label  ──►  repos.yaml
(topic+lang+size)      (license, size,          (planner.py:            (run k=1,     (T-tier +          ({url, sha,
                        single-entry, has         entrypoint+deps+        did it run?    expect per         domain, tier,
                        a reported number)        targets resolvable?)    captured?)     claim; dev/test)   license, date})
```

- **Stage 1 — search.** GitHub code/repo search by domain topic + language + size bound + "has a README
  number" heuristic (regex for `\d+\.\d+%|accuracy|sharpe|ndcg|bleu|precision`). This is the
  "programmatic sourcing" stage every scalable benchmark automates
  ([SWE-Bench++](https://arxiv.org/html/2512.17419)).
- **Stage 2 — cheap filters.** SPDX license present + permissive; repo < ~50MB; a single plausible entrypoint;
  self-contained data; ≥1 extractable number. Cuts the long tail before spending LLM tokens.
- **Stage 3 — planner triage (the key reuse).** Run `planner.py` on each survivor. The planner already
  returns entrypoint + pip deps + python version + **targets** (custom metric functions). Use its output as
  a *triage signal*: if the planner returns an empty entrypoint ("a wrong guess is worse than none," per its
  system prompt), or can't resolve any target for a non-sklearn domain, deprioritize. This mirrors the
  LLM-judge filter that SWE-rebench uses to drop unsound instances
  ([SWE-rebench](https://arxiv.org/pdf/2505.20411)) — except we already built the judge.
- **Stage 4 — dry-run.** One `k=1` run in the sandbox. Did it run? Did anything get captured? Auto-record
  the outcome into the couldn't-reproduce taxonomy. This is exactly the SetUpAgent "execute and validate,
  then refine" loop ([daVinci-Env](https://arxiv.org/pdf/2603.13023v2)).
- **Stage 5 — human label.** A human assigns the difficulty tier, the per-claim `expect` verdict for the
  graded subset, and the dev/test split. Humans are the *oracle*, never the *sourcer* — the expensive,
  reliable step, kept small.

**Target distribution (steady state ≈ 180 repos):**

| Domain | dev | test | of which T4 (adversarial) | Primary capability driven |
|---|---|---|---|---|
| ML classification/regression | 15 | 10 | 6 | regression floor (T1) |
| Finance / quant | 15 | 10 | 8 | convention-search (§B.2) + `__main__` (§B.1) |
| Statistics / econometrics | 12 | 8 | 6 | ddof/type conventions (§B.2) |
| IR / LLM-evals | 12 | 8 | 5 | reference-oracle + k/variant conventions |
| NLP generation | 12 | 8 | 6 | LLM-synth + tok/smooth conventions (§B.3) |
| Deep learning | 10 | 6 | 3 | determinism gate + heavy build |
| Genomics | 8 | 5 | 3 | native deps + artifact-recompute |
| **Total** | **84** | **55** | **37** | |

**Phasing:**

- **Phase 1 (now → +2wk): instrument + stratify what exists.** Add the `domain / tier / license /
  commit_date / split` fields to `repos.yaml`; build the metric×domain×tier scorecard; re-classify the 10
  existing repos (all `ML / T1-T3 / dev`). Deliverable: the measurement instrument, even before new repos.
- **Phase 2 (+2 → +5wk): finance + statistics (the convention frontier).** ~25 repos + their adversarial
  negatives. Land §B.2 convention registry against this cohort. Success = Sharpe/Sortino/correlation repos
  reaching CONFIRMED under convention-search with **0 false-confirms on the coincidental-value fuzz set.**
- **Phase 3 (+5 → +9wk): IR + NLP (the recompute-breadth frontier).** ~24 repos. Land §B.3 (reference-oracle
  synth + tok/smooth convention search) and the learned-metric fail-closed rule. Success = BLEU/ROUGE/nDCG
  repos CONFIRMED under a matched signature; BERTScore/BLEURT correctly REPRODUCED-ONLY.
- **Phase 4 (+9 → +14wk): deep learning + genomics (the reproduction frontier) + sourcing automation.**
  ~19 repos + turn the Stage 1–4 pipeline into a standing script so the corpus self-refreshes. Success =
  the quarterly-refresh loop runs unattended to Stage 4 and only queues Stage-5 human labels.

Grow **capture reach and recompute breadth**, never the corpus's easiness. A rising binding rate is only
meaningful if the corpus difficulty distribution held or hardened.

---

# Part B — Fixing the honest limits

## B.1 The `__main__` capture gap

### The precise failure

The runner executes the entrypoint as a subprocess: `subprocess.run([python, *entry])` in
`local_runner.run_local()` (and the same shape in `e2b_runner`). Capture arms at interpreter startup via
`capture/sitecustomize.py` on `PYTHONPATH`, so a repo's `from sklearn.metrics import accuracy_score` binds to
our already-wrapped function — this is why **library-sink capture works**.

Custom (non-library) metrics go through `calma_capture.install_targets(specs)`, which does:

```python
mod = importlib.import_module(mod_name)   # e.g. "metrics" for target "metrics.sharpe_ratio"
orig = getattr(mod, attr)
setattr(mod, attr, wrapper)               # patches the IMPORTED module object
```

This works when the target lives in an *imported* module (`from metrics import sharpe_ratio`). It **fails**
when the metric is **defined and called in the entrypoint's own `__main__`**: running `python train.py`, the
executing script's globals *are* `sys.modules["__main__"]`, but `import_module("train")` (or any
non-`__main__` name) returns a **different module object**. Patching that second object never touches the
function the running `__main__` actually calls. The Phase-0 `digits-softmax` miss is the value-recompute
sibling of this (a hand-rolled numpy metric with no library call to hook at all).

Note a subtlety: you cannot fix this by `import_module("__main__")` either — that *does* return the running
module, but by the time `install_from_env()` runs (interpreter startup, before the script body executes),
the function isn't defined yet; and by the time it is defined, the call is imminent in the same straight-line
`__main__` code, so there is no safe "after def, before call" window to patch from the outside.

### The options, ranked

**Constraint that dominates the ranking: capture must not change the repo's numbers.** Anything that mutates
runtime values, alters control flow, or perturbs timing enough to move a throughput/latency metric is
disqualified. FCR=0 depends on capture being *observational*.

**① `sys.monitoring` (PEP 669) — RECOMMENDED PRIMARY (Python ≥ 3.12).**
Register a tool id, enable `PY_START` (and `PY_RETURN`) events, and in the callback check the executing code
object against the planner-identified targets (match `code.co_qualname` + `code.co_filename`); for every
non-target location, return `sys.monitoring.DISABLE` so that location is *never re-instrumented* — "disabling
events for specific locations is very important for high performance monitoring ... a program can be run
under a debugger with no overhead if the debugger disables all monitoring except for a few breakpoints"
([sys.monitoring docs](https://docs.python.org/3/library/sys.monitoring.html)). Capture the bound arguments
from the frame at `PY_START` (they're the function's locals: named args, not `arg0/arg1` — strictly better
than today's positional mapping) and the value at `PY_RETURN`.
   - *Why it wins:* (a) It observes calls **regardless of where the function is defined** — `__main__`,
     imported, or dynamically created — because it hooks the *code object's execution*, not a module
     attribute. (b) Near-zero overhead everywhere except the targets ("up to 20× faster than the old API,"
     and orders of magnitude cheaper than `settrace` for a few active locations
     ([PyCharm blog on PEP 669](https://blog.jetbrains.com/pycharm/2024/01/new-low-impact-monitoring-api-in-python-3-12/))).
     (c) **Per-interpreter, not per-thread** ([PEP 669](https://peps.python.org/pep-0669/)) — so it catches
     metrics computed in worker threads, which `settrace` silently misses. (d) It never mutates repo source
     → cannot change the numbers.
   - *Caveats:* 3.12+ only (need the fallback below for older repos); `sys.monitoring` is a namespace, not an
     importable module (`import sys; sys.monitoring...`); pick a tool id that won't collide (ids 6/7 are
     reserved for `settrace`/`setprofile`).

**② AST source-rewrite + `runpy.run_path(run_name="__main__")` — RECOMMENDED PORTABLE FALLBACK (all versions).**
Before execution, parse the entrypoint (and any planner-named *local* target modules) with `ast`, locate the
target `FunctionDef`(s) by qualname, and **append a capture decorator** to each (do not touch the body).
`ast.fix_missing_locations` + `ast.copy_location` to preserve line numbers, `compile`, then execute in a
`__main__`-named namespace via `runpy.run_path(entry, run_name="__main__")` (or `exec` of the compiled code
in a `{"__name__": "__main__"}` globals dict).
   - *Why `run_name="__main__"` is essential:* the metric is almost always computed inside the
     `if __name__ == "__main__":` block. Running the file as an imported module or via `-m` with a *different*
     run name **skips that block entirely** — you'd reproduce nothing. `runpy` runs "in a fresh module
     namespace" and its known limitation ("functions ... defined by the executed code are not guaranteed to
     work correctly after a runpy function has returned") is irrelevant to us because we capture *during* the
     run ([runpy docs](https://docs.python.org/3/library/runpy.html)).
   - *Why decorator-append, not body-rewrite:* the smallest possible transform. The function's semantics are
     untouched; only a wrapper observes args/return. Low, target-only runtime overhead.
   - *FCR guard (the belt-and-suspenders):* because this path *does* alter the source, add a **round-trip
     determinism check** — Calma already runs k≥2 for determinism; run at least one of those k as the
     *untransformed* source and assert the captured metric result equals the transformed run's produced
     value. If the AST transform perturbed the number, the results diverge → discard capture → fall back to
     INCONCLUSIVE/REPRODUCED-ONLY. Capture can never silently change a verdict.

**③ `sys.settrace` / `sys.setprofile` — fallback of last resort (pre-3.12, no-AST).**
Register a global trace/profile function; on `call` events whose frame matches a target, snapshot
`frame.f_locals`. `setprofile` (call/return only) is materially cheaper than `settrace` (which also fires per
line) and is the right choice for arg capture. *But:* it is **per-thread** (must be re-armed in every spawned
thread, and thread pools will slip through), and it imposes "an order-of-magnitude slowdown [on code that]
involves many sub-calls ... unacceptable for interactive workflows"
([Mandala on settrace](https://amakelov.github.io/mandala/blog/02_deps/);
[pythonspeed on profiling affordances](https://pythonspeed.com/articles/measuring-python-performance/)).
That slowdown can (a) blow wall-clock/timeout budgets and (b) *perturb any timing-derived metric*
(throughput, "2.3× faster") — which is a correctness risk, not just a speed one. Use only where ① and ② are
unavailable.

**④ Import hook (MetaPathFinder + AST transform on load) — COMPLEMENT, not a `__main__` fix.**
A meta-path finder that AST-wraps *target modules as they are imported* elegantly covers the
`from metrics import sharpe_ratio` case with one mechanism shared with ②. **But it does not intercept
`__main__`** run as `python script.py` / `run_path`: the `__main__` code object isn't loaded through the
import finder. So it's a clean upgrade for the *imported-target* path (a more robust version of today's
`install_targets`), and it composes with ② for `__main__`, but it cannot stand alone.

**⑤ `coverage.py`-style line tracing / bytecode rewriting — NOT RECOMMENDED for arg capture.**
Coverage cores are line/branch oriented (`ctrace`/`pytrace` via `settrace`, `sysmon` via `sys.monitoring`
([coverage.py how-it-works](https://github.com/coveragepy/coveragepy/blob/main/doc/howitworks.rst))); they
record *which lines ran*, not *what arguments a function received*. Ned Batchelder's bytecode-offset tracing
trick is explicitly fragile ("if the Python interpreter changes their line numbering mechanism, this
technique could be completely broken" ([Ned Batchelder](https://nedbatchelder.com/blog/200804/wicked_hack_python_bytecode_tracing))).
Highest overhead, lowest fit.

### Recommended design: a three-tier capture ladder, one sink

Keep the single JSONL sink (`calma_capture.record`) and the call-site provenance (`user_site`) that already
lets the binder collapse GridSearchCV's 31 internal calls to the one the repo made. Select the mechanism per
target:

```
Tier 0  library sinks (sklearn.metrics.*, ClassifierMixin/RegressorMixin.score)
        → keep today's import monkeypatch. Highest yield, zero overhead. UNCHANGED.

Tier 1  planner "targets" (custom metric fns), Python ≥ 3.12
        → sys.monitoring PY_START/PY_RETURN, filtered to target code objects, DISABLE elsewhere.
          Catches __main__-defined AND imported AND threaded. Reads named args from the frame.

Tier 1b imported targets on any Python version
        → keep/upgrade install_targets' import patch (or the ④ import hook). Already works for non-__main__.

Tier 2  __main__-defined targets on Python < 3.12, OR when monitoring can't resolve the code object
        → AST decorator-append + runpy.run_path(run_name="__main__") + round-trip determinism guard.

Fallback (rare)  sys.setprofile, target-filtered — only if Tier 1/2 both unavailable.
```

Wiring: `capture/sitecustomize.py` already reads `CALMA_CAPTURE_TARGETS`; branch on
`sys.version_info >= (3, 12)` to arm `sys.monitoring` (Tier 1) instead of the import patch for targets, and
have the runner choose Tier 2 (AST) when the planner marks a target as `__main__`-defined. **In every tier
the verdict still comes from independent recompute + three-way diff**, so a capture that is
wrong-but-plausible can only produce INVALIDATED/INCONCLUSIVE, never a false CONFIRM. The value-recompute
fallback for `digits-softmax`-style hand-rolled metrics is then just Tier 1/2 capturing the
`(y_true, y_pred)` arrays that the hand-rolled function received, which flow into the existing catalog
recompute.

## B.2 Convention-sensitive metrics

### The current state and the risk of growth

`catalog.CONVENTIONS` today holds exactly one entry — Sharpe, a 12-cell grid
(`periods_per_year ∈ {1, 252, 52, 12, 4, 365}` × `ddof ∈ {1, 0}`). `diff.diff_claim` runs it **only** when
the default recompute disagrees with the produced value, tries each convention against the *real captured
inputs*, and accepts the first that reproduces the produced value — recording *which* convention matched. The
FCR argument in the code is sound: "a fabricated value matches none of a small set of standard conventions."
The danger is entirely in **grid growth** — every convention you add is another chance for a fabricated or
buggy number to coincidentally match. So the design goal is: cover the real convention space *without*
letting the grid become a curve-fitter.

### The convention space to cover (finance + statistics)

Grounded in the standard references:

**Sharpe** — `(mean(excess) / stdev(excess, ddof)) × √periods_per_year`:
- **Annualization** `periods_per_year ∈ {1 (per-period), 252, 260, 250 (daily variants), 52 (weekly),
  12 (monthly), 4 (quarterly)}`. Ratios annualize by √ppy ([Composer](https://help.composer.trade/article/19-sharpe-ratio);
  [Quant Decoded](https://quantdecoded.com/en/the-sharpe-ratio-measuring-risk-adjusted-returns)).
- **ddof** `∈ {0 (population, numpy default), 1 (sample, pandas default)}`.
- **Risk-free handling** `∈ {0, a per-period constant}` — "the risk-free rate is expressed as a per-period
  figure matching the return frequency" ([Quantt](https://www.quantt.co.uk/resources/risk-adjusted-returns-guide)).
  **Do not** make `risk_free` a free search dimension (see FCR rules); take it from captured kwargs or the
  small fixed set `{0}`.
- **Numerator mean** — arithmetic is standard; **geometric Sharpe is nonstandard and always lower** and must
  **not** be in the default grid ("some practitioners report 'geometric Sharpe' ... but it's nonstandard"
  ([QuantOracle geo vs arith](https://quantoracle.dev/compare/geometric-vs-arithmetic-vs-time-weighted-returns))).
  Add it only as an explicitly-flagged, opt-in convention.
- **Denominator base** — Sharpe strictly uses the stdev of *excess* returns, but many implementations use the
  stdev of *raw* returns (identical when `rf=0`). Both are common; include as a `{excess, raw}` axis only if
  the corpus shows it, and cap accordingly.

**Sortino** — `(mean(return) − target) / downside_deviation × √ppy`:
- **Target / MAR** `∈ {0, risk_free}`; **downside-deviation denominator** `∈ {N (all obs),
  N_downside (below-target count)}` — a genuine, common divergence. Sortino "uses downside deviation ...
  returns below a target threshold" ([Quantt](https://www.quantt.co.uk/resources/risk-adjusted-returns-guide);
  [Quant Decoded](https://quantdecoded.com/en/the-sharpe-ratio-measuring-risk-adjusted-returns)).

**Calmar** — `CAGR / |max_drawdown|`: numerator is **already annual → no √ppy**; the only real axis is the
drawdown sign/abs convention. "The numerator should already be a CAGR ... so no additional annualisation is
needed" ([Quantt](https://www.quantt.co.uk/resources/risk-adjusted-returns-guide)).

**Information ratio** — `mean(active) / stdev(active, ddof) × √ppy`: axes are `ddof ∈ {0,1}` and annualization.
Note the naming hazard — some sources equate IR with a Sharpe-of-active-returns; disambiguate by the presence
of a benchmark input ([Stanford / W. F. Sharpe](http://web.stanford.edu/~wfsharpe/art/sr/SR.htm)).

**Statistics:**
- **stdev / variance** `ddof ∈ {0 (numpy), 1 (pandas)}` — the single most common numeric discrepancy in the
  whole product.
- **Correlation type** `∈ {pearson, spearman, kendall}` — resolve by *type search*, treated like a
  convention: recompute all three, confirm only if exactly one reproduces the value (Spearman already lives
  in the synth registry).
- **p-value** `∈ {two-tailed, one-tailed}`; **R²** `∈ {plain, adjusted}`.

### How to keep it FCR-safe as the grid grows — a hard registry contract

Structure the registry declaratively and enforce it with tests:

```python
# spike/core/conventions.py  (proposed)
CONVENTIONS = {
  "sharpe": Convention(
     grid=[{"periods_per_year": p, "ddof": d} for p in (1,252,260,250,52,12,4) for d in (1,0)],
     sources=["composer.trade/...", "quantt.co.uk/...", "stanford/~wfsharpe/..."],  # every axis cited
     forbidden_free_params=["risk_free"],   # never fit a continuous parameter
     max_grid=24,                            # combinatorial cap
  ),
  # sortino, information_ratio, stdev, correlation, ...
}
```

Enforcement rules (each a CI test):

1. **Documented-standard only.** Every convention axis carries a citation. No arbitrary transforms; if it's
   not in a reference, it doesn't go in the grid. (The `catalog.py` comment already states this intent —
   "keep these grids to genuinely-standard settings only"; make it a test, not a comment.)
2. **Size cap.** `len(grid) ≤ max_grid` (≈24). A large grid is a curve-fitter; the go/no-go argument only
   holds for a *small* set. Combinatorial axes must be pruned to the ones the corpus actually exhibits.
3. **No free continuous parameters.** Search only over *discrete, semantically meaningful* settings
   (ppy=252 vs 12; ddof 0 vs 1). A free `risk_free`/`target`/scale factor could fit almost any number →
   forbidden. Continuous inputs come from captured kwargs, never from search.
4. **Tight tolerance.** The convention match uses the *same* confirm tolerance as a normal three-way confirm
   (no loosening). A near-miss is not a match.
5. **Gated on prior reproduction.** Convention-search runs *only after* produced ≈ claim (the number already
   reproduced at runtime) and only when the default recompute disagrees. It is rescuing "this real runtime
   number is a legitimate metric under a standard convention," not blessing an arbitrary value.
6. **Ambiguity guard.** If *two different* standard conventions reproduce the produced value to tolerance,
   that's fine only because they agree on the value; but if the search would need a *non-standard* convention
   to match, refuse (INCONCLUSIVE), don't stretch the grid at diff-time.
7. **Audit surface.** A confirm reached via convention-search is reported as **"CONFIRMED (under the repo's
   <ppy=252, ddof=0> convention)"** — never a bare CONFIRMED — so a human can sanity-check the inferred
   convention. `diff.py` already writes this note; make it a first-class field on the verdict record.
8. **The coincidental-value fuzz test (the real FCR proof).** For each metric with a grid, generate N random
   *fabricated* target values and random inputs, and assert the convention-search confirms **none** of them
   beyond the base rate implied by tolerance. This is the T4 "coincidental" negative (§A.5) turned into a
   property test; it must be green in CI for the grid to ship. Extend the existing adversarial
   no-false-confirm tests to cover every new grid.

**Unifying insight:** IR (nDCG variant + k) and NLP (tokenization + smoothing, §B.3) are *the same pattern* —
a metric whose value depends on a discrete, standard, un-captured convention. Build the convention registry
generically so all three domains share it: `search_conventions(metric, inputs, produced, tol) -> matched
convention | None`, one code path, per-metric grids.

## B.3 NLP generation metrics + a safe LLM-synthesized recompute

### The machinery already exists — productionize it behind its oracle

`synth/formula.py` already implements the correct shape: `catalog → recipes → store → synth`, where synth
means *cross-check the candidate formula against a trusted reference oracle on random inputs before trusting
it.* `_validate_synth` runs the candidate on 40 random cases and refuses unless it matches the reference
(sklearn/scipy) to `1e-9`; validated formulas are banked in the store for instant reuse. Today the
`SYNTH_REGISTRY` (mcc/cohen_kappa/spearman) *is* "the LLM's output" hand-written; the one remaining piece is
replacing that with a real Claude call. **The validate/store/reuse machinery around it is real and tested —
so the FCR-critical part is already built.** Productionization:

1. **Ground → synthesize → validate → bank.** Keep `_exa_define` grounding; call Claude to emit
   `def recompute(I, K) -> float` from the Exa-confirmed definition; **always** gate on `_validate_synth`
   against a trusted reference; only `store.add` on pass. Never execute an unvalidated formula against a
   verdict path. (The restricted-namespace `exec_formula` — safe builtins + math only — stays.)
2. **The oracle is the reference implementation.** For a metric absent from the catalog, the trust anchor is
   the canonical library, used *only at validation time*: sklearn/scipy for classification/stats,
   `pytrec_eval`/`ranx` for IR ("tested against TREC Eval for correctness"
   ([ranx](https://amenra.github.io/ranx/))), `sacrebleu`/`rouge-score`/`nltk` for NLP. Validation compares
   the synthesized formula to the library on *random inputs of the correct type* — which for text metrics
   means random token sequences, not floats (add text-case generators alongside the numeric ones).

### The NLP twist: these are not pure functions of arrays

BLEU/ROUGE/METEOR depend on **tokenization, casing, smoothing, n-gram order, and stemming**; BERTScore/BLEURT
/COMET depend on an **exact neural checkpoint.** This changes the design in three ways.

**(a) Capture the raw strings, then run a convention search over the standard configs.** If a Tier-1/2 target
wrap (§B.1) captures the candidate/reference *strings* passed to the repo's BLEU call, Calma can recompute
BLEU with `sacrebleu` — but may CONFIRM only if it can pin the same knobs. So BLEU needs the *same convention
search as Sharpe* (§B.2), over the standard sacreBLEU signature space:
`tokenize ∈ {13a, intl, none, char, zh, ja-mecab}`, `smooth_method ∈ {none, floor, add-k, exp}`,
`lowercase ∈ {T, F}`, `use_effective_order ∈ {T, F}`, `max_order = 4`. sacreBLEU's whole reason for existing
is that "different flags ... can produce wide swings in the final score," which is why it emits a
reproducibility signature like `BLEU|nrefs:1|case:mixed|eff:no|tok:13a|smooth:exp|version:2.0.0`
([sacrebleu](https://github.com/mjpost/sacrebleu)). Confirm only under a *named, matched* signature and
report it (like §B.2 rule 7). ROUGE gets the analogous grid: `stemming ∈ {T,F}`, variant `∈ {rouge1, rouge2,
rougeL, rougeLsum}`, and the `rouge-score` vs perl-`ROUGE-1.5.5` implementation axis.

**(b) The determinism / version gotchas to encode (each a real FCR trap):**
- **Scale: 0–1 vs 0–100.** `nltk`/HF `bleu` return 0–1; `sacrebleu` returns 0–100 — "a score of 45.0 in
  SacreBLEU equals 0.45 in BLEU" ([HF evaluate DeepWiki](https://deepwiki.com/huggingface/evaluate/5.2-text-generation-metrics)).
  A 100× scale mismatch would masquerade as REFUTED (or, worse, a coincidental match) — normalize scale
  before comparison and treat scale as part of the signature.
- **Tokenizer default drift.** BLEU's default `13a` mimics `mteval-v13a`; `intl` mimics `mteval-v14`. Wrong
  tokenizer → wrong number → false disagreement.
- **METEOR is NLTK-data-version-dependent** (`wordnet`, `omw-1.4`, `punkt`/`punkt_tab`) — the resource
  versions change the score, so it is not reproducible without pinning them
  ([HF evaluate DeepWiki](https://deepwiki.com/huggingface/evaluate/5.2-text-generation-metrics)).
- **sacreBLEU has a real RNG** for its bootstrap CI (`BLEU_SEED`) — the *point estimate* is deterministic,
  but any reported CI is not without the seed ([sacrebleu](https://github.com/mjpost/sacrebleu)).
- **IR reference bugs are real:** empty-qrels queries make `pytrec_eval` emit **NDCG > 1**
  ([pytrec_eval #57](https://github.com/cvangysel/pytrec_eval/issues/57)) — so even the *oracle* must be
  guarded (drop empty-qrels cases in the validation generator), or the synth would validate against a wrong
  reference.

**(c) Fail closed on learned/embedding metrics.** BERTScore is "roughly [0.8, 1.0]" and depends on the exact
BERT model + layer + baseline-rescaling + idf weighting ([EngineersOfAI](https://engineersofai.com/docs/llms/llm-evaluation/BLEU-ROUGE-and-Generation-Metrics);
[BERTScore paper](https://typeset.io/pdf/bertscore-evaluating-text-generation-with-bert-2adr2b16xq.pdf));
BLEURT and COMET are *learned regression models* on top of BERT ([EngineersOfAI](https://engineersofai.com/docs/llms/llm-evaluation/BLEU-ROUGE-and-Generation-Metrics)).
There is no *independent* recompute of a neural metric: reproducing it means re-running the same checkpoint,
which is not an independent oracle — it's the thing under test. **Rule: for learned/embedding metrics, Calma
returns REPRODUCED-ONLY** (we ran it, it reproduced, but we cannot independently *recompute* it to ground
truth) unless the exact model hash + config are captured *and* we accept re-running the same model as
"reproduction, not recomputation." This is the honest, FCR-safe verdict; it's exactly the `unknown_metric`
fixture's REPRODUCED-ONLY path generalized, and it prevents dressing up a non-independent number as CONFIRMED.

### The safe path, end to end

```
repo reports "BLEU = 34.2"
  → capture (§B.1 target wrap) records candidate + reference STRINGS + the produced 34.2
  → resolver miss in catalog/recipes  → synth path
  → LLM emits a BLEU recompute (or we call sacrebleu directly as the reference)
  → VALIDATE candidate vs sacrebleu on random token sequences, tol tight   ← FCR gate
  → convention search over {tok, smooth, lowercase, eff_order, scale}       ← §B.2 pattern
       exactly one standard signature reproduces 34.2  → CONFIRMED (tok:13a, smooth:exp, scale:0-100)
       none reproduces                                 → REFUTED / INCONCLUSIVE (fail closed)
  → bank the validated formula + matched signature in the store (next repo reuses instantly)

repo reports "BERTScore-F1 = 0.91"
  → learned metric → REPRODUCED-ONLY (independent recompute impossible without being non-independent)
```

Every branch preserves FCR=0: nothing is CONFIRMED unless an *independently validated* recompute reproduces
the runtime number under a *named standard convention*; everything else fails closed.

---

# Prioritized roadmap

Ordered by **franchise-safety first, then value unlocked per unit effort.** Each item names its success gate;
**no item ships if it moves FCR above 0 on any corpus split.**

**P0 — measurement before movement (Phase-A.1, ~1–2 wk).**
1. Add `domain / difficulty_tier / license / commit_date / split(dev|test)` to every `repos.yaml` entry;
   re-classify the existing 10. *Gate: the scorecard renders metric×domain×tier with n-counts.*
2. Build the metric×domain×tier scorecard (extend `spike/optimize/SCOREBOARD.md`) and wire the whole corpus
   as CI, reporting per-cell deltas per engine change. *Gate: a rise in any FCR cell fails the build.*
3. Seed the T4 adversarial tier per existing domain from the synthetic fixtures; add the **coincidental-value
   fuzz test** harness (used by P2). *Gate: FCR=0 across T4.*

**P1 — close the `__main__` capture gap (§B.1, ~2–3 wk).** Highest-leverage capability: it unlocks
finance/stats/NLP custom-metric capture that the corpus expansion depends on.
1. Tier 1: `sys.monitoring` target capture (≥3.12), DISABLE-elsewhere, named-arg reads. *Gate:
   `custom_metric` + a new `__main__`-defined-metric fixture capture correctly; overhead ~0 off-target.*
2. Tier 2: AST decorator-append + `runpy.run_path(run_name="__main__")` + round-trip determinism guard
   (pre-3.12 / unresolved). *Gate: identical captured value to the untransformed run, else discard.*
3. Value-recompute for hand-rolled metrics (`digits-softmax`) falls out of Tier 1/2. *Gate: `digits-softmax`
   moves from INCONCLUSIVE to a real verdict.*
*Overall gate: binding rate ≥ 85% on T2/T3 (from 58%), FCR still 0.*

**P2 — generalize convention-search (§B.2, ~2 wk, overlaps Phase-A.2).**
1. Extract `spike/core/conventions.py` with the hard registry contract (cited axes, size cap, no free
   continuous params, tight tol, audit note). Cover Sharpe/Sortino/Calmar/IR + stdev-ddof + correlation-type.
2. Ship the coincidental-value fuzz test as the grid's release gate. *Gate: finance/stats CONFIRMs reachable
   under convention-search; **0 false-confirms** on the fuzz set + T4.*

**P3 — productionize LLM-synth + NLP recompute (§B.3, ~3 wk, overlaps Phase-A.3).**
1. Replace the hand-written `SYNTH_REGISTRY` with a Claude call behind `_validate_synth`; add text-input case
   generators; wire `pytrec_eval`/`ranx` (IR) and `sacrebleu`/`rouge-score` (NLP) as validation oracles
   (guard the empty-qrels reference bug).
2. Add the tok/smooth/scale convention search for BLEU/ROUGE (reuse P2's `search_conventions`).
3. Implement the learned-metric fail-closed rule (BERTScore/BLEURT/COMET → REPRODUCED-ONLY). *Gate:
   BLEU/ROUGE/nDCG repos CONFIRMED under a matched signature; learned-metric repos correctly REPRODUCED-ONLY;
   FCR=0.*

**P4 — automate sourcing + refresh (Phase-A.4, ~2 wk).** Turn the Stage 1–4 pipeline (GitHub/Exa search →
cheap filters → planner triage → dry-run) into a standing script; stand up the post-cutoff freshness slice
and quarterly refresh. *Gate: the loop runs unattended to Stage 4 and only queues Stage-5 human labels; the
corpus hits ~180 repos across six domains with the target distribution.*

**The single invariant across all of it:** coverage grows by extending *capture reach* (§B.1) and *recompute
breadth* (§B.2, §B.3) behind independent oracles — never by loosening the three-way diff or the verdict.
Every new domain, convention, and synthesized formula is admitted only with an oracle that proves it, and the
T4 adversarial split is the standing, continuously-run proof that **FCR stays 0.**
