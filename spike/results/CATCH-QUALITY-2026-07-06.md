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

## Fixes

- **#1 (support column) — SHIPPED (merge 855d4ee, deployed + live-validated).** Instead of a
  classification-report parser (there is none — extraction is general), added a source-agnostic post-extraction
  guard `discovery.extract._plausible_value`: a unit-interval metric (accuracy/precision/recall/f1/roc_auc/
  balanced_accuracy/specificity/brier/ndcg) whose value is a bare number > 1 with NO `%` is a count, not a
  score → dropped. FCR-safe (only drops; 12/12 gates green, 1129 tests). Live re-run: digits' `36` and
  breast_cancer's `72` false REFUTES are gone; the genuine `CONFIRMED 98.89%` survives; breast_cancer now
  surfaces the real `accuracy 0.98` as REPRODUCED-ONLY instead of a bogus refute.
- **#2 (bounds) — STILL DEFERRED (needs founder review, FCR-sensitive).** Detect bound qualifiers (`>`, `>=`,
  `≥`, "at least", "over", "more than") and verdict = CONFIRMED iff computed satisfies the bound. Risk: if an
  EXACT claim is mis-parsed as a bound, a too-high computed value would falsely CONFIRM (moat breach). Add to
  redteam/edgecases FCR gates first. (Still visible live: digits' ">95%" → `95%` REFUTED.)

## Minor (noted, not fixed)

- breast_cancer now yields 7× `accuracy 0.98` (the classification-report's repeated 0.98 cells all mapped to
  accuracy). Harmless (same real value, REPRODUCED-ONLY, no false verdict) but redundant — a dedup/labeling
  polish, low priority.
