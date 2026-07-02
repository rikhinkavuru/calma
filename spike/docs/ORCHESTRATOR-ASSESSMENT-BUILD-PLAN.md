# Repo-Assessment Orchestrator — SOTA build plan

> **The reframe.** Today the make-runnable phase is a fixed heuristic pipeline (`detect_entrypoint` →
> `infer_requirements` → single-shot AI `planner` → run → 2-shot dep-heal → optional `repair` loop). Every
> edge case we hit (package layout, notebooks, conda, declared deps, args, non-Python) is a *new branch* we
> have to hand-code into that fixed pipeline. That does not scale — the long tail of repo shapes is
> unbounded.
>
> **The new model:** after clone, run an **assessment + tool-selection orchestrator**. It profiles the repo,
> then chooses *how* to make it runnable from a rich toolbox — the right entrypoint strategy, dep manager,
> interpreter, runner, capture targets — and drives a bounded execute/observe/revise loop until the repo runs
> (or is honestly declared un-runnable). New edge cases become **new tools in the registry**, not new
> branches in a monolith. The agent handles the combinatorics we can't enumerate.
>
> This document is the SOTA build plan. It is grounded in the current code (file:line anchors throughout) and
> maps **every** edge case from the make-runnable audit (A1–C3) to a concrete tool + phase.

---

## 0. The non-negotiable: the FCR firewall

Handing an LLM agent "a ton of tools" is exactly where a correctness product dies if it's careless. The
entire design rests on one structural guarantee:

> **The orchestrator can only change HOW a repo is made runnable and run. It can never touch a claim value,
> the captured computation, the binding, the recompute, the three-way diff, or the verdict.**

This is enforced structurally, not by prompt:

1. **Typed hand-off, no verdict tool.** The agent's *only* output is a validated `RunApproach` / `RunResult`
   (schemas in §3). The deterministic core (`core/diff.py`, `core/verdict.py`, `pipeline._diff_claims`,
   `_apply_*` overlays) consumes that hand-off and is **unchanged**. The agent has no tool that writes a
   verdict, a claim value, or a binding.
2. **Determinism disposes.** Whatever the agent chooses still flows through k-runs → identity-binding (never
   value-proximity, `core/diff.py`) → independent recompute → fail-closed verdict. A *wrong* agent choice
   (wrong entrypoint, wrong dep, wrong notebook) yields wrong/empty capture → `DISCOVERED` / `REFUTED` /
   `INCONCLUSIVE`, **never a false `CONFIRMED`**.
3. **Source edits are capped.** If any tool modifies repo compute source, every `AFFIRMATIVE` verdict is
   capped to `REPRODUCED-ONLY` — the existing `pipeline._apply_agent_modified_cap` (pipeline.py:223) already
   does this; the orchestrator reuses it and extends the modified-file manifest to cover every exec tool.
4. **CI firewall test.** A test asserts no module under `orchestrator/` imports `core.verdict` /
   `core.diff` as a writer, and that the agent tool registry contains zero verdict-affecting tools. Mirrors
   the existing edges/core firewall discipline.

**Net:** the orchestrator can only ever make us verify *more* repos (coverage ↑) or honestly fail
(`DISCOVERED` ↑). The false-confirm surface stays zero by construction. This is the sentence every reviewer
must be able to check.

---

## 1. Where it sits in the pipeline

```
server.clone ──▶ supervisor child ──▶ pipeline.verify_repo
                                          │
                                          ├─ [NEW] orchestrator.assess(repo_dir)         ← after clone, before run
                                          │        static profile → RunApproach (ranked)
                                          │
                                          ├─ orchestrator.execute(approach)  ── bounded ReAct in sandbox/E2B
                                          │        run → observe → revise (next tool) → …
                                          │        emits RunResult (runs, captures, manifest)
                                          │
                                          ├─ discover / salience / leakage               (unchanged)
                                          ├─ three-way diff + verdict                    (unchanged, deterministic)
                                          └─ overlays (leakage / red-team / agent-cap)    (unchanged)
```

Concretely it **replaces the make-runnable brain** — today's `_run_repo` (pipeline.py:320) with its inline
precedence ladder (opts › AI plan › `detect_entrypoint` › fabricated `eval.py`) becomes a thin executor
*driven by* the orchestrator. `planner.py` (single-shot propose) and `runner/repair.py` (env-only ReAct on
failure) are **absorbed** into it: planner = the first assessment turn, repair = the revise turns. Nothing
downstream of the run changes.

---

## 2. Design principles

- **Static-first, escalate on need.** Cheap deterministic tools (tree walk, AST, ripgrep, git) build the
  profile with **zero LLM cost**. The LLM is invoked only for judgment (ranking candidates, reading a README,
  choosing among approaches) and only when static signals are ambiguous. Most repos never need a second turn.
- **Tools are individually FCR-safe and typed.** Each tool declares: name, typed args, `static | exec` kind,
  cost hint, and a `touches_verdict: False` assertion checked in CI.
- **Bounded everything.** Step cap (default 6 turns), token budget, wall budget, and the supervisor's
  existing RSS/CPU/wall caps on any execution. A stuck loop degrades to `DISCOVERED`, never hangs.
- **Prompt-injection hardened.** Repo content is untrusted (a README can say "ignore your instructions").
  All repo text reaches the agent inside an untrusted envelope; no tool executes arbitrary strings; pip specs
  pass `core/limits.sanitize_pip`; the action space is a fixed enum, not free-form shell.
- **Cost-aware + flywheel-cached.** The assessment + winning approach are cached by repo fingerprint
  (tree-hash + commit). A repeat or sibling repo skips the LLM entirely — the reproduction flywheel from
  `PRICING.md`. Cost-per-scan trends down as coverage compounds.
- **Transparent.** The orchestrator emits a human-readable **Assessment Report** ("this is a `code/`-package
  genomics repo; no root script; running `python -m code.run_analysis`; deps from pyproject; 4 capture
  targets") surfaced in the job logs + UI. This is the "reports back the best way to approach the repo" the
  product wants, and it's the audit trail for "AI proposes."

---

## 3. Data contracts (the typed hand-off)

```python
# orchestrator/types.py  — validated dataclasses; the agent NEVER emits anything outside these.

@dataclass
class RepoProfile:                     # produced by the static assessment pass
    language: str                      # python | r | julia | shell | mixed | unknown
    layout: str                        # root-script | package | src-layout | notebook | monorepo | make-driven
    pkg_manager: str                   # requirements | pyproject | poetry | pipenv | conda | none
    py_version: str | None             # declared interpreter (detect_python_version)
    entry_candidates: list[EntryCand]  # ranked; each {argv, kind, confidence, signals}
    notebooks: list[str]
    make_targets: list[str]
    declared_deps: list[str]           # from the resolved manifest (pyproject/poetry/conda/…)
    data_needs: list[str]              # referenced data paths not present in the tree
    determinism: dict                  # core.determinism.analyze()
    domain: str | None                 # ml | genomics | quant | analytics | … (salience + import signal)
    fingerprint: str                   # tree-hash + commit (cache key)

@dataclass
class RunApproach:                     # the agent's decision (ranked list; top is tried first)
    runner: str                        # local | e2b | e2b-gpu
    builder: str                       # venv-pip | uv | conda-micromamba | declared
    entry: list[str]                   # argv: ["-m","code.run"] | ["code/run.py","--split","test"] | ["nb:analysis.ipynb"]
    deps: list[str]                    # resolved specs (sanitized)
    capture_targets: list[dict]        # target_discovery proposals + agent additions
    env: dict[str, str]
    notes: str                         # the human-readable rationale (→ Assessment Report)
    confidence: float

@dataclass
class RunResult:                       # what execute() returns → deterministic verify (UNCHANGED shape)
    ran_ok: bool
    runs: list                         # captured computations per k (as today)
    meta: list                         # stdout/stderr tails
    cost: dict
    source_modified: list[str]         # → _apply_agent_modified_cap (verdict cap)
    approach: RunApproach              # for the receipt + telemetry
```

These schemas are the whole firewall surface. If it isn't in `RunResult.runs`, it can't reach a verdict.

---

## 4. The tool registry

Each is a small, testable function wrapped with a typed schema. **Assessment (static)** tools are pure/cheap;
**execute** tools run inside the sandbox under supervisor caps. None returns a verdict.

### 4a. Assessment tools (static, no LLM, ~free)
| Tool | Backs edge case | Source today / new |
|---|---|---|
| `list_tree`, `read_file`, `grep`, `ast_imports` | all | new thin wrappers |
| `find_entrypoints` → ranked `EntryCand[]` | A4 | **wrap** `build.detect_entrypoint` (now package/subdir aware) |
| `find_notebooks` | **A1** | new (`*.ipynb` walk) |
| `find_make_targets`, `find_shell_scripts`, `detect_language` | **A3** | new |
| `detect_pkg_manager` + `read_declared_deps` | **B1** | new — parse pyproject `[project.dependencies]`, poetry, Pipfile, conda `environment.yml` |
| `resolve_requirements_includes` | **B3** | new — follow `-r`/`-c`, treat `-e .`/`.` as self-install |
| `import_to_dist` | **B4** | new — `importlib.metadata.packages_distributions()` + mapping table |
| `entry_seeded_imports` | **B5** | new — BFS from the entrypoint's transitive imports |
| `detect_python_version` | C1 | **wrap** `build.detect_python_version` |
| `propose_capture_targets` | capture | **wrap** `runner/target_discovery.propose` |
| `analyze_determinism` | adaptive-k | **wrap** `core/determinism.analyze` |
| `find_prediction_files`, `find_data_refs` | C2 | **wrap** `core/artifacts` + new |
| `git_era` | C1 | **wrap** `build.repo_commit_date` |

### 4b. Execute tools (sandboxed, supervisor-capped)
| Tool | Backs edge case | Source today / new |
|---|---|---|
| `build_venv_pip(specs)` | baseline | **wrap** `build.ensure_venv` |
| `build_uv(specs)` | baseline | **wrap** e2b uv path |
| `build_conda(environment.yml)` | **B2** | new — micromamba in the E2B image |
| `install_declared(profile)` | **B1** | new |
| `era_pin_compat(specs, pyver)` | **C1** | **extend** `build.era_pin` with wheel/`requires_python` filter |
| `run_script(argv)`, `run_module(-m)` | A-baseline | **wrap** `local_runner` / `e2b_runner` |
| `run_notebook(path, params)` | **A1** | new — papermill/nbclient with capture shim armed |
| `run_make(target)` | **A3** | new — dispatch a Makefile target |
| `run_lang(r|julia|shell, argv)` | **A3** | new (phased) — R/Julia/shell interpreters in-sandbox |
| `add_argv(args)`, `set_env(kv)` | **A2** | **wrap** `repair` action space |
| `fetch_data(path)` | data | **wrap** `runner/data_resolver` (gated, SSRF-guarded) |
| `probe_run(argv)` | A2/A4 | new — a fast dry-run (import + `--help`) to check an entry before a full k-run |
| `rescan_outputs()` | **C2** | new — artifact-verify the **post-run** tree, not just committed files |

Adding a future edge case = adding one row here. That is the whole point of the reframe.

---

## 5. The orchestration loop

```
assess(repo_dir):
    profile = run all static assessment tools            # cheap, deterministic, cache-checked
    if profile.fingerprint in cache: return cached RunApproach     # flywheel: skip the LLM
    approaches = agent.rank_approaches(profile)          # 1 LLM turn; static-only if profile is unambiguous
    return approaches                                     # ranked RunApproach[]

execute(approaches):
    for approach in approaches[:MAX_APPROACHES]:          # A4: try ranked candidates in order
        probe = probe_run(approach.entry)                 # cheap gate before a full k-run
        if probe.import_error → agent revise (turn++)     # add dep / fix module / next approach
        result = build + run_k(approach)                  # in sandbox, supervisor-capped
        observe: ran_ok? captures cover the salient metrics?
        if ran_ok and captured: cache(approach); return result
        agent.revise(result)                              # B-family: switch builder, add dep, fetch data,
                                                          # A-family: add argv, switch to notebook/make, next entry
        if turns >= STEP_CAP: break
    return best_effort_result                             # → honest DISCOVERED, never a fabricated eval.py (C3)
```

- **Concurrency with boot** stays: the first agent turn overlaps E2B boot exactly like `planner` does today
  (`pipeline.py:558`, background thread).
- **`probe_run`** is the cost lever — a 2s import/`--help` check kills a doomed approach before a full k-run.
- **`STEP_CAP`, token + wall budgets** are tier-scaled (`core/limits.Tier`): free = 1 approach, no LLM
  revise; pro/enterprise = full loop. Fail-closed at every ceiling.

---

## 6. Edge-case → fix mapping (the "address every one" table)

| # | Edge case (from the audit) | Addressed by | Phase |
|---|---|---|---|
| **A1** | Notebook-driven repos never execute | `find_notebooks` + `run_notebook` (papermill) | 3 |
| **A2** | CLI-arg entrypoints fail | `probe_run` + `add_argv`; README arg parsing (path-validated) | 2–3 |
| **A3** | Python-only runner (R/Julia/Make/shell) | `find_make_targets`/`detect_language` + `run_make`/`run_lang` | 3 (Make/shell), 5 (R/Julia) |
| **A4** | Commits to one entrypoint | `find_entrypoints` returns ranked `EntryCand[]`; loop tries candidates | 1–2 |
| **B1** | Declared deps only from requirements.txt | `detect_pkg_manager` + `read_declared_deps` + `install_declared` | 1–3 |
| **B2** | No conda | `build_conda` (micromamba) + `environment.yml` detect | 3 |
| **B3** | `-r` includes / `-e .` dropped | `resolve_requirements_includes` | 1 |
| **B4** | 15-entry import→PyPI map | `import_to_dist` (`packages_distributions()` + table) | 1 |
| **B5** | Import scan capped at 120, arbitrary order | `entry_seeded_imports` (BFS from entry) | 1 |
| **C1** | Era-pin ignores interpreter compat | `era_pin_compat` (wheel/`requires_python` filter) | 3 |
| **C2** | Fresh run outputs not recaptured | `rescan_outputs` (post-run artifact verify) | 3 |
| **C3** | Fabricated `eval.py` shown | loop returns honest `DISCOVERED` when no approach runs | 2 |

Everything the audit found has a home. Anything the audit *missed* becomes a new registry row + the agent
routes to it — that is the reframe's payoff.

---

## 7. Phases (deliverables, files, tests, gates)

Each phase is independently shippable and FCR-gated. Nothing merges without the firewall test green and a
no-false-confirm corpus run.

### Phase 0 — Foundations (interfaces + firewall)
- `orchestrator/types.py` (§3 schemas), `orchestrator/registry.py` (tool interface + `touches_verdict`
  assertion), `orchestrator/__init__.py`.
- **CI firewall test** `tests/test_orchestrator_firewall.py`: no `orchestrator/*` writes a verdict/binding;
  registry has zero verdict-affecting tools.
- **Gate:** firewall test green. No behavior change yet.

### Phase 1 — Static assessment tools (biggest coverage-per-effort, no LLM)
- Wrap existing heuristics as tools; add the static B-family + A4 tools (B1/B3/B4/B5, `find_notebooks`,
  `find_make_targets`, ranked `find_entrypoints`).
- `orchestrator/assess.py` builds a `RepoProfile` from tools only (deterministic).
- **Tests:** one per tool on fixture repos (package, src-layout, poetry, conda, notebook, monorepo).
- **Gate:** profile correctness on a 15-repo fixture set; still no LLM, no pipeline wiring.

### Phase 2 — The orchestrator loop (assess → approach → execute)
- `orchestrator/orchestrate.py`: rank approaches (LLM turn, Sonnet, reusing `planner`'s client), the bounded
  execute/observe/revise loop, absorb `repair` as the revise step.
- Wire into `pipeline.verify_repo` **behind `opts.orchestrate`**, owner/enterprise only; heuristic path stays
  the default until the corpus clears it.
- **C3:** kill the fabricated-`eval.py` fallback when the orchestrator runs.
- **Tests:** loop picks the right approach on the Phase-1 fixtures; step-cap + budget enforcement;
  prompt-injection fixture (a README that tries to hijack) is neutralized.
- **Gate:** on the Phase-0 corpus (spike/results GO/NO-GO set), reproduction rate ≥ heuristic baseline,
  **false-confirm rate == 0**.

### Phase 3 — New execute tools (the make-runnable expansions)
- `run_notebook` (A1), `build_conda` (B2), `install_declared` (B1), `era_pin_compat` (C1), `run_make` (A3
  Make/shell), `rescan_outputs` (C2), `add_argv` path-validation (A2).
- E2B template gains micromamba + jupyter/papermill (image-size + boot budget tracked).
- **Tests:** a real notebook repo → CONFIRMED; a conda repo builds; a pyproject-only repo installs; a
  post-run-output repo recomputes.
- **Gate:** each tool has a no-false-confirm adversarial test (e.g. a notebook that reports a wrong number →
  REFUTED, not CONFIRMED).

### Phase 4 — Safety, cost, flywheel, transparency
- Assessment/approach cache keyed by fingerprint (`orchestrator/cache.py`) → LLM-skip on repeats.
- Budgets + tier gating via `core/limits`; `/api/cost` extended with orchestrator token spend.
- **Assessment Report** rendered in job logs + the dashboard ("how Calma approached this repo").
- Prompt-injection + tool-sandbox hardening pass (senior-security review).
- **Gate:** cost-per-scan telemetry; cache hit-rate on sibling repos; security sign-off.

### Phase 5 — Rollout + long tail
- R/Julia/shell interpreters (A3 remainder), GPU-runner routing, monorepo sub-project selection.
- Tier ramp: enterprise → pro → free (with the tightest budget).
- **Gate:** GO/NO-GO memo on an expanded corpus (add package/notebook/conda/R repos), FCR==0 maintained.

---

## 8. Cost model

- **Static assessment: ~$0** (tree/AST/git). Runs on every repo.
- **LLM ranking: 1 Sonnet turn** (~a few ¢), only when static is ambiguous, **cached by fingerprint** → ~$0
  on repeats. Revise turns only on failure, step-capped.
- **`probe_run`** amortizes execution cost by killing doomed approaches in ~2s before a full k-run.
- Net: a modest bump over today's single-shot planner, bounded and tier-metered, trending to zero as the
  cache fills. Matches the user's "costs a little more, we have almost no cost now" — and the flywheel makes
  it structurally cheaper over time (`PRICING.md`).

---

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Agent drives a wrong approach that *runs* and produces a number | Fail-closed: identity-binding + recompute → wrong capture = REFUTED/DISCOVERED, never CONFIRMED (§0). Source edits → REPRODUCED-ONLY cap. |
| Prompt injection via repo content | Untrusted envelope, fixed action enum, `sanitize_pip`, no arbitrary shell, CI injection fixture. |
| Unbounded compute / cost | Step + token + wall budgets, tier-scaled; supervisor RSS/CPU/wall caps on all exec; `probe_run` gate. |
| Non-determinism from LLM choice | The *choice* is non-deterministic; the *verdict* is not. Same repo may take a different path to the same fail-closed verdict; the receipt records the approach for auditability. |
| Regression vs today's heuristics | Orchestrator is flag-gated behind the heuristic default until the corpus proves ≥ baseline reproduction AND FCR==0. |
| E2B image bloat (conda/jupyter) | Track boot + image size per phase; keep micromamba/papermill in a separate template variant, routed by profile. |

---

## 10. What we keep (unchanged, downstream of the firewall)

`discovery/*`, `core/diff.py` (identity binding + three-way diff), `core/verdict.py`, all `_apply_*` overlays,
leakage, red-team gate, receipt/attestation, salience, tier limits. The orchestrator makes the repo *runnable
and run*; everything that turns a run into a **verdict** is deterministic and untouched. That separation is
the product.
