# Calma — session handoff

Onboarding for a fresh Claude Code session continuing this project. Read this, then `BUILD-NOTES.md`
(build log) and `.claude/skills/calma/SKILL.md`.

## What Calma is

An open-source Claude Code **skill** (and standalone pure-Python toolkit) that **verifies a computational
result by re-executing it and recomputing the headline number from the raw outputs** — then proves or breaks
the claim. The verdict is computed by deterministic scripts, never by a model. It is **Stage 1**; the
end-goal is a paid quant/DS **CLI** (deep statistics, signed audit) and a managed layer. Same shape as the
CLI, one notch shallower.

## Repo & current state

- **Public:** https://github.com/rikhinkavuru/calma · default branch `main` (HEAD `471b42d`) · MIT · CI green.
- **Milestones M0–M2 complete and tested:** 184 checks across 11 suites, all green.
- The repo also contains a small Next.js project website (`app/`, `components/`) — optional, unrelated to using the skill.
- **Private (NOT in repo):** GTM/strategy docs (PITCH, STARTUP, ROADMAP, BUILD-REVIEW) live at `~/calma-strategy/`. They were purged from git history before the repo went public — do not re-commit them.

## How to run

```bash
# tests (pure stdlib, no deps, ~100s):
python3 .claude/skills/calma/scripts/tests/run_all.py

# verify a result dir that has a verify.yaml (exit 0 clean / 1 not-clean / 2 invalid):
python3 .claude/skills/calma/scripts/calma.py verify <target> "<claim>"
python3 .claude/skills/calma/scripts/calma.py teardown <target>     # shareable card on a REFUTED
python3 .claude/skills/calma/scripts/run_hermetic.py doctor          # check isolation tier on this host

# flagship demo (reproduces +14,698% -> -32% REFUTED end-to-end):
python3 .claude/skills/calma/scripts/calma.py verify .claude/skills/calma/assets/btc
```

## Architecture (the skill, under `.claude/skills/calma/`)

- `scripts/verdict.py` — THE single deterministic `verdict()` pure function. Every label comes from here.
- `scripts/ledger.py` — schema + semantic `_validate()` that re-derives each label byte-for-byte; the gate.
- `scripts/numeric.py` + `recipes.py` — reference-deterministic kernels (fsum/sqrt, no transcendentals,
  no numpy) + **15 recipes** across quant / classification / regression / analytics.
- `scripts/draft_contract.py` — zero-config `verify.yaml` auto-draft (tag inference + graded binding).
- `scripts/run_hermetic.py` — verified macOS Seatbelt isolation + `doctor` self-test; dispatches by language
  (Python/R/Julia/C++/Rust/Node).
- `scripts/recompute.py` / `compare.py` / `attest.py` — recompute → calibrated diff → in-toto/SLSA +
  CycloneDX ML-BOM attestation.
- `scripts/calma.py` — orchestrator (`verify` / `teardown`). `report.py` — strictly-progressive render.
- `calibration/` — `calibrate.py` (M2: determinism band + FP-guard corpus → `assets/calibration.json`),
  `served_fraction.py`, `CALIBRATION.md`, `VENDORING.md`, `calma_vendor.py` (HTTP record/replay).
- `assets/` — `btc/` (flagship fixture), `leakage/` (ML), `lang/` (R/Julia/C++/Rust/Node fixtures),
  schemas, `calibration.json`, `served_fraction.json`.

## Invariants — DO NOT break these (they are the product)

1. No statistic OR verdict label is computed by the model — all in unit-tested scripts; `ledger.py`
   re-derives every label from its `verdict_inputs` and rejects mismatches.
2. Recompute ONLY from machine-readable raw outputs (csv/json/...), never a reported value.
3. No REFUTED under uncontrolled-and-insufficient-K determinism, non-independently-bound input, resource
   kill, or unconfirmed claim → degrade to INCONCLUSIVE. Conservative defaults in `verdict.DEFAULTS`.
4. Measured-band REFUTED requires M2 calibration (`assets/calibration.json` present). CONTROLLED-TO-BIT
   (pure-stdlib, AST-proven) is exempt. Non-Python runs are `uncontrolled`; a fraud-grade gap REFUTES via
   the calibrated fraud-multiple M=5.
5. Isolation is **macOS Seatbelt** (own-code tier) — `doctor` proves it blocks secret-read + egress.
   Untrusted third-party code requires a container/VM tier (M5) and is refused otherwise. On hosts without
   `sandbox-exec` (e.g. Linux CI) the suite's isolation-gated checks skip; the pure-Python core runs everywhere.

## Roadmap / what's next

- **Skill polish (next):** live "agent-calls-Calma mid-task" demo; more recipes (time-series, ECE); CI/IDE
  surfaces; hosted teardown gallery; more vendored real repos (tightens served-fraction/PPV).
- **CLI (M3, paid quant):** Deflated Sharpe / PBO / Harvey-Liu; realism deflators; leakage re-run; verified
  container isolation; data-change re-verification; defensibility report.
- **Managed (M5):** point-in-time / survivorship-free data; signed audit trail at scale; EU-AI-Act
  compliance-evidence engine; team dashboards. (Full design in `calma-skill-blueprint.md`.)

## Honest limits

Calma proves a result is **real and reproduces — not that it solved the right problem** (reproducible ≠
semantically correct). It returns CAN'T-CONFIRM (INCONCLUSIVE) with the exact fix rather than crying wolf.
Live-data repos need their data vendored (the `calma_vendor` shim) before they verify offline.

## Operational notes for a new CC session

- Everything is **pure stdlib** — no `pip install` needed to run or test. Built/tested on macOS + Python 3.14;
  CI runs Linux + Python 3.12.
- `verify.yaml` files are **JSON content** (valid YAML) so scripts parse them dependency-free.
- Branches `main` and `calma-skill-build-kit` currently point to the same commit.
- Commit after each passing acceptance test; keep the suite green. Run `run_all.py` before pushing.
- Design source of truth: `docs/internal/calma-skill-blueprint.md` (full spec) + `calma-build-runbook.md`.
