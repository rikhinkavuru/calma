# Orchestrator as Adaptive Edge-Case Brain — SOTA Build Plan

**Status:** design (validated against 2024–2026 SOTA + the current codebase) · **Author:** staff-eng · 2026-07-05

## 0. TL;DR

Stop hand-patching a strict pipeline for each edge case (hardcoded paths, results in odd places, domain
metrics, missing binaries…). Make the **orchestrator the adaptive layer**: *assess → propose a fix → apply it
HOW-only → validate independently → learn it → replay it next time.* This is the "AI proposes, determinism
disposes" contract Calma already runs for env, generalized to **discovery, data, and binding**.

The SOTA literature (SetupX, BootstrapAgent, Repo2Run, SWE-agent, Reflexion, the grounding-gate line, the
self-healing-pipeline line, CORE-Bench/PaperBench) **validates the architecture Calma already has** (ReAct
loop + typed firewall + experience cache) and tells us exactly which four things to add: (1) a **prosecutor–
judge** verification protocol that separates *setup-induced failure* from *repo bug*, (2) **dual-modality
experience units** with vector retrieval, (3) **speculative execution + snapshot rollback**, (4) an
**evidence-grounded, agentic discovery/binding** step. All behind the same non-negotiable: **the LLM never
touches the verdict.**

---

## 1. Problem & thesis

Calma's coverage tail is infinite and *per-repo*: `benchmark_ci.json` under `results/`, a hardcoded
`/Users/…/Downloads/sts/results/x.csv`, "homology_sensitivity_testable", a Foldseek binary, a notebook-only
output, a CSV of predictions that needs a scoped recompute. Pre-coding each is a losing game (I just proved
it — my `results/` scan fixed *one* shape). **The intelligence has to move to run time.**

**Thesis.** The orchestrator becomes a bounded ReAct loop whose *action space* covers not just "make it run"
(env) but "make it verifiable" (find the numbers, bind them to evidence, resolve missing inputs) — with an
LLM proposing fixes over a **typed, audited registry** and a **deterministic gate** disposing of the verdict.
Every fix is **evidence-supported, reversible, and learned**.

**Franchise invariant (unchanged, load-bearing): FCR = 0.** The adaptive brain can only ever change *coverage*
(a wrong guess → DISCOVERED/INCONCLUSIVE/REFUTED), **never** cause a false CONFIRM.

---

## 2. SOTA foundations (validated, cited)

| Source | Year | What it contributes | Calma today | Action |
|---|---|---|---|---|
| **SetupX** (Zhou et al.) | 2026 | The closest prior work: functionality-correct repo setup. Names the 3 gaps — (1) cross-repo experience transfer, (2) multi-step trial-and-repair under **non-invertible** state, (3) verification that separates **setup-induced failure from repo bug**. Mechanisms: **XPU** dual-modality experience units (text guidance + executable action) in a **vector store** w/ 2-tier retrieve (vector + LLM rerank) + delayed audit; **speculative execution** on a **LIFO snapshot stack**; **Prosecutor–Judge** verification. 92% pass, +19% over baseline. | HintStore (error-sig → action), ApproachCache, RunPlanCache; no snapshot; env-only revise; `classify_failure` distinguishes some repo-bugs | Adopt all three mechanisms (§4.3–4.5) |
| **BootstrapAgent** | 2026 | Discovery agent scans README/**CI**/lockfiles/metadata → evidence; planner → setup+diagnostic+**verification** commands → a persistent **`.bootstrap` contract**; deterministic verifier **replays in a CLEAN container**. **Warm-repair + clean cold-start replay**; **delta-repair with sanity checks** (each repair a constrained, evidence-supported delta — never free regeneration, never weakens the verification). | `ci_workflow_signals` (just shipped) is a first "discovery agent"; RunPlan ≈ the contract | Formalize RunPlan as a replayable contract; delta-repair discipline (§4.2) |
| **Repo2Run** (ByteDance) | 2025 | Iterative build→test→**rollback**→synthesize a runnable **Dockerfile** by **recording+replaying** the winning action sequence. Dual-environment, base-image change, "environment pollution" failure mode. 86% on 420 repos. | Env-repair ladder + RunPlan cache | Record winning action-sequence → replay artifact (§4.4) |
| **SWE-agent** (Yang et al., NeurIPS'24) | 2024 | **Agent-Computer Interface**: a *minimal, well-defined* command set + **structured observations** (line numbers, pagination, "N lines below") beats raw shell. Linter-in-the-loop discards invalid edits. "How the agent interacts matters as much as the model." | 31-tool typed registry | Registry = our ACI; keep it minimal + structured obs (§4.1) |
| **Reflexion** (Shinn et al., NeurIPS'23) | 2023 | **Verbal reinforcement**: reflect on a failure → store the reflection in an **episodic memory buffer** → better next trial ("semantic gradient"). | HintStore action-only | Add the *textual* half → dual-modality (§4.3) |
| **jingu-trust-gate / groundcheck / groundguard / SHOR** | 2026 | The grounding-gate line, one message: **separate generation from verification; the proposer must never self-certify.** The gate is **deterministic, shares no latents** with the generator, is constrained to the **evidence** (not open-world truth). SHOR: a *dumb* deterministic entity-checker whose errors are **uncorrelated** with the generator's. groundcheck: per-claim `supported/refuted/unverifiable/needs_qualification` + `keep/revise/retract`; **decompose compound claims** so a true sub-claim can't launder a false bundle. | The pure-stdlib recompute oracle (zero shared code) **is** this gate; the firewall test enforces it | Make it explicit as the Judge (§3, §4.5) |
| **Self-healing pipelines** (Kestra Aegis; AIJCST/IJERET surveys; toph-eval) | 2024–26 | **Error-signature → cached fix** (DuckDB local memory → resolve in <0.5s, no LLM; MTTR 13h→3s). **Constrained-autonomy safety model**: act only with *sufficient evidence + bounded risk + validated rollback + policy*. **AST safety engine** + **shadow/dry-run sandbox** before prod. A **fault taxonomy** (toph-eval: 63 types × 10 categories) with **causal-chain accuracy** weighted highest (trace to origin, not where it surfaced). ReAct trace = an **audit feature**. | `classify_failure` taxonomy; supervisor caps | Extend the taxonomy + a remediation-safety model (§5) |
| **CORE-Bench / PaperBench / AutoReproduce** | 2024–25 | The reproduction-agent benchmark domain (our exact market). Agent must **search ALL outputs** to answer. PaperBench: run the reproduction in a **fresh, separate** environment to distinguish real results from **hard-coded** ones. AutoReproduce: LLM judges **overrate** code-vs-code consistency → **execution** is the reliable signal. | discovery + independent recompute | "Search all outputs" = agentic discovery (§4.6); "fresh separate reproduction" = our firewall |
| **Trace2Skill** | 2026 | Distill trajectory lessons into transferable skills via a **parallel fleet** of analyzers + **hierarchical, conflict-free** consolidation (holistic, not sequential-overfit). Low-abstraction memories cause **negative transfer** → need the textual half. | — | How to grow the experience library offline (§4.3, §7) |

**Net:** the research doesn't say "rebuild." It says Calma's spine is right (ReAct + typed firewall +
experience cache) and pinpoints four upgrades. That's the plan.

---

## 3. The invariant — the FCR firewall as an explicit Prosecutor–Judge gate

This is the load-bearing wall. Every grounding paper independently converges on it, and it is Calma's moat:

- **Proposer (untrusted):** the LLM/orchestrator proposes *HOW* — an entrypoint, a dep, a Python bump, a
  file relink, a claim→artifact binding, "these numbers live in `results/benchmark_ci.json`". It may be wrong.
- **Judge (deterministic, zero shared code):** the pure-stdlib recompute + three-way diff. It **shares no
  latents** with the proposer (SHOR's "uncorrelated errors"), is constrained to the **repo's own captured
  evidence** (not the proposer's assertion), and emits the verdict.
- **Hard rule (jingu):** *never let the proposer self-certify.* A binding the LLM proposes is
  **verdict-adjacent** → the independent recompute validates it; a wrong binding → REFUTED/INCONCLUSIVE,
  **never** CONFIRM. A "confirmed with no evidence ref" is the canonical bug the gate exists to catch.
- **Prosecutor–Judge separation (SetupX):** distinguish a **setup-induced** failure (Calma's fault → keep
  adapting) from a **repo bug** (the code is broken / the number isn't reproducible → report honestly). The
  ebv-ms hardcoded path is the textbook case: Prosecutor collects evidence ("the file exists at
  `results/x.csv`, code reads an absolute path"), Judge rules "relink is a valid HOW-only fix" — but if the
  file were genuinely absent, Judge rules "repo bug, surface it."
- Enforced in CI by the existing `test_orchestrator_firewall` (types.py imports no `core.verdict`/`core.diff`).
  **Every slice below extends the PROPOSER; none may touch the JUDGE.**

---

## 4. Architecture

```
                    ┌───────────────────────────  ADAPTIVE BRAIN (proposer, untrusted)  ──────────────────────────┐
  repo ──► ASSESS ──►  observe → RETRIEVE experience(XPU) → PROPOSE fix(delta) → APPLY(HOW-only) → speculative-run  │
           (§4.6)   │      ▲                                                                    │  (snapshot/rollback)│
                    │      └──────────────────────── revise, bounded (Budget state machine) ◄──┘  (§4.2, §4.4)      │
                    └─────────────────────────────────────────────┬──────────────────────────────────────────────┘
                                                                   │  RunResult.runs  (repo's OWN captured numbers only)
                    ┌──────────────────────────────  FIREWALL  ────┴────────────────────────────────────────────────┐
                    │  JUDGE (deterministic, zero shared code): capture → recompute → three-way diff → fail-closed    │
                    │  verdict.  Distinguishes setup-failure vs repo-bug.  Learns the winning fix back into XPU.      │
                    └─────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 The action registry = Calma's ACI (SWE-agent, SetupX)
Keep the **typed 31-tool registry** as the agent-computer interface — minimal, audited, each tool `kind`-tagged
(`static` / `env` / `data` / `discovery`) and firewall-classified. Add **structured observations** (the tool
returns a compact, uniform "what I saw" — file list, error signature, missing-entity list) so the proposer
reasons over clean state, not raw logs. **New tool kinds this plan adds:** `resolve_path` (relink a hardcoded
path to a committed file), `locate_results` (find where numbers are reported), `bind_artifact` (propose a
claim→predictions binding for the Judge to validate), `install_binary` (bioconda/apt). The registry stays the
**only** surface the LLM can act through (no free shell into the verdict path).

### 4.2 The loop: delta-repair, bounded by a deterministic state machine (BootstrapAgent, CalibreOS)
- **Warm repair, clean replay.** Iterate fixes fast in the **warm** sandbox; the number that counts is the one
  captured on the **final clean run** (= our independent reproduction). This is BootstrapAgent's cold-start
  guarantee and it *is* the firewall.
- **Delta-repair with sanity checks.** Each revise is a **constrained, evidence-supported delta** over the
  current RunApproach (add-dep / set-env / relink-path / bind-artifact), never a free regeneration, and it may
  **never weaken the verification** (can't "fix" a run by disabling a check). Preserve what already worked.
- **The state machine — not the LLM — decides termination** (CalibreOS): `Budget` (step_cap, tokens_cap,
  wall) + oscillation guard + the new **per-fault attempt cap**. Three independent limits, already Calma's
  design.

### 4.3 Experience = dual-modality XPU with vector retrieval (SetupX, Reflexion, Trace2Skill)
Upgrade `HintStore` → **XPU store**: each unit = `{ symptom (retrievable text: error signature + a
one-line reflection), action (executable: the exact delta), scope (metric/lang/pkg-manager), telemetry
(hits/successes/failures) }`.
- **Dual-modality is non-optional** — action-only records cause **negative transfer** (Memory Transfer
  Learning); the text half is what makes a fix *retrievable by symptom*.
- **Two-tier retrieval:** vector coarse filter (Helix vector search — already the planned backend) → LLM
  rerank for precise match. **Delayed audit** demotes an XPU whose downstream verdict later fell.
- **HOW-only + telemetry-gated:** an XPU only ever proposes a HOW; a low-success XPU is demoted, never
  auto-applied. Local-JSON now (RunPlanCache pattern), **Helix `XPU` node** for the durable cross-instance
  store (mirrors `synth/store.py`'s local↔Helix swap). Cached hit → **skip the LLM** (Kestra: 13h→3s).
- Grow it **offline** with a Trace2Skill-style parallel fleet over the run-journal (post-MVP).

### 4.4 Speculative execution + snapshot rollback (SetupX LIFO, Repo2Run)
Non-invertible state is the core hazard: a half-applied fix pollutes the env; re-deriving from scratch is
slow. Add an **E2B snapshot/rollback** layer (E2B supports pause/resume; the latency roadmap already lists
snapshots): before trialing a candidate fix, snapshot; on failure, roll back to the last known-good state
(LIFO). This makes "try the XPU suggestion" safe and cheap, and lets us **record the winning action sequence →
replay it as the RunPlan contract** (Repo2Run's Dockerfile synthesis; our RunPlanCache).

### 4.5 Verification: Prosecutor–Judge, setup-failure vs repo-bug (SetupX, §3)
The observe step runs a **Prosecutor** (evidence collection: does the missing file exist elsewhere in the
repo? is the entrypoint's error a dep vs a data vs a logic failure? did the install actually complete or just
the base image?) feeding a **Judge** decision on the *loop's* next move — **distinct** from the FCR Judge that
issues the verdict. This is what turns "surfaced honestly" into "assessed and fixed": the ebv-ms path is
*Prosecutor: file committed at results/x.csv + code reads an abs path → Judge: relink (HOW-only) → retry*.
Beyond exit codes (SetupBench's lesson: agents declaring "done" when only the install ran).

### 4.6 Evidence-grounded, agentic discovery (CORE-Bench, BootstrapAgent, groundcheck)
Generalize my `results/` patch into a capability: **"where does this repo report its numbers, and how do I
bind each to evidence?"**
- **Locate:** CORE-Bench's "search ALL outputs" — scan result dirs + arbitrary result files (shipped) →
  next, an LLM `locate_results` over the file tree + README/paper when the deterministic scan finds nothing.
- **Bind (verdict-adjacent → gated):** propose claim→artifact bindings ("`homology_sensitivity_testable` =
  recall over rows where `pfam_testable=True`, from `benchmark_classifier.csv`, cols label/call"), then the
  **Judge validates by independent recompute** — a wrong scope → REFUTED/INCONCLUSIVE, never CONFIRM
  (groundcheck: decompose scoped claims so a broad recompute can't launder a scoped one).
- **Decompose compound claims** (groundcheck) so the pfam-testable subset is its own verifiable unit.

---

## 5. Edge-case taxonomy → remediation registry (self-healing-pipeline "fault taxonomy + safety model")

A structured, extensible taxonomy (toph-eval style, causal-chain-weighted) mapping a **fault signature** → a
**HOW-only remediation** → the **evidence** that licenses it → the **validation** that confirms it. Seed:

| Fault (signature) | Remediation (HOW-only, proposer) | Evidence required | Judge validates |
|---|---|---|---|
| Hardcoded abs path → `FileNotFoundError` | `resolve_path`: relink basename to a committed file (data_resolver — **exists, wire it**) | basename committed in-repo & unique | recompute unchanged; a wrong file → REFUTED |
| Python↔dep conflict | reprovision Python / relax pins (**shipped**) | resolver's required-python | env builds; determinism/recompute unchanged |
| Missing system binary | bioconda/apt install (`install_binary`) | README/CI/`environment.yml` names it | run proceeds; recompute independent |
| Numbers only in a committed file Calma didn't scan | `locate_results` + arbitrary result-file scan (**partly shipped**) | file parses to metric(s) via `map_metric` gate | discovered → recompute from committed artifact |
| Domain-scoped metric (sensitivity on a subset) | `bind_artifact`: propose scope + columns | claim + a predictions file with the columns | **independent recompute of the scoped metric** |
| Multi-step pipeline (step B needs step A's output) | order approaches by data-flow; run producer first | producer writes the consumer's input | consumer runs; recompute independent |
| Data behind auth / external fetch | gated acquire (**exists**) | tenant secret / catalog source | mismatch on auto-fetched data → capped INCONCLUSIVE |

**Remediation-safety model (constrained autonomy):** a remediation fires only with *(sufficient evidence) ∧
(bounded risk: HOW-only, env/data, never source-logic that a snapshot can't revert) ∧ (validated rollback) ∧
(policy: tier-gated + FCR-firewalled)*. A source edit that a repair makes is already capped to REPRODUCED-ONLY
by the snapshot rail — keep that.

---

## 6. Build plan (phased slices — each FCR-gated, `make gate` green, FCR 11/11)

Ordered by leverage × safety. Every slice: proposer-only, bounded, tested, HOW-only.

- **S0 — Wire the fix that already exists (proof-of-pattern). ✅ DONE (2026-07-05).** *Diagnosis:* the tool
  logic was fine; the wiring wasn't. The DEFAULT deep pipeline path (`pipeline._verify_deep`, the path the smoke
  actually ran — `orchestrate` is flag-gated OFF) repaired missing data with the relative-only
  `relink_committed_data`, which **explicitly refuses absolute paths** (`data_resolver.py` L174). The ebv-ms
  hardcode `/Users/…/results/x.csv` is absolute → silently skipped → surfaced as missing-data. The
  absolute-capable `make_data_available` (copy committed file to repo-root + AST-rewrite the literal, or
  sole-dataset substitution) was reachable ONLY via `resolve_data_path` → `orchestrate()` (inert). *Fix:*
  pipeline default path now calls `make_data_available`; its `modified` list (the rewrite / substitution
  marker) is folded into `repair_manifest.source_modified` so `_apply_agent_modified_cap` caps
  AFFIRMATIVE→REPRODUCED-ONLY (a source edit can't attribute the number to the repo's own code → no false
  CONFIRM). A same-basename relink returns `[]` → full verdict, unchanged. Reaches E2B (fresh microVM
  re-uploads `repo_dir` per run). Test: `test_data_relink_pipeline_e2e.py` (absolute→runnable+capped;
  relative→uncapped CONFIRM). `make py` green, FCR 11/11, 1022 tests.
- **S1 — Fault taxonomy + remediation registry (§5). ✅ DONE (2026-07-05).** `orchestrator/remediation.py`:
  the `Evidence`/`Remediation`/`RemediationPlan` types + a `REMEDIATIONS` taxonomy (fault kind → ordered
  HOW-only remediations, cheapest first) + deterministic evidence collectors + `propose()` (the pre-LLM
  dispatch: first WIRED remediation whose evidence licenses it) + `classify()` (the structured taxonomy view).
  Wired: hardcoded-path relink (evidence = basename committed / sole dataset — reuses the `data_resolver`
  primitives so evidence matches the apply). Evidence-wired, apply-follow-up: missing-binary (allowlisted tool
  named missing AND declared in CI/environment.yml/README — supply-chain rail; apply exists on the E2B acquire
  path, main-path promotion is next). Firewall-clean (no `core.verdict`/`core.diff`). 12 hermetic tests.
- **S2 — Prosecutor–Judge observe step (§4.5). ✅ DONE (2026-07-05).** `orchestrator/observe.py`: `observe()`
  labels a failure **setup-induced vs repo-bug vs environmental** (SetupX's lesson, beyond exit codes) and
  picks the loop's next move (`remediate` / `stop` / `revise`) over the S1 registry. Wired into `execute()`
  (new `repo_dir` kwarg; `None` on the hermetic fake path → signature-only classification = the pre-S2 control
  flow, so zero behavior change on injected effectors). Behavior preserved (all `test_orchestrator_loop`
  green); NEW: the label + Prosecutor evidence go into the ReAct trace (`data-resolved`/`environmental-stop`
  events now carry `evidence`/`label`/`detail`). 7 hermetic tests (observe labels + loop remediate→retry +
  honest repo-bug stop). `make py` green, FCR 11/11, 1041 tests.
- **S3 — Dual-modality XPU store + 2-tier retrieval (§4.3). ✅ DONE (2026-07-05).** `orchestrator/xpu.py`:
  the `XPUnit` (signature + retrievable **symptom text** + HOW-only action + scope + telemetry) upgrades the
  action-only HintStore — the symptom half is what makes a fix retrievable by a novel repo whose signature
  differs (kills negative transfer). **Two-tier retrieval:** exact-signature (certain) → vector cosine over
  the symptom (paraphrase path) ≥ threshold. **Telemetry-gated delayed audit:** a unit whose success-rate
  falls below the floor is demoted, never proposed. **Two backends behind one interface (mirrors
  `synth/store.py`):** `LocalXPU` (stdlib embed+cosine, offline/test) + `HelixXPU` (an `XPU` node on HelixDB —
  **OD-B: Helix now**, activates on `CALMA_HELIX` + reachable, else falls back to local — no sqlite-vec
  interim). Wired into `make_revise` (XPU tier BEFORE the heuristic → cached-hit-skips-LLM) + `execute`
  (records the symptom+action on a verified win) + the pipeline's orchestrated path. Reuses `synth.store`'s
  embedder (DRY); firewall-clean. 9 hermetic tests. *Note:* the delayed-audit NEGATIVE reward is API-complete
  + tested (reward/demotion), but its automatic trigger from the post-VERDICT signal is a small pipeline
  follow-up (positive record-on-win is live). `make py` green, FCR 11/11, 1050 tests.
- **S4 — Evidence-grounded discovery/binding (§4.6). ✅ PART 1 DONE (2026-07-05) — deterministic scoped
  binding, FCR held at 0.** `core/artifacts.py`: `read_scoped` (roles + boolean scope columns, row-aligned) +
  `scope_qualifiers` (strip metric/split words → subset tokens) + `bind_scope` (token ∩ real boolean column,
  **refuses ambiguity** — never guesses between subsets) + `recompute_scoped` (recompute over the truthy subset,
  guarded: a real proper subset of ≥3 rows) + `bind_and_recompute_scoped`. Wired into `pipeline._artifact_verify`
  (the qualifier rides in `claim.location`'s raw name; scoped result preferred over all-rows for a subset claim).
  Closes the ebv-ms case: `homology_sensitivity_testable`=recall over `pfam_testable==True` → CONFIRMED on the
  subset (0.75), while the all-rows number (0.50) can no longer launder it → REFUTED. **Two scope kinds:**
  boolean column (truthy subset) AND low-cardinality **categorical value** (`variant_class==rare` — the common
  "metric on the minority/rare/hard class" shape). **FCR stayed 0** — the scope is deterministically grounded
  (claim-named qualifier ∩ a real column/value) with ambiguity-refusal + subset guards, so the coverage win
  spent none of the ≤5% budget. 11 hermetic + adversarial tests. `make py` green, FCR 11/11, 1061 tests.
- **S4 part 2a — BLIND LLM `bind_artifact` (2026-07-05). ✅ DONE.** `planner.propose_scope`: when the lexical
  binder misses a subset claim ('minority class' ≠ the value 'rare'), a BLIND LLM proposes the {column, value}
  from the label semantics — it is NOT shown the claim's numeric value, so it cannot p-hack a subset to match —
  validated against the real columns/values (hallucinations rejected) and recomputed by the SAME unchanged
  Judge (`core.recompute_scoped`). Wired into `pipeline._artifact_verify` (gated on `opts.plan` + key; audit
  labels it `AI:col==val`). **FCR stayed 0** — the blind proposer + independent recompute means even this LLM
  surface produced no false confirm (adversarial test: a label-says-subset / value-is-all-rows claim → REFUTED,
  not laundered). The LLM stays OUT of `core/`. 7 hermetic (stubbed-model) tests. `make py` green, FCR 11/11,
  1068 tests.
- **S4 part 2b — LLM `locate_results` (2026-07-05). ✅ DONE.** `planner.locate_claims`: when the deterministic
  discovery scan finds NOTHING, an LLM searches the repo's result-ish files (bounded haystack) for REPORTED
  metric values the patterns missed (an odd file, a log, notebook prose) — CORE-Bench "search ALL outputs".
  Every located number is gated through `map_metric` (a real metric), a numeric value, and a file we ACTUALLY
  showed the model (no hallucinated files). Wired into the discovery stage (gated `opts.plan` + empty scan).
  **FCR:** a located value is only a CLAIM — CONFIRMED only if the independent recompute matches it, so a
  misread/hallucinated number → REFUTED/DISCOVERED, never a false CONFIRM. FCR stayed 0. 5 hermetic tests.
  `make py` green, FCR 11/11, 1073 tests.
  **S4 remaining (optional next):** numeric-threshold scopes ("sensitivity for coverage > 30x") — deliberately
  deferred (a threshold surface is more p-hackable; needs the §7 adversarial eval to bound it under ≤5%).
- **S4 grounding notes (original).** *Grounding (done):*
  the Judge already exists — `core/artifacts.py` `recompute_from_artifacts` → `recompute_from_cols(cols,
  metric, resolver)` recomputes a metric from a committed predictions CSV over ALL rows via the deterministic
  `SYNTH.recompute_any`, and `pipeline.py:863` binds it per-claim behind `_artifact_binds` (the
  anti-value-coincidence guard). **S4 = a SCOPED binding feeding that SAME unchanged recompute:** (1) a
  scope-retaining CSV parse (keep a boolean/categorical column besides the y_true/y_pred roles), (2)
  `recompute_scoped(cols, scope={col,value}, metric, resolver)` = filter rows then recompute, (3) the binding
  PROPOSAL of {metric, scope-col, value, column-map}. *FCR design (the delicate part — build with the §7
  adversarial eval as its gate):* the proposer saw the claim value, so it could p-hack a scope to match →
  **a DETERMINISTIC scope (claim-text ∩ a real column name, only when the claim explicitly names a subset) may
  reach CONFIRMED; an LLM-proposed scope caps to REPRODUCED-ONLY** (the `source_modified`/`data_auto_resolved`
  cap pattern) — never CONFIRMED on a scope the model invented. A wrong scope → wrong number → REFUTED. Wire
  the `edgecases/` FCR eval (§7) to PROVE a p-hacked/wrong scope never CONFIRMs before shipping. This is the
  ebv-ms recompute (`homology_sensitivity_testable` = recall over `pfam_testable==True` rows from
  `benchmark_classifier.csv`) and the highest-value coverage slice.
- **S5 — Speculative execution + snapshot rollback (§4.4). ✅ FOUNDATION DONE (2026-07-05); run_e2b wiring +
  live smoke = the ops step to enable.** *OD-A resolved:* E2B pause/resume is on ALL plans; the installed SDK
  (`e2b==2.30.0`) API is verified working — `sbx.pause()->bool` (id via `sbx.sandbox_id`),
  `Sandbox.connect(id)->Sandbox` (resume-by-id, a class-method-variant descriptor), `Sandbox.kill(id)`.
  *Built + tested:* `runner/snapshot.py` (pause/resume/kill primitives — best-effort, never raise, gated
  `CALMA_E2B_SNAPSHOT` off) + `orchestrator.cache.SnapshotCache` (fingerprint→snapshot-id warm-env flywheel;
  SMALL-bounded since each entry is a live paused sandbox = cost; **reaps** the old sandbox on
  replace/evict/discard via an injected `kill_fn` — E2B retains paused sandboxes indefinitely, so a cache MUST
  kill or it leaks). 15 hermetic tests (fake sandbox + monkeypatched SDK). HOW-only, firewall-clean. *Turnkey
  wiring (the live-smoke ops step, NOT done — E2B can't be validated hermetically):* in `run_e2b`, thread the
  repo `fingerprint`; before `_create_sandbox`, `if snapshots_enabled(): sbx = resume_sandbox(cache.get(fp),
  cfg)` and, on a hit, SKIP `_upload_dir` + `_install` (the snapshot already has `/work` + deps) → run directly
  (~1s vs a minutes-long boot+install); after a successful run, `cache.put(fp, pause_sandbox(sbx))` with
  `cache=snapshot_cache(kill_fn=lambda sid: kill_snapshot(sid, cfg))`. On any resume miss/failure →
  `cache.discard(fp)` and boot fresh (today's path). Flip `CALMA_E2B_SNAPSHOT=1` only after a live smoke
  confirms resume fidelity + measures the pause (~4s/GiB) / resume (~1s) cost on the deployed template.
  Speculative in-loop LIFO rollback (pause→trial→rollback) reuses the same primitives — S5 v2.
- **S6 — Delta-repair discipline + registry-driven LLM revise (§4.2).** Constrained, evidence-supported
  deltas; the LLM proposes only within the registry vocabulary; sanity checks forbid weakening a verification.
- **S7 — Offline experience distillation (Trace2Skill).** A parallel fleet over the journal consolidates
  trajectory lessons into a conflict-free XPU library; delayed-audit prunes. Post-MVP flywheel.

Cadence: S0–S1 immediately (deterministic, testable, closes real cases). S2–S4 are the intelligence core.
S5 needs the E2B snapshot primitive. S6–S7 harden + scale.

---

## 7. Evaluation — an internal edge-case benchmark (CORE-Bench / SetupBench / DI-BENCH style)

**✅ V1 DONE (2026-07-05):** `spike/optimize/edgecases.py` — a fault-class-tagged corpus (scoped-bool,
scoped-cat, unscoped) of synthetic repos run through the real `_artifact_verify` recompute, reporting coverage
+ the false-confirm RATE disaggregated by class, gated at ≤5% (currently **coverage 100%, FCR 0%**). Wired
into `make fcr` (the 12th eval). Grow it: add hardcoded-path / missing-binary / notebook-only / multi-step rows
and the LLM-proposer cases (stubbed) as those surfaces expand; add the numeric-threshold adversarial set before
building that surface.

You can't ship adaptivity you can't measure. Build **`spike/optimize/edgecases/`**: a curated corpus of real
repos, each tagged with its fault class(es) (hardcoded path, results-elsewhere, scoped metric, missing binary,
notebook-only, multi-step). Metrics, disaggregated by fault class:
- **Coverage lift:** % of tagged repos that go DISCOVERED→bound→verified (vs the pre-brain baseline).
- **Causal-chain accuracy** (toph-eval's headline): did the loop fix the *root* fault, not the surface symptom?
- **FCR = 0** (hard gate — a wrong adaptive fix must never CONFIRM; adversarial cases included).
- **Cost:** LLM calls / sandbox-minutes per repo; XPU **hit-rate** (should climb → cost/scan → $0).
- **Repro fidelity:** the winning RunPlan **replays clean** on a fresh sandbox (BootstrapAgent cold-start).
Wire it into the existing FCR meta-eval harness so it runs in CI at low `k`.

---

## 8. FCR safety model (non-negotiable, restated)

1. **Proposer ≠ Judge.** The LLM/registry proposes HOW; the pure-stdlib recompute (zero shared code) disposes
   the verdict. CI firewall test stays green. No slice imports `core.verdict`/`core.diff` into the brain.
2. **Bindings are validated, never trusted.** An LLM-proposed claim→artifact binding is confirmed only by
   independent recompute; wrong scope → REFUTED/INCONCLUSIVE.
3. **Auto-fetched / substituted inputs cap to REPRODUCED-ONLY / INCONCLUSIVE** (existing rails hold).
4. **Bounded + reversible.** Every remediation is HOW-only, snapshot-reversible, attempt-capped, tier-gated.
5. **Auditable.** The ReAct trace + XPU provenance are the audit log (self-healing lit: the trace is a
   feature). Every verdict remains traceable to the repo's own captured evidence.

---

## 9. What Calma already has (the head start the research validates)

ReAct assess→rank→execute→observe→revise (`orchestrator/`) · a typed **firewall** surface (`types.py`, CI-
enforced) = the SOTA "separate proposer from judge" · `Budget` + oscillation = the deterministic termination
state machine · `HintStore`/`ApproachCache`/`RunPlanCache` = the experience-cache seed · `data_resolver`
= the hardcoded-path remediation, **already written** · `ci_workflow_signals` = a first discovery agent ·
`classify_failure` = the taxonomy seed · Helix = the vector-store backend · the pure-stdlib recompute oracle
= SHOR's uncorrelated deterministic judge. **We are ~70% of the way to the SOTA design; this plan is the other
30%, in FCR-safe slices.**

---

### Open decisions (founder calls — resolved 2026-07-05)
- **OD-A → RESOLVED (2026-07-05): E2B pause/resume is on ALL plans**, verified working on `e2b==2.30.0`. S5
  foundation built on it — no microVM simulation needed; only the `run_e2b` wiring + live smoke remain.
- **OD-B → HELIX NOW.** S3's XPU vector store goes straight to the Helix vector node (durable, cross-instance)
  behind the store interface — no local sqlite-vec interim.
- **OD-C → FULLY-AUTO ALL SCOPES.** `bind_artifact` (S4) auto-recomputes every proposed claim→artifact scope;
  no propose-and-ask gate. FCR-safe by construction — the Judge validates each binding by independent
  recompute, so a wrong auto-scope → REFUTED/INCONCLUSIVE, never CONFIRM.
