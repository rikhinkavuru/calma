# Calma benchmark — can you catch a wrong number?

A reproducible benchmark for the one job that matters: given a computational result and a *claimed*
headline number, decide whether the claim is **honest** (matches what the data actually yields) or
**flawed** (materially wrong). Three approaches, same 117 labeled cases:

| approach | what it does |
|---|---|
| **trust-the-number** | the status quo — believe the reported number |
| **LLM-as-judge** | the common "ask an LLM whether this result looks right" eval — reasons over the data + claim, **no code execution** |
| **Calma** | re-executes the project and **recomputes** the metric from the raw outputs on deterministic kernels |

**Why recompute, instead of trusting the score?** Because a score is the thing that gets gamed. In 2026 a
UC Berkeley team built an agent that scored ~100% on six major agentic benchmarks (SWE-bench, WebArena,
GAIA) *without solving a single task* — on SWE-bench by planting a `conftest.py` that makes the grader
report every test as passing ([Wang et al., 2026](https://www.rdworldonline.com/how-a-berkeley-team-broke-8-major-ai-benchmarks-six-of-them-hit-100-without-solving-a-single-task/)).
The results below are the same lesson at metric scale: trust-the-number catches **0 of 77** planted wrong
numbers, and an LLM-as-judge **silently confirms 14** of them. You can't game a number recomputed from raw
outputs — which is the one thing Calma does and the other two don't.

## Corpus: 117 cases, 3 tracks, 29 metrics, 8 families

**Synthetic track (84 cases).** 28 deterministic pure-stdlib bases across classification (accuracy,
precision, recall, f1, auc, log_loss, brier, mcc, balanced_accuracy), retrieval/LLM-eval (pr_auc,
recall@5, mrr, exact_match), regression + forecasting (rmse, mae, r2, mape), quant (total_return,
sharpe, volatility, sortino, cagr), analytics (sum, mean, median), engineering (latency p95,
error_rate), and stats (pearson correlation). Every ground-truth oracle is **cross-validated against
the published reference implementation** — scikit-learn, SciPy, NumPy — to ≤1e-9 relative
(`validate_oracles.py`; recorded run: **28/28 exact** on scikit-learn 1.9.0 / SciPy 1.17.1 /
NumPy 2.4.6 — `results/oracle_validation.json`).

**External track (29 cases).** Real scikit-learn models on **recognized benchmark datasets** —
Breast Cancer Wisconsin (UCI), Optical Handwritten Digits (UCI), Wine (UCI), and the Diabetes
regression benchmark (Efron et al. 2004) — with 5-fold out-of-fold predictions (fixed seeds) frozen
to CSV. Ground truth is **scikit-learn's own metric** on those predictions (the canonical
implementation, version recorded in the manifest). Models are feature-restricted/regularized so
metrics land in the realistic model-card range rather than ceiling values.

**Real-world track (4 cases).** Cases with citable provenance: a replication of a **published
academic-correction case** (the civil-war RF leakage study — reported AUC ~0.97, leakage-corrected
~0.91; the claim under test is the published inflated number), a real BTC backtest that claimed
**+14,698%** (recomputes to −32.4% out-of-sample), and two real vendored GitHub repos
(sh-mukherjee/momentum-strategy, HilmiSamdya/btc-sma-backtest) with their honest numbers.

**Flaw tiers.** Each base carries an honest claim, an **obvious** flaw (a large misreport a reviewer
could catch by eyeballing a sample), and a **subtle** flaw (a few points / 4–10% — the way numbers
actually get shaded), with sign-aware direction (lower-is-better metrics get *under*-reported).
Where a dataset is too small for a subtle lie to clear the 95% sampling band (Wine, n=178), the
subtle tier is dropped — a refusal to refute a statistically indistinguishable claim is *correct*,
and the benchmark doesn't punish honesty.

**Anonymization.** The LLM judge sees opaque ids, the metric, the claim, and a ≤150-row sample —
no labels, no generator code, siblings shuffled across batches with different sample windows
(`prep_judge.py`).

## Results (recorded run; `results/summary.json`, `results/site_data.json`)

```
method                    catch%   caught   MISSED  FALSE-AL  abstain
trust-the-number              0%     0/77       77         0        0
LLM-as-judge (no exec)       82%    63/77       14        12        0
Calma                       100%    77/77        0         0        0
```
- **MISSED** = flawed claim called honest (**false-confirm** — the dangerous error that launders a wrong number)
- **FALSE-AL** = honest claim called flawed (**false-alarm** — cries wolf)

### By difficulty and by track

```
                          obvious   subtle   real-world   false-alarms     synthetic  external(UCI)  real-world
LLM-as-judge (no exec)       97%      68%        50%           12            80%/18w     89%/7w        50%/1w
Calma                       100%     100%       100%            0           100%/0w     100%/0w       100%/0w
                                                                            (catch% / wrong verdicts)
```

**The headline isn't the catch rate — it's the error columns.** The judge is strong on obvious
flaws (97%) but collapses where it matters: **68% on subtle shading, 50% on the real-world cases**,
and it was *wrong 26 times in two directions* — it both blessed fabricated numbers (14×) and
rejected honest ones (12×), and nothing in its output tells you which calls to trust. Calma caught
**every flaw on every track — including the published leakage case and the +14,698% backtest — with
zero wrong verdicts**, at a **p50 of ~216 ms** per verification.

## Honest caveats

- The LLM-judge is the realistic *eval* condition (no execution). A judge allowed to write and run
  code would approach Calma's accuracy — but that is re-execution without Calma's determinism,
  zero-false-verdict guarantees, sandbox isolation, and signed/replayable proof.
- Data-validation tools (Great Expectations / pandera) check schemas and ranges, not whether a
  *claimed metric* recomputes — they would catch ~0 of these by construction (not run here).
- Calma's recipes are themselves validated against 385 byte-reproducible reference vectors from
  published implementations (`assets/reference_vectors.json`) — independent of this benchmark.

## Reproduce

> **The committed results reflect the FULL 117-case run** (synthetic + external UCI/sklearn track +
> real-world), and they feed the tables above and the website (`results/summary.json`,
> `results/site_data.json`). Reproduce the full run with the steps below.
>
> **`make benchmark` is the synthetic-only quick track** (`gen_corpus.py → run_calma.py → score.py`,
> the 84 synthetic cases). Because it re-runs `score.py` over synthetic results alone, **it OVERWRITES
> the committed `results/summary.json` and `results/site_data.json` with synthetic-only numbers** and
> does NOT reproduce the published 117-case figures. Use it for a fast local Calma-side sanity check; do
> not commit its output. Run the full sequence below to regenerate the published numbers.

Full 117-case reproduction:

```bash
python3 benchmark/gen_corpus.py                     # synthetic track (deterministic, stdlib)
python3 -m venv /tmp/calma_bench_venv && /tmp/calma_bench_venv/bin/pip install numpy scikit-learn scipy
/tmp/calma_bench_venv/bin/python benchmark/external_track.py    # UCI/sklearn track + real-world entries
/tmp/calma_bench_venv/bin/python benchmark/validate_oracles.py  # oracle cross-validation report
python3.13 benchmark/run_calma.py                   # calma over all 117 (3.13: momentum deps need cp313 wheels)
python3 benchmark/prep_judge.py                     # anonymized judge batches
#   run the LLM-as-judge on each judge_batches/batch_*.json (no code execution) -> results/judge_batch_*.json
python3 benchmark/score.py                          # tables + summary.json + site_data.json (full 117-case)
```
