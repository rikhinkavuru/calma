# Recipe catalog (59 recipes, all SOTA-validated)

Every recipe recomputes its number ONLY from raw machine-readable artifacts via the
reference-deterministic kernels in `numeric.py` (fsum / pairwise product / sqrt, plus the
deterministic transcendental kernels - never platform libm, never numpy). Every recipe is
validated against published reference implementations (scikit-learn, SciPy, NumPy, the
HumanEval pass@k estimator, the SQuAD eval normalizer, Guo et al. ECE) by
`tests/test_recipes_sota.py` over `assets/reference_vectors.json` (312 vectors, regenerable
with `calibration/gen_reference_vectors.py`).

Binding = semantic tag -> column name. A binding value `other.csv::col` reads from a sibling
artifact. Tags listed as *string* keep raw cell strings (everything else parses to float).
`convention` is a plain string on the contract metric; defaults in parentheses.

## Trading (3)

| metric_id | binding tags | convention | definition |
|---|---|---|---|
| total_return | return | compounded | prod(1+r) - 1 (pairwise product) |
| sharpe | return | periods: 252/365/52 (252) | mean/std(ddof=1) * sqrt(periods); near-zero vol degrades |
| max_drawdown | return | compounded | worst peak-to-trough of the equity curve (path-dependent) |

## ML classification (12)

| metric_id | binding tags | convention | definition |
|---|---|---|---|
| accuracy | prediction, label | argmax | mean(pred == label) |
| auc | score, label | roc-auc | Mann-Whitney with tie=0.5 + DeLong SE |
| precision / recall / f1 | prediction, label | - | binary 0/1 confusion counts |
| brier | prob, label | - | mean((p-y)^2) |
| macro_f1 / micro_f1 | prediction, label | - | multiclass; classes = union(labels, preds); zero_division=0 (sklearn) |
| pr_auc | score, label | average_precision \| trapezoid | sklearn AP step integral (ties grouped) |
| log_loss | prob, label | exact (default) \| clip | -mean(y ln p + (1-y) ln(1-p)); exact mode -> inf is degenerate, clip = legacy 1e-15 |
| mcc | prediction, label | - | Gorodkin multiclass MCC, exact integer sums; 0.0 on zero denominator (sklearn) |
| ece | prob, label | bins=`<int>` (15) | Guo et al. equal-width (lo,hi] bins, sum (n_b/n)\|acc_b - conf_b\| |

## Regression (3)

rmse, mae, r2 - binding `prediction, target`; sklearn-checked.

## Data / analytics (12)

| metric_id | binding tags | convention | definition |
|---|---|---|---|
| column_sum / column_mean / row_count | value / value / (column) | - | fsum / fsum/n / n |
| column_median | value | - | numpy 'linear' quantile at q=0.5 |
| percentile | value | REQUIRED: p95 / p99.9 / q=0.9 / 90 | numpy 'linear' method; no convention -> degenerate |
| groupby_aggregate | group *(string)*, value | sum \| mean \| sum:`<group>` \| mean:`<group>` | per-group fsum/mean; no group label -> degenerate (groups kept in terms) |
| distinct_count | value *(string)* | drop_null (default) \| include_null | distinct stripped cells (pandas nunique) |
| growth_rate | value | period (default: last/prev - 1) \| total (last/first - 1) | time-ordered column |
| ratio_share | flag | - | fraction of truthy rows |
| null_fraction | value *(string)* | - | fraction of ""/nan/na/null/none cells |
| duplicate_count | value *(string)* | - | rows duplicating an earlier row (pandas duplicated keep='first') |
| join_row_loss | left_key *(string)*, joined_key *(string)* | - | len(left) - len(joined); 0 = lossless, negative = fan-out; use `left.csv::id` cross-artifact binding |

## Performance & engineering (8)

| metric_id | binding tags | convention | definition |
|---|---|---|---|
| speedup_ratio | before, after | mean (default) \| median | mean(before)/mean(after) from raw timings |
| latency_p50 / p95 / p99 | duration | - | numpy 'linear' quantile of raw durations |
| throughput | duration | - | n / fsum(durations) (ops per unit time) |
| peak_memory | value | - | max of sampled series |
| test_coverage | hits | - | lines with hits>0 / lines, from raw per-line hit counts |
| error_rate | flag | flag (nonzero=error) \| http4xx \| http5xx | failures / total |

## Retrieval / RAG / LLM evals (6)

Retrieval layout: one row per (query *(string)*, rank, relevance); rank 1 = best.

| metric_id | convention | definition |
|---|---|---|
| recall_at_k | k=`<int>` (10) | per query: relevant in top-k / all relevant; zero-relevant queries skipped |
| ndcg_at_k | k=`<int>` (10), optional `,exp` | discount 1/log2(i+1); linear gains (sklearn) or 2^rel-1 |
| mrr | k=`<int>` (uncapped) | mean 1/rank of first relevant; 0 when none |
| top_k_accuracy | k=`<int>` (5) | hit-rate: queries with >=1 relevant in top k |
| exact_match | strict (default) \| normalized | prediction *(string)* vs reference *(string)*; normalized = SQuAD (lower/punct/articles/whitespace) |
| pass_at_k | k=`<int>` (1) | problem *(string)*, correct; HumanEval unbiased 1 - C(n-c,k)/C(n,k), exact integers; n<k -> degenerate |

## Statistical claims (6)

| metric_id | binding tags | convention | definition |
|---|---|---|---|
| p_value | sample_a, sample_b | welch (default, scipy) \| pooled \| z | two-sided two-sample p via deterministic incomplete beta / erfc |
| confidence_interval | value | t95 (default) / t90 / t99 / z95 / z99 | CI half-width of the mean: crit * s/sqrt(n) |
| lift | sample_a (control), sample_b (treatment) | relative (default) \| absolute | (mb-ma)/ma or mb-ma |
| chi_square | group *(string)*, outcome *(string)* | p (default) \| statistic \| p-no-yates \| statistic-no-yates | independence test from RAW observation pairs; Yates only when df==1 (scipy) |
| correlation | x, y | pearson (default) \| spearman | fsum-centered Pearson; Spearman = Pearson on midranks (ties averaged) |
| effect_size | sample_a, sample_b | cohen_d (default) \| hedges_g \| glass_delta | pooled-SD d; Hedges' exact-gamma J; Glass = control SD |

## Business & finance (6)

| metric_id | binding tags | convention | definition |
|---|---|---|---|
| cagr | value | periods=`<per-year>` (1) | (last/first)^(1/years) - 1; years = (n-1)/periods_per_year |
| npv | cashflow | REQUIRED: rate=`<frac>` | sum cf_t/(1+r)^t, cf[0] at t=0 (numpy-financial); no rate -> degenerate |
| irr | cashflow | - | rate where npv=0, deterministic bisection; no sign change -> degenerate |
| churn_rate | flag | churn (default) \| retention | churned/total from raw flags; retention = 1 - churn |
| margin_pct | value (revenue), cost | - | (sum rev - sum cost) / sum rev |
| reconciliation_total | value_a, value_b | - | sum(a) - sum(b); 0 = reconciled; use `ledger.csv::col` cross-artifact binding |

## Forecasting (3)

| metric_id | binding tags | convention | definition |
|---|---|---|---|
| mape | prediction, target | mape (default) \| smape | mean(\|p-a\|/\|a\|); zero actual -> degenerate (no epsilon fudge); smape = mean(2\|p-a\|/(\|p\|+\|a\|)) |
| mase | prediction, target | m=`<season>` (1) | MAE scaled by in-sample naive-m MAE (Hyndman & Koehler) |
| pinball_loss | prediction, target | q=`<quantile>` (0.5) | mean(max(q(a-p), (q-1)(a-p))) (sklearn mean_pinball_loss) |

## Determinism notes

- Transcendental-bearing recipes (log_loss, ndcg, p_value, chi_square, confidence_interval,
  effect_size hedges_g) run on the deterministic kernels (`dlog`, `dexp`, `dlgamma`,
  `betainc_reg`, `gammainc_upper_reg`, `derfc`, bisection inverses) - built only from IEEE
  correctly-rounded primitives, bit-identical across platforms, validated to <=1e-11 of SciPy.
- pass_at_k is exact rational arithmetic (math.comb); mcc and chi-square tables use exact
  integer sums before the final float ops.
- All recipes propagate NaN to a degenerate INCONCLUSIVE - never a silent number.
