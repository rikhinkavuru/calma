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
| sh-mukherjee/momentum-strategy (MIT, yfinance) | honest/quant | **yes** | CONFIRMED | — |
| HilmiSamdya/btc-sma-backtest (MIT, Coinbase) | honest/quant | **yes** | CONFIRMED | — |

**Served-fraction = 1.00** (4/4). Terminal verdicts: REFUTED 2, CONFIRMED 2. The dominant coverage killer
— **live-data dependency** — is now resolved two ways, both reproducible: momentum-strategy via a frozen
data **snapshot** (`vendored_prices.csv`, the BTC pattern), and btc-sma-backtest via the `calma_vendor` HTTP
**record/replay shim** proven end-to-end on a live, non-geoblocked source (Coinbase) — recorded once,
replayed offline under network-off isolation (a cache MISS raises, so the replay is provably hermetic).
The original `Erfaniaa/crypto-backtester` was retired: it is deleted upstream AND its binance source is
geo-blocked (HTTP 451), so it could never be reproduced — `btc-sma-backtest` replaces it like-for-like
(real, MIT, BTC). Both flawed repos are caught (REFUTED); the engine never false-confirmed. Each member is
vendored under `assets/corpus/<name>/` with a `VENDORED.md` provenance + re-record recipe.
Full data: `assets/served_fraction.json` (regenerate with `calibration/regen_served_fraction.py`).

## Cross-language served-fraction matrix

The "partial" M2 deliverable is now filled. Calma runs the program as a **black box** and recomputes in
its own Python reference layer, so language only touches the run + env gates. Verified on this host
(R 4.5, Julia 1.12, clang, rustc, node 24) with `run_hermetic` dispatching by entrypoint extension
(.R→Rscript, .jl→julia, .c/.cpp→compile+run, .rs→rustc, .js→node) under the SAME verified Seatbelt tier.

| language | served | verdict | notes |
|---|---|---|---|
| Python | yes | REFUTED ×2 | controlled-to-bit (BTC) + measured-band (leakage) |
| R | yes | CONFIRMED-WITH-CAVEATS | honest fixture; uncontrolled determinism caveat |
| Julia | yes | CONFIRMED-WITH-CAVEATS | honest fixture |
| C++ | yes | **REFUTED** | flawed claim (+500% vs ~7%) → fraud-multiple path on an uncontrolled run |
| Rust | yes | CONFIRMED-WITH-CAVEATS | honest fixture |
| Node | **yes** | CONFIRMED-WITH-CAVEATS | profile now grants metadata-only reads on the run base's ancestors |

All five honest cross-language fixtures emit the **identical** `returns.csv` (shared deterministic series),
demonstrating cross-language numeric agreement. Findings, all honest: (1) non-Python runs are stamped
`uncontrolled` (bit-determinism not statically provable) yet a **fraud-grade** gap still REFUTES via the
calibrated fraud-multiple M=5 (C++); (2) Node's CJS loader `lstat`s `/Users` while realpath-resolving the
entrypoint, which a blanket read-deny rejected — fixed by granting `file-read-metadata` (lstat/stat/readlink
only) on the **exact ancestor chain of the run base**, so any runtime can resolve its script while directory
listing and file-content reads under `/Users` stay denied (the doctor positive-control still proves zero
secret-reads + zero egress; an adversarial probe confirms lstat passes but `listdir`/`open` are denied).
The Seatbelt profile also keeps a toolchain allowlist (`~/.julia`, `~/.cargo`, `~/.rustup`, `~/.npm`).

## Overall served-fraction (full corpus)

9 corpus members across 6 languages: **served-fraction 1.00 (9/9)**. Terminal verdicts: REFUTED 3,
CONFIRMED 2, CONFIRMED-WITH-CAVEATS 4. The engine never false-confirmed and never false-REFUTED. Three
engine improvements got here, all general (not corpus-specific): (a) the isolation profile's metadata-only
ancestor reads (Node + any realpath-resolving runtime); (b) **restore/run interpreter consistency** —
a Python repo whose deps are restored into `<base>/.calma_venv` now RUNS under that venv, not the host
interpreter (momentum-strategy's numpy/pandas path); (c) **whole-program** determinism detection — the
controlled-to-bit stamp now requires every `.py` under the program tree (not just the entry file) to be
RNG/GPU/scientific-stack-free, so a thin entrypoint over numpy-using modules is honestly `measured-band`.
Full data: `assets/served_fraction.json`.
