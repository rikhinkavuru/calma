# Calma M2 calibration (Stage-1, Python)

On-target self-calibration run on **Apple M4 / darwin, 2026-06-07**. Reproduce with
`python3 .claude/skills/calma/calibration/calibrate.py` (pure stdlib, no GPU, no external deps).
The artifact it writes — `assets/calibration.json` — is the GATE: `compare.py` loads it and only then
unlocks `REFUTED` on a **measured-band (nondeterministic)** run. Delete it to revert to pre-M2
(controlled-to-bit-only REFUTED).

## Determinism band (false-REFUTED guard, two-sided)

The on-target numeric recompute-spread is modelled the way BLAS nondeterminism actually arises —
reduction/summation **order** — by recomputing each metric under many random summation orders. We fit the
distribution-free one-sided order-statistic tolerance bound (max-of-K covers the β-quantile with
confidence 1−β^K).

| quantity | value |
|---|---|
| min K for (coverage 0.95, confidence 0.95) | **59** |
| realized coverage — total_return | **0.98** (≥ 0.95 nominal) |
| realized coverage — sharpe | **0.97** (≥ 0.95 nominal) |
| per-metric spread floor | ~1e-15 (well-conditioned; ABS_FLOOR 1e-9 dominates) |

Below min-K in measured-band mode, REFUTED stays forbidden (degrades to INCONCLUSIVE).

## FP-guard corpus (the §16 fixture list)

13 fixtures with known ground truth (10 honest/ambiguous that must NOT REFUTE, 3 true positives that
SHOULD). Calibration is accepted only when **false-REFUTED == 0** and every true positive is caught.

| metric | value |
|---|---|
| fixtures | 13 |
| false-REFUTED | **0** (fp_rate 0.0) |
| true positives caught | **3 / 3** |

The corpus surfaced two real budget terms (now in `compare.py`): a **claim-precision** term (a claim of
"0.42" means ±0.005, so a rounded/float32 author value does not false-REFUTE) and a **convention cap** (a
declared in-set convention, e.g. Sharpe 252 vs 365, caps at CAVEAT — the conclusion only flips under a
legitimate convention choice).

## Calibrated constants

`abs_floor 1e-9 · rel_floor 1e-9 · z 1.96 · conv_ratio 3.0` (written to `assets/calibration.json`).

## Honest scope

This is the **Python** M2. The cross-language served-fraction matrix (R/Julia/C++) is NOT run here — it
needs those toolchains + a real multi-repo corpus. The determinism band is validated as a *methodology*
(self-calibrating on-target), not as a transferable constant; re-run `calibrate.py` on any host to
re-self-test (it refuses to write the artifact if that host false-REFUTEs).
