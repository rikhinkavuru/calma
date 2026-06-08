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

## Served-fraction (real-repo corpus)

Research-vetted candidates (GitHub API checked for license/size/freshness). Most public "backtest"/ML
repos failed the permissive-Python bar (AGPL `backtesting.py`; R `benchm-ml`; 246MB `pmlb`; several with
no license). The strongest documented leakage case — the civil-war RF study (AUC 0.97 → 0.91 corrected;
ML-over-LR edge 0.14 → 0.01) — is **R-only**, so it is reproduced faithfully in self-contained Python
(`assets/leakage/`). Corpus run via `calibration/served_fraction.py` (4-gate + terminal verdict):

| repo | bucket | served | verdict | failing gate |
|---|---|---|---|---|
| btc-overfit backtest (vendored snapshot) | flawed/quant | yes | **REFUTED** | — |
| ml-leakage civil-war repro | flawed/ML | yes | **REFUTED** (measured-band, M2-unlocked) | — |
| sh-mukherjee/momentum-strategy (MIT) | honest/quant | no | INCONCLUSIVE | run (needs yfinance live data) |
| Erfaniaa/crypto-backtester (GPL, local) | flawed/quant | no | INCONCLUSIVE | run (needs binance live data) |

**Served-fraction = 0.50** (2/4). Terminal verdicts: REFUTED 2, INCONCLUSIVE 2. The honest finding:
**live-data dependency is the dominant coverage killer**, not the verification logic — a repo that fetches
market/ML data at runtime cannot run under network-off isolation until its data is vendored to a snapshot
(as BTC was). Both *self-contained flawed* repos are caught (REFUTED); the verification engine never
false-confirmed. Full data: `assets/served_fraction.json`.
