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

## Tiers — at a glance

| | **OSS / CLI** | **Free (hosted)** | **Pro / Team** | **Enterprise** |
|---|---|---|---|---|
| Price | $0 (open-source) | $0 (subsidised) | ~$20–50/user/mo *or* $99–299/mo flat + metered overage | contract, ~$1k–10k+/mo |
| One-liner | the engine as a library + CLI: recompute from committed artifacts + local runs, validity checks | connect a repo, capped verifies/day, top-K claims, CPU, public repos | private repos, bigger budget, **CI / merge-gate**, connectors, history/retention, signed proofs | **GPU verification**, SSO/RLS/roles, SLAs, **audit/compliance pack + transparency log**, **neutral third-party attestation**, dedicated capacity, BYOC/on-prem |
| Who it's for | OSS devs, self-hosters, air-gapped | individual devs kicking the tires; a repo maintainer badging one project | dev teams, agent-CI, quant/DS teams putting Calma in the deploy path | funds/labs/regulated orgs where a wrong number costs millions |
| Compute | BYO (your machine) | a monthly **sandbox-minute budget** | larger budget + data-connect | pooled + GPU, dedicated |
| Isolation | local (Seatbelt / bubblewrap) | E2B Firecracker (CPU) | E2B Firecracker (CPU) | E2B (CPU **+ GPU**) + self-hosted / BYOC |
| **Usage add-ons** (metered) | — | — | extra sandbox-minutes | + GPU-minutes, large-repo/long-run budgets, extra connectors |

**Why these prices hold — value-anchored, not cost-plus.** Marginal cost is *cents per scan* (E2B
sandbox-seconds; see above), but the buyer's alternative — one wrong number reaching a trade, a shipped model,
an LP report, or an audit — is **thousands to millions**. A single caught error pays for Pro for years, so
tens-of-dollars (Pro) and thousands (Enterprise) are trivially justified. COGS only sets the *floor* and the
*meter* (sandbox-minutes); value sets the price.

**Free is a funnel, not charity:** free = *discovery on any public repo* (cheap, the static layer always
lights up) + a *capped* deep-verify budget. The expensive part (re-execution) is the thing the budget meters.

---

## What's in each tier — full feature matrix

> Legend: **✅** included · **⚠️** included but capped/shared (see rate limits) · **➕** metered add-on · **—** not
> available. The **verdict itself is never gated** — FCR=0 and the full fail-closed taxonomy
> (CONFIRMED / CONFIRMED-STOCHASTIC / REFUTED / INVALIDATED / REPRODUCED-ONLY / NON-DETERMINISTIC /
> INCONCLUSIVE / DISCOVERED) are identical on every tier. Tiers gate **how much you can run, how deep, and
> what trust artifact you get out** — never *whether a wrong number can slip through*.

### A. Discovery & claims (the static layer — cheap, stays generous everywhere)
| Capability | OSS/CLI | Free | Pro/Team | Enterprise |
|---|:--:|:--:|:--:|:--:|
| Auto-discover claims (results.json / results.csv / README tables / prose / stdout) | ✅ | ✅ | ✅ | ✅ |
| Claim salience ranking — lead with the headline number (F4 P0, deterministic) | ✅ | ✅ | ✅ | ✅ |
| LLM claim-classifier refinement (F4 P1) | — | ⚠️ shared | ✅ | ✅ |
| Trusted metric catalog (628 recipes: ML / stats / finance / IR+LLM-eval / forecasting) | ✅ | ✅ | ✅ | ✅ |
| Convention search (ddof / annualization / gain / correlation-type disambiguation) | ✅ | ✅ | ✅ | ✅ |
| Batch / multi-repo & wide results-CSV discovery | ✅ local | ⚠️ | ✅ | ✅ |

### B. Deep verification (re-execution — the metered part)
| Capability | OSS/CLI | Free | Pro/Team | Enterprise |
|---|:--:|:--:|:--:|:--:|
| Recompute from **committed artifacts** (predictions/splits, no re-run) | ✅ | ✅ | ✅ | ✅ |
| **Deep verify** — re-run the repo in a sandbox, k×, instrument-capture the raw arrays | ✅ BYO | ⚠️ capped | ✅ | ✅ |
| Three-way diff (claimed vs produced vs independent recompute) + fail-closed verdict | ✅ | ✅ | ✅ | ✅ |
| Synth flywheel — recompute an **unrecognized** metric (LLM synth, validated, then banked) | ⚠️ BYO key | ⚠️ shared | ✅ | ✅ |
| Adaptive-k determinism gate (proven-deterministic → k=1) | ✅ | ✅ | ✅ | ✅ |
| Certified numeric enclosures at the tolerance boundary (F19) | ✅ | ✅ | ✅ | ✅ |
| Differential recompute / independent-oracle cross-check (F17) | ✅ | — | ✅ | ✅ |

### C. Un-foolability (extra sandbox runs — the anti-cheat layer)
| Capability | OSS/CLI | Free | Pro/Team | Enterprise |
|---|:--:|:--:|:--:|:--:|
| Fuzz-the-formula — re-invoke the repo's own metric fn on fresh inputs vs catalog (F2) | ✅ BYO | — | ✅ | ✅ |
| Metamorphic verification — exact analytic relations (F7) | ✅ BYO | — | ✅ | ✅ |
| Perturbation-fabrication — catch a hard-coded constant (F10) | ✅ BYO | — | ✅ | ✅ |
| Inline red-team gate on every CONFIRMED (F8, deterministic) | ✅ | ✅ | ✅ | ✅ |

### D. Determinism depth
| Capability | OSS/CLI | Free | Pro/Team | Enterprise |
|---|:--:|:--:|:--:|:--:|
| Enforced-env (PYTHONHASHSEED/TZ) + empirical k≥2 | ✅ | ✅ | ✅ | ✅ |
| Statistical / distribution verify — CONFIRMED-STOCHASTIC (F6, raises k) | — | — | ➕ metered runs | ✅ |
| Seed characterization — "is the non-determinism seed-controlled?" (F15) | ✅ | — | ✅ | ✅ |
| Shim tier — SOURCE_DATE_EPOCH / single-core clock pinning (F20) | ✅ | ⚠️ | ✅ | ✅ |
| Nix hermetic environment — OS/BLAS/glibc pinned (F14) | — | — | — | ✅ |
| rr record-and-replay — bit-for-bit determinism proof (F20 rr) | — | — | — | ✅ |

### E. Get-it-running (coverage — turn DISCOVERED into a real verdict)
| Capability | OSS/CLI | Free | Pro/Team | Enterprise |
|---|:--:|:--:|:--:|:--:|
| Heuristic dep-heal (auto-install a missing import + retry) | ✅ | ✅ | ✅ | ✅ |
| AI run-planner — propose entrypoint/deps/targets (validated, never touches the verdict) | ⚠️ BYO key | ⚠️ shared | ✅ | ✅ |
| **Get-it-running repair agent** — iterative env-only ReAct loop (F1) | ✅ BYO | — | ✅ | ✅ |
| `fetch_data` — resolve a missing dataset via search (opt-in, provenance-caveated, SSRF-guarded) | ✅ BYO | — | — | ➕ opt-in |
| GPU verification (CUDA repos) | — | — | — | ✅ / ➕ GPU-minutes |

### F. Trust, proof & compliance (the moat layer)
| Capability | OSS/CLI | Free | Pro/Team | Enterprise |
|---|:--:|:--:|:--:|:--:|
| Verdict + human-readable reason + three-way diff detail | ✅ | ✅ | ✅ | ✅ |
| Content-addressed **reproducibility receipt** (F18) | ✅ | ⚠️ view | ✅ | ✅ |
| Dataset digest field on each claim (F16) | ✅ | ✅ | ✅ | ✅ |
| **Signed verdict attestation** — DSSE + in-toto VSA (F3) | ⚠️ self-key | — | ✅ ed25519 | ✅ **KMS + neutral** |
| **Transparency log** — append-only, tamper-evident + Rekor anchor (F12) | — | — | ⚠️ local | ✅ |
| Reproducibility **badge** + public **registry** (F13, CONFIRMED-only-green, SHA-pinned) | ⚠️ self-host | ✅ badge | ✅ registry | ✅ |
| **Neutral third-party attestation** (an in-house tool *cannot* be neutral) | — | — | — | ✅ the wedge |
| Audit / compliance evidence pack ("SOC-2-for-backtests") | — | — | — | ✅ |
| FCR bug-bounty participation (F9) | public program | public | public | public + private triage |

### G. Collaboration, CI & data
| Capability | OSS/CLI | Free | Pro/Team | Enterprise |
|---|:--:|:--:|:--:|:--:|
| Private repos | ✅ local | — (public only) | ✅ | ✅ |
| **CI / merge-gate** — block a PR whose numbers don't verify | ✅ self-host | — | ✅ | ✅ |
| PR bot / commit status checks | ✅ self-host | — | ✅ | ✅ |
| GitHub App connector (connect your org's repos) | — | ⚠️ public | ✅ | ✅ |
| Data connectors (bring the real eval dataset) | BYO | — | ➕ | ✅ |
| History / retention of past verifications | local | 7 days | 90 days | contractual |
| Cross-run anomaly detection (F11, volume-gated) | — | — | ⚠️ | ✅ |
| Learning-flywheel priors (F5 — warm-start plans/conventions) | shared | shared | shared | ✅ **private** bank |

### H. Ops, security & support
| Capability | OSS/CLI | Free | Pro/Team | Enterprise |
|---|:--:|:--:|:--:|:--:|
| Process-isolation supervisor (a bad repo crashes its child, never the API) | ✅ | ✅ | ✅ | ✅ |
| SSO / SAML | — | — | — | ✅ |
| RLS / roles / org management | — | — | ⚠️ team | ✅ |
| Dedicated capacity / warm sandbox pool | — | — | — | ✅ |
| BYOC / on-prem / air-gapped | ✅ (it's OSS) | — | — | ✅ |
| Support | community | community | email, best-effort | dedicated + SLA |

## Expensive additions worth gating (ranked by margin + defensibility)

1. **Neutral third-party attestation / registry** — highest margin, least replicable. An in-house tool *can't*
   be neutral; barely costs us anything to produce. The enterprise wedge.
2. **GPU verification** — real COGS, unlocks the ML/LLM-eval segment. A priced tier (its own SKU and/or a
   GPU-minute add-on); exact pricing TBD.
3. **Continuous CI / merge-gate** — recurring, sticky, high willingness-to-pay (sits in the deploy path).
4. **Signed proofs + transparency log + retention/audit** — the compliance / "SOC-2-for-backtests" layer.
5. **Private repos + data connectors**, and **higher sandbox / concurrency / large-repo budgets**.

## Rate limits — per tier (admission control, fail closed)

Limits are enforced at the runner's **admission gate**, *before* a sandbox is ever provisioned, and at the
**process-isolation supervisor** (per-sandbox hard caps). The design principle: **meter the one expensive
thing (sandbox-minutes), keep everything cheap generous** so the funnel stays wide. Discovery (the static
layer) never draws down the budget; only re-execution does.

> The numbers below are **proposed defaults** — a starting point sized to keep the free-tier subsidy small
> while cost-per-scan is high, meant to loosen as the flywheel drives cost down (see Open decision #1). They
> are the tunable knobs, not commitments.

| Limit | OSS/CLI | Free | Pro/Team | Enterprise |
|---|:--:|:--:|:--:|:--:|
| **Deep-verify scans / day** | ∞ (BYO compute) | **5 / day** | **100 / day / user** | custom / contract |
| **Claims deep-verified per scan** (top-K by salience) | all | **top 3** | **top 25** (or all) | **all** |
| Discovery (list every claim, static) | ∞ | ∞ | ∞ | ∞ |
| **Sandbox-minutes / month** (the meter) | BYO | **30 min** | **600 min** incl. + metered overage | pooled / contract |
| **GPU-minutes / month** | — | — | — (route to "needs-GPU") | **metered add-on** |
| **Concurrency** (parallel sandboxes / tenant) | local only | **1** | **3–5** | **10+** / dedicated pool |
| **k** (runs per repo; determinism) | your config | **2** | up to **10** (stochastic verify) | contract |
| Per-sandbox **wall-clock** cap | your config | **5 min** | **20 min** | **60 min+** / contract |
| Per-sandbox **memory** (RSS) cap | your config | **1 GB** | **4 GB** | **16 GB+** / GPU mem |
| Per-sandbox **egress** | your config | **denied** | **denied** | denied (or allowlisted BYOC) |
| Repo size / clone depth | your config | small, depth-1 | larger | contract |
| Private repos | ∞ local | — (public only) | ✅ | ✅ |
| **API rate** (requests / min) | — | **30** | **300** | custom |
| Retention / history | local | **7 days** | **90 days** | contractual |
| `fetch_data` external-data pulls | BYO | **off** | **off** | opt-in, metered |
| Repair-agent steps per scan (F1) | your config | — | **4** | contract |

**How each limit behaves at the ceiling (all fail closed — never a wrong answer, always an honest one):**

- **Scan quota / sandbox-minute budget** — the two primary meters. At the ceiling, **deep verify is refused**
  with a clear "out of budget / upgrade" reason; **discovery still runs** (it's ~free), so you always get the
  claim list, just not a fresh re-run. Deep verify draws the budget down; discovery, recompute-from-artifacts,
  and banked-formula recomputes do not.
- **Claim cap (top-K)** — a free scan deep-verifies the **K highest-salience claims** (the headline numbers),
  not all of a benchmark's hundreds; discovery still lists every claim so nothing is hidden, and the rest are
  marked DISCOVERED ("upgrade to verify").
- **Concurrency cap** — bounds parallel sandboxes per tenant (a CWE-770 unbounded-resource guardrail; the
  warm pool is finite). Excess scans queue rather than fan out.
- **GPU gating** — a CUDA/GPU repo on a non-GPU tier is **not run**; it's routed to the "needs-GPU"
  couldn't-reproduce taxonomy row (the upsell), never silently run on CPU and mis-scored.
- **Per-sandbox hard caps** (wall-clock, memory, egress-denied, ephemeral, single-core on the small tier) are
  enforced by the supervisor: a pathological repo hits its wall/RSS ceiling and its **child** is tree-killed
  — the API never crashes, and the verdict for that repo is an honest couldn't-reproduce, not a hang.
- **k (runs per repo)** — below the tier's k, an unstable-but-correct repo stays NON-DETERMINISTIC rather than
  confirming; the stochastic verdict (CONFIRMED-STOCHASTIC) needs the higher k that Pro/Enterprise allow.

Every meter is observable via the cost telemetry (`/api/cost`: sandbox-seconds + inference calls per tenant),
which is also how the **subsidised-free ratio** and **cost-per-scan** health metrics are tracked.

## Enforcement — where each limit lives (implemented)

The limits above are **live**, not aspirational. Admission control runs at two layers, fail-closed, and the
verdict taxonomy is untouched (a limit only refuses a run or caps deep verification to the top-K claims — it
can never turn a wrong number green; FCR surface is zero).

| Knob | Enforced in | How |
|---|---|---|
| Tier resolution / identity | `web/lib/tier.ts` → `spike/server.py:identity` | The WorkOS-authed proxy (which alone holds the service token) forwards `X-Calma-Tenant` + `X-Calma-Tier`; the backend trusts them *because* only the token-holder can set them. Unknown tier → `free` (fail closed). Token unset → local `owner` (unmetered). |
| Deep-verify scans / day | `spike/core/limits.py:Limiter.admit_scan` | Calendar-day counter per tenant; at the ceiling deep is **deferred to discovery-only** (funnel stays open), not hard-refused. |
| Sandbox-minutes / month | `Limiter.record_sandbox_seconds` (billed in `server.run_job`) + `admit_scan` | Monthly counter; exhaustion → 402, discovery still runs. |
| Concurrency / tenant | `Limiter.admit_scan` (+ `release_slot`) | In-flight counter; excess → 429 + `Retry-After`. (The process-isolation supervisor also caps global concurrency by memory.) |
| API rate (req/min) | `Limiter.check_api_rate` (backend) + `edgeGuard` (`web/lib/tier.ts`) | Backend per-tenant 60s window on the **submit** path (the cost vector; polling GETs are exempt); the edge guard sheds a single-instance flood first. |
| top-K claims | `clamp_request` → `pipeline.VerifyOptions.top_k` | Only the K highest-salience claims are deep-verified; the rest are listed as DISCOVERED (“upgrade to verify”). |
| k / wall-clock | `clamp_request` | k clamped to the tier ceiling; per-sandbox wall passed as `opts.timeout`. |
| Private repos / `fetch_data` | `clamp_request` (hard **402 gate**) | A capability the tier lacks is refused with an upgrade path, not silently downgraded. |
| fuzz / repair (paid anti-cheat + env-repair) | `clamp_request` (soft-disabled) | Turned off on tiers that don't include them, with a note. |

**Non-limit hardening shipped alongside** (senior-security pass): constant-time service-token compare
(`hmac.compare_digest` — no timing side channel); a public deployment refuses **local-path repos**
(`_is_remote_repo` — blocks `repo=/app` from uploading the host's own source/secrets into a sandbox);
**tenant-scoped GitHub installation binding** (`_installation_ok` — a guessed `installation_id` can't clone
another account's private repos); and **pip-spec sanitization** of LLM-planned + API-supplied deps
(`sanitize_pip` — a prompt-injected plan can't smuggle `--index-url http://evil/` or a VCS ref into the
installer). The AI planner's blast radius stays bounded to a failed run (→ DISCOVERED) by the existing
entrypoint/target validation gates; it never touches a verdict.

Every default is an **env knob** (`CALMA_FREE_SCANS_PER_DAY`, `CALMA_PRO_SANDBOX_MIN`, …,
`CALMA_PRO_USERS`/`CALMA_ENTERPRISE_USERS` for tier assignment, `CALMA_EDGE_RPM`) so the founder can loosen
limits as cost-per-scan falls — no redeploy.

> Known residual (MVP, tracked): jobs are in-memory and read via 48-bit random ids behind the first-party
> proxy; job **reads** aren't yet tenant-scoped (an attacker would need the authed proxy *and* to guess an id).
> Durable, tenant-scoped job storage is the control-plane's job in the next layer.

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
