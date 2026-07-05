# Hardening Audit — Calma

**Branch:** `hardening/2026-07-05` (off `main`) · **Started:** 2026-07-05 · **Engineer:** staff-eng hardening pass (automated)

This is the append-only source of truth for the production-hardening pass. One section per phase.
Operating rules: fix root causes (never suppress), preserve behavior (characterization-test first),
prove code dead before deleting, never weaken security, small scoped commits, stop + log ambiguous/
destructive decisions under **OPEN DECISIONS** rather than guessing.

---

## Phase 0 — Discovery & Baseline (2026-07-05)

### Architecture summary

Calma is a *correctness layer*: connect a repo → re-run it in a sandbox → independently recompute every
number it reports → three-way diff (claimed vs produced vs recomputed) → fail-closed verdict
(CONFIRMED / REFUTED / INVALIDATED). The franchise invariant is **false-confirm rate (FCR) = 0**.

Two products in one repo:

| Path | Stack | Role | Deploy |
|---|---|---|---|
| `spike/` | Python 3.12 | The engine **and** the verify API + dashboard. 274 tracked files, ~115 source modules. | Fly.io — `spike/Dockerfile` + `spike/fly.toml` → `calma-engine.fly.dev` |
| `web/` | Next.js 15 (App Router), React 19, TypeScript | Marketing landing (the brand) + WorkOS-gated `/dashboard/verify` that proxies to the engine. 95 tracked files. | Vercel → `calma1.vercel.app` |

**`spike/` module map (boundaries):**
- `core/` — the trust oracle: recompute catalog, three-way diff, validity (leakage/overfitting), fail-closed
  verdicts, tiered limits. **Pure-stdlib, zero shared code with the repo under test** (the anti-circularity
  firewall; enforced by a firewall test).
- `capture/` — instrumented capture; intercepts the raw arrays passed to each metric (`colab_shim` shims
  notebook/Colab I/O).
- `runner/` — repo-to-runnable: env build, sandbox (host / E2B Firecracker / Modal-GPU), secrets, egress,
  data resolution, E2B runner.
- `discovery/` — claim extraction (TDMR) from results.json / README / stdout + salience ranking.
- `synth/` — novel-formula synthesis + independent validation + Helix-backed store.
- `orchestrator/` — flag-gated "make-runnable" brain (assess → rank → bounded execute/observe/revise);
  never touches the verdict (behind the FCR firewall). Off by default.
- `attest/` — trust/attestation stack. `helix/` — HelixDB graph+vector store for the formula catalog.
- `optimize/` — the FCR meta-evals (the franchise gates) + `SCOREBOARD.md`.
- `hook/` — the CI stop-hook. `recipes/` — ported numeric library (math-convention single-letter names).
- `server.py` — FastAPI verify API (durable jobs, admission control, service-token auth, tenant/tier
  headers). `pipeline.py` — the one reusable verify loop shared by server + tests. `validity_scan.py` —
  the no-reproduction "report card" backend.

**External I/O:** GitHub (clone + App installations), E2B (sandboxes), Modal (GPU), Exa (formula search
fallback), Anthropic API (planner/orchestrator/synth), HelixDB, WorkOS (auth), Stripe (pricing, pre-launch).

**History context:** this codebase has already been through multiple audit/hardening passes (process-
isolation supervisor, security + rate-limit layer, adversarial FCR hardening, DX audits). It is *mature and
heavily tested*. This pass is therefore about (1) closing the objective gate gaps below, (2) wiring
enforcement so they cannot silently regress, and (3) a fresh deep pass on error-handling / perf / resilience
/ observability with characterization tests — not a greenfield cleanup.

### Baseline state (exact, measured 2026-07-05)

Tooling lives in `~/.calma/spike-venv/bin` (system python has none). Web uses Node 24 / npm 11.

| Gate | Command | Result |
|---|---|---|
| Python tests | `pytest tests -q` | ✅ **995 passed, 2 skipped** (78s); 997 collected |
| FCR franchise gates | `optimize/{redteam,formula_fuzz_eval,metamorphic_eval,fabrication,repair,stochastic,anomaly_eval,xcheck_eval,interval_eval,bounty,convention_fuzz}.py` | ✅ **11/11 OK** — FCR=0 holds |
| Python lint | `ruff check .` | ✅ clean |
| Python dead-code | `vulture … --min-confidence 80` | ✅ clean (0) |
| Python types | `mypy core capture discovery synth runner optimize attest connect orchestrator hook *.py --ignore-missing-imports` | ❌ **23 errors in 5 files** (115 checked) |
| Python format | `ruff format --check .` | ❌ **219 of 222 files would reformat** (never adopted) |
| Web types | `tsc --noEmit` | ✅ clean |
| Web lint | `next lint` | ⚠️ passes with **5 warnings** (2 exhaustive-deps, 3 no-img-element) |
| Web build | `next build` | ✅ succeeds |
| Web deps | `npm audit --omit=dev` | ✅ **0 vulnerabilities** |
| Python deps CVE / SAST | pip-audit / safety / bandit | ⚠️ **not installed / not run** — no Python CVE or SAST scan exists |
| TODO/FIXME/XXX/HACK in source | grep | ✅ **0** |
| Secrets | root `.env` present but **gitignored** (not tracked); `.env.example` tracked | ✅ no secrets tracked (deep secret-scan deferred to Phase 1) |

**CI reality (`.github/workflows/ci.yml`):** runs **only** `pytest spike/tests`. It does **not** run ruff,
mypy, vulture, the FCR gates, or **anything** for `web/` (no build/lint/tsc). This is the root cause of the
drift below — nothing gates types/lint/format, so they rot. Dependabot covers pip + npm + github-actions ✅.

### Ranked issues (severity × category A–H)

**BLOCKER** — breaks the definition-of-done gate as written:
- **B0.1 [Phase 1 / gate]** Type-checker is RED: **mypy 23 errors**. Fixing this to 0 is required for the
  gate. Breakdown below (most are one root cause).
- **B0.2 [Phase 1 / gate]** Formatter gate is undefined: `ruff format` was never adopted (219-file drift).
  The gate item "formatter: no diffs" cannot pass without a **decision** — see OPEN DECISIONS. Not a
  code defect; a policy gap. Marked blocker only because the gate can't go green until decided.

**MAJOR:**
- **M0.1 [Phase 1 — safety net]** CI enforces only pytest. ruff/mypy/vulture/FCR-gates and the *entire* web
  pipeline (build/lint/tsc) run on no commit. This is *why* mypy drifted to 23 errors and lint warnings
  accumulated. Highest-leverage fix: make the full gate a single command and wire it into CI.
- **M0.2 [Phase C — error handling]** `core/leakage.py:256` — assigning a 6-tuple to a 7-tuple-typed
  variable (`[assignment]`). Real arity mismatch; verify the leakage-detection path isn't dropping a field.
- **M0.3 [Phase C — error handling]** `discovery/salience.py:47` — `float(Any | None)` can raise `TypeError`
  on malformed discovery input (`[arg-type]`). Needs a None-guard + explicit handling.
- **M0.4 [Phase D — security]** No Python dependency-CVE gate (pip-audit) and no SAST (bandit). npm side is
  clean but not CI-gated. Dependabot opens PRs but does not fail a build on a high/critical CVE.
- **M0.5 [Phase C — error handling]** **120 broad `except (Exception)?:`** blocks in `spike/` source. Many
  are deliberate best-effort (fail-closed philosophy), but each must at minimum log context — audit for
  silent swallow vs. deliberate-and-logged.

**MINOR:**
- **m0.1 [Phase D — security, hygiene]** `server.py` mypy cluster (9 of 23): `Identity.tier` is annotated
  `object` (`server.py:106`) though it is really `core.limits.Tier`; that single annotation cascades into
  every `check_api_rate` / `clamp_request` / `admit_*` / `.name` / `.allow_data_acquisition` error on the
  authz path. Runtime is correct today; annotate `tier: LIM.Tier` to fix the cascade. Also `server.py:91`
  `hmac.compare_digest(str|None, …)` — guarded at runtime but not narrowed for the type-checker; and
  `server.py:181` `dict|None.get`.
- **m0.2 [Phase C]** `capture/colab_shim.py` mypy cluster (10 of 23): `[attr-defined]` on a dynamically
  constructed module shim. Needs proper typing (ModuleType / typed facade), not suppression.
- **m0.3 [Phase G — UX]** `web` lint: 2× `react-hooks/exhaustive-deps` in `CardNav.tsx` (stale-closure risk
  in the GSAP timeline) and 3× `no-img-element` (`CardNav`, `BpFlow`, `BpFooter` — LCP/bandwidth). Resolve
  at root (correct deps / `next/image`) or document a justified exception.
- **m0.4 [Phase A — hygiene]** Doc drift: `spike/README.md:92` claims "mypy … clean across the source tree"
  — currently false (23 errors). Fix the code, then the doc is true again.
- **m0.5 [Phase A — hygiene]** No formatter configured for either side beyond lint (no `ruff format` in the
  gate, no prettier for web). Tracked `.DS_Store` noise (`.github/.DS_Store`, root `.DS_Store`).
- **m0.6 [Phase 1]** No coverage measurement configured (no pytest-cov). Cannot state a coverage % or set a
  target until added.

### Categories not yet deep-audited (scheduled for their themed phases)
Error-handling completeness (C), least-privilege on every protected path (D), perf hot-paths / N+1 /
streaming (E), resilience / graceful-shutdown / idempotency / resumability (F), UX loading/empty/error
states (G), structured logging / metrics (H). Memory + history indicate much of F/H is already built
(process-isolation supervisor, durable background jobs, timestamped logging, health checks); each phase
will verify against the current code rather than assume.

### Proposed phase order (by leverage, not by mission letter)
1. **Phase 1 — Safety net.** Single-command gate runner (Makefile/`scripts/`), add pip-audit + a secret
   scan + coverage, then wire the **full** gate (Python + FCR + web) into CI so nothing can regress. Resolve
   the formatter OPEN DECISION. *Defines the clean bar for the final loop.*
2. **Phase 2 = D+C on the type errors.** Drive mypy to 0 by root cause (Tier annotation, compare_digest
   narrowing, leakage tuple arity, salience None-guard, colab_shim typing, hook_stop). These sit on the
   auth/limits/leakage paths — characterization-test any behavior-adjacent change first.
3. **Phase 3 = G.** Web lint → 0 warnings at root cause.
4. **Phase 4 = C.** Broad-except audit (M0.5): classify all 120, add logging/context or deliberate-and-
   documented, no silent failures.
5. **Phase 5 = D.** Security deep pass (headers, CORS, cookie flags, input validation on every external
   boundary, secret scrubbing in logs, fail-closed ingress doc).
6. **Phase 6 = E / F / H.** Perf hot-paths, resilience/background-execution verification, observability.
7. **Phase 7 = A / B.** Targeted dead/duplicate + architecture pass (repo is already ruff/vulture clean, so
   this is verification + small consolidations, not a rewrite).
8. **THE LOOP.** Run the full gate end-to-end; fix root causes; re-run the *entire* gate; repeat until one
   clean pass; write the final summary.

### Gate deltas at baseline (what "done" must flip)
`[✅ build] [✅ 995 tests / ⚠️ coverage unmeasured] [❌ mypy 23→0] [⚠️ web lint 5→0] [❌ ruff-format undecided]
[✅ ruff] [✅ vulture] [⚠️ pip-audit absent] [✅ npm audit] [✅ 0 secrets tracked] [✅ 0 TODO] [✅ FCR 11/11]`

---

## OPEN DECISIONS

**OD-1 — Adopt `ruff format` repo-wide? (219-file reformat)**
The mission gate requires "formatter: no diffs," but `ruff format` was never adopted: **219 of 222** Python
files would be reformatted. Reasonable engineers disagree here, so per Rule 8 I am **not** unilaterally
reformatting. Options:
- **(a)** Adopt `ruff format` as the standard: one isolated "style: apply ruff format" commit (219 files,
  no logic change), then add `ruff format --check` to the gate. Clean long-term; large one-time diff that
  touches nearly every file's blame.
- **(b) [recommended]** Declare **`ruff check` (lint) the formatting bar** and drop `ruff format` from the
  gate — the repo is already lint-clean and the founder has deliberately linted-not-formatted to date. The
  gate item becomes "ruff check clean" (already ✅). Zero churn.
- **(c)** Scope `ruff format` to only files this pass otherwise touches (format-on-edit), leaving the rest.
  Compromise: no mega-diff, gradual convergence, but the global `--check` stays red for a while.

*Decision needed before the formatter gate can go green. I will proceed with everything else meanwhile and
treat (b) as the working assumption unless told otherwise.*
