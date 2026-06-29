# Calma rebuild — Phase 0 spike report

_The de-risking loop (guide §9): clone → discover claim → make-runnable → sandbox run → instrument-capture raw inputs → independent recompute → three-way diff → verdict._

## Go / no-go gates

| Gate | Target | Measured | |
|---|---|---|---|
| **False-confirm count** | **0** (the franchise) | **0** | ✅ PASS |
| Reproduction rate | ≥ 0.60 floor | 80% (8/10) | ✅ |
| Input-binding rate | high | 58% (7/12 claims)|  |
| Verdict accuracy (graded) | high | 100% (1/1) | ✅ |
| Auto-discovered claims | (free path) | 11 verified |  |
| Wall-clock / repo | low | 10.2s |  |

## Per-repo

| Repo | Runner | Ran | s | Claims (verdict vs expect) |
|---|---|---|---|---|
| ml-in-10-lines | local | ✅ | 1.8 | acc:REFUTED |
| breast-cancer-rf | local | ✅ | 1.9 | d0_accuracy:REFUTED |
| iris-algos-compare | local | ❌ the entrypoint errored | 2.2 | — |
| iris-logreg | local | ✅ | 2.1 | d0_accuracy:CONFIRMED |
| iris-svm | local | ✅ | 2.1 | d0_accuracy:CONFIRMED, d1_accuracy:CONFIRMED |
| iris-naive-bayes | local | ✅ | 2.1 | d0_accuracy:CONFIRMED, d1_accuracy:CONFIRMED |
| iris-codealpha | local | ✅ | 4.8 | d0_accuracy:INCONCLUSIVE, d1_accuracy:INCONCLUSIVE |
| digits-softmax | local | ✅ | 2.3 | d0_accuracy:INCONCLUSIVE, d1_accuracy:INCONCLUSIVE |
| titanic-seaborn | local | ❌ the entrypoint errored | 42.1 | — |
| iris-multimodel | local | ✅ | 40.5 | d0_accuracy:INCONCLUSIVE |

## Verdict distribution

- **CONFIRMED**: 5
- **REFUTED**: 2
- **INCONCLUSIVE**: 5
