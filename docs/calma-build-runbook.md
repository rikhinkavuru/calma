# Calma — Build Runbook (full product, start to finish)

For a Claude Code build session — or a series of them, with the founder assisting on the empirical
lock-gates — building the **complete** Calma verification skill. **No MVP cut, no descoping, no
stubs-left-as-final.** Read this, then `docs/calma-skill-blueprint.md` — start with its **§0 Product
framing** section, which is authoritative. Build the whole skill, milestone by milestone **M0 → M4** (M5 is
the optional Stage-2/3 bridge), to the blueprint's acceptance tests.

**What you're building, in one paragraph:** a **domain-agnostic, agent-callable** skill that verifies
**AI-agent-produced results** by *re-executing them to ground truth* — used either **post-hoc** (verify
what an agent just produced) or **inline** (an agent calls it as a guardrail while it works). It is NOT
quant-specific: quant/DS is ONE optional domain pack, and the deep quant statistics (Sharpe/DSR/backtest
realism) belong to the **CLI end-goal, not this skill**. The method is the **four checks, generalized**:
provenance/no-leakage · independent recomputation from raw outputs · unseen-data re-run · invariant
assertion (universal = reproducibility + recomputation; domain packs add holdout / point-in-time / declared
invariants). The verdict is **exit-code-style + structured** so a calling agent can branch on it, and works
**with an explicit claim OR via property/invariant checks** when there's no stated number.

**North star: the trust layer for agentic work** — verify what AI agents produce so a FAIL catches the
*agent's* mistake (pure value to the user, no ego hit). Build these **adoption-core features as first-class
M1 requirements** (blueprint §0.5): (1) **zero-config** — `verify <target>` works with no setup and
**auto-extracts the claim from the agent's own output**; (2) **three always-on default checks** — does it
reproduce, recomputed-metric-vs-claim, leakage heuristics — so value lands on any result; (3)
**actionable INCONCLUSIVE** — return what IS verified + the exact fix ("set seed", "emit metrics.csv"),
never a bare shrug, and bias to CAVEAT over a false FAIL; (4) **every FAIL is a shareable teardown**
("claimed X → really Y + repro command"). These win the first users; the heavier trust machinery (verified
isolation, pinned libm, DSR) is still built in full but is not the day-one hook.

---

## Kickoff prompt (paste into the build session)

> You are building **Calma** — a **domain-agnostic, agent-callable** open-source Claude Code skill that
> verifies **AI-agent-produced results** by re-executing them to ground truth. An agent produces a result
> that *looks* right; Calma re-runs the work inside an isolation boundary, **recomputes the headline number
> from the raw machine-readable outputs** (never the reported value, never by reading the code for an
> opinion), diffs it against the claim under a calibrated tolerance model, and applies the **four checks,
> generalized: provenance/no-leakage · independent recomputation · unseen-data re-run · invariant
> assertion**. It emits a fixed-vocabulary, agent-consumable verdict (PASS=CONFIRMED /
> CONFIRMED-WITH-CAVEATS / FAIL=REFUTED / INCONCLUSIVE) — usable **post-hoc** (verify what an agent just
> finished) or **inline** (an agent calls it as a guardrail as it works) — and verifies **with an explicit
> claim OR via property/invariant checks** when there's no stated number. It is NOT quant-specific:
> quant/DS is one optional domain pack; the deep quant stats belong to the CLI end-goal, not this skill.
> (The five failure families — leakage, overfitting, realism, data-integrity, baseline-validity — are HOW
> lies are hunted under the hood; the four checks are the user-facing method.)
>
> **Read first:** `docs/calma-skill-blueprint.md` — the COMPLETE spec; it is the source of truth, follow
> its Build Sequence (§15), Validation Plan (§16), and Roadmap (§17). **Reference fixture:**
> `scripts/teardowns/btc_overfit_teardown.py` produces the target behavior (claimed +14,698% →
> recomputed −32% REFUTED on real BTC data); the finished skill must reproduce that verdict through its
> OWN pipeline scripts.
>
> **Build the COMPLETE Stage-1 SKILL, milestone order M0 → M4, no descoping.** (M5 is the optional
> Stage-2/3 bridge — CLI + managed-layer on-ramp — NOT part of the skill; build it only if continuing
> past the skill.) Every component gets its real implementation and must pass its blueprint acceptance
> test (§15) before you move on. This is a
> multi-session build — work top-down, commit continuously, span as many sessions as it takes. Nothing
> is "out of scope"; the only things deferred are the empirical lock-gates in §16, which are *run as
> experiments*, not skipped.
>
> **Hard components get real engineering, not shortcuts.** Where the blueprint specs intent — the
> verified container/VM isolation tier, the pinned correctly-rounded libm recompute path
> (crlibm/CORE-MATH/mpmath), the full determinism harness (seeds + sitecustomize shim + cudnn/CUBLAS
> flags), the DSR/PBO/CSCV stats engine, the split-hook leakage re-run — RESEARCH the correct approach,
> implement it properly, and validate it against the acceptance test. Do NOT ship a weaker version as the
> final answer; if a component needs an external toolchain, install/vendor it and wire it in.
>
> **Honesty invariants (machine-enforce in scripts, never violate):**
> 1. No statistic OR verdict label is computed by you, the model — all arithmetic and the `verdict()`
>    function live in deterministic, unit-tested scripts.
> 2. Recompute ONLY from machine-readable raw outputs (csv/parquet/json/npy/arrow) — never a notebook
>    cell, rendered repr, or README number (those are claims-to-confirm).
> 3. No REFUTED under uncontrolled determinism, insufficient K, or resource-kill — degrade to
>    INCONCLUSIVE and say so.
> 4. No auto-inferred trial-count N into a printed statistic — declared/evidence-floored N only.
> 5. Stamp achieved isolation + hermeticity tiers in every verdict; install + run + interpreter-startup
>    are ALL untrusted-code execution behind the SAME verified tier.
>
> **Working style:** commit after every passing acceptance test. Maintain `BUILD-NOTES.md` (what shipped,
> what's in progress, decisions, open questions). When you reach a genuine empirical unknown from the
> Validation Plan (§16) — tolerance constants, served-fraction matrix, FP/PPV rates, split-hook
> declarability — run the experiment the plan specifies; if it needs data/compute/judgment you lack,
> STOP and surface it to the founder with concrete options. Never guess a value and fake-pass. Keep the
> repo green and runnable at every commit.

---

## The full build — milestone map (nothing out of scope)

Authoritative detail (deliverables + acceptance tests) is in blueprint §15 (Build Sequence) and §17
(Roadmap); empirical lock-gates are §16. Summary so the session knows the shape:

- **M0 — Orchestration + skill skeleton.** `.claude/skills/calma/` (`SKILL.md` discovery description +
  TOC body, `references/`, `scripts/`, `assets/`). Clone paper-audit's ledger/gate/status-lifecycle/
  fixable_by LOGIC; build the NET-NEW `ledger.schema.json` with a `claims[]` per-claim verdict object
  alongside `findings[]` (dimension enum = the five families + reproducibility + metric-mismatch). The
  shared deterministic `verdict()` pure function. Anti-pattern invariants encoded.
- **M1 — Recompute-and-diff spine (FULL).** `draft_contract.py` (auto-draft `verify.yaml`, claim
  grounding, authorship + dependency-trust classification, independent input-binding with row-integrity
  checks); `run_hermetic.py` (real `sandbox-exec` Seatbelt profile AND the verified container/VM tier
  with `calma doctor` credential-read self-test, network/egress denial, env classify-and-repair);
  `recompute.py` + metric-recipe library on the pinned correctly-rounded libm reference path;
  `compare.py` on the calibrated tolerance model; verdict renderer + gate. DoD: BTC fixture → REFUTED via
  scripts.
- **M2 — Calibration + contract-validation lock-gate.** `consistency.py` (real GRIM/SPRITE/statcheck);
  the tolerance MODEL calibrated on real GPU/BLAS-nondeterministic runs (§16); served-fraction matrix
  across Python/R/Julia/C++; schema lock only after validation on 3–5 real repos.
- **M3 — Full check engine + domain packs.** The four checks deepened across the failure families
  (leakage, overfitting/selection, realism, data-integrity, baseline-validity) as **domain-pluggable**
  checks. Ship the **general** packs (reproducibility, recomputation, holdout, declared invariants) plus a
  **quant domain pack as ONE example** — its deep statistics (effective-N Deflated Sharpe, Harvey-Liu,
  PBO/CSCV) are that pack's contents, and the *productized* quant depth lives in the CLI, not the skill
  core. Ship the planted-bug corpus (incl. the upstream-leakage fixture the spine alone misses).
- **M4 — Breadth + trust hardening.** per-domain realism templates (ML/A-B/science); LLM-contamination
  probe suite; re-run manifest / SBOM cryptographic signing; fix/harden mode; security threat-model
  verification. Publish measured catch-rate + false-positive numbers.
- **M5 — (BEYOND THE SKILL) CLI + managed-layer bridge.** CLI wrapper around the same scripts; signed
  audit trail; opt-in independent point-in-time / survivorship-free vendor-data tier. This is the on-ramp
  to Calma **Stage 2 (CLI)** and **Stage 3 (managed layer)** — it is NOT part of the Stage-1 skill. Build
  it only if/when you continue past the skill; the skill is complete at M4.

---

## Per-step acceptance tests (the build's definition of progress)

| Step | Deliverable | Acceptance test |
|---|---|---|
| 0.1 | Skill skeleton + `SKILL.md` | Skill loads; `/calma` discoverable |
| 0.2 | `ledger.schema.json` + `ledger.py` + `verdict()` | `ledger.py validate` passes; gate exit code authoritative; `verdict()` re-derived byte-for-byte in validation |
| 1.1 | `verify.yaml` schema + `draft_contract.py` | Auto-drafts a contract a human confirms in one batched screen; input-binding graded (bound/plausible/asserted) |
| 1.2 | `run_hermetic.py` (Seatbelt **and** container/VM tier) | `calma doctor` self-test passes; untrusted code refused unless verified tier live; achieved tier stamped |
| 1.3 | `recompute.py` + recipe lib + pinned libm | Recomputes Sharpe/return from raw `trades.csv`, bit-stable on the reference path |
| 1.4 | `compare.py` + verdict renderer | BTC fixture → **REFUTED** with recomputed number, via scripts (no model math) |
| 2.x | `consistency.py` + calibrated tolerance + served-fraction matrix | GRIM/statcheck catch a planted impossible claim; tolerance model calibrated on real nondeterministic runs; matrix published |
| 3.x | five-family engine + `stats_engine.py` + planted-bug corpus | Each family catches its planted bug; DSR/PBO match reference impls; quant CONFIRMED reachable |
| 4.x | breadth templates + contamination probes + signing | Measured catch-rate + FP published; manifest signed/verifiable |
| 5.x | CLI + vendor-data tier | CLI reproduces skill verdicts; signed audit trail; opt-in independent-data path |

---

## Definition of done (the whole product)

The **Stage-1 skill** is complete when **milestones M0–M4 pass their blueprint acceptance tests**, the
five-family engine runs, the verdict pipeline is fully deterministic (no model arithmetic anywhere),
every Validation Plan (§16) lock-gate has been **run** (passed, or its measured result stamped into the
verdict scope), and the skill reproduces the BTC fixture REFUTED end-to-end through its own scripts.
(M5 — the CLI + managed-layer bridge — is the start of Calma Stage 2/3 and sits beyond "the skill is
done.") Per-milestone
"done" = that milestone's acceptance tests green and committed, with open items recorded in
`BUILD-NOTES.md`.

The hard components (verified isolation tier, pinned libm, DSR/PBO engine) are **built, not descoped** —
research them, implement them, validate them. The founder is available to assist on the empirical
lock-gates; everything else is the build session's to engineer in full.
