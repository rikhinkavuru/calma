# Calma pilot dress rehearsals

The whole pilot pipeline run end-to-end on quant repos across stacks: intake (+restore) → isolated run → recompute → signed bundle → branded report + offline replay bundle → a redacted, hash-chained registry entry. Regenerate with `python3 rehearsals/run_rehearsal.py`.

## Runs

| Strategy | Stack | Isolation | Verdict | Report+Replay | Sealed | Published |
|---|---|---|---|---|---|---|
| BTC inflated backtest (walk-forward) | python/stdlib | `container` | **REFUTED** | ✓ | ✓ | ✓ |
| Momentum strategy (real MIT repo) | python/pandas+numpy | `seatbelt-verified` | **CONFIRMED** | ✓ | ✓ | ✓ |
| Backtrader SMA-cross strategy | python/backtrader | `seatbelt-verified` | **CONFIRMED** | ✓ | ✓ | ✓ |
| R momentum strategy | R | `seatbelt-verified` | **CONFIRMED-WITH-CAVEATS** | ✓ | ✓ | ✓ |
| Omitted-costs deck (gross sold as net) | python/stdlib | `seatbelt-verified` | **CONFIRMED-WITH-CAVEATS** | ✓ | ✓ | ✓ |

## What each run caught (or confirmed)

- **BTC inflated backtest (walk-forward)** (python/stdlib): REFUTED - in-sample +14,698% collapses to a negative out-of-sample return
- **Momentum strategy (real MIT repo)** (python/pandas+numpy): CONFIRMED reproduction - the pandas backtest re-runs and the number recomputes
- **Backtrader SMA-cross strategy** (python/backtrader): CONFIRMED reproduction - restored backtrader, ran the strategy, recomputed the return
- **R momentum strategy** (R): CONFIRMED-WITH-CAVEATS - R reproduces; determinism is uncontrolled (honest)
- **Omitted-costs deck (gross sold as net)** (python/stdlib): CONFIRMED-WITH-CAVEATS - the gross number reproduces, but net-of-cost is far lower

## Registry dry-run (redaction-by-construction)

- Entries appended to a scratch chain: **5**
- Hash chain verifies offline: **YES**
- Redaction leak scan (code / data / positions in any entry): **NONE — only claim/metric/gap/verdict/hashes**
- Verdict counts: `{"REFUTED": 1, "CONFIRMED": 2, "CONFIRMED-WITH-CAVEATS": 2}`

Every entry carries only the whitelisted fields (claim, metric, claimed, recomputed, verdict, hashes, keyid, dates). Code, data, and positions never enter the registry — enforced at append AND re-checked here independently.
