# Validity-family demo fixtures — the INVALIDATED / REFUTED teardowns

Seven self-contained, deterministic fixtures (pure stdlib `gen_fixture.py` + a committed `verify.yaml`)
that exercise the validity families end-to-end. Each shows the most sellable output the engine produces:
a distinct verdict word, the evidence line, the `claimed X → Y` pair, and exit 1. The verdict is computed
by deterministic scripts (never a model), so every model that drives the producer yields the identical
stamp — that is the headline for a cross-model benchmark (`/benchmark-models`).

Run any of them:

```
python3 scripts/calma.py verify assets/demos/<dir> --claim "<claim>" --metric <id>
```

| Dir | Family | Verdict | The teardown |
|---|---|---|---|
| `leakage-heldout` | leakage | **INVALIDATED** | "your held-out AUC isn't held-out" — 30 of 100 test rows are exact duplicates of training rows; `claimed 1.0 → leakage-corrected 1.0` (survives correction, but the split was contaminated). |
| `realism-net-sharpe` | execution-realism | **REFUTED** | "your net Sharpe is really gross" — `claimed 3.13 → friction-deflated −0.05`; the entire edge is transaction costs + slippage. |
| `contamination-heldout` | contamination | **INVALIDATED** | "your zero-shot benchmark isn't held-out" — 10 of 25 eval items are present in the declared pretraining corpus; `claimed 0.92 → recomputed 0.92` (reproduces, but not a held-out measurement). |
| `overfitting-multiple-testing` | overfitting | **INVALIDATED** | "doesn't survive multiple-testing" — Sharpe 3.17 selected as the best of 1000 configs; `DSR=0.026 (p=0.974)`. |
| `deflated-sharpe-overfit` | deflated_sharpe (recipe) | **REFUTED** | the direct recipe path — `claimed DSR 0.95 → recomputed 0.02` over the declared `trials=1000,var_sr=0.01` search. |
| `deflated-sharpe-survives` | deflated_sharpe (recipe) | **CONFIRMED** | the honest mirror — a strong edge (per-period Sharpe ~0.50) whose `claimed DSR 0.996` survives the 1000-config correction. Shows the recipe isn't one-sided. |
| `realism-soft-caveats` | execution-realism | **CONFIRMED-WITH-CAVEATS** | the soft-caveat side — the Sharpe reproduces, but it's run at 3x leverage, 20% of ADV, and a VWAP fill, so the caveats are surfaced on the headline (the number holds, but narrower than it looks). |

The exact claim strings used in dev (each pins the headline so the core recompute CONFIRMS first, then
the family promotes the verdict):

```
leakage-heldout                 --metric auc            --claim "auc 1.0 on the held-out test set"
realism-net-sharpe              --metric sharpe         --claim "net Sharpe 3.13 after costs"
contamination-heldout           --metric accuracy       --claim "92% zero-shot accuracy on the held-out benchmark"
overfitting-multiple-testing    --metric sharpe         --claim "sharpe 3.17, the best of 1000 backtested configs"
deflated-sharpe-overfit         --metric deflated_sharpe --claim "deflated sharpe 0.95, the best of 1000 backtested configs"
deflated-sharpe-survives        --metric deflated_sharpe --claim "deflated sharpe 0.996, survives the 1000-config search"
realism-soft-caveats            --metric sharpe         --claim "Sharpe 2.38 at 3x leverage"
```

Notes
- `runs/*.csv` are committed (the fixture is self-contained) and `re_emit: true` regenerates them on
  re-execution, so the recompute reads fresh bytes.
- The `.calma/` run directories these produce are git-ignored.
