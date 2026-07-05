# Calma beachhead analysis — grounded in a 45-repo eval (2026-07-05)

Ran Calma over 45 diverse public repos to answer: **is it catching useful information, and which niche does it
deliver the most value in (weighed against market size)?** 42 shallow (no-run validity) + 3 deep (recompute).

## What the eval actually found

**Shallow validity wedge (42 repos, ml + quant/finance + genomics):**
- Catch-rate is **low in every domain** (ml ~3/33, quant 0/5, genomics 1/4) and **not domain-differentiated**.
- Most repos → INCOMPLETE: no committed train/test split (→ no leakage check), no committed predictions
  (→ no misreport check), no degenerate value (→ no baseline check). The committed numbers live in README /
  markdown / CSV tables the no-run scan can't bind to raw predictions.
- Two **false-alarm** patterns found (and one fixed):
  - *Baseline over-fire* — a notebook training sweep printed 444 accuracy values, 288 near the majority
    baseline → "288 problems". **Fixed** (collapse to one honest summary; heart-kvns 288→1).
  - *Leakage on toy fixtures* — gfmbench-api flagged "8/8 test rows in train" on an 8-row sanity dataset.
    (Still open; fix must not suppress real leakage.)

**Deep recompute (3 classical-ML repos — the hypothesized beachhead): 0 CONFIRMED, 0 REFUTED.**
Three distinct walls, each → no verdict:
1. **Run failure / OOM** — employee-attrition's notebook was killed (exit -9); the synthesized fallback driver
   captured nothing → DISCOVERED.
2. **No hookable computation** — eval-classification's entry ran but the reported numbers weren't produced by a
   hookable metric call (hardcoded / printed) → 0 captured → DISCOVERED.
3. **Disambiguation** — adult-income ran and captured 30 computations, but the repo reports 3 recall values
   (per-model/class) and Calma captured 9 recall computations; it (correctly, fail-closed) refuses to bind a
   reported value to a computation by VALUE (that would be circular / p-hackable) → INCONCLUSIVE.

## The insight

Calma's moat — **never a false confirm** — costs it CONFIRM-rate on messy real-world repos. A clean verdict
needs a repo shape that avoids all three walls:
- **one unambiguous headline number per metric** (no disambiguation), and
- **produced by a hookable computation OR committed predictions** (something to recompute), and
- **a lightweight, runnable entrypoint** (no OOM/kill).

Random classical-ML student repos (multi-model notebooks, hardcoded numbers, heavy runs) fail all three. That
is why the "classical-ML model-comparison" wedge from earlier notes under-delivers in practice.

## Recommendation — beachhead = AI-eval / benchmark-integrity (+ agent-CI)

This segment fits the shape Calma actually verifies well, and the market is large + growing + monetizable:
- An **eval / benchmark run** produces **one score per (model, task)** through a **standard harness** (a
  hookable computation) with a **committed leaderboard number** — exactly the one-headline, hookable,
  reproducible shape that lands a CONFIRMED/REFUTED verdict.
- The buyer pain is real and paid-for: "can we trust this benchmark number / leaderboard submission?" —
  "SOC-2-for-benchmarks" / eval-integrity. Aligns with the prior market-readiness note (#1 AI-eval, #2
  agent-CI).
- Agent-CI is the same shape: an agent reports a number → Calma gates it in CI (the `calma verify --deep`
  non-zero-exit path already built).

**Go-to-market:** lead with `calma verify <benchmark-repo> --deep` on repos with committed leaderboard tables +
a runnable harness, and the GitHub Action / PR-check on eval repos. De-prioritize the generic "point it at any
ML repo" funnel until the binding walls below are lowered.

## Product work this implies (priority order)
1. **Disambiguation** (the highest-leverage wall): when N reported values of a metric map to M captured
   computations, use call-site / label / order provenance to bind 1:1 without value-matching. This is the
   single biggest CONFIRM-rate unlock; FCR-sensitive, so gated + tested.
2. **Capture coverage**: reported numbers produced without a hookable library call (hardcoded / printed) —
   extend capture or committed-prediction recompute.
3. **Run robustness**: notebook OOM/kill on a 1GB box — right-size resources / lighter re-run.
4. **Leakage-on-toy-fixtures** false alarm — demote tiny/100%-overlap splits.

## Empirical validation (iteration 4 — deep-verify the ideal SHAPE)

Deep-verified 4 **single-headline-metric** repos (no disambiguation) to test the recommendation:

| repo | entry | result | note |
|---|---|---|---|
| iris-svm-classification | iris-svm.py | **CONFIRMED ×2** | number reproduces |
| iris-ml-classifier | iris_classifier.py | **CONFIRMED ×2** | number reproduces |
| Breast_Cancer | model.py | **REFUTED ×1** | claimed 97.37%, committed code deterministically produces 95.61% — a real "the code doesn't reproduce the README number" catch |
| Heart-Disease-Classification | main.py | INCONCLUSIVE ×15 | 15 reported vs 9 computed → the disambiguation wall, as predicted |

**Conclusion holds:** on the right shape (one hookable headline number + runnable entrypoint), Calma lands
real CONFIRMED/REFUTED verdicts — including catching a non-reproducing number (the money verdict). The
disambiguation wall is exactly what separates "lands a verdict" (single-value) from INCONCLUSIVE (multi-value),
so priority #1 (disambiguation) is the single biggest lever to extend the beachhead to richer benchmark repos.

## Method
Harnesses: `scratchpad/beachhead_eval.py` (corpus + genomics), `scratchpad/diverse_batch.py` (quant+genomics
via Exa). Deep verifies via the new `calma` CLI against calma-engine.fly.dev. n=45; grows each loop iteration.
