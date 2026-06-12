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
Calma                        58%    14/24        0        0       10
```
- **MISSED** = a flawed claim called honest (**false-confirm** — the dangerous error that launders a wrong number).
- **FALSE-AL** = an honest claim called flawed (**false-alarm** — cries wolf).
- **abstain** = a safe non-answer (CAN'T-CONFIRM); never a wrong verdict.

**The point isn't the raw catch rate — it's the error columns.** The LLM-judge catches more headline-wise
(71%) but is wrong **10 times in two directions** (7 false-confirms + 3 false-alarms): it both blesses
fabricated numbers and rejects honest ones, and *you can't tell which of its calls to trust*. Calma is
**never wrong** — 0 false-confirms, 0 false-alarms — it either catches the lie or abstains.

### Where Calma is designed to refute (classification + quant: 14 flawed, 7 honest)

```
Calma:      14/14 caught   0 false-confirm   0 false-alarm   (100% catch, incl. every subtle flaw)
LLM-judge:  10/14 caught   4 false-confirm   2 false-alarm
```

Calma's lower *overall* 58% is entirely **abstentions** on the value-family (rmse/mae/r2/sum/mean), where
it currently degrades a clear miss to CAN'T-CONFIRM rather than refuting (a known, conservative
limitation — see the repo's "remaining improvements"; closing it would push Calma toward ~100% catch with
the error columns still at zero). It is never a *wrong* answer.

Latency: Calma re-executes + recomputes each case with a **p50 of ~250 ms** (`results/calma.json`).

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
