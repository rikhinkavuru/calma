# Calma — metric × domain × tier scorecard (guide §A.4)

## Corpus as a distribution (intake)

n=27 repos · splits={'dev': 26, 'test': 1}

| domain \ tier | T1 | T2 | T3 | T4 | total |
|---|---|---|---|---|---|
| analytics | 1 | 0 | 0 | 0 | 1 |
| finance | 0 | 0 | 1 | 1 | 2 |
| ir | 0 | 0 | 1 | 0 | 1 |
| ml | 5 | 3 | 6 | 6 | 20 |
| nlp | 0 | 0 | 2 | 0 | 2 |
| statistics | 0 | 0 | 1 | 0 | 1 |
| **total** | 6 | 3 | 11 | 7 | **27** |
- **T1** — trivial — single library-metric call, seeded, light deps (regression floor; must stay ~100%)
- **T2** — standard — custom metric / .score() / committed artifact, medium deps (the real product surface)
- **T3** — hard — multi-candidate / hand-rolled / convention-sensitive / __main__-defined (the honest-limits frontier)
- **T4** — adversarial/negative — fabricated/leaked/trivial/convention-mismatched/nondeterministic/coincidental (the standing FCR=0 proof; a false CONFIRM here is P0)

## Outcomes per cell (from the last corpus run)

| cell | repos | reproduction | capture | binding | verdict-acc (graded) | **FCR** |
|---|---|---|---|---|---|---|
| finance/T3 | 1 | 100% (1/1) | 100% (1/1) | 100% (1/1) | 100% (1/1) ⚠️ | **0** ✅ |
| finance/T4 | 1 | 100% (1/1) | 100% (1/1) | 100% (1/1) | 100% (1/1) ⚠️ | **0** ✅ |
| ir/T3 | 1 | 100% (1/1) | 100% (1/1) | 100% (1/1) | 100% (1/1) ⚠️ | **0** ✅ |
| ml/T1 | 1 | 100% (1/1) | 100% (1/1) | 100% (2/2) | 100% (2/2) | **0** ✅ |
| ml/T3 | 2 | 100% (2/2) | 100% (2/2) | 67% (2/3) | 100% (3/3) | **0** ✅ |
| ml/T4 | 5 | 100% (5/5) | 100% (5/5) | 100% (5/5) | 100% (5/5) | **0** ✅ |
| nlp/T3 | 2 | 100% (2/2) | 100% (2/2) | 100% (2/2) | 100% (2/2) | **0** ✅ |
| statistics/T3 | 1 | 100% (1/1) | 100% (1/1) | 100% (1/1) | 100% (1/1) ⚠️ | **0** ✅ |

**FCR gate (per-cell + global): ✅ PASS (0 everywhere)** — a single false-confirm anywhere is a P0.

## Verdict distribution per cell

- **finance/T3**: CONFIRMED=1
- **finance/T4**: INVALIDATED=1
- **ir/T3**: CONFIRMED=1
- **ml/T1**: CONFIRMED=2
- **ml/T3**: CONFIRMED=2, INCONCLUSIVE=1
- **ml/T4**: REFUTED=1, INVALIDATED=3, NON-DETERMINISTIC=1
- **nlp/T3**: CONFIRMED=1, REPRODUCED-ONLY=1
- **statistics/T3**: CONFIRMED=1
