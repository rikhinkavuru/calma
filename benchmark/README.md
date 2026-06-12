# Calma benchmark — can you catch a wrong number?

A reproducible benchmark for the one job that matters: given a computational result and a *claimed*
headline number, decide whether the claim is **honest** (matches what the data actually yields) or
**flawed** (materially wrong). It compares three approaches on the same labeled corpus:

| approach | what it does |
|---|---|
| **trust-the-number** | the status quo — believe the reported number |
| **LLM-as-judge** | the common "ask an LLM whether this result looks right" eval — reasons over the data + claim, **no code execution** |
| **Calma** | re-executes the project and **recomputes** the metric from the raw outputs on deterministic kernels |

## Corpus

`gen_corpus.py` builds **36 cases** (12 honest + 12 *obvious* flaws + 12 *subtle* flaws) across 12 datasets
spanning classification (accuracy, precision, recall, f1, auc), quant (total_return, sharpe), regression
(rmse, mae, r2), and analytics (column_sum, column_mean). Every dataset is 500–1000 rows of deterministic,
pure-stdlib data; the **true** value is computed by an *independent* pure-Python oracle (not Calma's
kernels). Two flaw tiers:
- **obvious** — a large overclaim a reviewer could catch by eyeballing a sample (e.g. accuracy +0.12).
- **subtle** — small but real (e.g. accuracy +0.05, sum +4%): beyond Calma's statistical band so it
  deterministically refutes, yet inside the noise of eyeballing a 150-row sample.

The LLM-judge sees an **anonymized** case (opaque id, the metric, the claim, and a ≤150-row sample of the
output) — no generator code, no labels, with sibling variants shuffled across batches (`prep_judge.py`).

## Results (recorded run; `results/summary.json`)

```
method                    catch%   caught   MISSED FALSE-AL  abstain
trust-the-number              0%     0/24       24        0        0
LLM-as-judge (no exec)       71%    17/24        7        3        0
Calma                       100%    24/24        0        0        0
```
- **MISSED** = a flawed claim called honest (**false-confirm** — the dangerous error that launders a wrong number).
- **FALSE-AL** = an honest claim called flawed (**false-alarm** — cries wolf).
- **abstain** = a safe non-answer (CAN'T-CONFIRM); never a wrong verdict.

**Calma catches every flawed claim (100%) with zero false-confirms and zero false-alarms.** The LLM-judge
catches fewer (71%) and, worse, is **wrong 10 times in two directions** (7 false-confirms + 3 false-alarms):
it both blesses fabricated numbers and rejects honest ones — and *you can't tell which of its calls to
trust*. trust-the-number (the status quo) launders all 24 fabrications.

### By flaw tier

```
method                  obvious   subtle   false-alarm
LLM-as-judge (no exec)      83%      58%        3
Calma                      100%     100%        0
```

The gap widens on **subtle** flaws (a few points off — rounding in your favor): the judge catches ~58% of
them by eyeballing a sample (often by luck, with false-alarms), while Calma's deterministic recompute
catches **100%** with no false-alarms. (Flaws *within* Calma's statistical band are correctly CONFIRMED —
it is statistically honest, not infinitely sensitive; the subtle tier here uses fixed small margins that
sit just beyond the band yet inside eyeballing noise.)

Latency: Calma re-executes + recomputes each case with a **p50 of ~220 ms** (`results/calma.json`).

## Honest caveats

- The LLM-judge is the realistic *eval* condition (no execution). A judge **allowed to write and run code**
  would approach Calma's accuracy — but that is just re-execution without Calma's determinism, zero-false
  guarantees, isolation, and signed/replayable proof; it is not the "LLM-as-judge" baseline people deploy.
- **Data-validation** tools (Great Expectations / pandera) check schemas and value ranges, not whether a
  *claimed metric* recomputes — they would catch ~0 of these by construction (not run here).

## Reproduce

```bash
python3 benchmark/gen_corpus.py     # build the labeled corpus (deterministic) + manifest.json
python3 benchmark/run_calma.py      # Calma over the corpus -> results/calma.json
python3 benchmark/prep_judge.py     # anonymized judge batches -> judge_batches/ + judge_map.json
#   run the LLM-as-judge on each judge_batches/batch_*.json (no code execution) -> results/judge_batch_*.json
python3 benchmark/score.py          # three-way comparison -> table + results/summary.json
```
