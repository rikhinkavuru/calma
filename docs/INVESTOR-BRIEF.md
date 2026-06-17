# Calma — investor brief

*A plain-English walk-through for someone seeing this for the first time. Code-grounded facts are real and testable today; market sizing and revenue figures are reasoned estimates, flagged as such.*

---

## In one line (≤ 50 chars)

**Verifies AI's numbers by re-running the code.**

## What the company makes

Calma is **the independent verifier for computational results**. You hand it a result and a claim — "this backtest has a Sharpe of 2.6," "this model is 94% accurate," "this pipeline is 2.3× faster" — and Calma **re-executes the code in a sealed, network-off sandbox, recomputes the headline number from the raw output files (not the number that was reported), and diffs it against the claim.** It returns a deterministic verdict — CONFIRMED, REFUTED, or INVALIDATED — plus a signed, replayable proof anyone can re-check offline.

The product exists because of one act almost nobody else performs: **recompute the claimed number from raw outputs, *and* separately check that the result is statistically sound** (not leaked, not overfit, not survivorship-biased). Those are two different questions. A number can be perfectly reproducible and still completely invalid. Calma answers both, and it's the only tool that does both in one deterministic pass.

Think of it as **"SOC 2 for backtests"**: a neutral third party that proves a number is real, where the auditor structurally cannot be the auditee.

---

## The problem

Every important decision rides on a number someone else produced, and there is almost no cheap, neutral way to check it.

- **In finance**, an allocator deciding where to place hundreds of millions sees a manager's backtested Sharpe ratio. Verifying it today means a bespoke, weeks-long, six-figure human "quant due diligence" engagement — or, far more often, just trusting the number plus a questionnaire. Inflated, overfit, and survivorship-biased backtests are a known, regulated problem (the SEC Marketing Rule treats hypothetical/backtested performance as high-risk).
- **In AI/ML**, agents now generate the backtests, the evals, and the "tests pass." They are confidently wrong at scale, and the most dangerous failures are the ones that *reproduce* — a model that quietly leaked its test set reports a real 94% that collapses in production.
- **Everywhere else** — a research paper, a vendor's benchmark, a data pipeline's "0 nulls" — the reported number is taken on faith.

The expensive failures are rarely fraud. They're a number that was technically reproducible but **not valid**, and no one had a fast, neutral way to catch it.

## How the problem is solved (specifically)

Calma is a deterministic pipeline with intelligence only at the edges:

1. **Contract.** It reads a committed `verify.yaml` (or drafts one — an LLM helps here, but never decides a verdict) describing how to run the code and which column is the metric.
2. **Re-execute in isolation.** It runs the entrypoint in a **network-off sandbox** — Seatbelt on macOS, bubblewrap on Linux, a network-denied Docker tier, or a remote Firecracker microVM for untrusted counterparty code. Isolation is *proven*: a planted secret-read and a network-connect must both fail an in-sandbox self-test, or the run is honestly stamped "not isolated."
3. **Recompute from raw outputs.** It reads the freshly re-emitted output files and recomputes the metric with one of **623 SOTA recipes** (across trading, ML, stats, engineering, retrieval/LLM evals, derivatives, credit…), run as a black box over Python/R/Julia/C++/Rust. It never reads the reported number.
4. **Diff under a calibrated tolerance.** Floating-point/BLAS noise is treated as a caveat, not a refutation. A real gap, with the claim statistically distinguishable from the recompute, is a REFUTED.
5. **Validity layer.** Ten families — leakage, overfitting (Deflated Sharpe/PBO), execution realism (fees/slippage/market-impact), contamination, survivorship, point-in-time/look-ahead, study-wide multiple-testing (the Harvey-Liu-Zhu *t > 3.0* haircut), walk-forward/regime, model-process leakage, distribution shift — each only ever *degrades* a verdict, and INVALIDATES a result that *reproduces but isn't sound*.
6. **One deterministic verdict, signed.** A single pure function produces the label; the gate re-derives it byte-for-byte, so it can't be faked — even by Calma. The catch ships a hash-chained ledger + a DSSE/SSHSIG-signed, RFC-3161-timestamped, offline-verifiable attestation.

The whole engine is **pure Python standard library, fully offline** — your code and data never leave your machine.

---

## Use cases, walked through

**1) An emerging quant manager raising capital (seller-side wedge).**
A small CTA has a 3.2-Sharpe backtest and a meeting with a seeder. They run `calma verify` on their own strategy repo. Calma re-runs it network-off, recomputes the Sharpe over the raw returns, finds it survives, *and* runs the validity layer: it confirms the costs are net, the universe is point-in-time, and the result isn't an artifact of testing 50 variants (the HLZ haircut still clears t > 3.0). They walk in with a **signed, portable artifact** the seeder can re-verify offline in seconds. Today that credibility costs weeks of human quant-DD they can't afford.

**2) A fund-of-funds vetting a manager (buyer-side, the aspirational ICP).**
An allocator's investment-DD team receives a manager's code + data under NDA. They point Calma at it. Calma INVALIDATES the headline: the number *reproduces*, but the universe is survivors-only — delisted names are absent, so the CAGR is upward-biased. The verdict carries the survivorship-adjusted gap and a one-line fix. The allocator just compressed a multi-week engagement into a same-day, defensible decision — and the verdict came from a neutral function, not a consultant's opinion.

**3) An AI agent shipping a result (the developer/PLG wedge).**
A coding agent finishes a data task and is about to report "accuracy 0.94 on the held-out set." Calma runs as an inline guardrail (a Claude Code Stop hook, or the MCP server in Cursor/Codex). It re-runs the eval in the sandbox, recomputes 0.94 — it reproduces — but the validity layer fires: a `StandardScaler` was fit on train+test, and refitting on train-only drops it to 0.79. Calma returns INVALIDATED with the leakage gap *before* the agent reports the number. The agent self-corrects in the loop.

**4) A PR that changes a result (the GitHub surface).**
A teammate's PR edits a notebook and a `runs/returns.csv`. The Calma PR bot re-runs the changed result-dir in the engine's sandbox and posts an inline review comment — "cell 5 says +14,698% → recomputes to −31.6%" — plus a failing `calma` check-run that gates the merge. It's CodeRabbit, but for numbers, with a deterministic verdict instead of an LLM opinion.

---

## Market & competition (PMF)

The category — *deterministic, signed, replayable verification of AI-produced results* — was an empty cell two years ago and is now visibly forming. Calma's defensible position is the **intersection** four ways: it **recomputes the reported number from raw outputs**, it has a **real validity layer → INVALIDATED**, it spans **16 domains / 5 languages**, and it is **neutral and fully offline**. Almost no one occupies that intersection.

- **AI-output verification (the forming category):** GeodesicAI (deterministic PASS/FAIL vs a "blueprint"), verist, NexArt, Zorynex, Lagrange DeepProve (zkML proof a model *ran*). Most attest *what ran* or prove *the model ran* — they don't recompute *the claimed metric*.
- **Quant backtest validation (the closest analogs):** **Null Hypothesis Labs** (CPCV + Deflated Sharpe + PBO + a 14-item leakage audit; ~$1.5k — the closest to our quant science), QuantProof, AlgoXpert's "Alpha Certificate" (literally pitching Calma's thesis), and human consultancies (Veritas Quant, Volos, Systemathics). Calma matches their overfitting core and goes **wider** — the study-wide HLZ haircut, point-in-time, walk-forward, model-process leakage, and distribution shift — across far more than quant.
- **Adjacent, converging:** LLM eval/observability (LangSmith, Braintrust, Arize — a ~$1.35B market; mostly trace + LLM-judge, almost none recompute a metric), data observability (Monte Carlo et al., >$1B; monitor pipelines, don't recompute a claim), bank model-risk (ValidMind, Yields.io — internal-validation workflow automation under SR 11-7), and the assurance rails (AIUC-1 + Schellman = "SOC 2 for AI agents," a partner not a competitor).

**Read:** the constituent ideas are shipping, but no one matches the full stack, and the *neutral-verdict + recompute-the-claim + validity-layer + breadth* intersection is the moat. The differentiating act is hard to fake and structurally credible (the verifier can't grade its own work).

---

## Target customer & ICP

**Primary ICP — who must trust or prove a quant track record.** The buying function is **investment/quant due diligence and research integrity** (note: *not* operational DD, which doesn't verify performance):

1. **Fund-of-funds / multi-manager allocators** with quant manager research (Blackstone BXMA, GCM Grosvenor, Man FRM, Goldman AIMS, Morgan Stanley AIP, Aurum, Lighthouse).
2. **Investment consultants / OCIOs** that scale or resell DD (Mercer, Aon, Cambridge Associates, Albourne, Aksia, Meketa).
3. **Asset owners** with in-house manager DD or quant teams (CalPERS, CPP, GIC, Temasek, Norges, Future Fund, large endowments).
4. **Seeders / emerging-manager & cap-intro platforms** (RQSI/FundSeeder, GP Digital, prime-broker cap-intro desks).
5. **Quant/systematic & pod platforms** that must *prove* numbers (emerging CTAs/crypto-quant raising capital; PM-vetting at Millennium, Citadel, Point72, Balyasny).
6. **GIPS verifiers / fund admins / audit firms** as a channel.

**Secondary ICP — the agent-guardrail / developer market:** fintech & AI teams whose agents produce numbers and must verify them before acting (the buyers of eval/guardrail tools, but wanting *execution-based* checks). Lower trust barrier, PLG distribution.

**Honest sequencing.** The aspiration (CalPERS-tier asset owners, big FoFs) requires SOC 2 / insurance / institutional standing Calma doesn't have yet. The realistic **wedges** are (a) **emerging managers & seeders** who need to prove a number cheaply with a portable artifact, and (b) the **agent-guardrail dev market**. Land those, accumulate a neutral public catch-history, and climb toward the asset owners with a Stage-2 certification.

---

## Legality, certifications & licenses

- **Software license:** MIT + Python standard library only at runtime. No copyleft exposure, nothing to license to ship, and a clean dependency supply chain — a real security-review advantage over rivals pulling numpy/sklearn/pandas. (Calibration oracles use scikit-learn/SciPy *offline only* to generate reference vectors; not shipped deps. Overfitting math is reimplemented from public papers, so there's **no license dependency on a competitor** like mlfinlab.)
- **Financial regulatory license:** *not required* — provided Calma verifies **facts** ("the number is real") and does **not** give investment advice or issue manager "ratings" that look like an NRSRO/credit-rating or adviser activity. Staying on the "is it true" side of that line is a deliberate, load-bearing constraint.
- **Adoption bars (to be *bought* by funds/allocators):** SOC 2 Type II is the de-facto gatekeeper; ISO/IEC 27001 for EU/international; vendor security questionnaires (SIG/CAIQ); professional-liability/E&O + cyber insurance (expected of anyone issuing verdicts). **Calma's structural advantage:** the answer to "where is our data processed?" is *"on your machine, network-off,"* which short-circuits a large fraction of security review — a faster path than SaaS rivals who need VPC/self-host to clear the same bar.
- **The certification ("Stage-2") play:** pursue **ISO 42001** certification of the AI-management system and/or align the verdict with an **AIUC-1 / Schellman-style accreditation** (standard body + accredited auditor + insurance-backing). This is how *"a Calma stamp carries signal."* It is a business/legal process, not a code feature.

**Data licensing watch-item:** if Calma ever vendors market data for backtests, exchange/Bloomberg/Refinitiv data licensing becomes real. The "you bring code + data, we recompute" model sidesteps this — preserve it.

---

## How we make money

A classic open-core + certification model, layered to match the sequencing:

1. **Open-source core (MIT)** — the CLI, the skill, the recipes. Drives adoption, trust, and the PLG funnel. Free forever.
2. **Self-serve / prove-a-number (the seller-side wedge)** — emerging managers and quant teams pay for portable, signed verification artifacts and richer validity coverage. Comparable self-serve quant validators price around **$1.5k**; a credibility-artifact-per-strategy or a low monthly subscription.
3. **Developer / agent-guardrail (PLG)** — the PR bot + hosted GitHub App + MCP, sold per-seat / per-repo / usage-based, like CodeRabbit and the LLM-eval tools. Land-and-expand inside engineering orgs.
4. **Allocator-grade verification-as-a-service (the buyer-side, high-ACV)** — a managed/hosted tier for FoFs, OCIOs, and asset owners running Calma across many managers, with audit trails, the catch-history registry, and SLAs. Per-engagement or enterprise-seat; **$10k–$100k+** ACV, displacing six-figure human quant-DD.
5. **Certification / the stamp (the long game)** — once the Stage-2 accreditation exists, a *"Calma-verified"* mark that carries signal to allocators — recurring, high-margin, and the deepest moat (neutral third-party standing).

## How much could you make (reasoned, not a forecast)

The adjacent, *paying* markets bound the opportunity: LLM eval/observability **~$1.35B**, data observability **>$1B**, plus bank model-risk and the institutional quant-DD spend (today bespoke human consulting). Calma sits at the recompute-the-claim intersection of all of these as AI-produced results explode.

- **Bottoms-up, near-term (wedges):** thousands of emerging managers + a fast-growing agent-dev market. A few thousand self-serve/dev seats at low-hundreds ARR + a few dozen prove-a-number subscriptions is a **low-seven-figure** early-ARR path.
- **Mid-term (allocators):** hundreds of FoFs/OCIOs/asset owners; even a small number at $25k–$150k ACV is a **low-eight-figure** ARR business, and this is the sticky, defensible revenue.
- **Long-term (the standard):** if "Calma-verified" becomes a checkbox in allocator DD the way SOC 2 is in vendor procurement, the certification layer is a durable, **nine-figure-potential** category — the same shape as the assurance/attestation businesses (Schellman, the SOC-2 ecosystem) but for *correctness*, not just security.

These are scenarios, not promises. The binding constraints are distribution and institutional trust, not the technology.

---

## Tech stack

- **Engine (built):** pure **Python standard library** — deliberate: no third-party runtime supply chain, fully offline, bit-stable, auditable. One total `verdict()` function; 10 validity detectors; 623 recipes that run user code as a **black box** in Python/R/Julia/C++/Rust.
- **Isolation:** macOS **Seatbelt** (`sandbox-exec`), Linux **bubblewrap**, network-denied **Docker**, remote **Firecracker microVMs** (E2B, vendor-neutral / self-hostable) — each with a fail-closed in-sandbox self-test.
- **Attestation:** DSSE + OpenSSH **SSHSIG** dual-signing, **RFC-3161** timestamps, optional **Sigstore/Rekor** transparency log (offline-verifiable Merkle inclusion proofs), in-toto/SLSA + CycloneDX SBOM.
- **AI edges:** Anthropic & OpenAI APIs (via stdlib `urllib`, no SDK) for claim extraction, contract drafting, CEGIS recipe synthesis, and auto-repair — all firewalled from the deterministic core.
- **Surfaces:** a Claude Code skill (hooks), a host-agnostic **MCP** server, a **GitHub Actions** PR bot (pwn-request-proof two-workflow pattern) + a hosted **GitHub App** (stdlib `http.server`, RS256 JWT via openssl).
- **Web:** the site (calma1.vercel.app) is **Next.js on Vercel**.
- **Planned:** a hosted SaaS/managed tier, a managed at-scale untrusted-code sandbox fleet, continuous monitoring/drift, regulatory-report templates, and the certification program.

## How far along

- **Built & tested:** the full engine, 10 validity families, 623 recipes (vs byte-reproducible reference vectors), five surfaces (skill, CLI, MCP, A1 artifact pipeline, PR bot + hosted App), and the AI edges. **39 core test suites / 0 failed** (pure stdlib) + **147 transport tests**. A published **129-case benchmark** with a two-axis result and a sandboxed, cross-model agent arm. Current version **v0.10.0**.
- **Distribution started:** a live site, a Claude Code plugin, and a first batch of personalized cold outreach to the ICP.
- **Honest gaps:** solo / pre-revenue; no SOC 2 / E&O insurance yet; no hosted SaaS tier (untrusted code is single-microVM-per-run, not a managed fleet); no Stage-2 certification yet; validity coverage is gated on contract richness (the split/trials/frictions/universe/study blocks must be declared). The technology is real; the institutional trust and distribution are the work ahead.

## What we need most now

In rough priority — the gates to the next stage, not all at once:

1. **First design-partner customers + warm allocator/seeder connections.** The single highest-leverage need: 2–3 emerging managers or a seeder/OCIO willing to run real verifications. This converts a skeptical DD team far better than any logo, validates pricing, and produces the public catch-history that compounds into trust. *(enterprise connections / clientele)*
2. **A path to the Stage-2 stamp.** Capital + the relationships to pursue ISO 42001 / an AIUC-1-Schellman-style accreditation + E&O insurance — the difference between "useful tool" and "a stamp that carries signal."
3. **A co-founder / first hires with quant-allocation domain + institutional sales.** The technology is ahead of the go-to-market; the missing half is someone who lives in the IDD/allocator world and can sell into it. *(co-founder / sales)*
4. **Capital** to fund SOC 2 + insurance + a hosted tier and a small founding team — sized to reach the allocator ACVs, not before.

The recommendation: lead with **design-partner traction in the seller-side wedge** (it's the cheapest proof and the trust flywheel), use it to raise on the path to the certification moat. Engineering is the strength, not the bottleneck.
