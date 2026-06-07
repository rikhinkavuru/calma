# Calma skill — build kit (START HERE)

Everything needed to build the SOTA Calma verification skill, start to finish.

## To build

Open a fresh Claude Code session in this repo and paste the **kickoff prompt** from
`calma-build-runbook.md`. It builds the full skill, milestones **M0 → M4**, top-down.

## What you're building (one paragraph)

A **domain-agnostic, agent-callable** Claude Code skill that verifies **AI-agent-produced results** by
**re-executing them to ground truth** — used **post-hoc** (verify what an agent just produced) or **inline**
(an agent calls it as a guardrail). The method is the four checks generalized: provenance/no-leakage ·
independent recomputation · unseen-data re-run · invariant assertion. The verdict is computed by
deterministic scripts, not model opinion. **Quant/DS depth is reserved for the CLI end-goal, NOT this
skill** (quant is one optional domain pack). Full skill = M0–M4; M5 = optional Stage-2/3 bridge.

## Artifacts (read in this order)

1. **`calma-skill-blueprint.md`** — the complete spec. **Start with §0 Product framing and §0.5 Product
   decisions — they are authoritative and override any quant-flagship language in the body.** Build
   Sequence is §15; Validation Plan (empirical lock-gates) is §16.
2. **`calma-build-runbook.md`** — how to build it: the kickoff prompt, milestone map M0→M4, per-step
   acceptance tests, the five honesty invariants, and the adoption-core M1 requirements.
3. **`calma-skill-README.md`** — what the skill is and its positioning (the trust layer for agentic work).
4. **`../scripts/teardowns/btc_overfit_teardown.py`** — the working fixture the finished skill must
   reproduce: claimed **+14,698% → recomputed −32% REFUTED** on real BTC data.

## Definition of done

Every M0–M4 acceptance test green · five-check engine running · fully deterministic verdict pipeline (no
model arithmetic) · every §16 lock-gate run (passed or its result stamped into scope) · the BTC fixture
reproduced end-to-end through the skill's own scripts.

## Adoption-core (build as first-class in M1)

Zero-config + auto-extract the claim from the agent's output · three always-on default checks (reproduces /
recompute-vs-claim / leakage) · actionable INCONCLUSIVE (what's verified + the exact fix) · every FAIL is a
shareable teardown. These win the first users.

## Reference

- `calma-teardown-tests.md` — worked teardown examples + the tech/demand signal write-up.
- Background: the market verdict was LAUNCH-IF; the wedge is verifying agent work (ego-free, growing
  need), not self-audit. See the project memory `calma-product-structure` / `calma-launch-decision`.
