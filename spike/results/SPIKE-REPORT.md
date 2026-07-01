# Calma rebuild — Phase 0 spike report

_The de-risking loop (guide §9): clone → discover claim → make-runnable → sandbox run → instrument-capture raw inputs → independent recompute → three-way diff → verdict._

## Go / no-go gates

| Gate | Target | Measured | |
|---|---|---|---|
| **False-confirm count** | **0** (the franchise) | **0** | ✅ PASS |
| Reproduction rate | ≥ 0.60 floor | 100% (1/1) | ✅ |
| Input-binding rate | high | 100% (1/1 claims)|  |
| Verdict accuracy (graded) | high | 100% (1/1) | ✅ |
| Auto-discovered claims | (free path) | 0 verified |  |
| Wall-clock / repo | low | 2.1s |  |

## Per-repo

| Repo | Runner | Ran | s | Claims (verdict vs expect) |
|---|---|---|---|---|
| main_metric | local | ✅ | 2.1 | acc:CONFIRMED |

## Verdict distribution

- **CONFIRMED**: 1
