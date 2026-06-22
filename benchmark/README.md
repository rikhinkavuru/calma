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

### The fourth arm: a code-running agent (`agent-with-exec`)

The LLM-judge above gets **no code execution** — the realistic *eval* condition. The honest question is what
survives once an agent *can* run code. `benchmark/run_agent.py` gives a frontier agent the same data plus a
`run_python` tool, **K times per case**, steelmanned with an explicit "recompute **and** check validity"
prompt. Its tool code runs in **Calma's own verified network-off sandbox** (Seatbelt / bubblewrap; a planted
secret-read and an egress attempt must both fail) — a host that can't verify isolation **drops** those runs
rather than execute untrusted code unsandboxed.

The point isn't raw catch-rate — a strong agent recomputes most simple numbers correctly. It's the residual
gaps a deterministic checker doesn't have, which `score.py` folds in automatically once `results/agent.json`
exists:

| metric | what it exposes | agent-with-exec (measured) | Calma |
|---|---|---|---|
| **verdict-instability** | % of cases whose verdict flips across the K reruns | **10%** (Haiku) · **52%** (GPT-4o-mini) | **0** (by construction) |
| **pass^k curve** | P(k i.i.d. runs all land on the right verdict); the pass^1 → pass^k drop is the consistency cliff | **0.88 → 0.84 → 0.82** (k=1→3, Haiku) | **1.0, flat** |
| **validity-blindness** | on the leakage / overfit / realism / contamination cut the number *reproduces*, so a recompute-only agent says "honest" and misses the invalidity | **catches 17%** (Haiku) · **50%** (GPT-4o-mini) of the 12-case cut | **INVALIDATES it (100%)** |
| **agreement-with-Calma · cost · latency** | how often it matches the deterministic verdict, at what $ and wall-clock | **89% agree · $5.13 · ~38 s p50** (Haiku) | **~0.21 s · $0 · offline** |

A second model from a **different family** (a GPT/o-series model alongside Claude) runs as a cross-arm
(`agent_cross.json`) to kill the single-model artifact + self-preference bias. Every counted run is
network-off-isolated; every transcript (system prompt → tool calls → tool output → final answer) is written
to `results/agent_transcripts/`, so nothing is hand-picked.

**Measured** (steelmanned, k=3, two model families — Claude Haiku 4.5 + GPT-4o-mini — over the live
129-case manifest, 774 runs, $5.75 total). On raw accuracy the code-running agent is strong: **84% catch,
0 false alarms, 95% on the reproducibility cut** (Haiku), genuinely approaching Calma's recompute — so the
edge is **not** "more accurate than an agent." It is the three axes a stochastic judge cannot close:

- **Determinism.** The agent's verdict *flips across identical reruns* on **10%** of cases (Haiku) and
  **52%** (GPT-4o-mini); pass^k slides **0.88 → 0.82** by k=3. Calma is **0% / 1.0-flat by construction.**
  *You can't put a coin-flip in a merge gate.*
- **Validity-blindness.** On the 12-case validity cut the number *reproduces*, so the agent recomputes it,
  says "honest," and catches only **17%** (Haiku) / **50%** (GPT-4o-mini) — vs Calma's **100%** (it
  INVALIDATES them by construction).
- **Cost + latency.** **$5.13** and a **~38 s** p50 per verdict (Haiku), vs Calma's **$0** incremental and
  **~213 ms** — and Calma emits a signed, offline-replayable proof the agent can't.

Agreement-with-Calma is **89%** (Haiku) / **74%** (GPT-4o-mini): where they disagree, it is the agent that
is stochastic or validity-blind, not Calma.

> **Recorded vs reproducible.** The 117-case three-arm table above is a committed, recorded result. The agent
> arm is the **reproducible methodology** — run the command in *Reproduce* below on your own API keys to
> generate the live spread (it costs real tokens, so it is not part of the offline suite). `--mock` validates
> the plumbing with zero network.

**Why a recompute, not a score.** A *score* can be gamed outright: in 2026 a UC Berkeley team built an agent
that hit **~100% on six agentic benchmarks** (SWE-bench, WebArena, GAIA) **without solving a single task**, by
gaming the grader — a planted `conftest.py` makes every test report as passing. A number *recomputed from the
raw outputs* has no grader to game; and even a sandboxed, code-running agent, as this arm measures, stays
stochastic and validity-blind. Calma is neither.

## Honest caveats

- The LLM-judge is the realistic *eval* condition (no execution). A code-running agent (the fourth arm,
  **measured** above) **does** approach Calma on raw accuracy — 84% catch, 95% on the reproducibility cut —
  but not on the axes a gate needs: it is stochastic (verdict-instability **10%** Haiku / **52%**
  GPT-4o-mini vs Calma's 0%), validity-blind (catches **17–50%** of the validity cut vs Calma's 100%), and
  costs **$5.13** at a **~38 s** p50 vs Calma's **$0 / ~213 ms** — with no signed, offline-replayable proof.
  The win is determinism + $0 + sub-second + a replayable proof, not a higher catch-rate.
- Data-validation tools (Great Expectations / pandera) check schemas and ranges, not whether a
  *claimed metric* recomputes — they would catch ~0 of these by construction (not run here).
- Calma's recipes are themselves validated against 385 byte-reproducible reference vectors from
  published implementations (`assets/reference_vectors.json`) — independent of this benchmark.
- **Validity-cut extension (opt-in):** `python3 benchmark/gen_validity_cases.py` adds two cases for the
  families shipped this cycle — **era-embargo** (an un-purged Numerai split) and **risk-sim
  simulation_assumptions** (a double-liquidation-per-block invariant violation), in `cases/emb_a` and
  `cases/sim_a`. Each is constructed so the headline **number reproduces** (recompute-only and the LLM
  judge call it *honest*) while **Calma INVALIDATES** it. With them the validity cut becomes **14 cases
  across 10 families**; Calma catches **14/14**, recompute-only and the judge **0/14**. The committed
  published results above stay at the established run; re-run the arms + `score.py` after generating to
  fold the two cases in.

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

# OPTIONAL fourth arm - a code-running agent (needs API keys + a host with a verified sandbox; --mock
# runs an offline plumbing check only). Folds verdict-instability / pass^k / agreement-with-Calma /
# validity-blindness / cost / latency into the tables across >=2 model families:
ANTHROPIC_API_KEY=... OPENAI_API_KEY=... python3 benchmark/run_agent.py --k 5 --models claude-opus-4-8,gpt-5
python3 benchmark/score.py                          # re-score WITH agent.json + agent_cross.json folded in
```
