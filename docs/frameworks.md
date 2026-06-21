# Calma by framework — recipes & starter contracts

`calma init <framework>` scaffolds a runnable `verify.yaml` for your stack, so a quant/ML team adopts
Calma without learning the contract format. This table maps each supported framework to the metric Calma
recomputes, the artifact you emit, and the validity blocks to declare.

| framework | command | headline metric | emit this artifact | declare for validity |
|---|---|---|---|---|
| **Backtrader** | `calma init backtrader` | `sharpe` / `total_return` | `results/returns.csv` — one `return` column (a `bt.Analyzer` or writer) | `frictions` (net-of-cost), `windows` (walk-forward) |
| **VectorBT** | `calma init vectorbt` | `sharpe` | `returns.csv` — `pf.returns().to_csv('returns.csv', header=['return'])` | `frictions`, `windows` |
| **zipline** | `calma init zipline` | `total_return` | `perf.csv` — `perf['returns'].to_csv('perf.csv', header=['return'])` | `frictions`, `windows` |
| **PyTorch** | `calma init pytorch` | `accuracy` | `predictions.csv` — `y_true,y_pred` (argmax labels) | `split` (leakage), `trials` (overfitting) |
| **XGBoost** | `calma init xgboost` | `auc` | `predictions.csv` — `y_true,y_score` (probabilities) | `split`, `trials` |
| **scikit-learn** | `calma init sklearn` | `f1` | `predictions.csv` — `y_true,y_pred` | `split`, `trials` |

Aliases: `torch` → pytorch, `xgb` / `lightgbm` / `lgbm` → xgboost, `scikit-learn` / `scikit` / `skl` → sklearn,
`bt` → backtrader, `vbt` → vectorbt. Lookup is case-insensitive.

## How it works

`calma init` writes a starter `verify.yaml` (the entrypoint hint, the artifact layout, the headline metric
+ its canonical binding, and — for ML — a `split` skeleton). Fill in the paths, then verify:

```bash
calma init pytorch                 # writes verify.yaml + prints the fill-in steps
# ... point predictions.csv / train.csv / test.csv at your real outputs ...
calma verify . "accuracy 0.94"
```

The metric is **recomputed from your raw outputs** (never the reported number). Declaring the validity
blocks above turns on the *authoritative* families:

- **`split: {train, test}`** (or `{file, column}`) → the leakage check (train/test row / id / temporal
  overlap) → `INVALIDATED` if the held-out set is contaminated.
- **`trials: N`** (or a grid-search artifact) → the overfitting check (Deflated Sharpe / PBO).
- **`frictions: {fee_bps, slippage_bps, ...}`** → execution realism (a "net" return that is really gross).
- **`windows`** → walk-forward / regime robustness.

Until you declare them, the **thin-input smell layer** still fires soft, no-block heads-ups from the
artifacts alone (an undeclared-split leakage smell when test rows duplicate train rows; a regime-drift
smell on a non-stationary return series; a train/validation loss-gap overfit smell) — each naming the
exact block to declare for the authoritative verdict. See the validity families in the README.

## Bindings (the canonical recipe inputs)

The starter contracts use the engine's canonical bindings, so they recompute without edits once the
columns exist:

- classification accuracy / f1 → `binding: {prediction: <col>, label: <col>}`, `convention: argmax`
- `auc` → `binding: {score: <col>, label: <col>}`, `convention: roc-auc`
- trading metrics (`sharpe`, `total_return`, …) → `binding: {return: <col>}`

`calma recipes` lists all 623 metric ids; pass `--metric <id>` (or set `metrics[].metric_id`) to verify a
different one.

## Reference vectors (status)

Calma's recipes are validated against byte-reproducible reference vectors (`assets/reference_vectors.json`)
and the benchmark's external scikit-learn track.

**Measured (in CI, every run):**
- The **contract half** of every `calma init` template validates against the schema and binds its
  headline metric (`tests/test_frameworks.py`, `tests/test_deferred_arms.py` → T2/C4).
- The benchmark **agent arm's** plumbing + scoring runs offline via the `--mock` backend
  (`tests/test_deferred_arms.py` → T2/D2). Mock numbers are flagged `MOCK` and never reported as real.

**Gated (manual / secret-gated CI job, documented not silently skipped):**
- **Framework-GENERATED vectors** — a Backtrader / VectorBT / zipline Sharpe, a PyTorch / XGBoost
  accuracy/AUC. A host-with-those-frameworks task: generate the artifact with the framework, freeze it,
  and assert Calma's recompute matches the framework's own number to ≤1e-9. Needs the frameworks
  installed (like the benchmark's sklearn track). The `calma init` templates are the contract half; the
  per-framework generators are the remaining piece.
- **The REAL benchmark agent arm** (`benchmark/run_agent.py` without `--mock`) — needs
  `ANTHROPIC_API_KEY`; measures verdict-instability across reruns, cost, latency.
- **`draft --ai` on real repos** — needs the edges deps + an API key; the heuristic fallback (no key)
  is exercised in CI (`tests/test_deferred_arms.py`).
