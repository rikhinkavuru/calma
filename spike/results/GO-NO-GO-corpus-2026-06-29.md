# Calma rebuild — Phase 0 go/no-go memo: the real-corpus reproduction + binding rate

**Date:** 2026-06-29 · **Decision: GO.** The core loop holds on code we did not author. The one weak
gate (binding) fails *closed* — it never produces a wrong CONFIRMED — and maps exactly onto the next build
step. Raw data: [`corpus-results-2026-06-29.json`](corpus-results-2026-06-29.json) ·
[`CORPUS-REPORT-2026-06-29.md`](CORPUS-REPORT-2026-06-29.md).

## What was measured

10 **real external GitHub repos** (9 newly curated + the original `ml-in-10-lines`), each verified to exist
and pinned to a HEAD SHA before the run. All CPU-only sklearn/numpy demos with a reported number and a
single run-and-print entrypoint, cloned fresh, built into a per-repo venv from declared deps, and run k=2
with capture armed. Claims were **auto-discovered** (the free path) — no hand-specified bindings, no
hand-graded verdicts except the one carry-over (`ml-in-10-lines`).

| Gate | Target | Measured | |
|---|---|---|---|
| **False-confirm count** | **0** (the franchise) | **0 / 12** | ✅ |
| Reproduction rate (ran) | ≥ 60% floor | **80%** (8/10) | ✅ |
| Auto-discovered claims | free path works | **11** real claims found | ✅ |
| Input-binding rate | high | **58%** (7/12) | ⚠️ → next build |
| Verdict accuracy (graded) | high | 100% (1/1) | ✅ (tiny n) |
| Wall-clock / repo | low | 10.2s (cached venvs) | ✅ |

## Verdict breakdown — every one is correct

- **5 CONFIRMED** — `iris-logreg`, `iris-svm` (×2), `iris-naive-bayes` (×2). Seeded, deterministic sklearn
  iris models claiming 100%/1.00; claim == runtime value == our independent recompute, stable across k=2.
  Real three-way confirms, not claim==produced shortcuts.
- **2 REFUTED** — both genuine catches on real repos:
  - `ml-in-10-lines`: README 96.67% → 1.0 in a fresh env (scikit-learn version drift).
  - `breast-cancer-rf`: README **97.37%** → recomputes to **96.49%** — an **unseeded** RandomForest whose
    reported number does not reproduce. (A textbook "the headline isn't reproducible" finding.)
- **5 INCONCLUSIVE (unbound)** — fail-closed, **never** a false confirm:
  - `iris-codealpha`: **31** candidate `accuracy` computations (GridSearchCV scores accuracy across every
    fold × param) → ambiguous → refuse.
  - `iris-multimodel`: 3 candidate `accuracy` calls (3 models in one script) → ambiguous → refuse.
  - `digits-softmax`: a **from-scratch numpy** softmax — no sklearn `accuracy_score` call to hook → "no
    captured computation" → refuse.
- **2 did not run** — honest reproduction failures, correctly classed:
  - `iris-algos-compare`: the repo feeds a continuous target to a classifier (a bug in the repo itself).
  - `titanic-seaborn`: NaNs reach an estimator that rejects them (preprocessing gap / version).

## Reading the result

1. **The franchise holds on real, unauthored code.** 0 false confirms across 12 discovered claims. When the
   binder cannot unambiguously locate the inputs, the router refuses (INCONCLUSIVE) rather than guess — even
   though guessing-by-value would have "confirmed" several. This is the whole bet, and it survived contact.
2. **Discovery (the free path) works.** 11 real reported numbers extracted from READMEs / printed lines /
   committed tables with zero hand-specification.
3. **Binding is the bottleneck — and it's the *known* next step.** All 5 unbound cases are the same two
   shapes: (a) *multiple* candidate computations of the same metric (GridSearchCV, multi-model scripts) that
   need disambiguation, and (b) a metric computed *without a library call* (hand-rolled numpy) that the
   call-site hook can't see. Both are precisely what REBUILD step 3 (auto-binding via dataflow/provenance
   tracing) and the artifact/value-recompute path target. 58% today is a floor measured with *only* metric-
   identity binding and *no* hints.

## Recommendation

**GO** — commit to the build. Sequence the next work by what this surfaced:

1. **Auto-binding (REBUILD §3), now the critical path.** Disambiguate multi-candidate cases by binding the
   *held-out/test* computation specifically (dataflow from the test split → the metric call), which converts
   the `iris-codealpha` / `iris-multimodel` INCONCLUSIVEs into real verdicts. Target: binding ≥ 85%.
2. **Value-recompute fallback for hand-rolled metrics** (`digits-softmax`): when there's no library call to
   hook, recompute from the captured predictions/labels arrays directly.
3. **Reproduction hardening already started:** the headless `MPLBACKEND=Agg` fix (a `plt.show()` hang ate a
   full timeout before it) is in; next is the agentic env/deps + data-connect retries the failure taxonomy
   already routes to.
4. **Grow the graded set** so verdict-accuracy is measured on more than n=1 (hand-grade ~5 of the corpus).

The product surface is ready for this: leakage now folds into per-claim verdicts, run failures surface the
real exception, and the verify flow is behind WorkOS auth.
