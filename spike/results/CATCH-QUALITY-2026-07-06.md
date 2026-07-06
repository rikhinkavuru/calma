# Catch-quality finding — single-metric repos (2026-07-06)

Ran 3 small single-headline-number sklearn repos (built-in datasets, no download) to answer the founder's
question: *is the tool catching useful info / errors?* Answer: **yes on real metrics, but with false-alarm
noise worth fixing.**

## What it caught (genuine)

| Repo | Reported | Verdict | Real? |
| --- | --- | --- | --- |
| Mai3Prabhu/Naive-Bayes-with-Iris-dataset | accuracy 1.0 / 100% | **CONFIRMED** ×2 | Yes — recompute reproduces |
| ShamsRupak/ML-Image-Classifier | accuracy 98.89% | **CONFIRMED** | Yes — the classification-report accuracy reproduces |

These are exactly the beachhead's value: an independent recompute confirming a reported number.

## The noise (false REFUTES — NOT false confirms; FCR moat intact)

Two mis-extraction / mis-verdict patterns produced spurious REFUTED claims:

1. **Classification-report SUPPORT column extracted as "accuracy".** `claimed=72` (breast_cancer),
   `claimed=11` (iris), `claimed=36` (digits) are the per-class *support* counts from sklearn's
   `classification_report`, mislabeled `metric=accuracy` and REFUTED. The author never claimed those as
   accuracies — they are row counts. → spurious "your accuracy is refuted".
2. **Lower-bound claim treated as exact equality.** README ">95% accuracy" → `claimed=95%` REFUTED against a
   computed 98.89%. A ">=/at least/over" bound is SATISFIED by 98.89% and should not REFUTE.

## Why NOT auto-fixed this session

Both live in claim-extraction + verdict logic, which is FCR-sensitive:
- Guarding #1 by "an accuracy value that is an integer > 1 with no % is invalid" risks dropping a legitimate
  bare-percentage claim ("accuracy: 95" meaning 95%). Bare integers are genuinely ambiguous.
- Fixing #2 means parsing bound qualifiers and switching from equality to a satisfy-check — but if an EXACT
  claim is mis-parsed as a bound, a too-high computed value would falsely CONFIRM. That is a false-confirm
  risk (the one thing the moat forbids), so it needs careful, reviewed handling — not an unsupervised change.

These are false REFUTES: conservative, moat-safe, but they read as false alarms and dent the "neutral auditor"
credibility. Priority = product polish, not a correctness breach.

## Candidate fixes (for review)

- **#1 (support column):** in the classification-report parser, do not emit the `support` column as a metric
  claim; only emit `precision/recall/f1-score/accuracy` cells. Narrow + safe if scoped to the
  classification-report shape specifically (not a global "drop integer accuracies" rule).
- **#2 (bounds):** detect bound qualifiers (`>`, `>=`, `≥`, "at least", "over", "more than") on a metric
  claim; verdict = CONFIRMED iff computed satisfies the bound, else REFUTED. Only apply to explicitly-bounded
  phrasing; an exact claim stays exact (preserves FCR). Add to the redteam/edgecases FCR gates first.
