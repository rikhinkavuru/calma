# Calma — pricing & rate limits (working model)

> The economic reality (rebuild guide §11): unlike near-zero-marginal-cost SaaS, **Calma re-executes the
> world's computations.** Every deep verify burns **sandbox compute (+ GPU for ML) + LLM/Exa inference.**
> Cost-per-scan is real and is the central variable. The free tier must be subsidised; the business is
> infra-heavy. That's not a flaw — it's the moat — but it means pricing and rate limits are a core part of
> the architecture, not an afterthought.

## What a scan actually costs

| Stage | Cost driver | Rough magnitude |
|---|---|---|
| Ingest (clone @ commit) | egress + disk | ~$0 |
| **Discover** (claims, static) | one LLM pass over README/results | ~$0.001–0.01 — cheap, runs on *any* repo |
| **Build-runnable** | pip / repo2docker, cached per stack | minutes the *first* time, ~$0 cached |
| **Sandbox execute** (deep verify) | **E2B microVM minutes (× k runs)** + GPU if ML | **the big one** — seconds-to-minutes of isolated CPU, more for GPU |
| **Recompute** | pure-stdlib / a banked formula | ~$0 |
| **Synthesize a novel formula** | 1 LLM synth + 1 Exa lookup, **once per metric ever** | ~$0.02, then **$0 forever** (banked in HelixDB) |

**The flywheel is also a cost curve.** Two of the moats directly *cut* cost-per-scan as volume grows:
- **Catalog flywheel (HelixDB):** a metric is synthesised + validated **once**, then every future repo that
  reports it gets an instant vector hit — no LLM, no Exa, no re-validation. Coverage compounds; per-scan
  inference cost trends to zero.
- **Reproduction flywheel:** a stack made runnable once yields a cached run-plan / image — the next similar
  repo builds in ~0. Reproduction *rate* rises and build *cost* falls together.

So month-18 cost-per-scan is structurally below month-1. Watch **cost-per-scan** and the **subsidised-free
ratio** as the core health metric.

## Shape: open-core, not pure-OSS or pure-proprietary

The cost table above decides the model. What's **cheap / commoditizable** (the recompute engine — catalog,
three-way diff, validity detectors; pure-stdlib, ~$0 to run) we **open-source**: secrecy isn't the moat
(re-executing to ground truth is the defense, not hiding the formulas), and OSS builds the trust,
distribution, and verification-corpus flywheel that *are* the moat. What's **expensive / defensible** (hosted
sandbox/GPU compute, private data, continuous gating, trusted artifacts) is **paid**. So: open-source the
engine; charge for the hosted/continuous/compliance layer. Neutrality, the proprietary verification corpus,
hosted reproduction at scale, and trusted attestation stay the edge regardless of the code being open.

## Tiers

| | **OSS / CLI** | **Free (hosted)** | **Pro / Team** | **Enterprise** |
|---|---|---|---|---|
| Price | $0 (open-source) | $0 (subsidised) | ~$20–50/user/mo *or* $99–299/mo flat + metered overage | contract, ~$1k–10k+/mo |
| What | the engine as a library + CLI: recompute from committed artifacts + local runs, validity checks | connect a repo, capped verifies/day, top-K claims, CPU, public repos | private repos, bigger budget, **CI / merge-gate**, connectors, history/retention, signed proofs | **GPU verification**, SSO/RLS/roles, SLAs, **audit/compliance pack + transparency log**, **neutral third-party attestation**, dedicated capacity, BYOC/on-prem |
| Compute | BYO (runs on your machine) | a monthly **sandbox-minute budget** | larger budget + data-connect | pooled + GPU |
| Why it sits here | zero COGS for us; pure adoption + trust + corpus flywheel | the funnel — marginal cost is sub-cent/scan, cheap to subsidise; the gate caps abuse | the dev/agent-CI + quant-team buyer; recurring value in the deploy path | the wrong-number-costs-millions buyer (LP/board/regulator), real GPU COGS + compliance |
| **Usage add-ons** (metered) | — | — | extra sandbox-minutes | + GPU-minutes, large-repo/long-run budgets, extra connectors |

**Why these prices hold — value-anchored, not cost-plus.** Marginal cost is *cents per scan* (E2B
sandbox-seconds; see above), but the buyer's alternative — one wrong number reaching a trade, a shipped model,
an LP report, or an audit — is **thousands to millions**. A single caught error pays for Pro for years, so
tens-of-dollars (Pro) and thousands (Enterprise) are trivially justified. COGS only sets the *floor* and the
*meter* (sandbox-minutes); value sets the price.

**Free is a funnel, not charity:** free = *discovery on any public repo* (cheap, the static layer always
lights up) + a *capped* deep-verify budget. The expensive part (re-execution) is the thing the budget meters.

## Expensive additions worth gating (ranked by margin + defensibility)

1. **Neutral third-party attestation / registry** — highest margin, least replicable. An in-house tool *can't*
   be neutral; barely costs us anything to produce. The enterprise wedge.
2. **GPU verification** — real COGS, unlocks the ML/LLM-eval segment. A priced tier (its own SKU and/or a
   GPU-minute add-on); exact pricing TBD.
3. **Continuous CI / merge-gate** — recurring, sticky, high willingness-to-pay (sits in the deploy path).
4. **Signed proofs + transparency log + retention/audit** — the compliance / "SOC-2-for-backtests" layer.
5. **Private repos + data connectors**, and **higher sandbox / concurrency / large-repo budgets**.

## Rate limits (admission control — fail closed)

Enforced at the runner's admission gate, before a sandbox is provisioned:

- **Scan quota** per tier (scans / day) and **claim cap** per scan (free scans deep-verify the top-K
  highest-stakes claims, not all 634 — discovery still lists them all).
- **Sandbox-minute budget** per tier per month — the real meter (deep verify draws it down; discovery
  doesn't). At the ceiling → deep verify is refused with "upgrade / out of budget", discovery still runs.
- **Concurrency cap** — parallel sandboxes per tenant (warm-pool bounded; CWE-770 guardrail).
- **GPU gating** — GPU repos require the GPU tier; otherwise routed to the "needs GPU" couldn't-reproduce
  taxonomy.
- **Per-sandbox hard caps** — wall-clock, memory, egress-denied, ephemeral (already in the runner).

Pricing meters the **sandbox-minute** because that's the COGS; everything cheap (discovery, recompute,
banked formulas) stays generous to keep the funnel wide.

## Open decisions (for the founder)

1. Free-tier sandbox-minute budget (sets the subsidy burn) — start tight, loosen as cost-per-scan falls.
2. Usage-metered vs flat Pro — likely a flat included budget + metered overage on sandbox-minutes.
3. ~~Where GPU sits~~ — DECIDED: a **priced tier** (Enterprise + a GPU-minute add-on). Exact pricing TBD
   when GPU verification ships; until then GPU repos route to the "needs-GPU" couldn't-reproduce taxonomy.
4. Exact OSS license + scope — which of the engine/catalog is open (lean: the recompute engine + a core
   catalog open; the flywheel-banked breadth + hosted corpus stay the edge).
5. Exa/HelixDB as COGS — both amortised by the flywheel; an enterprise Exa deal (founder note) lowers the
   synth tail further.
6. The benchmark proof: *deterministic / ~$0 / 0% false-confirm vs an LLM-agent's stochastic / ~$5 /
   coin-flip* is the value anchor for any price.
