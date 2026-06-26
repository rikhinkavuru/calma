# Explanation — why Calma works the way it does

This page is for understanding, not for doing. It explains the design choices that make a Calma
verdict mean something: why it **recomputes** instead of re-reading the reported number, why the
verdict comes from **deterministic scripts** rather than a model, what the **validity layer**
adds on top of reproducibility, the **data-authenticity ceiling** the product refuses to claim
past, and the **threat model** it defends.

---

## Why recompute, instead of reading the diff or trusting the score

Every dashboard, paper, and pitch deck reports a number. Almost none can be independently checked
without trusting whoever produced it — and AI agents make this worse, because they now generate
the backtests, the evals, and the "tests pass," and they are confidently wrong at scale. The
expensive failures come from a number that was **technically reproducible but not valid**: a
model that leaked its test set, a fund that allocated on an inflated Sharpe.

There are three things you can do with a reported number, and only one of them holds up:

1. **Trust it.** Free, and worthless against an adversary or an error. On Calma's own
   head-to-head benchmark, trusting the reported number caught **0 of 77** wrong results.
2. **Reason *about* it.** Read the diff, or ask an LLM-as-judge whether the result *looks* right.
   This reasons about a result without re-deriving it — so it inherits whatever the result claims.
   The LLM judge **silently confirmed 14 wrong numbers** and caught only ~82% of cases.
3. **Re-derive it.** Re-run the work and recompute the number from the raw output files. There is
   no reported score left to game. Calma caught **77 of 77**, with zero false confirms.

The clearest demonstration of why "reason about it" fails: in 2026 a UC Berkeley team built an
agent that scored **~100% on six major agentic benchmarks** — SWE-bench, WebArena, GAIA —
*without solving a single task*. On SWE-bench it dropped a `conftest.py` that makes the grader
report every test as passing; on WebArena it read the gold answer straight off a `file://` URL.
The score was perfect; the work was never done. Reading the diff doesn't catch that, and neither
does asking a model whether the result looks plausible — both consume the very artifact that lies.
Re-executing the work and recomputing the number from the raw outputs is the only method with
nothing left to fake.

This is the one act almost nobody else performs: **recompute the claimed number from the raw
outputs, and separately check that the result is sound.** Those are two different questions, and
the rest of this page is about answering both honestly.

---

## Why the verdict is a deterministic function, not a model

The label is produced by one total pure function (`verdict.py`) that maps a fully-specified input
vector to one verdict. Two properties follow, and both matter:

- **Non-gameable.** The verdict function is imported by *both* the emitter and the gate, and the
  gate re-derives every label byte-for-byte from the stored `verdict_inputs`. A hand-edited or
  model-authored verdict cannot pass — the re-derivation would not match. A stamp can't be faked,
  *even by Calma*. This is why it works as a guardrail you can't talk your way past, even when
  it's checking your own agent's work: there is no prompt that changes arithmetic.
- **Conservative by construction.** Missing information degrades the verdict toward `INCONCLUSIVE`
  (Can't tell), never toward an accidental `CONFIRMED` or `REFUTED`. A `REFUTED` is heavily
  guarded — it requires independent binding, controlled-to-bit determinism, and the claim falling
  outside the recompute's confidence interval — so the loud verdict is the trustworthy one.

LLMs appear in Calma only at the edges, where they *propose* and can never *dispose*: extracting
claims from messy artifacts, drafting verify contracts, synthesizing new recipes, repairing a
broken result. In every case the deterministic core has the final say (a synthesized recipe is
admitted only when it reproduces the reference vectors to 1e-9; a repaired result is accepted only
when the recompute independently flips it clean). The `edges/` package is firewalled from the
verdict core, enforced by a test that fails if a transport or a validity detector imports a model.

---

## Reproducibility is not validity — the validity layer

A number can recompute *perfectly* and still be wrong, because reproducibility (the number
re-derives) and validity (the result is sound) are different questions. dbt tests, Pandera
schemas, snapshot diffs, and LLM-eval harnesses all confirm a number is *internally consistent* —
none confirm it is *correct*. Calma ships an integrated validity layer (pure stdlib, bit-stable)
whose detectors only ever **degrade** a verdict, grouped into families. The headline families:

- **Leakage** — row / id / temporal look-ahead / target leakage between train and test, plus a
  leakage-corrected re-run.
- **Overfitting** — the Deflated Sharpe (Bailey–López de Prado), PBO via CSCV, and the
  deflated-AUC selection-overfit haircut. The number of trials is never guessed.
- **Regime / walk-forward** — an in-sample → out-of-sample edge collapse, corroborated by a
  two-sample KS regime shift.
- **Execution realism** — fees / slippage / borrow / financing + Almgren √ market-impact, a
  net-of-friction re-run, and capacity. A gross number sold as net is caught here.
- **Statistical plausibility** *(thin-input)* — the one family that fires with no declared block,
  soft-only: an implausibly-high Sharpe, a too-smooth (serial-correlation) equity curve, a
  regime-drift non-stationarity smell, an undeclared-split leakage smell, a train/test loss-gap
  overfit smell. Each names the exact block to declare for an authoritative verdict.

Further families cover contamination (exact eval-in-corpus sha256 + near-duplicate MinHash/LSH),
backtest soundness, point-in-time / look-ahead, data-snooping (study-wide multiple testing),
model-process leakage, distributional shift, era-embargo / purged-CV (tournament), and risk-sim
assumptions (DeFi). Two diff-time guards sit alongside them and fire on a number that recomputes
exactly: the **trivial-baseline edge** (a 92%-accuracy model is worthless if 92% of rows are one
class) and **eval contamination** (a "held-out" benchmark whose items are already in pretraining).

The design rule is strict: each detector can only **degrade** a verdict, never inflate one.
`INVALIDATED` fires only under a scope-guard — when the claim *positively asserts* the clean
property the data violates (e.g. a "zero-shot held-out" claim against a contaminated corpus).
And **validity depth scales with what you declare.** A thin-input result with nothing declared
gets the soft plausibility layer only (it can reach `CONFIRMED-WITH-CAVEATS`, never
`INVALIDATED`). This is why the "not verified" list on every verdict matters — it names exactly
which families did *not* run because no scope was declared. Calma never guesses a scope that could
flip a verdict.

---

## The data-authenticity ceiling

Calma is honest about what it does *not* prove, and prints that ceiling on every verdict. A
`CONFIRMED` means the headline number **re-derives from the raw outputs and is internally sound
under the stated scope.** It is **not**:

- a guarantee of real-world correctness, future performance, or investment merit (it is not
  investment advice);
- a claim that the *upstream input data is authentic or untampered* — Calma content-hashes the
  inputs it was given; it does not independently source market or return data. A program that
  deterministically fabricates its own raw outputs will reproduce. Calma checks the number against
  the outputs, not the outputs against reality;
- an assessment of any validity family the producer did not declare.

These limits are structural, not a disclaimer bolted on: they ship inside the product as the
IDD/ODD report's fixed L1–L3 limitations and the input-lineage attestation's `does_not_prove`
block, so the deliverable cannot over-claim. The honesty is the point — it is what lets a verdict
be trusted at all.

---

## The threat model — and where the bytes go

Calma's load-bearing fact: it runs **untrusted code offline (network-off) in a sandbox**, with
**raw data that never leaves the customer environment** in the BYOC / on-prem path. Only the
**verdict + proof + metadata** egress.

- **Re-execution is sandboxed and network-denied in two layers** (a provider flag plus a host
  deny). A planted secret-read *and* an egress attempt must both fail, proven by an in-sandbox
  self-test before the tier is stamped. Verified own-code tiers are Seatbelt (macOS) and bubblewrap
  (Linux); untrusted counterparty code escalates to a network-denied Docker container or a remote
  Firecracker microVM, and the run **refuses** (exit 3) rather than silently dropping isolation.
  The ledger always records the tier actually achieved.
- **Recompute happens host-side, outside the sandbox**, reading the raw output files. The verdict
  is decided by code there, never by a model.
- **Only metadata egresses** — the verdict, the recomputed number, hashes, validity results, and
  a signature. Raw data is redacted by construction: the published-record schema is a metadata-only
  whitelist that fails closed on any non-whitelisted key. If the control plane were fully
  compromised, an attacker would get hashes and verdicts, never raw data.

The hosted cloud path is stated honestly: there the raw bundle *does* transit to Calma to be
re-executed, but it is **deleted immediately after the run** — no-retention, not non-transit —
and only hashes + verdict + proof persist. The four controls behind all of this are runnable
(`make controls`): sandbox isolation, egress-blocked, no-raw-data-retention, and verdict-integrity.
See [`TRUST.md`](TRUST.md) for the full data-flow and the security-questionnaire mapping.

Running untrusted adversarial code *creates* one new burden — "prove the boundary holds" — which
Calma answers with continuous evidence (controls #1/#2), a microVM (not container) choice for the
hosted tier, and an annual pentest. It does not pretend the architecture relieves the ordinary
corporate-hygiene domains (IAM, change-management, incident response); those are policy work, done
separately.

---

## In one paragraph

Calma re-derives the number instead of trusting or reasoning about it, so there is no score left
to game; it decides with a deterministic function the gate re-checks byte-for-byte, so the verdict
can't be faked even by Calma; it separates *reproducible* from *valid* and only ever degrades a
verdict on a validity concern, declaring exactly what it did and did not check; and it prints the
ceiling — recompute, not authenticity or semantic correctness — on every verdict, because the
honesty is what makes the verdict worth trusting.

## See also

- [Reference](reference.md) — the verdict semantics, the exit codes, the full command surface.
- [`TRUST.md`](TRUST.md) — the data-flow architecture and the four runnable controls.
- [`extending.md`](extending.md) — the eval-gated contract for adding a metric or a validity family.
- [The benchmark](../benchmark/README.md) — the reproducible head-to-head corpus behind the numbers above.
