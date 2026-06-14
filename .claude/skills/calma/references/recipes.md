# Recipe catalog (422 recipes, all SOTA-validated)

Every recipe recomputes its number ONLY from raw machine-readable artifacts via the
reference-deterministic kernels in `numeric.py` (fsum / pairwise product / sqrt, plus the
deterministic transcendental kernels - never platform libm, never numpy). Every recipe is
validated against published reference implementations (scikit-learn, SciPy, NumPy, the
HumanEval pass@k estimator, the SQuAD eval normalizer, Guo et al. ECE) by
`tests/test_recipes_sota.py` over `assets/reference_vectors.json` (385 vectors, regenerable
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

## Quant risk & relative performance (13)

| metric_id | binding tags | convention | definition |
|---|---|---|---|
| volatility / downside_deviation | return | periods 252/365/52 | std (ddof=1) x sqrt(P); downside uses sqrt(mean(min(r,0)^2)) |
| sortino | return | periods | mean / downside-dev x sqrt(P), target 0, full-sample denominator |
| calmar | return | periods | CAGR-style annualized return / \|max drawdown\| (path-dependent) |
| value_at_risk / cvar | return | p95 (default) / p99 | historical: -quantile(r, 1-level); CVaR = -mean(tail). Loss-positive |
| win_rate / profit_factor / omega_ratio | return | omega: threshold=<frac> (0) | count(r>0)/n; sum gains/\|sum losses\|; sum max(r-t,0)/sum max(t-r,0) |
| beta / alpha | return, benchmark | alpha: periods | cov/var (ddof=1); alpha = (mean r - beta mean b) x P, rf=0 |
| information_ratio / tracking_error | return, benchmark | periods | mean(r-b)/std(r-b) x sqrt(P); std(r-b) x sqrt(P) |

## Classification & regression depth II (17)

| metric_id | binding tags | convention | definition |
|---|---|---|---|
| balanced_accuracy / cohen_kappa | prediction, label | - | mean per-class recall (sklearn); (po-pe)/(1-pe) exact marginals |
| specificity / jaccard | prediction, label | - | tn/(tn+fp); tp/(tp+fp+fn) |
| fbeta | prediction, label | beta=<v> (1) | (1+b^2)PR/(b^2 P+R); beta parsed from "F2"/"F0.5" claims |
| weighted_f1 | prediction, label | - | support-weighted per-class F1 (sklearn weighted, zero_division=0) |
| ks_statistic / gini_norm | score, label | - | max ECDF gap between class score distributions; 2*AUC-1 |
| msle | prediction, target | msle / rmsle | mean((ln(1+p)-ln(1+a))^2); values <= -1 degrade (sklearn) |
| medae / max_error / explained_variance | prediction, target | - | sklearn median_absolute_error / max_error / explained_variance_score |
| wape / forecast_bias | prediction, target | - | sum\|e\|/sum\|a\|; (sum p - sum a)/sum a |
| adjusted_r2 | prediction, target | REQUIRED: p=<predictors> | 1-(1-R2)(n-1)/(n-p-1); no predictor count -> degenerate |
| nrmse | prediction, target | mean (default) / range | RMSE normalized |
| durbin_watson | prediction, target | - | sum((e_t-e_{t-1})^2)/sum(e^2) on residuals (statsmodels) |

## Analytics & engineering depth II (13)

| metric_id | binding tags | convention | definition |
|---|---|---|---|
| column_min / column_max / column_std | value | std: ddof=1 / ddof=0 | min / max / sample std |
| iqr / outlier_count | value | k=<fence> (1.5) | q75-q25 linear; Tukey-fence count |
| mode_share | value *(string)* | - | most frequent cell share |
| gini_coefficient / hhi | value | - | sorted-rank Gini; sum((x/sum x)^2) |
| entropy | value *(string)* | bits (default) / nats | Shannon entropy of value counts |
| latency_p90 | duration | - | linear quantile at 0.90 |
| apdex | duration | REQUIRED: t=<seconds> | (satisfied + tolerating/2)/n; satisfied <= T, tolerating <= 4T |
| uptime_pct / cache_hit_rate | flag | - | nonzero flags / n |

## Statistical tests II (12)

| metric_id | binding tags | convention | definition |
|---|---|---|---|
| mann_whitney | sample_a, sample_b | - | tie-corrected, continuity-corrected asymptotic two-sided p (scipy) |
| ks_test | sample_a, sample_b | - | classical Kolmogorov asymptotic p (kstwobign; documented vs scipy's finite-n refinement) |
| anova | group *(string)*, value | p (default) / statistic | one-way F from raw rows; p via deterministic incomplete beta (scipy f_oneway) |
| proportion_z | sample_a, sample_b | - | pooled two-proportion z, two-sided (statsmodels) |
| fisher_exact | group *(string)*, outcome *(string)* | - | exact two-sided hypergeometric via integer combinatorics (scipy semantics) |
| odds_ratio / relative_risk | group *(string)*, outcome *(string)* | OR: sample / haldane | ad/bc (zero cell degrades); (a/(a+b))/(c/(c+d)) |
| cramers_v | group *(string)*, outcome *(string)* | - | sqrt(chi2_nc/(n min(r-1,c-1))) |
| skewness / kurtosis | value | - | biased g1; biased excess g2 (scipy defaults) |
| jarque_bera | value | p (default) / statistic | n/6(S^2+K^2/4); p via chi2(2) |
| autocorrelation | value | lag=<k> (1) | biased ACF at lag (statsmodels) |

## Retrieval / LLM evals II (4)

| metric_id | binding tags | convention | definition |
|---|---|---|---|
| precision_at_k | query, rank, relevance | k=<int> (10) | relevant-in-top-k / k, averaged over queries |
| map_at_k | query, rank, relevance | k=<int> (10) | AP@k with min(R,k) denominator (documented), zero-relevant skipped |
| perplexity | value (logprobs) | - | exp(-mean(logprob)), natural log; positive logprobs degrade |
| wer | prediction *(string)*, reference *(string)* | wer (default) / cer | corpus Levenshtein edits / reference tokens (jiwer) |

## Determinism notes

- Transcendental-bearing recipes (log_loss, ndcg, p_value, chi_square, confidence_interval,
  effect_size hedges_g) run on the deterministic kernels (`dlog`, `dexp`, `dlgamma`,
  `betainc_reg`, `gammainc_upper_reg`, `derfc`, bisection inverses) - built only from IEEE
  correctly-rounded primitives, bit-identical across platforms, validated to <=1e-11 of SciPy.
- pass_at_k is exact rational arithmetic (math.comb); mcc and chi-square tables use exact
  integer sums before the final float ops.
- All recipes propagate NaN to a degenerate INCONCLUSIVE - never a silent number.

## Compiled recipes (pack C: the recipe compiler)

Compiled recipes are drafted offline as DSL compositions of the kernels above
(`references/recipe-draft.schema.json`) and admitted by the deterministic gate in
`scripts/compiler.py`: differential testing against the named reference implementation in the
reference venv, the declared metamorphic relations, degeneracy checks, and a bit-stability
double-run. Each ships frozen under a content hash in `assets/compiled_recipes.json` with
`set_maturity: compiled-validated` and its differential vectors pinned (they re-validate
pure-stdlib in `tests/test_compiler.py`).

- **sem** - standard error of the mean: `fstd(value, ddof=1) / sqrt(n)`. Reference:
  `scipy.stats.sem(ddof=1)`. Binding: one numeric `value` column. Metamorphics: permutation-
  invariant, scales linearly, shift-invariant, >= 0.
- **coefficient_of_variation** - relative dispersion: `fstd(value, ddof=1) / fmean(value)`.
  Reference: `scipy.stats.variation(ddof=1)`. Binding: one numeric `value` column. Metamorphics:
  permutation-invariant, SCALE-invariant, >= 0 on positive data.

## Quant-risk depth (Pack QR, 25)

Binding `return` (relative-performance metrics also bind `benchmark`). Drawdown metrics use the
engine convention: equity peak floored at initial capital 1.0 (matching `max_drawdown`). Moments
use scipy defaults (biased skew g1, biased excess kurtosis g2). Validated by
`tests/test_recipes_sota.py` against NumPy/SciPy reference values.

| metric_id | binding | convention | definition |
|---|---|---|---|
| ulcer_index / pain_index | return | - | √(mean(ddₜ²)) ; mean(\|ddₜ\|) over the drawdown series |
| martin_ratio | return | periods | annualized return / ulcer index (Ulcer Performance Index) |
| recovery_factor | return | - | total return / \|max drawdown\| |
| gain_to_pain_ratio | return | - | sum(r) / \|sum(r<0)\| (Schwager) |
| tail_ratio | return | - | \|p95\| / \|p05\| of returns |
| gain_loss_ratio / win_loss_ratio | return | - | mean(r>0)/\|mean(r<0)\| ; count(r>0)/count(r<0) |
| kelly_criterion | return | - | W − (1−W)/R ; W=wins/(wins+losses), R=avg win/\|avg loss\| |
| upside_deviation | return | periods | √(mean(max(r,0)²)) × √periods |
| upside_potential_ratio | return | - | mean(max(r,0)) / √(mean(min(r,0)²)) (target 0) |
| kappa_three | return | - | mean(r) / (mean(max(−r,0)³))^(1/3) (Kaplan-Knowles) |
| cdar | return | p95/p99 | mean of drawdowns at/beyond the (1−level) drawdown quantile (Chekhlov-Uryasev) |
| max_drawdown_duration | return | - | longest consecutive run below the running peak (periods) |
| parametric_var / parametric_es | return | p95/p99 | Gaussian VaR −(μ+Φ⁻¹(1−α)σ) ; ES −(μ−σφ(z)/α) |
| cornish_fisher_var | return | p95/p99 | Gaussian VaR with the Cornish-Fisher skew/kurtosis z-expansion |
| adjusted_sharpe_ratio | return | - | SR·(1+(S/6)SR−(K/24)SR²) per-period (Pézier-White) |
| probabilistic_sharpe_ratio | return | - | Φ((SR−SR*)√(T−1)/√(1−g₃SR+((g₄−1)/4)SR²)) (Bailey-LdP) |
| up_capture_ratio / down_capture_ratio | return, benchmark | - | mean(r\|b>0)/mean(b\|b>0) ; mean(r\|b<0)/mean(b\|b<0) |
| capture_ratio | return, benchmark | - | up-capture / down-capture |
| treynor_ratio | return, benchmark | periods | annualized mean return / β (rf=0) |
| r_squared | return, benchmark | - | pearson(r,b)² |
| active_return | return, benchmark | periods | mean(r−b) × periods |

## Statistics & hypothesis tests (Pack ST, 8)

Validated against SciPy / statsmodels.

| metric_id | binding | convention | definition |
|---|---|---|---|
| point_biserial | binary, value | - | Pearson r between a 0/1 and a continuous column (SciPy pointbiserialr) |
| kendall_tau | x, y | - | tau-b, tie-corrected concordant/discordant pairs (SciPy kendalltau) |
| theil_sen_slope | x, y | - | median of all pairwise slopes (SciPy theilslopes) |
| cliffs_delta | sample_a, sample_b | - | (#(a>b)−#(a<b))/(nₐn_b) ordinal effect size |
| rank_biserial | sample_a, sample_b | - | 1 − 2U/(n₁n₂) from Mann-Whitney U (Wendt) |
| eta_squared | group, value | - | SS_between / SS_total (one-way) |
| g_test | group, outcome | p/statistic | 2·Σ O·ln(O/E), χ²((R−1)(C−1)) (SciPy log-likelihood, no continuity) |
| mcnemar | sample_a, sample_b | - | (\|n₁₀−n₀₁\|−1)²/(n₁₀+n₀₁), χ²(1) (statsmodels asymptotic) |
