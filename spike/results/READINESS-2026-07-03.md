# Calma — market readiness + who we're actually pitching (2026-07-03)

_Grounded in ~22 external sources (Exa research) + the current product state. Full research in the session
log; this is the decision memo._

## Bottom line

The pain is **real, worsening, and public** in every domain Calma names. But the segment with the most
urgency (AI-code-CI guardrails) is **crowded with free tools**, and the segment with the most budget
(quant / model-risk) **demands enterprise features we don't have** (on-prem, no data egress, SOC 2). The
genuine empty cell — **neutral, deterministic, fail-closed RE-COMPUTATION** — is real but narrow.

**Move: ship the no-run validity wedge as a FREE / open-core dev tool for adoption, and run 3–5 PAID
design-partner pilots in exactly ONE paying segment (an AI-eval/benchmark company, or a quant/model-risk
team). Do NOT build enterprise features (SSO/SOC2/on-prem/GPU) on spec — let a pilot tell you which.**

## Who we're actually pitching (ranked by fit × willingness-to-pay)

1. **AI-eval / benchmark-integrity orgs + benchmark-publishing labs** — sharpest "SOC 2 for benchmarks" fit.
   Trigger: a contamination / gaming accusation (LM Arena "Leaderboard Illusion" 2025; "Benchmarking is
   Broken — don't let AI be its own judge" NeurIPS 2025 literally calls for Moody's-style third-party
   oversight; 42% of papers leak benchmark data). Buyer: leaderboard-org founder / lab eval lead. **Cleanest
   narrative fit; labs have budget.**
2. **AI-coding-agent correctness guardrail in CI** — highest urgency + explicit budget (GitLab: 98% have
   budget for AI-code governance; Sonar: 96% don't trust AI output, only 48% verify). Buyer: VP Eng / DevEx.
   **But crowded with FREE OSS (Verdict, Sembl, TruthGuard, …) — all LLM-judge / diff-vs-intent, NONE
   recompute.** Our determinism is the one thing they can't do. Risk: $0 price anchor.
3. **Quant / prop trading + regulated model-risk** — biggest checks, real regulatory clock (SR 11-7; EU AI
   Act high-risk enforceable Aug 2 2026). "A second team reproduces the headline number from the same data"
   is literally a backtest-integrity checklist item. **But: mandatory on-prem/no-egress, quarters-long
   cycle, incumbent validation vendors. A solo MVP can't close here yet.**
4. **(weak WTP) ML researchers / academic labs / journals** — undisputed pain (294-paper leakage survey; a
   2024 Nature retraction from a normalization bug), but **near-zero budget.** This is our **adoption / demo
   channel, not a buyer.** NOTE: our hardened beachhead (classical-ML model-comparison author) sits *here* —
   great for a free-tool demo, not for revenue.

## The moat (in priority order)

1. **Determinism + fail-closed** ("never falsely confirms a wrong number") vs the LLM-judge crowd — the
   one-line wedge. 2. **Cross-domain, multi-language black-box recompute** (Py/R/Julia/C++/Rust across
   ML+quant+genomics+analytics) — nobody spans this. 3. **Neutral third-party standing** ("SOC 2 for
   benchmarks/backtests"), validated by the NeurIPS "Moody's for AI" framing.

Adjacent threats to NOT drift into: W&B/MLflow (track, don't verify), Braintrust/Galileo/Patronus
(LLM-app-output eval, well-funded), Code Ocean (reproducible packaging, not adversarial recompute).

## Are we ready to ship? — partial. Ship the wedge, pilot the rest.

- **Ready to SHIP (free):** the no-run validity wedge (leakage / trivial-baseline / misreport). It's
  reliable today, maps to the single most-cited failure mode (leakage), and needs no reproduction. → free
  CLI / GitHub Action, launched to ML/DS + agent-CI audiences for logos + stars.
- **Ready to PILOT (paid design partners):** full recompute is coverage-bound but genuinely catches — good
  enough for a hand-held 3–5-partner pilot in ONE segment. Do NOT gate revenue on the weaker capability.
- **NOT ready for enterprise self-serve.** The blockers below are real.

## Enterprise / pro gap (what a paying eval-co or quant team requires that we lack)

**Must-have (deal-blockers):** on-prem / VPC / no-data-egress (the #1 regulated blocker); audit logs /
immutable verification record (EU AI Act Art. 12); CI/API integration (guardrail in the pipeline, not a web
form); SSO/SAML + RBAC. **Strongly-wanted:** SOC 2 Type II (required to sell to banks/funds); **GPU compute
for heavy reproduction** (DL/genomics — flagged Modal-backend gap); seats/quotas (partly built).
**Defer:** SLAs, signed attestation, on-prem admin dashboards.

Strategic tension: on-prem + SOC 2 + GPU are exactly what the *paying* segments need and exactly what's slow
to build. → that's the whole argument for **free-wedge-adoption + one narrow paid pilot** before building
the enterprise stack speculatively.

## What's next (concrete)

1. **Package the free validity wedge** as a CLI + GitHub Action (no signup) — the adoption front door.
2. **Line up 3–5 paid design partners** in segment #1 (eval/benchmark org) — Calma as the neutral recompute
   badge. One quant/model-risk partner as a stretch.
3. **Corpus expansion into the money segments** (quant backtests: Sharpe/Sortino/VaR/drawdown; LLM-evals:
   pass@k / recall@k) — the recipes exist; the hardening loop should target THESE, not more classical-ML.
4. **Enterprise stack only after a pilot signs** — then build the one thing that partner blocks on (likely
   on-prem or GPU).
