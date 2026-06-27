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

## Tiers

| | **Free** | **Pro / Team** (paid) | **Enterprise** |
|---|---|---|---|
| Repos | public only | + private | + BYOC / on-prem |
| Discovery (static layer) | unlimited-ish | unlimited | unlimited |
| **Deep verify** | a monthly **sandbox-minute budget** (scoped claims) | a larger budget + data-connect | custom + **GPU tier** |
| Concurrency | 1 scan at a time | N parallel | pooled, SLA |
| Connectors | GitHub | + GitLab, warehouses, MLflow/wandb | + private connectors |
| Proof / audit | basic report | signed proofs | signed proofs + retention + SSO |
| Price | $0 (subsidised) | usage-metered over an included budget | contract |

**Why pay:** one wrong number costs far more than the tool — a trade, a deployed model, an LP report. Paid
is where wrong numbers cost real money (private repos, connected data, scoped-but-heavy deep verify, GPU).

**Free is a funnel, not charity:** free = *discovery on any public repo* (cheap, the static layer always
lights up) + a *capped* deep-verify budget. The expensive part (re-execution) is the thing the budget meters.

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
3. Where GPU sits — its own SKU vs a multiplier on sandbox-minutes.
4. Exa/HelixDB as COGS — both amortised by the flywheel; an enterprise Exa deal (founder note) lowers the
   synth tail further.
5. The benchmark proof: *deterministic / ~$0 / 0% false-confirm vs an LLM-agent's stochastic / ~$5 /
   coin-flip* is the value anchor for any price.
