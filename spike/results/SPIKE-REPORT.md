# Calma rebuild — Phase 0 spike report

_The de-risking loop (guide §9): clone → discover claim → make-runnable → sandbox run → instrument-capture raw inputs → independent recompute → three-way diff → verdict._

## Go / no-go gates

| Gate | Target | Measured | |
|---|---|---|---|
| **False-confirm count** | **0** (the franchise) | **0** | ✅ PASS |
| Reproduction rate | ≥ 0.60 floor | 100% (11/11) | ✅ |
| Input-binding rate | high | 94% (16/17 claims)|  |
| Verdict accuracy (graded) | high | 100% (14/14) | ✅ |
| Auto-discovered claims | (free path) | 3 verified |  |
| Wall-clock / repo | low | 1.6s |  |

## Per-repo

| Repo | Runner | Ran | s | Claims (verdict vs expect) |
|---|---|---|---|---|
| clean_eval | local | ✅ | 1.7 | acc:CONFIRMED, auc:CONFIRMED |
| misreported | local | ✅ | 1.4 | acc:REFUTED |
| custom_metric_invalid | local | ✅ | 1.5 | acc:INVALIDATED |
| trivial_baseline | local | ✅ | 1.4 | acc:INVALIDATED |
| nondeterministic | local | ✅ | 1.5 | acc:NON-DETERMINISTIC |
| two_splits | local | ✅ | 1.5 | acc_bare:INCONCLUSIVE, acc_test:CONFIRMED |
| unknown_metric | local | ✅ | 1.4 | bleu:REPRODUCED-ONLY |
| realistic_sklearn | local | ✅ | 1.4 | acc:CONFIRMED, auc:CONFIRMED, f1:CONFIRMED |
| realistic_autodiscover | local | ✅ | 1.7 | d0_accuracy:CONFIRMED, d1_f1:CONFIRMED, d2_roc_auc:CONFIRMED |
| e2b_smoke | e2b | ✅ | 2.4 | mean:CONFIRMED |
| ml-in-10-lines | local | ✅ | 1.5 | acc:REFUTED |

## Verdict distribution

- **CONFIRMED**: 10
- **REFUTED**: 2
- **INVALIDATED**: 2
- **REPRODUCED-ONLY**: 1
- **NON-DETERMINISTIC**: 1
- **INCONCLUSIVE**: 1
