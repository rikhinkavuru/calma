# Calma — Feature Build Plans (20 features, Exa-researched, FCR=0-grounded)

**Date:** 2026-07-01 · **Audience:** Calma engineering · **Status:** research-backed design doc, not yet implemented.
Companion to [`DOMAIN-GENERALIZATION-GUIDE.md`](DOMAIN-GENERALIZATION-GUIDE.md) — same discipline, applied to the 20-feature roadmap.

> **Anchors in this repo.** Capture ladder `spike/capture/calma_capture.py` + `spike/capture/ast_capture.py`;
> trusted recompute `spike/core/catalog.py` (+ `CONVENTIONS`) + `spike/core/diff.py` + `spike/core/validity.py`
> + `spike/core/conventions.py` + `spike/core/textmetrics.py`; verdict `spike/core/verdict.py`; determinism
> `spike/core/determinism.py`; synth flywheel `spike/synth/formula.py` + `spike/synth/store.py`; planner
> `spike/planner.py` (Claude Sonnet 5); runners `spike/runner/{local_runner,e2b_runner,build,supervisor,isolated_verify,data_resolver}.py`;
> pipeline `spike/pipeline.py`; discovery `spike/discovery/extract.py`; server `spike/server.py`;
> meta-eval `spike/optimize/{measure,binding,invalidate,recompute_stress,leakage_stress,redteam,convention_fuzz,scorecard,source_corpus}.py`;
> corpus `spike/repos.yaml` + `spike/corpus.py`; the trust placeholder `spike/core/artifacts.py` (currently empty);
> the old engine at `legacy/` (gitignored, reference-only — has ed25519/DSSE signing to LIFT). Tests: `~/.calma/spike-venv/bin/python -m pytest`.

---

## How to read this document

Twenty features, one law. Calma's whole franchise is a single number — **FCR = 0**, the false-CONFIRM rate — and
every feature below is scored first by whether it can ever move that number the wrong way. The detailed build plans
are grouped into five **technical clusters** (they share infrastructure and were researched together); the
**Executive summary** and the **Sequencing** section below re-index them by *priority* and *dependency* so you can
read either lens. Each feature's plan has the same five parts: *What & why · SOTA & best practices (cited) · Fit to
Calma (FCR=0-safe) · Build plan (phased) · Effort & dependencies.*

| Cluster | Theme | Features |
|---|---|---|
| **A** | Reproduction & determinism infrastructure | 1 (get-it-running), 14 (Nix hermetic), 15 (seed injection), 20 (record-replay) |
| **B** | Formula & numerical correctness | 2 (fuzz-the-formula), 7 (metamorphic), 17 (differential recompute), 19 (interval arithmetic) |
| **C** | AI & statistical verification | 4 (claim-classifier), 6 (statistical/distribution), 10 (perturbation-fabrication), 11 (cross-run anomaly) |
| **D** | Trust, cryptography & transparency | 3 (signed attestations), 12 (transparency log), 16 (dataset registry), 18 (reproducibility receipts) |
| **E** | Adversarial hardening, flywheel, distribution | 8 (red-team-the-confirm), 5 (learning flywheel), 9 (FCR bug bounty), 13 (badges + registry) |

---

## Executive summary

**Where the engine actually is (the constraint that shapes the whole plan).** The core verification *logic* is
already maxed within FCR=0 on the current corpus: misreport-catch, wrong-formula catch (INVALIDATED), binding, and
reproduction-given-runnable are all at their safe ceiling, and FCR has held at **0** under ~260 deliberately-wrong
injections + 8/8 red-team attacks + 0/16 on the live real-repo corpus (`spike/optimize/SCOREBOARD.md`). The live
numbers that are *not* at ceiling are all **coverage**, not logic: reproduction **80%**, binding **58%**, and a
capture gap on hand-rolled/`__main__`-defined metrics (`spike/results/GO-NO-GO-corpus-2026-06-29.md`). Read that
way, the 20 features sort cleanly into four jobs, and the priority order falls out of the constraint:

1. **Raise the coverage floor** — *make more repos run and more numbers recomputable.* This is where raw value is
   gated. `#1 get-it-running` (reproduction), `#2 fuzz-the-formula` + `#7 metamorphic` (recompute breadth /
   no-recompute-path claims), `#4 claim-classifier` (legibility so the coverage we have is *usable*), `#6
   statistical` + `#15 seed injection` (opens the unseeded-DL domain that is a dead-end today).
2. **Make CONFIRMED un-foolable** — *upgrade "the number matches" to "the method is provably right,"* and turn
   FCR=0 from a passive property into a self-attacking one. `#2 fuzz-the-formula`, `#7 metamorphic`, `#10
   perturbation-fabrication`, `#8 red-team-the-confirm`, `#9 FCR bug bounty`.
3. **Make the verdict checkable, not "trust me"** — *the neutral-third-party moat made cryptographic.* `#18
   receipts` (the payload) → `#16 dataset hash` (a field) → `#3 signed attestations` (SLSA-style **Verification
   Summary Attestation**) → `#12 transparency log` (Rekor) → `#13 badges/registry` (distribution).
4. **Compound** — *get better and cheaper with every verify, in a way volume-less competitors can't copy.* `#5
   learning flywheel`, `#11 cross-run anomaly`.

**The moat, stated plainly.** A value-matching competitor can check that a reported number equals a recomputed
number. It *cannot* cheaply copy: (a) the reproduction breadth of `#1`; (b) the un-foolability of `#2`/`#7`/`#10`
(the formula *is* the metric; a fabricated constant doesn't move under input perturbation); (c) the neutral,
publicly-verifiable attestation stack `#3`/`#12`; and (d) the compounding data of `#5`/`#11`. Features are ordered
below to build that moat in the order that each layer unblocks the next, while never trading FCR.

---

## The FCR=0 safety doctrine (cross-cutting)

Only one verdict carries false-CONFIRM risk: **CONFIRMED**. Everything else (REFUTED, INVALIDATED,
REPRODUCED-ONLY, NON-DETERMINISTIC, INCONCLUSIVE, DISCOVERED) is a safe "no positive commitment" outcome. So every
feature is classified by *how it relates to the CONFIRMED gate*, and the rule is mechanical: **a feature may add
coverage, add downgrade-power, or add trust — it may never add a path that turns a wrong number into CONFIRMED.**

| Safety class | What it may do | Rule | Features |
|---|---|---|---|
| **Coverage-adding** | Make more claims *bindable / runnable / recomputable* | New coverage still passes through the *unchanged* fail-closed gate in `verdict.py`; it can only move a claim from INCONCLUSIVE/REPRODUCED-ONLY *toward a real verdict*, and that verdict is still earned by independent recompute | 1, 2, 5, 6, 14, 15, 16, 17, 19, 20 |
| **Downgrade-only** | *Lower* a verdict, never raise it | Wired as a monotone gate: `min(verdict, redteam_verdict)` — structurally cannot upgrade | 8, 10, 11 |
| **Identification-only** | Change *which* claims we verify, not the verdict | A misclassification drops a claim to unverified/DISCOVERED; it can never fabricate a CONFIRM | 4 |
| **Trust-layer** | Sign / log / publish an *already-decided* verdict | Operates strictly downstream of `verdict.decide`; must preserve fail-closed semantics but touches no verdict logic | 3, 9, 12, 13, 18 |

Two load-bearing invariants the feature plans must respect, both learned the hard way in the optimization loop:

- **Never bind or confirm by value.** A wrong number can coincidentally equal a *different* correct computation; any
  auto-resolution that lands on value CONFIRMs a wrong number. Binding stays value-blind (`spike/core/diff.py`),
  and `#5`'s banked "known values" are **priors/hints only** — the verdict is always re-earned by recompute.
- **Seeding changes the claim.** Forcing a seed (`#15`) generally verifies a *different* number than the paper
  reported (a different split/init). Seed injection may therefore only *characterize non-determinism* or *establish
  a distribution* (`#6`); it may never be used to manufacture a point CONFIRM against an unseeded claim.

Every meta-eval instrument in `spike/optimize/` exists to keep this doctrine honest; each new feature ships with its
own injection/adversarial harness there, and the standing proof is `scorecard.fcr_breaches()` staying empty and
`convention_fuzz` staying at 0.

---

## Sequencing & dependencies (build order)

The dependency graph, then the waves. `A → B` means "A meaningfully unblocks or de-risks B."

```
                 ┌─────────────────────────── #1 get-it-running (the coverage floor; gates the whole funnel)
                 │        │            │
                 ▼        ▼            ▼
        capture ladder  #14 Nix    #15 seed-inject ──► #6 statistical/distribution ──► opens unseeded DL
        (sys.monitoring    (deeper       (careful)            │
         / AST)          hermetic tier)                       ▼
                 │                                     #11 cross-run anomaly ◄── corpus volume
                 ▼
        #2 fuzz-the-formula ──┐
        #7 metamorphic ───────┼──► un-foolable CONFIRMED
        #10 perturbation ─────┤
        #8 red-team-confirm ──┘        #17 differential-recompute, #19 interval-arith (belt-and-suspenders)
                 │
                 ▼
        #4 claim-classifier (legibility — makes all coverage usable)

        #18 receipts ─► #16 dataset-hash ─► #3 signed VSA ─► #12 transparency log ─► #13 badges/registry
                                                    │
                                                    └─► #9 FCR bug bounty (needs public, verifiable verdicts to challenge)

        #5 learning flywheel  ── compounds across everything; feeds #11
```

**Wave 0 — cheap FCR-hardeners + legibility (days each, no deps, do first).**
`#8 red-team-the-confirm` (promote the existing `optimize/redteam.py` gate inline), `#10 perturbation-fabrication`
(a new check in `core/validity.py`), `#4 AI claim-classifier` (a scoring pass in `discovery/extract.py`). Highest
safety- and usability-ROI per unit effort; each strictly downgrade- or identification-only.

**Wave 1 — the coverage floor + un-foolability (the raw-value levers).**
`#1 get-it-running agent` (XL — the single biggest lever; everything downstream is gated on it), `#2
fuzz-the-formula` (the marquee moat feature; rides the capture ladder), `#7 metamorphic` (verdicts for
no-recompute-path claims). This wave is where measured reproduction/binding actually move.

**Wave 2 — the trust stack (the moat made checkable).**
`#18 receipts` → `#16 dataset registry` → `#3 signed attestations` (lift ed25519/DSSE from `legacy/`, emit a
SLSA-style VSA) → `#12 transparency log` (Rekor). Then `#9 FCR bug bounty` and `#13 badges/registry` ride on `#3`.
Signing was explicitly deferred in `REBUILD.md §6` "until an enterprise buyer asks" — this wave is enterprise-gated,
not technically-gated, so it can slot whenever GTM calls for it.

**Wave 3 — new domains + compounding.**
`#6 statistical/distribution` + `#15 seed injection` (together, they open unseeded deep learning), `#5 learning
flywheel` (extends `synth/store.py` into a general experience bank), `#11 cross-run anomaly` (volume-gated — waits
for `#5`/`#13` to feed it a corpus).

**Wave 4 — deep / marginal determinism infra (last, effort ≫ marginal reach).**
`#14 Nix hermetic` (kills the residual version-drift false-REFUTEs era-pinning/uv don't), `#17 differential
recompute` (catalog-vs-synth agreement assertion — cheap to add once synth is load-bearing), `#19 interval
arithmetic` (certified bounds for ill-conditioned recomputes), `#20 record-and-replay` (the strongest hammer,
narrowest reach — Linux/x86, single-core).

### Effort × impact × FCR-risk (at a glance)

| # | Feature | Impact | Effort | FCR-risk if done right | Safety class | Wave |
|---|---|---|---|---|---|---|
| 1 | Get-it-running agent | ★★★★★ | XL | none (fail = DISCOVERED) | coverage | 1 |
| 2 | Fuzz-the-formula | ★★★★★ | M | none (deterministic) | coverage/un-fool | 1 |
| 7 | Metamorphic verification | ★★★★ | M | none (downgrade/verify only) | coverage | 1 |
| 4 | AI claim-classifier | ★★★★ | S–M | none (identification-only) | identification | 0 |
| 8 | Red-team-the-confirm | ★★★★ | S | none (downgrade-only) | downgrade | 0 |
| 10 | Perturbation-fabrication | ★★★ | S | none (downgrade-only) | downgrade | 0 |
| 3 | Signed attestations | ★★★★ | M (lift) | none (post-verdict) | trust | 2 |
| 18 | Reproducibility receipts | ★★★ | M | none (post-verdict) | trust | 2 |
| 16 | Dataset registry (hash) | ★★★ | M | none (adds a binding key) | coverage/trust | 2 |
| 12 | Transparency log (Rekor) | ★★★ | M | none (post-verdict) | trust | 2 |
| 9 | FCR bug bounty | ★★★★ | S | none (crowdsources hardening) | trust | 2 |
| 13 | Badges + registry | ★★★ | M | none (renders a signed verdict) | trust | 2 |
| 6 | Statistical/distribution | ★★★★ | M–L | low (multiple-comparisons discipline) | coverage | 3 |
| 15 | Seed injection | ★★ | M | **elevated** — must not manufacture a point CONFIRM | coverage | 3 |
| 5 | Learning flywheel | ★★★★ | L | low (known-values are hints, never confirms) | coverage | 3 |
| 11 | Cross-run anomaly | ★★★ | M | none (flag/downgrade-only) | downgrade | 3 |
| 14 | Hermetic Nix | ★★★ | L | none (reduces false-REFUTE) | coverage | 4 |
| 17 | Differential recompute | ★★ | S | none (adds INVALIDATED path) | coverage | 4 |
| 19 | Interval arithmetic | ★★ | M | none (tightens/loosens tolerance rigorously) | coverage | 4 |
| 20 | Record-and-replay | ★★ | XL | none (determinism proof) | coverage | 4 |

*Impact is raw product value on the current corpus's constraints; effort is engineering size (S/M/L/XL); the FCR
column is the residual risk **assuming the FCR-safe design in the plan is followed** — the whole point of each plan's
"Fit to Calma" section is to drive that column to "none."*

---

# Detailed build plans

The plans below are grouped by cluster (A–E). Use the tables above to read them in priority or dependency order.


# Cluster A — Get-it-running & Determinism-hardening (Features 1, 14, 15, 20)

These four features all live *upstream of the verdict*: they raise the **reproduction floor** (how many repos run at all) and the **determinism ceiling** (how confidently a run that agrees can reach CONFIRMED instead of being fail-closed to REPRODUCED-ONLY / NON-DETERMINISTIC). None of them ever touch the oracle (`spike/core/catalog.py` + `spike/core/diff.py`) or the verdict math (`spike/core/verdict.py:33` `decide()`), which is exactly why they can be FCR-safe by construction: the recompute-and-diff that decides CONFIRMED stays byte-identical. The recurring FCR discipline (from `spike/core/verdict.py:12-14` "FAIL CLOSED" and `spike/core/determinism.py:8-14` "false deterministic → the cardinal sin") is: *coverage/determinism helpers may only ADD a runnable path or ADD downgrade-power; they may never widen what counts as agreement.*

---

## Feature 1 — Get-it-running agent

**What & why.** The coverage floor: nothing downstream (capture → recompute → three-way diff) fires unless the repo actually runs and emits its headline numbers. Today Calma has an AI *run-plan* pre-stage (`spike/planner.py:197` `plan_repo`, "AI proposes, determinism disposes") plus two-shot dep self-heal (`spike/pipeline.py:253-263`), but **no iterative repair→verify loop** — a single wrong plan just falls to heuristics and the repo drops to DISCOVERED. A sandboxed coding agent that reads the error, edits the *environment* (not the repo's compute), and re-runs until the entrypoint produces numbers is the single biggest lever on catch-rate, which memory already flags as coverage-bound. The moat is that Calma's loop is *verdict-gated*: the agent only has to get it *running*; a deterministic layer then decides if the number is *right* — a bar an ordinary setup agent never has to clear.

**SOTA & best practices (2026).**
- **Installamatic** (LLM searches repo docs → builds+verifies an install; 55% of repos installed ≥1/10 tries) — the canonical "add a repair step" lesson and the "`--user` installs vanish in a fresh shell" gotcha. https://github.com/coinse/installamatic and paper https://coinse.github.io/publications/pdfs/Milliken2025aa.pdf
- **Repo2Run** (NeurIPS 2025 spotlight): iteratively build image → run tests → synthesize Dockerfile until green; **86.0% success, beats SWE-agent's 77%**. Key ideas to steal: a *waiting-list / conflict-list* dependency queue and rollback. https://arxiv.org/abs/2502.13681 · https://github.com/bytedance/repo2run
- **ExecutionAgent** (33/50 projects, 14 languages, matches ground-truth results within 7.5%, ~$0.16/repo): meta-prompting + summarization, and it *emits* `commands.sh`/`launch.sh`/`manifest.json` — a replayable recipe, not just a transient success. https://github.com/sola-st/ExecutionAgent
- **SetupX**: multi-agent, **speculative execution via `docker commit` snapshot + LIFO rollback**, XPU vector knowledge store of transferable fixes, and a **Prosecutor–Judge adversarial verifier** that structurally separates "configure" from "confirm" (anti self-confirmation-bias). https://github.com/OpenDataBox/SetupX
- **EnvBench** (ICLR-DL4C 2025): 994 repos; SOTA is only **6.69% Python / 29.47% JVM** — env-setup is *hard*, and agents *without error feedback produce broken scripts* (validates the repair loop). Metric = missing-imports via static analysis / compile check. https://github.com/JetBrains-Research/EnvBench · https://arxiv.org/html/2503.14443v1
- **SetupBench** (Microsoft, 93 bare-OS bootstrap tasks): deterministic one-line `success_command` as the gate; corroborates the "`--user` disappears in a fresh shell" and "tools disappear between sessions" failure class. https://github.com/microsoft/SetupBench · https://ar5iv.labs.arxiv.org/html/2507.09063
- **SWE-agent** (NeurIPS 2024): the *Agent-Computer Interface* + guardrails (linter-gated edits, discard-invalid-edit, collapse-old-observations context management) — the ergonomics that make a bash repair loop converge. https://github.com/swe-agent/swe-agent · https://arxiv.org/abs/2405.15793
- Pitfalls: (a) success signal must be *"produced the headline numbers"*, not "pytest collects" (Repo2Run's own README flags the narrow-success trap); (b) `--user`/session-scoped installs are the top silent failure — install into the run's actual interpreter; (c) agent gets network only in a build phase, then runs egress-off.

**Fit to Calma (FCR=0-safe).**
- Slots between the plan pre-stage and the runner. Wrap `spike/pipeline.py:198` `_run_repo` so that when `run_e2b`/`run_local` returns `ran_ok == False`, instead of the current fixed 2-shot heal (`spike/pipeline.py:253-263`, driven by `_missing_module_from` at `:188`), a bounded **repair agent** proposes the next *environment* action (pip/apt/env-var/entrypoint-arg/data-fetch), applies it *inside the same E2B sandbox* (reusing `spike/runner/e2b_runner.py:249` `run_e2b`'s already-booted VM + `_provision_python` uv path at `:184`), and re-runs. The agent's action space is **exactly the plan schema Calma already validates** — entrypoint (`spike/planner.py:159` `_valid_entry`, anti-hallucination existence check) + pip + python_version + data — never a source edit to compute.
- **FCR argument (identical to the planner's, `spike/planner.py:3-7`):** the agent only changes *whether/how the repo's own code runs*. It cannot write the metric, cannot pick the number, cannot alter `spike/core/diff.py`/`spike/core/verdict.py`. Its entire blast radius is: a bad action → a still-failed run → **DISCOVERED**, never a false CONFIRM. Two hard rails preserve this: **(1) no edits to files the capture/recompute reads or to `.py` under the repo's compute path** — restrict the agent to the environment (deps, env vars, argv, fetched data files), and if it must touch repo source (e.g. a broken import path), that run is *flagged agent-modified* and can reach at most REPRODUCED-ONLY, never CONFIRMED; **(2)** determinism is still decided by `spike/core/determinism.py:110` `analyze` + the empirical k≥2 check — a repo the agent *made* run is not thereby trusted; it re-enters the normal gate. Adopt SetupX's Prosecutor/Judge split conceptually: the agent is the "prosecutor" (gets it running), Calma's deterministic core is the incorruptible "judge."
- **Verdicts affected:** moves repos from DISCOVERED/INCONCLUSIVE ("could not run the entrypoint", `spike/pipeline.py:334`) into the space where CONFIRMED/REFUTED/INVALIDATED/REPRODUCED-ONLY become *possible*. It adds coverage only; it removes no downgrade.

**Build plan.**
- **P0 (spike).** New `spike/runner/repair.py`: `repair_loop(sandbox, state, run_fn, propose_fn, max_steps=4)` — a ReAct loop over an *env-only* action enum `{PIP, APT, SETENV, ENTRYPOINT_ARG, FETCH_DATA, GIVE_UP}`; `propose_fn` calls the same client as `spike/planner.py:130` `_call_model` with the last `_error_summary` (`spike/pipeline.py:94`) + `classify_failure` kind (`spike/pipeline.py:435`) + file tree. Emit a replayable `manifest.json` (ExecutionAgent-style) of the winning actions. Wire behind `VerifyOptions.repair: bool = False` (default off, like `fetch_data`) in `spike/pipeline.py:38`; call it inside `_run_repo` where the 2-shot heal is today.
- **P1 (product).** Reuse the *one already-booted* E2B VM (`run_e2b` `resolve=` deferral at `:291`) so repair steps are cheap; snapshot-before-action / rollback-on-regression (SetupX pattern) via a filesystem checkpoint; persist the manifest so a *re-verify of the same repo* skips the agent (determinism-safe cache keyed by commit SHA). Surface repair steps in the existing `Trace`/LogConsole.
- **P2 (hardening).** Cap agent tokens/steps/wall; apt/pip allow-list; **agent-modified-source detector** (diff the repo tree pre/post; any compute-path `.py` delta caps the verdict at REPRODUCED-ONLY and records the diff in `provenance`); egress only during a build phase, then off for the scored runs.
- **Meta-eval instrument.** `spike/optimize/repair.py` — over `spike/repos.yaml` measure Δcatch-rate (repos reaching a non-DISCOVERED verdict) **and, the load-bearing check, ΔFCR (must stay 0)** and Δfalse-REFUTE; assert the agent never flips a known-wrong fixture (e.g. `spike/fixtures/main_metric_cheat/`) to CONFIRMED. Add an adversarial "prompt-injection README" repo that *tells* the agent to edit the metric — must still not CONFIRM.
- **Tests.** `spike/tests/test_repair_loop.py`: (a) a fixture that fails on a missing dep the imports don't reveal → agent installs it → runs → correct verdict; (b) an unfixable repo → GIVE_UP → DISCOVERED; (c) injection fixture → agent's source edit is refused/flagged → ≤ REPRODUCED-ONLY. **Green gate:** full suite via `~/.calma/spike-venv/bin/python -m pytest` green + `spike/optimize/redteam.py` FCR=0.

**Effort & dependencies.** **L.** Deps: existing planner client + E2B runner + supervisor concurrency gate. Sequence **first** in the cluster — every other feature's coverage gains are multiplied by more repos actually running. Independent of 14/15/20.

---

## Feature 14 — Hermetic environments (Nix)

**What & why.** Kills *version-drift false-REFUTEs* at the root: when Calma re-runs a repo under a slightly different NumPy/sklearn/BLAS than the author used, a legitimately-correct number can come out different and get mis-scored. Calma already has two hermeticity tiers — **era-pinning** (`spike/runner/build.py` `era_pin`, called at `spike/pipeline.py:237`) and **uv** env provisioning (`spike/runner/e2b_runner.py:184` `_provision_python`, declared-Python via `uv python install`/`uv venv`). Nix is the *deeper* tier for the residual cases those two can't reach: system libraries, compilers, C/Fortran ABI, glibc/BLAS — the layer below pip. Position it as an **optional escalation**, not a rewrite: pip/uv for the common case, Nix flakes when a build needs the OS pinned too.

**SOTA & best practices (2026).**
- **Nix flakes** — `flake.lock` pins the *entire input graph* to exact revisions (rev + narHash), so "two developers on opposite sides of the world get the same result." But flakes fix the **input** problem, *not* the **output** problem: a derivation can still be internally non-deterministic. https://determinate.systems/blog/nix-flakes-explained/ · https://zero-to-nix.com/concepts/flakes/
- **rix / rixpress (+ Python port ryxpress)** — generate **declarative, date-pinned** Nix expressions across R/Python/Julia + system deps; each pipeline step is a **hermetically sealed derivation cached on the hash of all its inputs**, so any dep change triggers a rebuild. The pragmatic hybrid they endorse: *Nix pins the system + toolchain layer, `uv.lock` pins the Python layer* — directly reusable by Calma. https://b-rodrigues.github.io/rix_paper/paper.pdf · https://docs.ropensci.org/rixpress/
- **preCICE case study (2025)** — real scientific stack (legacy solvers, adapters, bindings) made reproducible with Nix/NixOS + a self-contained VM image, `flake.lock` pinning all deps. Evidence Nix survives *hard* multi-language HPC repos, and honest about its friction. https://eceasst.org/index.php/eceasst/article/view/2613 · https://github.com/precice/nix-packages
- **uv hash-pinning as the cheaper adjacent tier** — `uv pip compile --generate-hashes` / `uv export` emit SHA-256 for every artifact and *fail install on mismatch*; `uv.lock` includes hashes by default; **`--exclude-newer <date>`** is the exact primitive behind Calma's era-pinning (resolve as-of the commit date). https://docs.astral.sh/uv/pip/compile/ · https://docs.astral.sh/uv/concepts/resolution/ · https://pydevtools.com/handbook/how-to/how-to-pin-dependencies-with-hashes-in-uv/
- Pitfalls: (a) flakes are still *experimental* in upstream Nix (stable only in Determinate Nix) — gate behind a template, don't assume host support; (b) Nix cold-build latency is large (fights the latency roadmap) — cache the store / use FlakeHub or a prebuilt template; (c) `nixpkgs` doesn't mirror PyPI, so pure-Nix Python is painful → use the **rix hybrid** (Nix system layer + uv Python layer); (d) Nix pins inputs but a non-deterministic *build/run* still needs Calma's k≥2 + `enforced_env`.

**Fit to Calma (FCR=0-safe).**
- A **third `runner` alongside** `local_runner`/`e2b_runner`, selected by `VerifyOptions.runner` (`spike/pipeline.py:42`). New `spike/runner/nix_runner.py` `run_nix(...)` returns the **same runner-agnostic shape** (`runs/meta/ran_ok/hooks_armed/cost`) `spike/core/diff.py` already consumes — so nothing downstream changes. Trigger only on escalation: a build/ABI failure class from `classify_failure` (`spike/pipeline.py:435`, e.g. "needs system lib", non-Python compile error) after uv/era-pin already failed.
- Env-parity: whatever interpreter Nix provides, the run still gets Calma's `enforced_env` (`spike/core/determinism.py:154`: `PYTHONHASHSEED=0`, `TZ=UTC`) and `MPLBACKEND=Agg` (`spike/runner/local_runner.py:34`) so hermeticity is *additive* to the existing determinism controls, never a substitute.
- **FCR argument:** Nix changes *only the environment the repo runs in* — same class of blast radius as choosing a Python version. It makes a run *more* faithful (closer to the author's stack), which can only turn a spurious REFUTE into a correct CONFIRMED/REFUTED or leave it unrunnable → DISCOVERED. It never loosens the diff or the CONFIRMED gate (`spike/core/verdict.py:70-99`). Critically, a *more*-hermetic env removing genuine noise does **not** manufacture agreement: the three-way diff (`spike/core/verdict.py:4-11`) still requires claimed == produced == independently-recomputed; Nix only affects `produced`, which must still match Calma's *independent* recompute of the *same captured inputs*. If Nix somehow "fixed" a number into false agreement, the independent recompute (computed by Calma, not the repo) would still catch a wrong formula.
- **Verdicts affected:** primarily **reduces false REFUTED** and false NON-DETERMINISTIC (drift-induced spread); adds coverage for OS-dependency repos (DISCOVERED → runnable). Adds no positive-verdict path.

**Build plan.**
- **P0 (spike).** `spike/runner/nix_runner.py`: given `{python_version, pip_install, system_deps}` synthesize a minimal `flake.nix` (rix-hybrid: nixpkgs system+interpreter, then `uv pip install` the Python layer inside the Nix shell), `nix develop --command <entry>` k×, parse capture identically. `nix_synth.py` to template the flake from the (already-validated) plan. Feature-flag `VerifyOptions.nix_escalate: bool=False` (`spike/pipeline.py:38`).
- **P1 (product).** Prebuilt base flake / warmed Nix store in the E2B template family (ties into the latency roadmap's pre-warm work) so cold-build cost is amortized; emit + persist `flake.lock` so a re-verify is bit-reproducible and skips resolution; add a `hermetic_tier` field to `run` telemetry (`era-pin | uv-hash | nix`).
- **P2 (hardening).** Cap Nix build wall/RSS under the supervisor; fall back to uv on Nix unavailability (never regress); optionally `uv pip compile --generate-hashes` even on the non-Nix path so the *pip* tier also carries hash-verification.
- **Meta-eval instrument.** `spike/optimize/hermetic.py` — a corpus of *drift-sensitive* repos (numeric result changes across NumPy/BLAS versions); measure false-REFUTE rate at era-pin vs uv-hash vs Nix, and prove **FCR stays 0** at every tier. Add a "wrong-on-purpose under any env" fixture that must stay REFUTED/INVALIDATED regardless of hermeticity.
- **Tests.** `spike/tests/test_nix_runner.py` (skipped if `nix` absent): flake synthesis shape; runner-agnostic return shape parity with `run_local`; `enforced_env` still applied. **Green gate:** suite green + `spike/optimize/hermetic.py` shows false-REFUTE ↓, FCR=0.

**Effort & dependencies.** **L–XL** (Nix build latency + template work is the cost, not the wiring). Deps: E2B template family / latency pre-warm work; build.py `classify_failure` taxonomy. Sequence **after** Feature 1 (many "drift" REFUTEs are actually *never-ran* repos the agent fixes first) and alongside the latency roadmap. The uv `--generate-hashes` sub-piece is **S** and can ship immediately, independently.

---

## Feature 15 — Seed injection

**What & why.** Some correct repos are simply *unseeded* — every run gives a different number, so Calma's k≥2 empirical check flags NON-DETERMINISTIC and refuses to CONFIRM even when the code is right. Seed injection = force-seed all RNGs to make such a repo reproducible. **This is the delicate one:** seeding is not a free determinism fix, because the seed *is an input to the computation* — it selects the train/test split, the weight init, the shuffle. **A run with an injected seed computes a DIFFERENT number than the one the author claimed**, so proving *that* number reproducible says nothing about the *claimed* number. The FCR-safe use is therefore strictly **characterization, never confirmation**.

**SOTA & best practices (2026).**
- Seeds change the answer, materially: "the gap between the best and worst performing seed replicates can be **more than 2%** even for well-performing models" and "conclusions can easily be forced by a bad actor" via seed choice. https://dl.acm.org/doi/fullHtml/10.1145/3589806.3600044
- **"We need to talk about random seeds"** — taxonomy of *safe* (sensitivity analysis, model selection, ensembling) vs *risky* (single fixed seed; varying only the seed to fabricate a performance distribution) seed uses; >half of surveyed NLP papers misuse seeds. This is the moral map for what Calma may/may not do with a seed. https://ar5iv.labs.arxiv.org/html/2210.13393
- Seed-of-data-split sensitivity is real and metric-visible: nDCG@k/Precision@k swing significantly across split seeds; cross-validation shrinks it. https://doi.org/10.31219/osf.io/r2vpk · Reimers & Gurevych "report score *distributions*, not a single value." https://aclanthology.org/D17-1035.pdf
- The **"butterfly effect"**: tiny init perturbations reliably diverge training trajectories in the chaotic early phase → a re-seeded run is not "the same experiment." https://proceedings.mlr.press/v267/altintas25a.html
- Determinism-tooling to *inject* seeds cleanly (for the characterization run, not the claim): `PYTHONHASHSEED` (already set, `spike/runner/local_runner.py:38`), NumPy `default_rng(seed)` / legacy `np.random.seed`, `torch.manual_seed` + `torch.use_deterministic_algorithms` (+ `CUBLAS_WORKSPACE_CONFIG`), `freezegun`/`libfaketime` for clock, and env-injected seeds à la Polarity's `KEYSTONE_SEED` (agent reseeds; *not* forced). https://tgraphx.com/articles/seeded-deterministic-gnn-experiments-tgraphx/ · https://docs.polarity.so/plr/determinism · https://github.com/spulec/freezegun
- Pitfall (the whole point): **do not** inject a seed and then compare the seeded run's output to the claimed number and CONFIRM — that confirms a *different* experiment. Seed injection is only sound to (a) test whether a repo is *deterministic-given-a-seed* vs *irreducibly* random, and (b) estimate the seed-induced *spread* to size tolerance / explain a NON-DETERMINISTIC verdict.

**Fit to Calma (FCR=0-safe).**
- **Never enters `verdict.decide`'s CONFIRMED path.** It plugs into the determinism *characterization* around `spike/core/determinism.py:110` `analyze` and the empirical k-loop consumed at `spike/core/verdict.py:94-97` (the NON-DETERMINISTIC branch). Concretely: when `analyze` returns AT_RISK because RNGs are unseeded (`spike/core/determinism.py:136-144`), an optional pass does **two extra runs with an injected seed** to answer one question — *"is the unseededness the ONLY source of spread?"* If seeded runs are stable but unseeded runs are not, Calma keeps the verdict **NON-DETERMINISTIC** but upgrades the *explanation* ("non-determinism is seed-controlled; the author's number depends on their unshared seed") and can report the seed-induced spread. It **cannot** promote to CONFIRMED — the claimed number was produced under the author's (unknown) seed.
- The one place a seed *is* legitimately confirmable is when the **repo itself seeds** — that's already handled: `analyze` detects the seed (`spike/core/determinism.py:118-125`) → DETERMINISTIC → adaptive-k → the `determinism.proven` CONFIRMED-by-construction path (`spike/core/verdict.py:81-89`). Feature 15 does **not** widen that; injecting a seed the *author didn't set* is explicitly excluded from that path.
- Guard to make misuse impossible: a `seed_injected: True` flag on the run record that `spike/core/verdict.py:33` `decide` treats as *disqualifying for CONFIRMED* (hard cap at NON-DETERMINISTIC/REPRODUCED-ONLY). Belt-and-suspenders on top of the fact that the injected-seed runs are never fed as `produced` for the claim.
- **Verdicts affected:** improves the *quality/explanation* of NON-DETERMINISTIC (and can add an advisory "seed-controlled, spread=X"); strictly **adds downgrade-context, never a positive verdict.**

**Build plan.**
- **P0 (spike).** `spike/core/seedchar.py`: `characterize_seed(repo_dir, run_fn)` → runs the entrypoint twice unseeded and twice with an injected seed (env `CALMA_INJECT_SEED` consumed by a tiny sitecustomize hook that force-seeds `random`/`numpy`/`torch` at startup, mirroring the existing capture bootstrap `spike/capture/calma_capture.py:583` `install_from_env`), returns `{seed_controls_spread: bool, seeded_spread, unseeded_spread}`. **No path from this into a claim's `produced`.**
- **P1 (product).** Surface in the NON-DETERMINISTIC reason string (`spike/core/verdict.py:94-97`) + UI advisory; add `run.determinism.seed_controlled`. Offer the user a "pin this seed to make it reproducible" *suggestion* (never auto-applied to a verdict).
- **P2 (hardening).** The `seed_injected` disqualification flag enforced in `decide`; a red-team fixture proving a seeded re-run of a *cheating* repo can't reach CONFIRMED; document the "seeded run ≠ claimed number" invariant in `verdict.py` docstring.
- **Meta-eval instrument.** `spike/optimize/seed_injection.py` — corpus of (i) genuinely-seeded, (ii) unseeded-but-seed-controllable, (iii) irreducibly-random repos; assert: category (ii) *stays* NON-DETERMINISTIC (never CONFIRMED) yet gains the seed-controlled explanation; **FCR=0 across all**; and a "claim under author-seed" fixture is *not* confirmed by an injected different seed.
- **Tests.** `spike/tests/test_seedchar.py`: injected seed makes an unseeded fixture stable *in the characterization runs only*; the claim's verdict remains ≤ NON-DETERMINISTIC; `seed_injected` flag hard-caps `decide`. **Green gate:** suite green + `spike/optimize/leakage_stress.py`/`redteam.py` FCR=0.

**Effort & dependencies.** **M.** Deps: `determinism.analyze`, the capture sitecustomize bootstrap, `verdict.decide`. Sequence **after** the determinism plumbing is stable; independent of 1/14/20. Highest *judgment* risk in the cluster — the value is honesty (better NON-DETERMINISTIC explanations), and the failure mode (CONFIRM a re-seeded different number) is a direct FCR breach, so the disqualification guard is non-negotiable.

---

## Feature 20 — Record-and-replay (rr-style)

**What & why.** The strongest determinism hammer: `rr` records *all* non-deterministic inputs (syscalls, signals, RDRAND/CPUID, scheduling) once and replays the execution **bit-for-bit** — "the replayed execution's address spaces, register contents, syscall data are exactly the same in every run." For Calma that means a *single* recorded run is provably re-playable, which is a determinism proof stronger than k=N sampling. **But** it is deliberately last: narrow reach (Linux, x86/Apple-M-series only), single-core (parallel repos pay a serialization slowdown), needs perf-counter virtualization (a constraint inside E2B/Firecracker), and unsupported syscalls break recording. Honest positioning: a niche escalation for high-value flaky repos, not a default path.

**SOTA & best practices (2026).**
- **rr** (Mozilla/Pernosco, v5.9.0 2025): user-space, stock kernels, records non-deterministic inputs + replays deterministically; **single-core by design** (context-switches threads onto one core to make scheduling deterministic and avoid data races). Constraints: Linux ≥4.7, Intel Nehalem+/certain AMD Zen/Apple M1+, VM guest needs virtualized HW perf counters (KVM ok, Xen not). https://rr-project.org/ · https://github.com/rr-debugger/rr · tech report https://arxiv.org/pdf/1705.05937
- **Trace-capsule blueprint (DebuggAI, 2025)**: the *lighter* alternative — a hermetic capsule with `--cpus=1`, `SOURCE_DATE_EPOCH`, `PYTHONHASHSEED=0`, `TZ=UTC`, **`LD_PRELOAD` libfaketime** for the clock, and network-replay; "the more determinism you push upstream into builds/execution, the less you need to capture." Prefer **kernel time namespaces** over LD_PRELOAD when available. https://debugg.ai/resources/time-travel-builds-debug-ai-record-replay-trace-capsules · https://debugg.ai/resources/deterministic-replay-code-debugging-ai-bugs-reproducible-fixes-verifiable
- **libfate / libfaketime** — tiny `LD_PRELOAD` shims that deterministically replace `getrandom()`/`/dev/urandom`, `clock_gettime()`, `sysinfo()` — the **80/20 of rr** for the common Python case (most Calma non-determinism is time+urandom+hash, not thread races). https://github.com/nicolas-graves/libfate
- **PEP 669 `sys.monitoring`** — the *language-level* analogue Calma already exploits: near-zero-overhead capture that returns `DISABLE` for non-target code (`spike/capture/calma_capture.py:460` `install_targets_monitoring`), 20× cheaper than `sys.settrace`. For *pure-Python* determinism, a monitoring-based value-replay is cheaper and more portable than rr. https://peps.python.org/pep-0669/ · https://blog.jetbrains.com/pycharm/2024/01/new-low-impact-monitoring-api-in-python-3-12/
- **rr chaos mode** — an *offensive* use: randomize thread priorities/timeslices to *provoke* rare races, then replay them deterministically — a way to strengthen the NON-DETERMINISTIC verdict (actively hunt hidden flakiness) rather than confirm. https://groups.google.com/g/golang-nuts/c/ouBKO-Q0Mtw
- Pitfalls: rr inside Firecracker needs HW perf counters exposed (may not be, on E2B); single-core kills throughput on parallel repos; unsupported syscalls abort; **replay proves the *recorded* run repeats — it does NOT prove the number is right** (that's still the oracle's job).

**Fit to Calma (FCR=0-safe).**
- A **capture/determinism escalation**, not a new oracle. Best framed as `spike/core/determinism.py` gaining a fourth tier *above* DETERMINISTIC-by-static-analysis: a `REPLAY_PROVEN` level from a successful rr record→replay, which — like the existing `determinism.proven` construction path (`spike/core/verdict.py:81-89`) — licenses k=1→CONFIRMED. New `spike/runner/rr_runner.py` still returns the runner-agnostic shape.
- **FCR argument — the subtle one:** rr proving replay-determinism must gate CONFIRMED **only in conjunction with the independent recompute** (`spike/core/verdict.py:70-99`), never alone. Replay determinism answers "does this run repeat?" It does *not* answer "is the number correct?" — so it substitutes for the *empirical k≥2 determinism check* only, exactly where static-proof-of-construction already substitutes today. The three-way diff (claimed == produced == **independently recomputed by Calma**, `spike/core/verdict.py:4-11`) is untouched: rr changes how `produced`'s stability is *established*, not what it's compared against. And it's conservative-by-construction like `analyze` (`spike/core/determinism.py:8-14`): **if rr record OR replay fails, or a syscall is unsupported, or perf-counters are unavailable → fall through to the existing k≥2 path** (one wasted attempt, never a false CONFIRM). The lighter LD_PRELOAD/SOURCE_DATE_EPOCH shim tier is even safer (it only *removes* clock/urandom noise, same category as `enforced_env` at `spike/core/determinism.py:154`).
- **Verdicts affected:** can lift a genuinely-deterministic-but-not-statically-provable repo from REPRODUCED-ONLY/NON-DETERMINISTIC to CONFIRMED **with a replay proof** (adds *downgrade-removal power*, gated on recompute agreement); chaos mode can *strengthen* NON-DETERMINISTIC by exposing hidden races. No path creates agreement that wasn't independently recomputed.

**Build plan.**
- **P0 (spike).** Start with the **cheap 80% first**: `spike/runner/shim_runner.py` (or extend `local_runner`/`e2b_runner` env) adding the DebuggAI/libfate shim — `SOURCE_DATE_EPOCH`, `--cpus=1`, `LD_PRELOAD` faketime + deterministic `getrandom`/urandom — as an *opt-in* determinism-enforcement extension to `enforced_env` (`spike/core/determinism.py:154`). This alone rescues most clock/urandom NON-DETERMINISTICs with none of rr's constraints.
- **P1 (product).** `spike/runner/rr_runner.py` `run_rr(...)`: `rr record` the entrypoint once in the E2B VM (probe perf-counter availability first; skip gracefully if absent), `rr replay` to prove bit-identical re-execution, return `replay_proven: True`. Add `DET.REPLAY_PROVEN` and thread it into `verdict.decide` as an *alternative* to `determinism.tested` **only when `recompute_known and recomputed agrees`** (mirror the `:81-89` block exactly).
- **P2 (hardening).** rr chaos mode as an optional "flakiness hunter" that can only *downgrade* to NON-DETERMINISTIC; syscall-unsupported/perf-counter fallback telemetry; strict wall/RSS caps under the supervisor; document that replay ≠ correctness in `verdict.py`.
- **Meta-eval instrument.** `spike/optimize/replay.py` — repos that are deterministic-in-fact but *not* statically provable (so today they can't reach CONFIRMED); measure how many rr correctly lifts, **and prove every lift also passed the independent recompute** (assert no CONFIRMED where recompute was absent/degenerate). Include an rr-incompatible repo (unsupported syscall) → must fall back to k≥2, FCR=0. Include a wrong-formula repo that replays perfectly → must stay INVALIDATED (replay can't rescue a bad formula).
- **Tests.** `spike/tests/test_rr_runner.py` (skipped without rr/perf-counters): shim tier removes clock-noise flakiness; `REPLAY_PROVEN` reaches CONFIRMED only with recompute agreement; unsupported-syscall → graceful fallback. **Green gate:** suite green + `spike/optimize/determinism.py` + `redteam.py` FCR=0.

**Effort & dependencies.** **XL** for full rr (perf-counter/Firecracker integration is the hard part); the **shim tier is S–M** and delivers most of the value — ship it first, treat rr as a research escalation. Deps: E2B/Firecracker perf-counter exposure, `determinism` tiering, `verdict.decide`. Sequence **last** in the cluster; the shim sub-piece can slot right after `enforced_env` work anytime.

---

### Cluster throughline (5 lines)
1. All four features are *upstream of the verdict*: they raise the reproduction floor (1, 14) and the determinism ceiling (15, 20), and none touch the oracle or the three-way diff — the reason each can be FCR-safe by construction.
2. The invariant that makes them safe is uniform: they may only ADD a runnable path or ADD downgrade-power; the CONFIRMED gate (`verdict.decide`: claimed == produced == *independently recomputed* + proven-deterministic) is byte-for-byte unchanged.
3. Sequence by leverage-per-risk: **Feature 1 first** (coverage multiplier for everything else), then **14** (kill drift-REFUTEs, reusing era-pin/uv), then **20's cheap shim tier**, with **15** and **full rr** as careful, tightly-gated escalations.
4. The two delicate ones share one rule — *seeding and replay prove a run REPEATS, not that its number is RIGHT* — so seed-injected and replay-proven runs are hard-capped unless the independent recompute already agrees.
5. Each ships with a dedicated `spike/optimize/` meta-eval whose non-negotiable assertion is **FCR=0**, so "more coverage" and "more confident determinism" can never smuggle in a false CONFIRM.


# Cluster B — Differential / Metamorphic / Certified Recompute (Features 2, 7, 17, 19)

Grounding read before writing: `spike/core/catalog.py` (the trusted pure-stdlib oracle + `recompute()` at
catalog.py:678–687; `math.fsum` already used in `mean`/`sum`/`sharpe`/`stdev`/`brier`/`correlation` at
catalog.py:354, 362, 384–393, 419, 290, 590–593), `spike/core/diff.py` (three-way diff `diff_claim`
diff.py:129–230; recompute at :164, resolver at :167–170, convention-search block at :181–193, determinism at
:198–214, `VD.decide` at :216), `spike/synth/formula.py` (`exec_formula` restricted namespace formula.py:37–46,
`_validate_synth` differential validation vs sklearn/scipy at :241–291, `recompute_any` catalog→store→synth→none
at :360–406), `spike/core/verdict.py` (`decide` at :33–116; INVALIDATED when produced≠recompute at :72–75),
`spike/core/conventions.py` (`search` at :154–173, the 8-rule hard contract at :12–31), `spike/core/tolerance.py`
(`close` rtol 1e-6 / atol 1e-9 at :23–31), `spike/capture/calma_capture.py` (targeted callable wrap
`install_targets` at :338–382, PEP-669 `install_targets_monitoring` at :460–538).

---

## Feature 2 — Fuzz-the-formula

**What & why.** Today the diff invokes the repo's metric on the *one* real captured input and checks the
number matches (diff.py:164). Fuzz-the-formula instead differential-tests the *repo's captured metric callable*
against the trusted catalog on many random inputs — turning "the number matches" into "the function *is* the
metric." A formula that only coincidentally hits the claimed value on the real data (a hard-coded return, a
subtly wrong denominator, a cheat keyed to the eval set) diverges immediately on fresh inputs. It is the
purest expression of the FCR=0 franchise: deterministic, un-foolable, and hard for a value-matching competitor
to replicate because it requires re-invoking the repo's own code, not just reading its output.

**SOTA & best practices (2026).**
- This is the classic property-based **"test oracle"** pattern: run the fast/suspect implementation and a
  simple obviously-correct reference on the same generated inputs and assert agreement — see the canonical
  taxonomy in F# for Fun and Profit (https://fsharpforfunandprofit.com/posts/property-based-testing-2/) and the
  2026 Hypothesis guide's dedicated "differential testing: multiple implementations, one truth" section
  (https://thecosmicmeta.com/coding-guide-property-based-testing-with-hypothesis/). Real-world instances:
  Elixir `AB`'s `compare_test` auto-diffs two impls (https://github.com/wende/ab); a Solana AMM proptest asserts
  the optimized swap matches the slow reference within a divergence bound
  (https://gist.github.com/S3v3ru5/3be85868e8907a5cf731446e782984c3).
- **Automatic shrinking** is the killer feature for our UX: on divergence, Hypothesis minimizes to the smallest
  counterexample so the report can show a 2-element array where repo-fn and catalog disagree
  (https://hypothesis.readthedocs.io/en/latest/, https://drmaciver.github.io/papers/reduction-via-generation-preview.pdf).
  Pitfall the docs flag: property tests need **determinism** — a repo-fn touching clocks/global RNG confuses
  replay (https://robulka.com/hypothesis/); guard by running the fuzz under our seeded, RNG-controlled env.
- **Held-out / uncontrollable-oracle framing** is exactly ours: `holdout` grades a candidate against "an oracle
  it cannot author" on inputs it never saw, catching false-greens that pass the visible examples — 28/29 on
  QuixBugs, and it flagged a patch SWE-bench's *own* oracle marked resolved
  (https://github.com/brevity1swos/holdout). Our catalog is that unforgeable oracle; the repo-fn is the candidate.
- Pitfall specific to metrics: a *legitimate* repo-fn can differ from the catalog default across random inputs
  purely by **convention** (ddof=0 vs 1, ×√252, gain/cutoff) — see conventions.py. Naive fuzz would mint false
  INVALIDATEDs. The fix is to fold the cited convention grid into the differential comparison (below).

**Fit to Calma (FCR=0-safe).**
- Capture tie-in: the callable is already resolvable. `install_targets` holds the live `orig` function object
  (calma_capture.py:356) and `install_targets_monitoring` matches the target's code object
  (calma_capture.py:406–419). Feature 2 adds an in-sandbox **fuzz pass**: after the normal run, re-invoke `orig`
  on K seeded random inputs shaped to the metric's canonical signature and emit `{seq, target, fuzz:[{inputs,
  output}...]}` to a sibling of `CALMA_CAPTURE_OUT`.
- Pipeline slot: a new host-side step inside `diff_claim` (diff.py), fired **only after** a claim is otherwise
  bound + reproduced + recomputed (i.e. would-be CONFIRMED/REPRODUCED-ONLY), reusing `C.recompute`
  (catalog.py:678) on each fuzz input and `T.close` (tolerance.py:23) for agreement.
- FCR-safety argument: the fuzz can **only downgrade**. Its output feeds a new invalidating signal into the
  existing `validity` overlay (diff.py:195 → verdict.py:76) so a formula-mismatch flips a would-be CONFIRMED to
  **INVALIDATED**; it never contributes to CONFIRMED. Two guards keep it from over-flipping (a UX regression, not
  an FCR breach): (1) an INVALIDATED requires divergence on a **majority of clean, non-degenerate** fuzz inputs
  (a single NaN/exception is discarded, matching catalog's `degenerate` fail-closed at catalog.py:14–16); (2)
  before declaring divergence we run the fuzz input through `CONV.search` (conventions.py:154) so any *standard*
  convention that reproduces the repo across all K inputs is accepted — and because the true convention is the
  only one that matches on **every** random input, fuzz simultaneously *disambiguates* the convention that the
  single-input search left ambiguous (conventions.py rule 6). If the callable can't be captured or re-invoked,
  we skip silently (fail-closed, verdict unchanged).
- Verdicts affected: strengthens **CONFIRMED** (now formula-verified, not value-verified) and produces new
  **INVALIDATED** on genuinely wrong/cheating formulas that value-matching would have confirmed.

**Build plan.**
- **P0 (sandbox fuzz emitter + host differential).** New `spike/capture/formula_fuzz.py`: `fuzz_target(orig,
  metric, k, seed)` builds canonical random inputs per metric family (labels for classification, floats for
  regression/finance, ranked lists for IR) and records `(inputs, output)` pairs; wire an opt-in call from
  `install_targets`/`install_targets_monitoring` gated on `CALMA_FUZZ=1`. New `spike/core/formula_diff.py`:
  `differential(metric, fuzz_pairs, base_kwargs) -> {"diverged": bool, "n_clean", "counterexample", "convention"}`
  using `C.recompute` + `T.close` + `CONV.search`. Edit `diff.py` diff_claim (after the convention block ~:193)
  to consume the emitted fuzz and, on a majority clean divergence, append to `validity["invalidating"]` (so
  verdict.py:76 fires INVALIDATED) and stash `rec["formula_fuzz"]` (counterexample + shrunk case) for the report.
- **P1 (shrinking + Hypothesis).** Add `hypothesis` as a **sandbox-only** dep (never in core; keep core
  pure-stdlib per the CI firewall). Use `@given` strategies to drive the fuzz and its built-in shrinker to
  minimize the counterexample; degrade gracefully to the P0 seeded-`random` generator when Hypothesis is absent.
- **P2 (coverage breadth).** Extend canonical input generators to every catalog family incl. `textmetrics`
  (BLEU/nDCG) and the synth/recipe resolver path (reuse `SYNTH.recompute_any`, formula.py:360, as the reference
  when the metric is not native-catalog).
- **Meta-eval instrument.** New `spike/optimize/formula_fuzz_eval.py` (mirrors optimize/convention_fuzz.py):
  generate two adversary classes — (a) *honest* repo-fns that equal the metric under some standard convention
  (must NOT be INVALIDATED: measure false-INVALIDATED rate), and (b) *cheating* repo-fns that hard-code / perturb
  the formula to hit the real value but diverge on random inputs (must be caught: measure catch-rate). Assert the
  cardinal invariant: **zero cheating formulas reach CONFIRMED**. Emit `formula_fuzz_eval.json` + a SCOREBOARD row.
- **Tests.** `spike/tests/test_formula_fuzz.py`: honest-formula-not-flipped, cheat-formula→INVALIDATED,
  convention-legit-formula survives, uncapturable-callable→verdict-unchanged, exception/NaN inputs discarded,
  determinism (same seed → same counterexample).
- **Green gate.** `~/.calma/spike-venv/bin/python -m pytest spike/tests/ -q` all pass **and**
  `formula_fuzz_eval.py` returns 0 false-CONFIRMs (FCR gate) with false-INVALIDATED rate under a set budget.

**Effort & dependencies.** **M** (2 new files + focused diff.py edit for P0; Hypothesis P1 is additive).
Depends on the capture layer already resolving the target callable (present) and on conventions.py (present).
Sequence **first** in the cluster — it is the highest value-per-risk and its differential harness is reused by
Feature 17. No conflict with FCR because it is downgrade-only.

---

## Feature 7 — Metamorphic verification

**What & why.** When there is no recompute path — the metric is unrecognised, the inputs were too large to
capture (diff.py:160 → recompute "inputs not captured"), or it is a learned/embedding metric with no independent
oracle (formula.py:369–377) — Calma currently falls to REPRODUCED-ONLY. Metamorphic relations (MRs) are a
**pseudo-oracle**: instead of recomputing the value, we perturb the captured inputs in a way whose effect on the
output is *known analytically* (permute samples → accuracy unchanged; flip labels → AUC → 1−AUC; positive-affine
rescale → Pearson unchanged; raise the threshold → recall monotone non-increasing) and check the repo's own
function honours it. A violated MR is proof the formula is not the metric it claims — a defensible verdict with
no ground truth, and a cheat-catcher even where recompute is possible.

**SOTA & best practices (2026).**
- MRs are the mainstream answer to the **oracle problem** in ML precisely because you test "without knowing the
  ground-truth label" (Giskard, https://www.giskard.ai/knowledge/how-to-test-ml-models-4-metamorphic-testing).
  State-of-the-art surveys: MR *generation* (ACM TOSEM 2024, https://doi.org/10.1145/3708521; 63 of 81
  MR-generation papers appeared 2019–2024) and MR *automation over two decades*
  (https://doi.org/10.22541/au.175872613.39541241/v1), plus the MR-generation survey
  https://arxiv.org/html/2406.05397v2.
- **Classifier-specific MRs already exist and are validated.** Xie et al.'s user-expectation MRs incl. **MR:
  permutation of class labels** (predictions permute with the label map) — catalogued and fault-measured by Saha
  & Kanewala (https://doi.org/10.48550/arxiv.1904.07348). A 2025 closed-form result proves twelve confusion-matrix
  metrics (accuracy, macro/micro/weighted F1, precision, recall) are **provably invariant** under class-label
  permutation and confusion-matrix transposition (https://doi.org/10.3390/math13162609,
  https://www.mdpi.com/2227-7390/13/16/2609) — i.e. these MRs are *exact*, not heuristic, so a violation is a
  hard fault. Metric-level MRs to encode: accuracy/F1 sample-order & label-permutation invariance; ROC-AUC
  score-negation → 1−AUC and strict-monotone score-transform invariance; Pearson affine invariance and sign flip;
  Spearman/Kendall strict-monotone invariance; RMSE/MAE translation-equivariance; Sharpe scale-equivariance.
- **Automated MR discovery** is maturing (genetic programming GenMorph,
  https://valerio-terragni.github.io/assets/pdf/ayerdi-tse-2024.pdf; LLM-discovered MRs, ~30–44% of candidates
  valid, https://doi.org/10.1109/saner64311.2025.00011) — a P2 path to grow MRs for novel metrics, gated by
  validation exactly like the synth flywheel.
- Pitfalls: (1) MR fault-detection is **partial** — Saha & Kanewala found a fixed MR set caught only ~14.8% of
  mutants — so MRs *supplement*, never replace, recompute. (2) A too-loose MR (approximate equality) can miss a
  fault; use exact analytic relations where they exist (the confusion-matrix invariances) and tight `T.close`
  tolerance elsewhere. (3) Floating-point noise: rescale/permute perturbations must respect the same tolerance
  regime as the recompute (tolerance.py:23).

**Fit to Calma (FCR=0-safe).**
- Anchors: reuse the captured `inputs` (diff.py:153) and the repo's callable re-invocation from Feature 2's
  capture emitter; new `spike/core/metamorphic.py` holds the MR registry keyed by canonical metric (catalog.py
  `canonical`, :666). MR checks run on the **repo's function** (via the fuzz/target re-invoke), not the catalog.
- Pipeline slot: a metamorphic pass in `diff_claim` positioned in the **no-trusted-oracle branch** (the state
  that today yields REPRODUCED-ONLY at verdict.py:101–116) and additionally as a corroborating check in the
  recompute branch.
- FCR-safety argument: MRs are **downgrade-or-hold only**. A *violated* MR adds to `validity["invalidating"]`
  → INVALIDATED (verdict.py:76/109). A *satisfied* MR never yields CONFIRMED — because MR satisfaction is
  necessary, not sufficient (a wrong formula can still honour permutation-invariance). The strongest a satisfied
  MR does is annotate REPRODUCED-ONLY as "reproduced + metamorphically consistent" (a caveat, verdict.py:114),
  keeping CONFIRMED reserved for genuine recompute. This preserves FCR=0 by construction: MRs can only fail a
  number closed, never open it.
- Verdicts affected: new **INVALIDATED**s where no recompute existed (the coverage win); enriched
  **REPRODUCED-ONLY** reason strings; extra INVALIDATED corroboration on cheating formulas.

**Build plan.**
- **P0 (exact classifier + correlation MRs).** New `spike/core/metamorphic.py`: `MR` dataclass
  `{metric, name, transform(inputs)->inputs', relate(v0, v1)->bool, source}` and a `check(metric, fn, inputs,
  kwargs)` runner. Seed the analytically-exact MRs: accuracy/precision/recall/f1 sample-permutation &
  label-permutation invariance (cite MDPI 2025); roc_auc score-negation→1−AUC; correlation positive-affine
  invariance + sign-flip. Edit diff.py to run `MR.check` on the repo callable and route a violation into
  `validity["invalidating"]`; annotate the satisfied case as an advisory caveat.
- **P1 (regression/finance/IR MRs + report surface).** Add RMSE/MAE translation-equivariance, R² scale/affine
  invariance, Sharpe/Sortino positive-scale equivariance, nDCG permutation-within-tie & cutoff monotonicity.
  Surface the fired MRs in `rec["metamorphic"]` for the report ("AUC did not flip to 1−AUC under label swap —
  the reported formula is not ROC-AUC").
- **P2 (MR discovery, validation-gated).** Optional LLM/GP-proposed MRs for novel metrics, each **validated**
  against the catalog on random inputs before it is ever trusted — identical discipline to `_validate_synth`
  (formula.py:241). An unvalidated MR is discarded (fail-closed).
- **Meta-eval instrument.** New `spike/optimize/metamorphic_eval.py`: (a) apply each MR to the *correct* catalog
  metric and assert it holds to tolerance across seeds (soundness — no false INVALIDATED on honest formulas);
  (b) apply to a corpus of mutated/cheating formulas and measure fault catch-rate; (c) assert zero MR path ever
  yields CONFIRMED. Emit `metamorphic_eval.json` + SCOREBOARD row.
- **Tests.** `spike/tests/test_metamorphic.py`: each exact MR holds on catalog metrics; label-flip on a
  not-really-AUC formula → INVALIDATED; satisfied-MR never CONFIRMED (stays REPRODUCED-ONLY); tolerance respected;
  uncallable-target → no MR run, verdict unchanged.
- **Green gate.** Full `pytest` green + `metamorphic_eval.py` reports zero false-INVALIDATED on the honest set
  and zero CONFIRMED via the MR path.

**Effort & dependencies.** **M–L** (the MR math is small but breadth accrues per metric family). Depends on
Feature 2's callable re-invocation (build after F2). Independent of F17/F19. The exact confusion-matrix MRs are
the cheap, high-confidence P0; discovery is optional upside.

---

## Feature 17 — Differential recompute

**What & why.** Require **two independent recompute paths to agree** before trusting a recompute — belt-and-
suspenders against a latent bug in the catalog itself. Position honestly: this is *marginal*, because the catalog
is already the trusted, sklearn-validated-to-1e-9 independent oracle, and single-oracle agreement with the repo
is the whole three-way diff. Its real, bounded value is (a) cross-checking the **synth/recipe** paths
(formula.py:360–406) — code that is generated or lifted, not hand-curated to 1e-9 — against the native catalog,
and (b) an optional second-language impl as a defence against a shared-language rounding assumption.

**SOTA & best practices (2026).**
- Differential testing of numerical libraries is well-trodden: **FPDiff** cross-tests GSL (C), SciPy, mpmath and
  jmat (JS), finding 655 discrepancies from source alone (https://doi.org/10.1145/3395363.3397380,
  https://github.com/ucd-plse/FPDiff; dissertation https://escholarship.org/uc/item/8n1443pk). The cross-
  referencing oracle also underpins **JEST**'s N+1-version JS-engine testing
  (https://plrg.korea.ac.kr/assets/data/publication/icse21-park-jest.pdf) and LLM-driven **Mokav**
  (https://arxiv.org/html/2406.10375).
- **N-version programming** is the theory: independence via diverse algorithms/languages/teams and cross-check
  vectors at decision points (Avizienis,
  https://curtsinger.cs.grinnell.edu/teaching/2019S/CSC395/papers/avizienis.pdf). Cross-language *verified*
  equivalence is now automatable (Galápagos, C-to-Go, https://arxiv.org/html/2408.09536v2).
- **The critical caveat — correlated failure.** Knight–Leveson showed independently written versions do *not*
  fail independently, and a 2026 replication with coding agents confirms it hard: 429 coincident failures where
  the independence model predicts 115, persisting across language and agent boundaries
  (https://arxiv.org/html/2606.20158). Consequence for us: **two agreeing recomputes multiply confidence only if
  they are genuinely diverse**; two LLM-synthesized formulas from the same prompt/definition can share a blind
  spot and agree while both wrong. So differential recompute must never *upgrade* on the strength of agreement
  from non-independent sources.

**Fit to Calma (FCR=0-safe).**
- Anchors: `recompute_any`'s ladder (formula.py:360) already selects catalog→store→synth→recipe. Add
  `spike/synth/xcheck.py`: `crosscheck(metric, inputs, kwargs) -> {agree, values, provenances}` that computes
  **all available** independent paths (native catalog + recipe + synth/stored formula, and optionally a
  second-language shell-out) and compares with `T.close`.
- Pipeline slot: invoked inside diff.py right after the primary recompute (diff.py:164–170), before `VD.decide`.
- FCR-safety argument: strictly **downgrade-only, and asymmetric**. If two independent paths **disagree**, the
  recompute is no longer trustworthy → force `recomputed.degenerate = True` so the verdict falls to
  REPRODUCED-ONLY/INCONCLUSIVE (verdict.py:101) instead of confirming on a possibly-buggy oracle — a strict
  tightening of FCR. If they **agree**, we do **not** raise confidence beyond what a single trusted catalog
  already grants (agreement among possibly-correlated impls is not independent evidence, per Knight–Leveson), so
  CONFIRMED is reached exactly as today. Net: F17 can only ever *remove* a CONFIRMED, never add one.
- Verdicts affected: new **downgrades** (would-be CONFIRMED/INVALIDATED → INCONCLUSIVE) when the catalog and a
  synth/recipe path disagree — i.e. it flags *oracle* bugs, which is its honest job.

**Build plan.**
- **P0 (intra-Python cross-check).** New `spike/synth/xcheck.py`. Edit `diff.py` to call it when ≥2 paths resolve
  the metric (native catalog **and** a recipe/stored formula both know it); on disagreement, mark the recompute
  degenerate with a "recompute paths disagree (catalog=… synth=…)" note; on agreement, pass through unchanged.
  Cheap and fully deterministic.
- **P1 (make synth-validation differential-by-default).** Strengthen `_validate_synth` (formula.py:241) to also
  cross-check a *newly synthesized* formula against the native catalog whenever one exists (not only sklearn/
  scipy), so a formula only banks if it agrees with **two** references — directly hardening the flywheel where the
  N-version correlated-failure risk actually bites.
- **P2 (optional second-language oracle).** A tiny, sandboxed C/Rust or R/Julia recompute for the top handful of
  convention-sensitive metrics (Sharpe/stdev/correlation), shelled out with numeric I/O, used only as a
  *disagreement detector*. Explicitly diversity-audited (distinct algorithm, not a transliteration) to earn any
  independence claim.
- **Meta-eval instrument.** New `spike/optimize/xcheck_eval.py`: inject a deliberately buggy shadow oracle and
  assert the cross-check catches the disagreement and downgrades (never CONFIRMs through a divergent oracle);
  assert on the honest corpus that agreement rate is ~100% and no new false REFUTED/INVALIDATED is introduced.
- **Tests.** `spike/tests/test_xcheck.py`: catalog-vs-synth agreement passes; injected mismatch → recompute
  degenerate → REPRODUCED-ONLY; single-path metric unaffected; agreement does not upgrade a k=1 REPRODUCED-ONLY to
  CONFIRMED.
- **Green gate.** Full `pytest` green + `xcheck_eval.py` shows zero FCR breach and zero regression in the live
  corpus CONFIRMED count (agreement is the common case).

**Effort & dependencies.** **S** for P0 (pure-Python, one small module + diff hook). **L** for the P2 second-
language oracle (sandbox toolchain, packaging). Sequence **after** Feature 2 (reuses its differential harness
concept) and value-order it last within the cluster — mostly a hardening of the synth flywheel, not new coverage.

---

## Feature 19 — Interval arithmetic on the recompute

**What & why.** Replace the catalog's point value + fixed tolerance (tolerance.py:23, rtol 1e-6/atol 1e-9) with a
**certified enclosure** [lo, hi] guaranteed to contain the true real-number result. Position honestly: marginal
in the common case, because the catalog already uses `math.fsum` (exact-rounded summation) throughout
(catalog.py:354/362/384/419/590) so most recomputes are already near-exact and the tolerance layer absorbs benign
float drift. The genuine payoff is at the **tolerance boundary under ill-conditioning**: catastrophic cancellation
in variance/correlation/Sharpe on offset or near-constant data, where a naive repo formula can differ from the
true value by *more than tolerance* for a legitimate reason — the point at which a false INVALIDATED (or, worse, a
boundary-hugging false CONFIRMED) becomes possible.

**SOTA & best practices (2026).**
- Rigorous enclosures are production-ready in Python: **mpmath**'s `iv` interval context guarantees
  f(v) ⊆ f̂(v) (https://mpmath.org/doc/current/contexts.html), and **python-flint / Arb** midpoint-radius **ball
  arithmetic** tracks error automatically (https://python-flint.readthedocs.io/en/latest/arb.html,
  https://www.arblib.org/). `certsf` shows the honest contract to copy: return `certified=True` **only** when a
  rigorous enclosure exists, never silently fall back and call an approximation certified
  (https://pypi.org/project/certsf/0.1.0a3/). Pitfall both docs stress: interval bounds can be **far too
  pessimistic** (mpmath: "sometimes provides far too pessimistic bounds"; ~2× slower), so use intervals as a
  *decision aid at the margin*, not the everyday recompute.
- Where certified bounds genuinely help — **catastrophic cancellation**: the textbook one-pass variance
  E[x²]−E[x]² loses all precision on offset data (variance of `1e9 + {4,7,13,16}` computes as −170.7); use the
  numerically-stable **two-pass** or **Welford** form and, for the sum, **Kahan / Neumaier compensated
  summation** / error-free transforms (https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance,
  https://en.wikipedia.org/wiki/Kahan_summation_algorithm, Rump–Ogita–Oishi
  https://www.tuhh.de/ti3/paper/rump/RuOgOi07I.pdf; AccurateArithmetic.jl doubles the effective working precision
  https://github.com/JuliaMath/AccurateArithmetic.jl). Note CPython ≥3.12 `sum()` already uses Neumaier
  compensation, and the **condition number** of the sum bounds the achievable accuracy (Chan–Golub–LeVeque,
  http://infolab.stanford.edu/pub/cstr/reports/cs/tr/79/773/CS-TR-79-773.pdf; Schubert–Gertz stable covariance,
  https://doi.org/10.1145/3221269.3223036; Kahan mean/variance
  https://people.eecs.berkeley.edu/~wkahan/Math128/MeanVar.pdf).

**Fit to Calma (FCR=0-safe).**
- Anchors: the enclosure lives beside the point recompute in the catalog (`result()` at catalog.py:33) and is
  consumed by the closeness decision in `tolerance.close` (tolerance.py:23) and the INVALIDATED/CONFIRMED gate
  (verdict.py:72,98). New `spike/core/intervals.py`: certified enclosures for the boundary-prone kernels
  (mean/sum/variance/stdev/correlation/sharpe) via python-flint Arb when installed, else a stdlib
  error-free-transform (Neumaier) fallback that still yields a rigorous [lo, hi].
- Pipeline slot: computed lazily **only when** `|produced − recomputed|` lands within a small factor of the
  tolerance (the ambiguous band) — never on the 99% of comfortably-inside or comfortably-outside cases, keeping
  the ~2× cost off the hot path.
- FCR-safety argument: intervals are used **only to widen doubt, never to narrow it.** Decision rule at the
  boundary: (a) if the certified enclosure lies **entirely outside** the claim/produced tolerance → the
  INVALIDATED is *certified* (upgrade the report's confidence, not the verdict class); (b) if it lies **entirely
  inside** → CONFIRMED stands, now provably so; (c) if the enclosure **straddles** the boundary → we cannot
  certify either way → **downgrade to INCONCLUSIVE** rather than guess. Case (c) is the only behavior change and
  it is strictly fail-closed, so FCR=0 is preserved (a straddling enclosure can never mint a CONFIRMED). The
  enclosure is our recompute's; it never trusts the repo's arithmetic.
- Verdicts affected: converts a thin slice of tolerance-boundary **CONFIRMED/INVALIDATED** into certified
  versions of themselves, and a genuinely-ambiguous slice into **INCONCLUSIVE** (fail-closed).

**Build plan.**
- **P0 (harden the kernels + stdlib enclosure).** Add Neumaier compensated summation and two-pass/Welford variance
  to the boundary-prone catalog kernels behind the existing `math.fsum` (catalog.py:419 stdev, :590 correlation,
  :384 sharpe), and a `spike/core/intervals.py` producing a rigorous stdlib [lo, hi] from error-free transforms.
  Zero new deps; already improves ill-conditioned recompute accuracy.
- **P1 (Arb enclosure + boundary gate).** Optional python-flint backend for tight certified balls; add the
  boundary-band trigger in diff.py/verdict.py implementing rule (a)/(b)/(c) above, with `certified` provenance in
  the report à la certsf — certified only when a rigorous enclosure was actually produced.
- **P2 (breadth + reporting).** Extend enclosures to the remaining convention-sensitive kernels and show the
  enclosure in the UI when a verdict was decided at the margin ("recompute ∈ [x, y]; claim outside → certified
  INVALIDATED").
- **Meta-eval instrument.** New `spike/optimize/interval_eval.py`: a battery of **ill-conditioned** inputs
  (offset variance à la `1e9+ε`, near-zero-vol Sharpe, high-offset correlation) asserting (1) the certified
  enclosure always contains the exact arbitrary-precision value (soundness), (2) straddling cases downgrade to
  INCONCLUSIVE not CONFIRMED (FCR gate), (3) no honest well-conditioned CONFIRMED is lost.
- **Tests.** `spike/tests/test_intervals.py`: enclosure contains an mpmath high-precision reference on random +
  adversarial inputs; catastrophic-cancellation case recomputes correctly; straddle→INCONCLUSIVE;
  comfortably-inside→CONFIRMED unchanged; python-flint-absent fallback still rigorous.
- **Green gate.** Full `pytest` green + `interval_eval.py`: zero enclosure-soundness violations, zero FCR breach,
  zero regression in well-conditioned CONFIRMED count.

**Effort & dependencies.** **M** for P0 (kernel hardening is contained, pure-stdlib). **L** if the Arb backend
and boundary gate ship together (optional dep + verdict-path plumbing). Sequence **last** — lowest marginal gain,
and it should build on the boundary logic only after F2/F7 have widened where verdicts get decided. python-flint
stays an optional, sandbox-side dependency; core remains pure-stdlib.

---

### Cluster throughline
All four features share one FCR=0-safe shape: they add *independent, downgrade-only* correctness pressure and
never open a path to CONFIRMED that value-matching alone would not already earn. Feature 2 (fuzz-the-formula) is
the anchor and the highest value-per-risk — differential-testing the repo's own callable against the catalog on
random inputs, un-foolable and hard to copy — and its callable-re-invocation harness is reused by Feature 7's
metamorphic pseudo-oracle (which extends coverage to the no-recompute case) and informs Feature 17's cross-check.
Feature 17 (differential recompute) and Feature 19 (interval arithmetic) are honestly marginal — a
hardening of the synth flywheel and a certified tolerance-boundary decision, respectively — valuable exactly
where correlated-oracle bugs (Knight–Leveson) and catastrophic cancellation live. Build order 2 → 7 → 17 → 19,
each gated by a `pytest` green plus an adversarial FCR meta-eval that proves zero false-CONFIRM, mirroring
`optimize/convention_fuzz.py`.


# Cluster C — Legibility, Stochastic Coverage, and Fabrication/Anomaly Defenses

Four features that widen Calma's coverage while holding the sacred invariant **FCR=0** (a wrong number must never reach `CONFIRMED`). Three of them (4, 10, 11) are structurally safe because they only *identify* or *downgrade*; the one that adds a positive path (6) is fenced behind a distinct label, per-run recompute, conservative prediction intervals, and multiple-comparison correction.

Code read to ground these plans: `spike/discovery/extract.py` (discovery/legibility), `spike/core/verdict.py` (`decide()` taxonomy), `spike/planner.py` (AI-proposes/determinism-disposes), plus `spike/core/diff.py`, `spike/pipeline.py`, `spike/core/determinism.py`, `spike/core/tolerance.py`, `spike/runner/local_runner.py`, `spike/capture/calma_capture.py`, and the meta-eval pattern in `spike/optimize/measure.py`.

---

## Feature 4 — AI claim-classifier

**What & why.** Today `discover()` emits *every* span that maps to a catalog metric, then sorts by a hand-tuned confidence (`spike/discovery/extract.py:236-269`). On a real repo this produces the "2,397 candidate claims → found nothing" legibility failure: the true headline numbers are buried under README boilerplate, hyperparameter tables, and per-fold noise. Feature 4 inserts a classifier that scores each discovered candidate as *headline metric-claim* vs *noise/context*, so the UI and the verifier work the short, high-precision list first. It is a pure **identification** stage: it changes *which* claims we spend a run verifying, never *what verdict* a claim gets.

**SOTA & best practices (2026).**
- **TDMR/TDMS extraction is the exact prior art.** Leaderboard extraction reliably nails Task/Dataset/Metric but *the Score/value is the bottleneck* — GPT-4-class models drop sharply on exact score match, and hallucinate method/score rows (LEGOBench: GPT-4 only ~25% correct methods, ~74% of those scores wrong) — https://arxiv.org/html/2401.06233 ; leaderboard-extraction LLM study https://arxiv.org/html/2406.04383v2 ; SCILEAD three-stage RAG TDMR pipeline (extract → normalize to a taxonomy → rank) https://aclanthology.org/2024.emnlp-main.453.pdf . Design implication: let the LLM *classify/rank*, keep the numeric *value* from the deterministic parser (Calma already does this — the value comes from `tolerance.parse_claim`, not from a model).
- **Separate omission from hallucination.** ExtractBench distinguishes present / null / MISSING and scores hallucination (fabricated field) separately from omission (missed field) — precisely the two error modes that matter for FCR https://arxiv.org/html/2602.12247 . For Calma, hallucinating a *claim* is harmless (it dead-ends at DISCOVERED/INCONCLUSIVE); omitting one is a coverage loss. So tune for **recall on the candidate set, precision on the "verify-now" head**.
- **Field-level, black-box confidence exists and works without logprobs** (Anthropic models expose none): CONSTRUCT scores per-field trustworthiness of structured outputs in real time, no labels/logprobs, higher precision/recall than baselines https://arxiv.org/pdf/2603.18014 ; sub-structure confidence via CABS https://arxiv.org/html/2406.00069 . Use this to attach a calibrated `salience` per candidate rather than trusting a single self-reported number.
- **Constrained decoding for the label schema, but don't over-trust it.** JSON-schema constrained decoding guarantees *shape*, not *value* correctness, and quality varies by engine https://arxiv.org/html/2501.10868v1 ; schema-as-contract framing (PARSE) reduces extraction errors https://doi.org/10.18653/v1/2025.emnlp-industry.184 . Calma's planner already uses Anthropic structured output (`spike/planner.py:147-151`), so reuse that machinery.
- **Scientific-claim verification framing** (SciFact SUPPORTS/REFUTES + rationale) is the mental model for "is this a checkable quantitative claim?" https://aclanthology.org/2020.emnlp-main.609 . Pitfall: prose numbers ("95% test accuracy") are the weak spot — Calma already has generous prose regexes gated by `map_metric` (`extract.py:120-170`); the classifier's job is to *rank* those, not re-extract them.

**Fit to Calma (FCR=0-safe).** Slot: a new stage strictly between discovery and diff — `spike/pipeline.py:446-451` (`DISC.discover(...)` → `claims.extend(discovered)`) and the diff at `pipeline.py:465-479`. The classifier consumes the existing claim dicts (each already carries `metric`, `value`, `location`, `source`, `confidence` — `extract.py:108-113`, `264-269`) and returns a `salience` score + `is_metric_claim` boolean; it re-orders and buckets, it does not delete the numeric value or touch `metric`. **FCR-safety argument:** `verdict.decide()` (`spike/core/verdict.py:33`) is never called by this stage and its inputs (`claimed_raw`, `produced`, `recomputed`, `binding`, `determinism`, `validity`) are untouched. A false-negative (real claim scored as noise) demotes it to the "not-verified-now" bucket → it stays `DISCOVERED`, a coverage loss, never a confirm. A false-positive (noise scored as claim) still has to pass binding + reproduction + recompute + determinism to reach `CONFIRMED`; noise fails binding at `verdict.py:51-56` → `INCONCLUSIVE`. Verdicts affected: **none directly**; it improves the *ordering and count* surfaced (`pipeline.py:485-487` counts) and unblocks the "found nothing" UX by promoting the true headline to the top of the list.

**Build plan.**
- **P0 — deterministic salience (no LLM, ship first).** New `spike/discovery/salience.py::score_claims(claims, repo_ctx)` computing a transparent 0–1 salience from features already present: source rank (`results-json` > `table` > `prose`/`stdout`), split hint (test/holdout > train, mirroring the train down-weight at `extract.py:266-269`), location (README/results.json headline vs deep table), metric-in-catalog confidence, and dedupe-context. Add `salience` to each claim; sort by it. Wire into `pipeline.py` right after `claims.extend(discovered)`. This alone fixes most of the legibility problem and has zero FCR surface.
- **P1 — LLM classifier (best-effort, planner-style).** New `spike/discovery/claim_classifier.py::classify(claims, repo_snapshot, model=env CALMA_CLAIM_MODEL)` reusing the planner's Anthropic structured-output call (`planner._call_model`, `planner.py:130-156`): input = the candidate list + bounded README/results context; output schema = `[{id, is_headline: bool, salience: 0..1, kind: metric|hyperparam|dataset-stat|noise}]`. Merge model `salience` with the P0 score (min/mean), never overriding the numeric value. Best-effort by construction: no key / any error → P0 ranking stands (same fallback discipline as `planner.plan_repo` returning `None`, `planner.py:197-204`).
- **P2 — calibrated confidence + head cut.** Add a black-box field-confidence pass (CONSTRUCT-style self-consistency across 2–3 samples) to set a `verify_head` = top-N by salience shown/verified first; the tail stays discoverable behind "show all N candidates."
- **Meta-eval instrument.** `spike/optimize/claim_legibility.py`: over the corpus captures, label each discovered claim as headline/noise (weak labels from results.json keys + README H2/table position), report **head-precision**, **recall@head**, and — the guardrail — assert `false_confirm_rate` from `optimize/measure.py:score` is **unchanged** with the classifier on vs off (it must be identical, since verdicts don't move).
- **Tests.** `spike/tests/test_claim_classifier.py`: (a) ordering — a results.json test-accuracy outranks a README hyperparameter table row; (b) FCR-invariance — inject the misreport corpus, run diff with classifier on/off, assert identical verdict set; (c) fallback — no API key → P0 order returned, no exception; (d) never mutates `metric`/`value`.
- **Green gate.** `~/.calma/spike-venv/bin/python -m pytest spike/tests/test_claim_classifier.py spike/tests/test_discovery.py` + `optimize/measure.py` shows `false_confirm_rate` == baseline.

**Effort & dependencies.** **S** for P0 (pure stdlib, ~half day), **M** with P1/P2. Depends only on the existing Anthropic client path in `planner.py`. Sequence **first** — it is a pure win and every downstream feature (6/10/11) reads cleaner input once the head is legible.

---

## Feature 6 — Statistical / distribution verification of stochastic claims

**What & why.** Unseeded deep-learning repos are currently a dead-end: `determinism.analyze` returns `at_risk` (`spike/core/determinism.py:136-144`), the k≥2 replay disagrees, and `verdict.decide` emits `NON-DETERMINISTIC` (`spike/core/verdict.py:94-97`) — we reproduce the code but can never confirm the number. Feature 6 turns that dead-end into signal: re-run k times, recompute the metric from each run's captured inputs, build a **prediction/tolerance interval**, and decide `CONFIRMED-STOCHASTIC` if the claim lands inside, `REFUTED` if provably outside, else `INCONCLUSIVE`. This opens the entire unseeded-DL segment while staying fail-closed.

**SOTA & best practices (2026).**
- **Prefer prediction intervals and permutation over paired bootstrap.** Medical-DL reproducibility shows paired bootstrapping *falsely* declared significance in 15% of same-method comparisons (miscalibrated); retraining variance is large and must be accounted for — https://proceedings.mlr.press/v227/bosma24a/bosma24a.pdf . For LLM/benchmark scores, a simple repeated-run **prediction interval** is the recommended cost-effective uncertainty estimate https://arxiv.org/html/2410.03492 . Permutation/sign-flip p-values beat the Student-t approximation and find fewer false significances https://scholarsarchive.byu.edu/cgi/viewcontent.cgi?article=2031&context=facpub .
- **CLT standard errors + question-level pairing** (Anthropic "Adding Error Bars to Evals": CLT SE of the mean, clustered SE for grouped questions, inference on paired per-question deltas, power analysis before claiming) https://arxiv.org/html/2411.00640v1 . Calma recomputes per-item, so the *within-run* SE is available cheaply when inputs are captured.
- **Significant AND meaningful; require P(A>B)≥γ.** Bouthillier et al.: randomize every variance source, don't compare means alone, use a decision criterion on the probability one run beats another; the natural threshold is the benchmark's own variance https://voletiv.github.io/docs/publications/2021a_MLSys2021_Variance_in_ML_Benchmarks.pdf . Seed variance is often *smaller* than the naive bootstrap CI, so a too-wide interval over-confirms — quantify it directly https://arxiv.org/pdf/2406.10229 .
- **Be conservative under tight budgets.** "When +1% Is Not Enough" — with only 3 seeds a paired BCa + sign-flip protocol never declared significance on 0.6–2.0pt gains; treat small k as low-power and default to INCONCLUSIVE https://arxiv.org/pdf/2511.19794 . Bosma recommends ≥25 seeds when effect sizes are <2.5% — so k must scale with how tight the claim is.
- **Multiple comparisons.** A repo yields many claims; controlling per-claim α inflates family-wise false-REFUTE/false-CONFIRM. Use Holm/Šidák or maxT simultaneous intervals https://link.springer.com/article/10.1007/s10994-024-06632-w . Pitfall: interval too wide (from tiny k or heavy tails) is the FCR hole — mitigate with a nonparametric min/max envelope + conservative widening and a hard "need ≥ k_min runs" gate.

**Fit to Calma (FCR=0-safe).** Slot: `spike/core/diff.py:199-218`. `diff_claim` **already computes `produced_each`** (the per-run recomputed/produced values) and today only asks "are they all close?" (`diff.py:205-211`). Feature 6 feeds that same list into an interval when `determinism.tested and not stable`. New `verdict.decide` branch guarded by a `distribution` argument. **FCR-safety argument, four fences:** (1) the interval is built from the repo's **own recomputed run values** — each run still passes `produced==recompute(inputs)` (`diff.py:153-193`) and the validity overlay, so a hardcoded/fabricated number that differs from what the code actually computes falls *outside* the interval → `REFUTED`, not confirmed; (2) `CONFIRMED-STOCHASTIC` is a **distinct label** kept *out of* `POSITIVE=(CONFIRMED,)` semantics where the moat's deterministic-confirm count is reported — it never masquerades as a hard CONFIRMED (mirrors the existing `deterministic-by-construction` distinction at `verdict.py:81-89`); (3) a hard **k_min power gate** — below it, stay `INCONCLUSIVE` (fail closed), exactly the conservative-under-budget SOTA above; (4) **multiplicity correction** across the repo's claims so family-wise error is bounded. It only *activates on claims that are otherwise `NON-DETERMINISTIC`/dead*, so it is strictly coverage-adding — worst case it returns INCONCLUSIVE. Verdicts affected: adds `CONFIRMED-STOCHASTIC`; can emit `REFUTED`/`INCONCLUSIVE`; drains `NON-DETERMINISTIC` from a dead-end to a decision.

**Build plan.**
- **P0 — interval core (pure stdlib).** New `spike/core/interval.py`: `predict_interval(values, coverage=0.99, k_min=5) -> {lo, hi, center, method, enough}` using a Student-t prediction interval for a future single run *and* a nonparametric min/max envelope widened by the sample range; take the **wider** (conservative) of the two; `enough=False` when `len(values) < k_min`. `contains(interval, claimed)` uses `tolerance.claim_close` semantics at the interval edges so rounding is honored.
- **P1 — verdict + diff wiring.** Add `CONFIRMED_STOCHASTIC = "CONFIRMED-STOCHASTIC"` to `verdict.py:20-27` and a `distribution=None` kwarg to `decide()`. In the `determinism.tested and not stable` path (`verdict.py:94-97`), if `distribution.enough`: `contains` → `CONFIRMED_STOCHASTIC` (reason cites k, interval, coverage, correction), provably-outside-by-margin → `REFUTED`, else `INCONCLUSIVE`; if `not enough` → keep `INCONCLUSIVE` ("re-run ≥k_min to decide"). In `diff.py:216-218` pass `distribution=interval.predict_interval(produced_each, ...)`.
- **P1 — adaptive k for stochastic repos.** Extend the adaptive-k gate (`pipeline.py:409-421`): when `determinism.analyze` is `at_risk` *and* the claim head is non-trivial, raise effective k from 2 to `k_stoch` (env `CALMA_K_STOCH`, default 5–10) so the interval has power. This is the inverse of the k=1 shortcut and equally fail-closed (more runs, never fewer for a risky repo).
- **P2 — multiplicity + two-sample.** Add Holm correction across a repo's stochastic claims (widen intervals by the family size) in `diff_repo` (`diff.py:233`). For "beats baseline"-style claims, add a permutation/sign-flip test module `core/permtest.py` (per the Bosma/Martinez findings) — only where a paired baseline is captured.
- **Meta-eval instrument.** `spike/optimize/stochastic.py`: synthesize run distributions (Gaussian + heavy-tailed) at controlled offsets from a claim, sweep k and offset, and report **FCR (must be 0)**, **catch-rate on out-of-interval misreports**, **interval coverage** (should ≥ nominal), and a **k-vs-power** curve. Reuse the `optimize/measure.py:score` confusion harness so the FCR guardrail is the same instrument.
- **Tests.** `spike/tests/test_interval.py` and additions to `test_adaptive_k.py`/verdict tests: claim inside interval → `CONFIRMED-STOCHASTIC`; far outside → `REFUTED`; k<k_min → `INCONCLUSIVE`; **fabricated constant** inside a *degenerate* zero-width interval must NOT confirm without value-match; a wide interval from k=2 must NOT confirm.
- **Green gate.** `pytest spike/tests/test_interval.py spike/tests/test_adaptive_k.py` + `optimize/stochastic.py` prints `false_confirm_rate: 0.0` across the whole sweep.

**Effort & dependencies.** **M–L** (statistics + a new positive verdict = highest review bar in this cluster). Depends on Feature 10 to close the "in-interval but hardcoded" residual (they compose). Sequence **third**, and only merge behind a green `optimize/stochastic.py` FCR=0.

---

## Feature 10 — Perturbation fabrication detector

**What & why.** A hardcoded or fabricated number does not move when you corrupt the inputs it was supposedly computed from. Value-matching already catches the case where a fabricated literal *disagrees* with the recompute (→ `INVALIDATED`), but it misses the number that *coincidentally equals* a real computation on the given inputs yet is actually a constant. Perturbation catches it cheaply: corrupt the captured inputs, re-derive, and if the "produced" value is invariant while the trusted oracle moves, the value is not a function of its inputs → fabrication signal. This is a strict **downgrade-only** detector.

**SOTA & best practices (2026).**
- **Metamorphic testing / metamorphic runtime checking** is the canonical oracle-free technique: define a relation between an input transform and the expected output change; a violation reveals a fault without knowing the correct answer. Function-level runtime checking (re-invoke a function in the running program with modified args, compare outputs) catches subtle faults the whole-program oracle misses — https://www.cs.columbia.edu/wp-content/uploads/sites/7/2016/08/crosstalk.pdf ; survey https://dl.acm.org/doi/10.1145/3143561 ; system-level automation + heuristic handling of float noise/non-determinism https://www.cs.columbia.edu/wp-content/uploads/sites/7/2011/03/3479-Murphy-Amsterdam-ISSTA2009.pdf .
- **Mutation/sensitivity framing.** Perturb inputs (mutants); a value that survives *all* mutations unchanged is "equivalent-mutant"-invariant → not computed from them https://doi.org/10.5772/intechopen.1013828 . For metrics, the *sign and rough magnitude* of the expected change is known from the trusted formula (e.g. flipping labels must drop accuracy), giving a strong metamorphic relation.
- **Float-noise discipline.** Metamorphic checks must treat "close enough" as unchanged to avoid false positives from FP reduction order https://www.cs.columbia.edu/wp-content/uploads/sites/7/2011/03/3479-Murphy-Amsterdam-ISSTA2009.pdf — Calma already has `tolerance.close` (`spike/core/tolerance.py:26`) for exactly this. Pitfall: some metrics are *legitimately* insensitive to a specific perturbation (e.g. a small sub-threshold nudge) — so require the *oracle to predict a material move* before expecting the produced value to move, and flag only when oracle-moves-but-produced-doesn't.

**Fit to Calma (FCR=0-safe).** Calma already captures the **raw input arrays** to each metric call (`spike/capture/calma_capture.py::record`, `captured_full`) and independently recomputes via the catalog (`diff.py:153-193`). Two slots: (1) **host-side oracle-differential** (P0) needs no re-execution — perturb the captured `inputs`, recompute the oracle on original vs perturbed; if the oracle moves materially but `produced` equals the *unperturbed* recompute *exactly to full precision* while the number is a suspicious round literal, raise an advisory. (2) **in-sandbox metamorphic shadow-call** (P1) is the real catcher — the targeted-wrap tier (`calma_capture.install_targets`, the repo's OWN metric fn identified by the planner, `planner.py:60-75`) re-invokes the wrapped callable with perturbed args and records `result_perturbed`; host-side we compare the repo function's sensitivity to the oracle's predicted sensitivity. **FCR-safety argument:** the output is only ever a `validity.invalidating` note or an advisory caveat consumed at `verdict.py:76-77` / `pipeline.py` overlay (`pipeline.py:125-161` pattern) — it can **only downgrade** (`CONFIRMED`→`INVALIDATED`, or block a would-be confirm), and it *never* supplies a `recomputed` value or a positive verdict. A false negative (fabrication missed) leaves the pre-existing verdict unchanged — no new confirm created. A false positive downgrades a real number to INVALIDATED (a trust cost, not an FCR breach), so we gate flagging on "oracle predicts a material move AND produced is bit-invariant across ≥2 distinct perturbations." Verdicts affected: adds an `INVALIDATED` path (fabrication) and an advisory caveat; strengthens the fence under Feature 6's `CONFIRMED-STOCHASTIC`.

**Build plan.**
- **P0 — oracle-differential perturbation (host-side, no re-exec).** New `spike/core/perturb.py::perturb_inputs(metric, inputs, kinds=("shuffle_labels","scale","noise","drop_tail"), seed=0)` producing a small deterministic set of corrupted input dicts, and `sensitivity(cid, inputs, kwargs, recompute) -> {oracle_delta, moved}`. In `diff.py` after the recompute block, if the metric is recognized and `produced` matched: compute oracle sensitivity; record `perturb={oracle_delta, ...}` on the record for the report (advisory only in P0).
- **P1 — in-sandbox shadow-recall (the fabrication catcher).** Extend `calma_capture._wrap`/`install_targets` (`spike/capture/calma_capture.py`) with an opt-in `CALMA_PERTURB=1` mode: after the real call is recorded, re-invoke the *same underlying* `orig` with 2 perturbed argument sets (using `perturb.py`'s transforms serialized in), record `{"result_perturbed": [...], "perturb_kind": [...]}` alongside the normal entry (fail-soft — any error → skip, never break the run, same discipline as the existing `except Exception` at the wrap site). Host-side `core/perturb.py::verdict_signal` compares repo Δ vs oracle Δ: oracle material-move but repo Δ≈0 (`tolerance.close`) across all perturbations → `invalidating=["value does not depend on its inputs (invariant under input perturbation) — fabrication/hardcode"]`.
- **P2 — data-level metamorphic re-run.** For claims whose number is a *literal* in results.json (no call to wrap), a `metamorphic` deep-run that corrupts a copy of the input data file and re-runs the entrypoint (`local_runner.run_local` already re-runs k times and accepts `env_extra`, `local_runner.py:30`); if the reported literal is invariant to corrupted data, flag. Expensive → gated to the verify-head from Feature 4 and opt-in.
- **Meta-eval instrument.** `spike/optimize/fabrication.py`: build fixtures where the reported number is (a) genuinely computed, (b) a hardcoded literal equal to the true value, (c) a hardcoded literal off the true value. Report **fabrication catch-rate** (must catch b and c), **false-fabrication-flag rate on genuine metrics** (target 0), and confirm `false_confirm_rate` (measure.py) stays 0. Reuse `optimize/inject.py` claim generation.
- **Tests.** `spike/tests/test_perturb.py`: shuffled-label perturbation drops accuracy in the oracle; a `lambda *a: 0.95` target flagged invariant/INVALIDATED; a real `accuracy_score` NOT flagged; float-noise-only change not mistaken for fabrication (`tolerance.close`); shadow-recall fail-soft on a non-re-callable target.
- **Green gate.** `pytest spike/tests/test_perturb.py` + `optimize/fabrication.py` shows catch b/c, `false_fabrication_flag_rate: 0`, `false_confirm_rate: 0`.

**Effort & dependencies.** **S–M**. P0 is stdlib on top of existing capture; P1 touches the capture shim (careful, fail-soft). Depends on `install_targets`/planner targets being populated (already shipped). Sequence **second** — cheap, composes with and hardens Feature 6.

---

## Feature 11 — Cross-run anomaly detection

**What & why.** Once Calma has verified many runs, a claim that is a wild outlier versus every other *verified* run on the same dataset+metric is suspicious even when it reproduces in isolation (e.g. a mis-split "99% accuracy" on a dataset where honest runs cluster at 80%). Feature 11 builds a reference distribution keyed by (dataset, metric) from prior verified runs and flags robust-outlier claims. It is powerful but **corpus-volume-gated** — useless until enough verified runs exist — so it is a later unlock, and it may only **flag/downgrade**, never confirm.

**SOTA & best practices (2026).**
- **Robust z-score via MAD, not mean/σ.** Modified z-score `M = 0.6745·(x − median)/MAD`, flag `|M| > 3.5`; robust to masking, reliable even with 25–30% contamination — NIST handbook https://itl.nist.gov/div898/handbook/eda/section3/eda35h.htm ; Leys et al. "use MAD not SD"; implementations: PyOD MAD (threshold 3.5) https://pyod.readthedocs.io/en/latest/_modules/pyod/models/mad.html , Apache Beam RobustZScore (median+MAD, SCALE_FACTOR 0.6745) https://beam.apache.org/releases/pydoc/current/apache_beam.ml.anomaly.detectors.robust_zscore.html .
- **Threshold to your error cost, and mind the failure modes.** 3.5 for near-Gaussian, 2.5 for stricter alerting; MAD=0 when >50% of values identical (undefined → must fall back / skip); bimodal reference inflates MAD → missed/false flags; **min ~10–30 samples** for a stable estimate — https://mcpanalytics.ai/articles/z-score-anomaly-detection-practical-guide-for-data-driven-decisions and https://github.com/antonbarr-data/dqt/blob/main/docs/algorithms/mad_outlier_fraction.md . These directly set Calma's `min_n` gate and "no flag when MAD degenerate."
- **Outlier labeling vs accommodation (NIST):** flag for *investigation*, do not auto-delete/auto-judge — an outlier can be a genuine SOTA or scientifically interesting result. This is the whole FCR posture: **flag, never confirm, never auto-refute.** Grubbs/GESD are alternatives when normality holds https://itl.nist.gov/div898/handbook/eda/section3/eda35h.htm . Leaderboard-integrity motivation (retraining variance can invalidate leaderboards) https://proceedings.mlr.press/v227/bosma24a/bosma24a.pdf .

**Fit to Calma (FCR=0-safe).** Slot: a new overlay in `spike/pipeline.py` modeled exactly on `_apply_leakage_overlay` (`pipeline.py:125-161`), which already matches claims to a dataset via `_claim_dataset_tokens` (`pipeline.py:116-122`). A persistent reference store of `(dataset_token, metric) -> [verified values]` is updated only from `CONFIRMED`/`CONFIRMED-STOCHASTIC`/`REPRODUCED-ONLY` runs (never from unverified claims, to avoid poisoning). New `core/anomaly.py::robust_z` computes the modified z against that store. **FCR-safety argument:** the overlay may only (a) attach an advisory caveat "cross-run outlier vs N verified runs (z=…)", or (b) gate an auto-`CONFIRMED` down to a **review/flagged** state — it can **never** raise a verdict, supply a recompute, or by itself emit `CONFIRMED`. Because a genuine SOTA is also an outlier, we do **not** auto-`REFUTED`/`INVALIDATED` on anomaly alone (that would be a *false-refute* risk, and semantically wrong per NIST). It is inert below `min_n` and when MAD is degenerate (fail-open on *flagging*, which is safe since flagging is only advisory). Verdicts affected: adds an advisory annotation and an optional `CONFIRMED`→`FLAGGED-FOR-REVIEW` downgrade; changes no number and creates no confirm.

**Build plan.**
- **P0 — store + detector (stdlib, dark-launched).** New `spike/core/refstore.py` (JSON/SQLite keyed by `(norm_dataset, metric)`, append verified values with run id) and `spike/core/anomaly.py::robust_z(value, ref_values, min_n=15, thresh=3.5)` returning `{z, is_outlier, n, degenerate}` with the MAD=0 / bimodal / small-n guards from the SOTA above. No pipeline wiring yet — populate the store from corpus runs.
- **P1 — advisory overlay.** New `pipeline._apply_anomaly_overlay(records, refstore)` mirroring the leakage overlay (`pipeline.py:125-161`): for each record with a dataset token and `n≥min_n`, attach `validity.advisory += ["cross-run outlier: z=…, N=…"]`. Advisory only — no verdict change in P1. Update the store *after* verdicts are decided (only from verified records).
- **P2 — review gate + dataset conditioning.** Add a config flag `anomaly_gate`: when on, an auto-`CONFIRMED` that is a strong outlier (`|z|>5`) is surfaced as `FLAGGED-FOR-REVIEW` in the UI (still not REFUTED). Condition the reference on split/task tokens (`_claim_dataset_tokens`) to avoid cross-task contamination; segment bimodal references before scoring.
- **Meta-eval instrument.** `spike/optimize/anomaly_eval.py`: seed a reference corpus per (dataset, metric), inject inliers + planted outliers, report **flag precision/recall**, **false-flag rate on inliers**, robustness under 25% contamination, and the hard guardrail: **no injected outlier is ever turned into CONFIRMED** and **no inlier is auto-REFUTED**. Reuse `measure.py` FCR harness.
- **Tests.** `spike/tests/test_anomaly.py`: a 0.99 claim among {0.79,0.81,0.80,…} flagged; `min_n` not met → no flag; MAD=0 reference → no flag, no crash; genuine-SOTA outlier flagged but NOT auto-refuted/auto-confirmed; store only ingests verified values.
- **Green gate.** `pytest spike/tests/test_anomaly.py` + `optimize/anomaly_eval.py` shows `false_confirm_rate: 0`, `auto_refute_rate: 0`, flag-precision above threshold.

**Effort & dependencies.** **M**, but **corpus-volume-gated** — low value until the verified-run store is large, so ship P0 dark early and turn on the overlay later. Depends on Features 4 (clean dataset attribution on the head) and 6/10 (more runs actually reach a verified state to feed the store). Sequence **last**.

---

### Cluster throughline
1. All four hold **FCR=0** by construction: 4 only *identifies* (never calls `verdict.decide`), 10 and 11 only *downgrade/flag* (never supply a recompute or a confirm), and 6 — the sole new positive path — is fenced behind a distinct `CONFIRMED-STOCHASTIC` label, per-run recompute, conservative prediction intervals, a k_min power gate, and multiplicity correction.
2. They plug into **existing slots** with minimal surface: `discover→classifier` (`pipeline.py:446`), `diff.produced_each→interval` (`diff.py:199`), `capture-target→shadow-recall` (`calma_capture.install_targets`), and a leakage-style `validity` overlay (`pipeline.py:125`).
3. Each targets a distinct gap: 4 fixes the "2,397 claims → found nothing" legibility failure; 6 unlocks the unseeded-DL dead-end; 10 catches hardcoding that value-matching structurally misses; 11 is the corpus-gated integrity layer.
4. They **compose**: 4 makes the head legible so 6/10/11 spend runs on real headlines; 10 closes 6's "in-interval but fabricated" residual; 11 feeds on the verified runs 6/10 produce.
5. Recommended order — **4 (pure win, unblocks all) → 10 (cheap, hardens 6) → 6 (medium-hard, highest review bar, merge only behind a green FCR=0 meta-eval) → 11 (dark-launch P0 now, enable when the verified-run corpus is large)**.


# Cluster D — Trust & Auditability of Verdicts (Features 3, 12, 16, 18)

> Scope: make Calma's *neutral-third-party* standing **checkable**, not just assertable. These four features
> sit strictly *downstream* of the verdict decision (`spike/core/verdict.py:decide` → `spike/pipeline.py`).
> None of them touch verdict logic; each is a serialization / attestation / registry layer over an
> **already-decided** verdict record. The sacred invariant (**FCR=0**) is preserved by a single rule applied
> throughout: *signing/logging is fail-OPEN (an outage yields an unsigned-but-well-formed record, never a
> blocked or altered verdict), while verification is fail-CLOSED (an invalid signature or missing inclusion
> proof must never be rendered as CONFIRMED).*
>
> Verdict-record shape being signed/hashed (read before building): the per-claim record is built by
> `_claim_out` (`spike/pipeline.py:71-88`) — `{id, metric, claimed, context, location, source, confidence,
> verdict, reason, diff, provenance, validity}`, augmented with `determinism`, `scope_options`, `convention`
> in `_diff_claims` (`spike/pipeline.py:346-360`); the decision primitive is `verdict.decide()` returning
> `{verdict, reason, confidence, diff, caveats}` (`spike/core/verdict.py:33-116`, `out()` at `:46-48`); the
> job-level envelope is `verify_repo`'s return `{status, repo_dir, run, claims, counts, n_claims, leakage,
> trace}` (`spike/pipeline.py:490-500`). `POSITIVE = (CONFIRMED,)` (`spike/core/verdict.py:30`) is the exact
> set a false attestation must never mislabel.

---

## Feature 3 — Signed attestations (ed25519 / KMS-signed verdicts)

**What & why.** Turn "Calma says CONFIRMED — trust us" into "here is a signed statement anyone can verify
offline against our published key." A verdict signed by a Calma-controlled key is the concrete artifact of the
neutral-third-party moat: a buyer, an auditor, or a downstream CI gate can check the signature without trusting
the API at fetch time. This is the "SOC-2-for-numbers" differentiator, and the legacy engine already ships a
production-shaped DSSE/ed25519/KMS implementation to **lift** rather than rebuild.

**SOTA & best practices (2026).**
- **Wrap the verdict as a DSSE-signed in-toto Statement.** The modern envelope is DSSE (Dead Simple Signing
  Envelope): a `payloadType`, base64 `payload`, and `signatures[]`, where the signed bytes are a
  Pre-Authentication Encoding (PAE), not the raw payload — this closes the ambiguity attacks that plagued
  earlier formats (https://github.com/secure-systems-lab/dsse/blob/master/envelope.md,
  https://safeguard.sh/resources/blog/in-toto-attestation-framework-walkthrough-2026). The payload is an
  in-toto Statement v1 (`_type: https://in-toto.io/Statement/v1`, a `subject[]` of `{name, digest}`, a
  `predicateType`, and a `predicate`) (https://github.com/in-toto/attestation/blob/main/spec/v1/envelope.md).
- **Calma's verdict is *exactly* a Verification Summary Attestation (VSA).** SLSA's VSA predicate
  (`predicateType: https://slsa.dev/verification_summary/v1`) is defined as "some entity (`verifier`) verified
  one or more artifacts by evaluating them against some `policy`," with fields `verifier.id`, `timeVerified`,
  `resourceUri`, `policy{uri,digest}`, `inputAttestations[]`, `verificationResult: PASSED|FAILED`,
  `verifiedLevels[]` (https://slsa.dev/spec/v1.1/verification_summary). This is Calma's shape almost 1:1:
  *verifier=Calma, resourceUri=repo@sha, policy=the FCR=0 verdict rules, verificationResult=CONFIRMED→PASSED.*
  Recommended: emit a **custom predicate** `https://schemas.trycalma.ai/verdict/v1` that carries the full
  seven-value verdict record (VSA `verificationResult` is binary; Calma has CONFIRMED/REFUTED/INVALIDATED/…),
  and *also* set the standard VSA fields for interop (`verificationResult=PASSED` iff verdict∈POSITIVE, else
  `FAILED` with the real verdict in `verifiedLevels`). Producers MAY add extension fields with URI names and
  consumers MUST ignore unrecognized fields, so this is spec-legal
  (https://slsa.dev/spec/v1.1/verification_summary parsing rules).
- **`cosign attest-blob` signs arbitrary predicates over a blob/digest** (not just container images), and as of
  July 2025 accepts a full in-toto Statement via `--statement` and verifies by `--digest` alone
  (https://github.com/sigstore/cosign/pull/4306, https://docs.sigstore.dev/cosign/verifying/attestation/) —
  the exact ergonomics for signing a verdict-over-a-receipt that isn't a file on disk.
- **Keyless (Sigstore/Fulcio) vs long-lived KMS — pick per trust model.** Keyless: Fulcio issues a short-lived
  cert binding an ephemeral in-memory key to an OIDC identity, the key is destroyed after signing, and the
  event is logged to Rekor; verifiers map *identities* to artifacts, eliminating key-management and revocation
  (https://docs.sigstore.dev/cosign/signing/overview/, https://docs.sigstore.dev/about/security/). **Pitfall
  for Calma:** keyless is optimized for CI identities, not for a *standing corporate authority* whose whole
  value is a stable, pinnable public key — a rotating ephemeral identity is the wrong primitive for "the Calma
  key." Long-lived KMS (AWS/GCP/Azure, `awskms://…`) keeps a **non-exportable** private key in an HSM; cosign
  and raw signing both support it (https://docs.sigstore.dev/cosign/key_management/overview/). **Recommended:**
  a long-lived, non-exportable **KMS ECDSA-P256** key as the Calma root of trust (auditors pin one published
  key), with ed25519 as the low-friction default for dev/self-host. P256 is also the empirically safe KMS
  choice — a self-hoster found "P256 was the only EC KMS-backed checkpoint-signing option that verified
  end-to-end… Ed25519 via KMS loaded but failed to hash for note signing"
  (https://linnemanlabs.com/posts/self-hosted-sigstore-transparency-infrastructure/).
- **Pitfalls:** never trust a key embedded in the envelope (pin out-of-band); the `keyid` only *selects* a key;
  DSSE supports multiple signatures (a Sigstore *bundle* is technically not ITE-5 compliant because it allows
  only one — relevant if you later dual-sign KMS+keyless)
  (https://github.com/in-toto/attestation/blob/main/spec/v1/envelope.md).

**Fit to Calma (FCR=0-safe).** Signing is a pure post-processing step on a decided verdict — it reads the
record, never writes back into `decide()`.
- **Subject** = the reproducibility receipt (Feature 18) digest: `subject[0] = {name: "<repo>@<sha>#<metric>",
  digest: {sha256: <receipt-hash>}}`. The receipt content-addresses inputs+env+code+outputs (see #18), so the
  signature commits to *what was verified*, not just the verdict string.
- **Predicate** = the per-claim record from `_claim_out` (`spike/pipeline.py:71-88`) plus the job `run` block
  (`spike/pipeline.py:442-443`), the `validity` overlay (`:349`, `:483`), and `determinism` (`:353-354`).
- **Where in the pipeline:** attestation is emitted at the terminal `done` stage — after `_apply_leakage_overlay`
  (`spike/pipeline.py:483`) and `counts` (`:485-487`), immediately before the `verify_repo` return
  (`:490-500`); or one layer out, in `server.run_job` right after `_set(job, status="done", …)`
  (`spike/server.py:175-177`). Signing MUST be wrapped so any signer error yields `signatures: []` (unsigned
  but well-formed) exactly as the legacy `sign_envelope` already does
  (`legacy/control_plane/api/signing.py:104-109`) — an HSM/KMS outage can never block or change a verdict
  (fail-open). Verification is fail-closed: `verify_proof` returns exit 2 on unsigned/invalid and only prints
  the verdict on a valid signature (`legacy/control_plane/verify_proof.py:55-92`).

**Build plan.**
- **P0 — lift + wire (the fast win).** Copy `legacy/control_plane/api/signing.py` → `spike/attest/signing.py`
  verbatim (it already implements DSSE PAE `:37-38`, canonical JSON `:41-43`, `key_id` `:46-47`,
  ed25519 env-seed *and* KMS ECDSA-P256 `sign_envelope` `:92-109`, `verify_envelope` `:112-133`,
  `public_key_info` `:78-89`) and `legacy/control_plane/verify_proof.py` → `spike/attest/verify_verdict.py`.
  Add `spike/attest/statement.py:build_statement(record, receipt_digest, repo_uri)` that emits the in-toto
  Statement v1 with the custom `verdict/v1` predicate + VSA-compatible fields. New endpoint
  `GET /api/jobs/{id}/attestation` (token-gated like the rest, `spike/server.py:66-68`) returns the DSSE
  envelope; `GET /api/signing-key` publishes `public_key_info()`. Commit `spike/attest/signing_pubkey.json`
  (pinned `trusted[]` = current KMS + retired ed25519), mirroring the legacy pin file.
- **Schema to sign** (`predicate`):
  ```
  {"_type":"https://in-toto.io/Statement/v1",
   "subject":[{"name":"<owner/repo>@<sha>#<metric>","digest":{"sha256":"<receipt-hash>"}}],
   "predicateType":"https://schemas.trycalma.ai/verdict/v1",
   "predicate":{
     "verifier":{"id":"https://trycalma.ai","version":{"engine":"<git-sha>","catalog":"<hash>"}},
     "timeVerified":"<iso8601>", "resourceUri":"git+https://github.com/<owner/repo>@<sha>",
     "policy":{"uri":"https://trycalma.ai/policy/fcr0","digest":{"sha256":"<policy-hash>"}},
     "verificationResult":"PASSED|FAILED",          // PASSED iff verdict in POSITIVE
     "verifiedLevels":["CALMA_<VERDICT>"],           // the real 7-value verdict
     "calmaVerdict":{...full _claim_out record incl diff/validity/determinism...},
     "run":{...job run block...}}}
  ```
- **P1 — KMS + provenance links.** Provision the non-exportable KMS P256 key (`CALMA_KMS_KEY_ARN`), set VSA
  `inputAttestations[]` to the receipt + any committed-artifact digests, and record the exact recompute
  provenance (`record["provenance"]`, `spike/pipeline.py:79`, e.g. `artifact:recipe`) so the attestation says
  *how* the number was independently recomputed.
- **P2 — optional keyless / `cosign attest-blob` path.** For customers who want ecosystem-native verification,
  offer `cosign attest-blob --statement --type https://schemas.trycalma.ai/verdict/v1` over the receipt digest
  (https://github.com/sigstore/cosign/pull/4306); this is the on-ramp to Feature 12 (Rekor).
- **Tests / green gate:** round-trip `sign_envelope→verify_envelope` for ed25519 and KMS (mock boto3);
  tamper-a-byte → verify fails; unsigned envelope → `verify_verdict` exits 2 (fail-closed);
  a CONFIRMED verdict's `verificationResult=="PASSED"` and a REFUTED's `=="FAILED"` with correct
  `verifiedLevels`; **firewall test**: importing `spike/attest/*` must not change any verdict in the existing
  `spike/tests/test_pipeline.py` suite (attestation is inert w.r.t. `decide()`). Green = full `pytest spike/`
  unchanged verdict counts + new `test_attest.py` passing.

**Effort & dependencies.** **T-shirt: S–M** (mostly a lift). Deps: `cryptography` (already used by legacy),
optional `boto3` for KMS. Sequencing: **build first** — Features 12/16/18 all reference the attestation as the
thing that gets logged / carries the dataset digest / signs the receipt.

---

## Feature 12 — Append-only transparency log (Rekor-style)

**What & why.** A public, immutable, tamper-evident ledger of verdicts. It upgrades Feature 3 from "you can
verify a signature *if Calma hands you the envelope*" to "Calma *cannot* silently un-issue, backdate, or
rewrite a verdict, and third parties can prove the log is append-only." This is the strongest form of neutral
standing — but it only earns its keep at verdict *volume*, so it's sequenced after #3.

**SOTA & best practices (2026).**
- **The primitive is a Merkle-tree verifiable log (RFC 6962 lineage).** Every verdict becomes a leaf; leaf
  hashes percolate to a signed tree head (STH/checkpoint). Consumers get an **inclusion proof** (sibling hashes
  that recompute the root, proving a verdict is in the log) and a **consistency proof** (proving tree version N
  is a strict append-only extension of version M) (https://transparency.dev/verifiable-data-structures/,
  https://google.github.io/trillian/docs/TransparentLogging.html). Critically: "logs are tamper-**evident** but
  not tamper-**proof**" — the guarantee only materializes if clients keep historical tree heads and *someone
  monitors* (https://github.com/sigstore/rekor-monitor).
- **Three build options.**
  1. **Use the public Rekor good instance** (`rekor.sigstore.dev`, 99.5% SLO, GA since 2022). Cheapest,
     instantly public, no ops. Constraints: **100 KB** entry size cap and rate limits — high-volume single-source
     pipelines hit them (https://github.com/sigstore/rekor/blob/main/README.md,
     https://safeguard.sh/resources/blog/sigstore-rekor-transparency-log-operations). Note Rekor **v1 is in
     maintenance**; build against **v2 (`rekor-tiles`)**, which shards by year and is the GA path
     (https://aevum.build/adrs/adr-007-transparency-log/).
  2. **Run your own Rekor/Trillian.** Rekor stores entries in a Trillian-backed Merkle tree; the Helm chart
     pulls Trillian + MySQL + the Rekor server, and a separate **log-signer** batches leaves and issues STHs
     (single-signer election via etcd) (https://safeguard.sh/resources/blog/sigstore-rekor-transparency-log-operations,
     https://github.com/google/certificate-transparency-go/blob/master/trillian/docs/ManualDeployment.md).
     Trillian is "General Transparency… an implementation of the Verifiable Data Structures white paper"
     (https://google.github.io/trillian/). Gives data-residency, no rate limits, and policy isolation — at real
     operational cost (the *instance key* becomes a trust root every consumer must pin).
  3. **Merkle-log-as-a-service / thin self-hosted checkpointing.** Publish your own signed checkpoints on a
     schedule and optionally *anchor* them into public Rekor (`hashedrekord` of the terminal
     `(sequence, prior_hash, key_id, time)`), storing the returned inclusion proof locally — external
     verification without putting Rekor on your write path (https://aevum.build/adrs/adr-007-transparency-log/).
- **Do NOT block the write path on the log** (the FCR-adjacent operational rule). The recommended pattern is
  *don't* submit every event synchronously (adds 50–500 ms and makes log availability a hard dependency);
  instead buffer + retry, or anchor periodic checkpoints (https://aevum.build/adrs/adr-007-transparency-log/).
- **Monitoring is mandatory, not optional.** `rekor-monitor` verifies consistency between saved checkpoints and
  watches for unexpected uses of your identity; run it hourly, expose Prometheus metrics, alert on a failed
  consistency check (https://blog.sigstore.dev/using-rekor-monitor/,
  https://www.redhat.com/en/blog/guide-rekor-monitor-and-its-integration-red-hat-trusted-artifact-signer). As
  of Dec 2025 it supports Rekor v2 + TUF and is "getting ready for production use"
  (https://openssf.org/blog/2025/12/19/catching-malicious-package-releases-using-a-transparency-log/).

**Fit to Calma (FCR=0-safe).** The leaf is the Feature-3 DSSE envelope (or its digest). Logging happens *after*
`done` (`spike/pipeline.py:489`) / after `_set(job, status="done", …)` (`spike/server.py:175-177`), off the
critical path, buffered. The verdict is fully valid whether or not it's logged yet; the log adds *non-repudiation*
over time, it is not a gate. Fail-open on submit (retry queue; a log outage never fails a job — mirror the
`sign_envelope` unsigned-fallback discipline at `legacy/control_plane/api/signing.py:104-109`). Fail-closed on
**verification**: a presented "logged verdict" whose inclusion proof does not replay to a checkpoint-signed root
MUST NOT be shown as CONFIRMED (same posture as `verify_proof` exit-2, `legacy/control_plane/verify_proof.py:90-92`).

**Build plan.**
- **P0 — anchor to public Rekor v2.** New `spike/attest/tlog.py:submit(envelope)` that hashes the DSSE envelope
  and writes a `hashedrekord` to public Rekor v2; store `{log_index, inclusion_proof, checkpoint}` on the job
  (`spike/server.py` job dict). New `GET /api/jobs/{id}/inclusion-proof`. Because Calma envelopes may exceed the
  **100 KB** public cap, log the *digest of the receipt*, not the receipt — keeps entries tiny.
- **P1 — self-checkpointing ledger + monitor.** Maintain a local append-only table of `(verdict_id, envelope_sha,
  prev_hash)`; on a schedule sign a checkpoint (reuse the KMS P256 key from #3, the empirically verified
  KMS-note choice, https://linnemanlabs.com/posts/self-hosted-sigstore-transparency-infrastructure/) and anchor
  it into Rekor. Stand up `rekor-monitor` (hourly, Prometheus alert on consistency failure).
- **P2 — own Trillian/Rekor (only if residency/volume demands).** Deploy Rekor v2 + Trillian + MySQL via Helm;
  publish the instance public key in the pinned trust file; document v1→v2 (never build on v1).
- **Verdict-record schema logged:** `{leaf: sha256(dsse_envelope), verdict_id, repo_uri, metric, verdict,
  time}` (tiny leaf; the full envelope stays retrievable via `GET /api/jobs/{id}/attestation`).
- **Tests / green gate:** inclusion-proof replay recomputes the checkpoint root; a mutated leaf fails the proof;
  consistency proof between two checkpoints holds; **the write path passes with the tlog stubbed to raise** (a
  simulated Rekor outage must produce a normal `done` job, proving fail-open). Green = `pytest spike/` verdict
  counts unchanged + `test_tlog.py`.

**Effort & dependencies.** **T-shirt: M (P0) → L (P2 self-host).** Deps: a Rekor v2 HTTP client (no official
Python client — implement HTTP calls per the ADR, https://aevum.build/adrs/adr-007-transparency-log/); P2 adds
Trillian+MySQL+Helm ops. Sequencing: **after #3** (needs the signed envelope) and gated on real verdict volume.

---

## Feature 16 — Content-addressed dataset registry

**What & why.** Hash the data so you catch the "quietly used a different data version" trick — a repo whose
number is real *for a dataset that isn't the one it claims*. Narrower than the signing features but directly
plugs an FCR-adjacent gap: today Calma binds a claim to a captured computation, but the *identity of the data
fed to that computation* isn't a first-class, attestable field. Making the dataset a content hash turns
"dataset=X" from a label into a checkable commitment, and gives Feature 3's attestation a binding key.

**SOTA & best practices (2026).**
- **The field-tested pattern is a content-addressable pointer.** DVC stores the data outside git and commits a
  tiny `.dvc` YAML pointer holding the content hash (`md5`), size, and path; identical files dedupe
  automatically (https://kindatechnical.com/mlops-guide/data-versioning-with-dvc-and-lakefs.html,
  https://dibi8.com/resources/data-science/data-version-control-dvc-lakefs-delta-lake/). Git-LFS is the
  lighter, less-featured ancestor (content-addressed blobs by hash, no dataset-diffing); lakeFS is the
  heavyweight (git-like zero-copy branches over S3 via prolly trees, for petabyte lakes)
  (https://lakefs.io/blog/dvc-vs-git-vs-dolt-vs-lakefs/). **For Calma, DVC-style per-file content hashing is
  the right altitude** — Calma verifies repos it doesn't own, so it should *read* whatever pointer/hash the
  repo already has, and independently *recompute* a hash of the bytes the run actually consumed.
- **Croissant is the interop standard for external/ML datasets and already carries a checksum.** MLCommons
  Croissant (schema.org-based, `conformsTo: http://mlcommons.org/croissant/1.0`) gives each `FileObject` a
  `sha256` (https://docs.mlcommons.org/croissant/docs/croissant-spec.html,
  https://mlcommons.org/working-groups/data/croissant/). 700k+ datasets on HuggingFace/Kaggle/OpenML publish
  Croissant, so for repos that pull a known dataset, Calma can cross-check the consumed bytes against the
  published `sha256` — catching a swapped data version *by standard*.
- **For large data, use a Merkle/CID over content-defined chunks.** A CID is a self-describing
  `(content-type, multihash)` built over a Merkle DAG; large files are chunked and linked
  (https://docs.ipfs.tech/concepts/content-addressing/, https://github.com/multiformats/cid). FastCDC is the
  fast content-defined chunker (Gear-hash rolling, ~10× faster than Rabin) for dedup-friendly chunking
  (https://www.usenix.org/system/files/conference/atc16/atc16-paper-xia.pdf). **Critical pitfall — determinism:**
  "two identical files can produce different CIDs" depending on chunk size, DAG layout, codec, and hash; only a
  fixed **CID profile** (or a plain canonical `sha256` for smaller data) gives cross-tool-reproducible digests
  (https://docs.ipfs.tech/concepts/content-addressing/). Calma should **default to a plain sha256 over
  canonicalized bytes** and reserve Merkle/CDC for genuinely large corpora, always with pinned parameters.

**Fit to Calma (FCR=0-safe).** Calma already has the data in hand at three points — hash it there, add it as a
*field*, never as a verdict gate:
- **Captured evaluation inputs** already flow to `CALMA_CAPTURE_OUT` as JSONL with the actual arrays
  (`y_true`, `y_pred`, `y_score`) and `n` (`spike/capture/calma_capture.py:154-182`, `_emit` `:195-203`). A
  canonical sha256 of those inputs is the **evaluation-input digest** — the data the number was actually
  computed on.
- **Committed prediction files** are located by `A.find_prediction_files` inside `_artifact_verify`
  (`spike/pipeline.py:301`); **committed train/test splits** by `LEAK.from_committed_splits`
  (`spike/pipeline.py:455`). Hash each → dataset/artifact digests.
- The digest becomes (a) a field on `_claim_out` (extend the record at `spike/pipeline.py:71-88`, e.g.
  `data_digest`), (b) part of the Feature-18 receipt subject, and (c) a **binding key**: two claims for the same
  metric on *different* `data_digest`s are distinct computations, and a claim labeled `dataset=X`
  (`_claim_dataset_tokens`, `spike/pipeline.py:116-122`) whose consumed-bytes digest doesn't match X's published
  Croissant `sha256` is *surfaced* — as an advisory/validity note, **not** an auto-CONFIRM downgrade path (the
  hash mismatch is evidence, and it must never let a mismatched dataset *upgrade* a verdict). FCR=0 posture:
  adding a hash can only ever add information or a validity caveat; it can never flip an INCONCLUSIVE/REFUTED to
  CONFIRMED.

**Build plan.**
- **P0 — hash what we already capture.** New `spike/core/datahash.py:canonical_sha256(inputs)` and
  `file_sha256(path)`. In `_diff_claims` (`spike/pipeline.py:329-361`) attach `data_digest` (from the bound
  capture's inputs) to each record; in `_artifact_verify` (`:296-326`) attach the prediction-file digest.
- **P1 — cross-check external datasets via Croissant.** If the repo references a known dataset (or ships
  `croissant.json`), compare the consumed-bytes digest to the published `FileObject.sha256`; on mismatch add a
  `validity.advisory` note ("consumed data digest ≠ declared dataset X"). Read a repo's existing `.dvc`
  pointer md5 when present (no recompute needed).
- **P2 — Merkle/CID for large corpora.** Add a pinned-parameter FastCDC + directory-Merkle-root path
  (opt-in, size-gated) so multi-GB datasets get a stable content address without full re-read cost.
- **Schema added to the signed record:** `"data": {"digest":"sha256:…","n":<int>,"source":"captured|artifact|
  split|croissant","declared":"<dataset-name>","matches_declared":true|false|null}` — folded into the receipt
  (#18) and thus into the attestation (#3).
- **Tests / green gate:** same inputs → identical digest (determinism); a one-element perturbation → different
  digest; a `dataset=X` claim whose bytes mismatch X's `sha256` produces an advisory but the *verdict is
  unchanged* (FCR=0 proof); large-file CDC digest is stable across two runs with pinned params. Green =
  `pytest spike/` counts unchanged + `test_datahash.py`.

**Effort & dependencies.** **T-shirt: S (P0/P1) → M (P2 CDC).** Deps: stdlib `hashlib` only for P0/P1; optional
`fastcdc` for P2. Sequencing: independent of #3/#12 but **most valuable feeding #18/#3** (the digest is a
receipt field and a binding key); do P0 alongside #18.

---

## Feature 18 — Reproducibility receipts

**What & why.** Content-address the *whole run* — inputs + environment + code + outputs — into one canonical
receipt. On its own it's an audit/caching artifact; in this cluster it is best positioned as **the payload that
Feature 3 signs**: the receipt is the in-toto `subject` (its hash) and its body is the `resolvedDependencies` /
run-context the attestation commits to. Once signing exists, the receipt is what gives the signature *meaning*
("signed over *this* reproducible run"), so #18 is largely subsumed by #3 as its content layer.

**SOTA & best practices (2026).**
- **Split the receipt into a deterministic *claim* and a machine-dependent *measurement* block.** The cleanest
  modern design (rosalind-receipt) hashes only the claim — tool version, subcommand, **content hashes of inputs
  + outputs**, params, and build identity (git sha, toolchain, dep-lock hash) — as canonical JSON (sorted keys,
  no timestamps), so "two identical runs produce a byte-identical manifest," while peak-RSS/wall-time live in a
  separately-hashed measurement block that "no longer perturbs" the claim hash
  (https://docs.rs/rosalind-receipt/latest/rosalind_receipt/index.html,
  https://docs.rs/rosalind-receipt/latest/rosalind_receipt/struct.RunManifest.html). The claim's content-address
  is *path-independent* (hash the bytes, drop paths) so the same data at a different path hashes identically.
- **A run manifest binds code+env+data+determinism in one file.** reprokit-ml's manifest ties
  `code{git commit, dirty}` + `environment{python, platform, gpus, requirements.lock}` +
  `data{merkle_root}` + `determinism{seed, PYTHONHASHSEED, torch/tf/jax}` + `config{hashes}`
  (https://github.com/abdulvahapmutlu/reprokit-ml); oxo-flow computes a composite "workflow fingerprint" over
  SHA-256 of workflow file + input data + resolved env + params, and re-runs only tasks whose fingerprint
  changed (https://github.com/Traitome/oxo-flow/blob/main/REPRODUCIBILITY.md). Content-addressed hermetic build
  fabrics (obelisk) key their cache on `canonical action spec + input hashes + toolchain hashes + declared env +
  platform fingerprint` (https://github.com/staticpayload/obelisk.build) — the same recipe Calma needs for a
  "have I verified this exact run before?" cache.
- **RO-Crate / Workflow Run RO-Crate is the archival provenance standard.** WRROC (an RO-Crate + schema.org
  extension aligned to W3C PROV) bundles inputs, outputs, code, and the run's actions
  (`CreateAction{instrument, object, result}`) into a self-contained `ro-crate-metadata.json`, implemented by
  six+ workflow engines and re-executable via `runcrate`
  (https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0309210,
  https://www.researchobject.org/workflow-run-crate/; RO-Crate 1.2 adds a "detached crate" for API use,
  https://galaxyproject.org/news/2025-06-04-ro-crate-1.2-release/). Nextflow's `nf-prov` plugin emits WRROC/BCO
  with zero pipeline changes, and Nextflow itself already "assigns each task a unique identity based on a hash
  of its inputs and script" (https://github.com/nextflow-io/nf-prov,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC12309086/). **For Calma, emit a lightweight JSON receipt as the
  signed payload, and offer a WRROC export as the interop/archival format** — don't make the science-heavy
  crate the internal primitive.
- **Pitfall:** timestamps, absolute paths, and measured cost inside the hashed claim destroy reproducibility —
  keep them out of the claim (rosalind-receipt's claim/measurement split is the discipline).

**Fit to Calma (FCR=0-safe).** Calma already computes every ingredient; the receipt is assembly + hashing, no
new verdict influence:
- **inputs** = captured evaluation inputs digest + committed data/split digests (Feature 16;
  `spike/capture/calma_capture.py:195-203`, `spike/pipeline.py:301`,`:455`).
- **env** = the static determinism analysis (`DET.analyze`, consumed at `spike/pipeline.py:412`, surfaced as
  `record["determinism"]` `:353-354`) + resolved deps/venv note (`build.ensure_venv`, `spike/pipeline.py:273`)
  + declared Python (`build.detect_python_version`, `:216`) + sandbox cost telemetry as a *measurement* block
  (`run_result["cost"]`, `spike/pipeline.py:438-441`).
- **code** = repo commit SHA (repos are already pinned by SHA in `spike/repos.yaml`).
- **outputs** = the three-way diff `{claimed, produced, recomputed}` and the verdict
  (`spike/core/verdict.py:42-44`, `_claim_out` `:71-88`).
- **Where:** build the receipt at the `done` stage (`spike/pipeline.py:489`) from the already-assembled
  `records` + `job_run`; its sha256 is the `subject.digest` handed to Feature 3. Splitting claim vs measurement
  guarantees the *signed* subject digest is stable across re-verifications of the same run (a re-run with
  identical inputs yields the same receipt hash → the attestation is idempotent), which is exactly what makes a
  transparency-log dedupe (Feature 12) meaningful. The receipt never feeds `decide()`; it's a serialization of
  its output.

**Build plan.**
- **P0 — the canonical claim receipt.** New `spike/attest/receipt.py:build_receipt(records, job_run, repo_meta)`
  producing `{schema, claim:{repo_sha, entry, inputs[], outputs[], params, env{python, deps_lock_sha,
  determinism}}, measurement:{sandbox_seconds, k, …}}` as canonical JSON (sorted keys, **no timestamps in
  claim**), with `receipt_sha256 = sha256(claim_canonical_json)`. Return it in `verify_repo`'s dict
  (`spike/pipeline.py:490-500`) and store on the job (`spike/server.py:175-177`); expose
  `GET /api/jobs/{id}/receipt`.
- **P1 — make it the #3 subject + a `reproduce` verifier.** Feed `receipt_sha256` as `subject[0].digest` in the
  attestation; add `spike/attest/verify_receipt.py` that re-hashes recorded input digests and re-checks the
  claim self-hash (à la rosalind-receipt `verify_receipt`), and a `code_git_sha` check against `repos.yaml`.
- **P2 — WRROC export.** `spike/attest/wrroc.py:to_rocrate(receipt)` emitting a detached
  `ro-crate-metadata.json` (Process/Workflow Run profile) for archival/interop
  (https://www.researchobject.org/workflow-run-crate/).
- **Schema signed (the payload #3 wraps):** the P0 receipt object above; the attestation's `subject.digest.sha256
  = receipt_sha256`, and `predicate.calmaVerdict` carries the human-facing verdict.
- **Tests / green gate:** same run → identical `receipt_sha256` (determinism, claim-only); a changed input digest
  → different receipt hash; measured cost changes do **not** change the claim hash (claim/measurement split
  proof); receipt round-trips through `verify_receipt`; WRROC output validates against RO-Crate context.
  **FCR=0 firewall:** building/verifying a receipt over the existing `spike/tests/test_pipeline.py` fixtures
  leaves every verdict count unchanged. Green = `pytest spike/` unchanged + `test_receipt.py`.

**Effort & dependencies.** **T-shirt: S–M.** Deps: stdlib `hashlib`/`json` for P0/P1; P2 WRROC is additive
(schema.org JSON-LD, no runtime dep). Sequencing: **build with Feature 16** (the receipt consumes the data
digests) and **immediately before / interleaved with Feature 3** (the receipt *is* what #3 signs).

---

### Cluster throughline (5 lines)
1. One spine, four layers: **hash the data (#16) → assemble a reproducible receipt (#18) → sign it (#3) → log it (#12)** — each strictly downstream of `verdict.decide()`.
2. Calma's verdict *is* a SLSA Verification Summary Attestation; adopt VSA-compatible in-toto/DSSE and **lift** the legacy ed25519+KMS signer (`legacy/control_plane/api/signing.py`) rather than rebuild.
3. FCR=0 is preserved by one rule everywhere: **fail-open on produce** (an unsigned/unlogged but well-formed record) and **fail-closed on verify** (an invalid signature/proof is never CONFIRMED); none of these features write back into the decision.
4. Sequence by leverage and volume: #16+#18 first (cheap, stdlib, they build the payload), #3 next (the moat made checkable), #12 last (network-effect ledger, only worth it at verdict volume).
5. Net effect: "trust me" becomes "verify it" — a pinnable Calma key over a content-addressed, tamper-evident run, which is the concrete asset behind neutral third-party standing.


# Cluster E — Hardening & Distribution: 4 build-plan sections

Positioned against the **sacred invariant FCR=0** (false-CONFIRM rate zero). Every feature below either *hardens* the invariant (8, 9), *compounds* it without weakening it (5), or *distributes proof of it* (13). Code anchors are grounded in the actual spike (`/Users/rikhinkavuru/calma/spike/`). `verdict.POSITIVE = (CONFIRMED,)` (`spike/core/verdict.py:30`) is the single definition of "a confirm," and every feature is expressed relative to it.

---

## Feature 8 — Red-team-the-confirm

**What & why.** Today `spike/optimize/redteam.py` is an *offline* meta-eval: it constructs 8 adversarial captures and asserts none reaches CONFIRMED (`adversarial_fcr == 0`). This feature promotes that gate *inline*: after the pipeline emits a CONFIRMED for a real claim, an adversarial pass re-attacks that specific captured computation and can **only downgrade** the verdict, never upgrade it. It turns FCR=0 from a property we *test in a lab* into a property the *production path actively re-earns on every confirm* — cheaply, because the deterministic re-checks are pure functions of already-captured data.

**SOTA & best practices (2026).**
- **Structural role-separation beats self-grading.** SetupX's Prosecutor–Judge pipeline "structurally separates configuration and verification roles, preventing self-confirmation bias" — Prosecutor gathers evidence, Judge renders a *binary* verdict from that evidence, never from the actor's own claim of success (https://github.com/OpenDataBox/SetupX/blob/main/README.md). Mirror this: the confirming path is the "defendant," the red-team pass is the "prosecutor," and the *deterministic re-check* is the judge.
- **LLM self-verification is not sound — it produces false positives.** Systematic study finds LLM self-critique loops often perform *worse* than not critiquing, and only an *external sound verifier* reliably prevents false accepts (https://openreview.net/pdf?id=4O0v4s3IzY). Verifiers "have their limitations, potentially producing false positives" and post-training can *raise* FPR (https://www.arxiv.org/pdf/2512.02304). **Design consequence: the LLM may only *propose a probe / file a charge*; a deterministic re-check disposes. The model can never itself flip a verdict to or keep it at CONFIRMED.**
- **Make the verifier "think differently" from the producer.** Solution-distribution similarity between solver and verifier *increases* false positives (https://www.arxiv.org/pdf/2512.02304, §5.3). Calma's independent recompute already satisfies this; the red-team pass should attack via *transformations of the inputs* (single-class, trivial-baseline, perturbation) rather than re-asking the same model.
- **Adversarial self-play as attack generation.** SPC evolves a "sneaky generator" vs a critic via adversarial games, improving error detection 70.8%→77.7% (https://arxiv.org/pdf/2504.19162); Mirror-Critique adds *selective abstention* — abstain rather than accept when critiques disagree (https://arxiv.org/html/2509.23152). Calma's analogue: attacks are the sneaky generator; *any* successful attack forces abstention (downgrade), never acceptance.
- **LLM-as-judge is intra-rater unstable.** Judges give inconsistent scores across identical runs (https://doi.org/10.18653/v1/2025.findings-emnlp.1361; https://arxiv.org/html/2412.12509v2). Pitfall to avoid: never let a single stochastic LLM judgment *gate* a confirm. Use it only to *nominate* a deterministic test; require self-consistency before it even nominates.

**Fit to Calma (FCR=0-safe).**
- **Anchors.** The monotone-downgrade pattern *already exists in the codebase* and is the template: `_apply_leakage_overlay()` (`spike/pipeline.py:125-162`) runs *after* verdicts are decided and only ever pushes a verdict *down* (CONFIRMED/REPRODUCED-ONLY/DISCOVERED → INVALIDATED; REFUTED stays REFUTED, `spike/pipeline.py:152-161`). Feature 8 generalizes this into a red-team overlay. The attack corpus and gate assertion live in `spike/optimize/redteam.py` (`attacks()` at `:51`, `confirmed = (v in VD.POSITIVE)` at `:96`, breach collection at `:99`). The verdict lattice top is `verdict.POSITIVE` (`spike/core/verdict.py:30`); downgrade targets already exist: `INCONCLUSIVE`/`NON_DETERMINISTIC`/`REPRODUCED_ONLY`/`INVALIDATED` (`spike/core/verdict.py:20-27`).
- **Pipeline slot.** New `_apply_redteam_gate(records, run_result, repo_dir)` invoked in `verify_repo()` immediately after `_apply_leakage_overlay(records, leakage)` (`spike/pipeline.py:483`) and *before* the `counts` tally (`spike/pipeline.py:485-487`). It iterates only over `records` whose `verdict in VD.POSITIVE` — the pass is a no-op on everything already non-CONFIRMED, so it is cheap by construction.
- **FCR-safety argument (downgrade-only, structural).** Define a partial order with CONFIRMED as the unique top. The gate computes `new = min_verdict(old, proposed)` where `min_verdict` returns `old` *unless* `proposed` is strictly weaker; it is *impossible* for the function to return CONFIRMED unless `old` was already CONFIRMED. The LLM critic never returns a verdict — it returns a *charge* (an attack to run); the charge is only actioned if a **pure deterministic re-check** (reusing `redteam.call()`/`acc_inputs` transforms at `spike/optimize/redteam.py:34,42` and `core.diff.diff_claim`) reproduces the breach. Thus a stochastic/false-positive-prone model can only ever *cast doubt*, matching the sound-verifier finding above. Verdicts affected: **CONFIRMED only** (as input); outputs stay CONFIRMED or move down.

**Build plan.**
- **P0 (inline deterministic gate).** In `spike/core/verdict.py` add `DOWNGRADE_ONLY` ordering + `def monotone(old, proposed) -> str` (unit-provable). Add `redteam.inline_attacks(record, runs)` to `spike/optimize/redteam.py` that, given a *real* CONFIRMED record + its captured `runs`, replays the input-transform attacks (single-class, trivial-baseline, length/NaN degeneracy, value-coincidence across candidates) against *this* computation and returns a proposed downgrade + reason or `None`. Wire `_apply_redteam_gate` into `spike/pipeline.py:483`. No LLM yet.
- **P1 (adversarial critic, propose-only).** Add `spike/optimize/redteam_critic.py`: a gated Claude call (same best-effort discipline as `planner`/`_llm_synthesize`, `spike/synth/formula.py:173-198` — no key ⇒ `None`) that reads the confirmed claim + captured inputs and *nominates* named probes from a fixed allowlist. Require **self-consistency** (k≥3 nominations, majority) before a probe runs; the probe itself is one of the deterministic re-checks. Model output can never widen the allowlist.
- **P2 (self-play attack mining).** Offline job that mines new attack templates (SPC-style) from any FCR bug-bounty submission (Feature 9) and from convention-mismatch corpus rows, auto-adding them to `attacks()` as construct-only fixtures.
- **Meta-eval instrument.** Extend `redteam.py:main()` to also emit `inline_gate_fcr` (adversarial-FCR *after* the inline gate) and a **"no-downgrade-of-honest-CONFIRMED" regression**: run the gate over the T1/T2 honest corpus (`spike/repos.yaml`) and assert it downgrades *zero* legitimately-CONFIRMED claims (precision guard — the gate must not become a false-REFUTE machine).
- **Tests.** `spike/tests/test_redteam_inline.py`: (a) every attack still yields non-CONFIRMED through the inline gate; (b) `monotone()` never returns CONFIRMED from a non-CONFIRMED input (property test over all verdict pairs); (c) honest CONFIRMEDs survive the gate unchanged; (d) critic stubbed to `None` ⇒ gate == P0 deterministic behavior.
- **Green gate.** `~/.calma/spike-venv/bin/python -m pytest spike/tests/` green **and** `python spike/optimize/redteam.py` exits 0 with `inline_gate_fcr == 0`.

**Effort & dependencies.** **S–M.** P0 is pure-stdlib and reuses existing transforms (S). P1 depends on the Anthropic SDK + `ANTHROPIC_API_KEY` (already used by `planner`/`formula`), gated so CI stays hermetic (M). Sequence: P0 ships first and is independently valuable; P1 layers on; P2 depends on Feature 9 existing.

---

## Feature 5 — Learning flywheel

**What & why.** `spike/synth/store.py` already banks *validated recompute formulas* keyed by metric, reused by vector match so the next repo with the same metric skips re-discovery (`spike/synth/store.py:1-16`). This feature generalizes that single store into an **experience bank** keyed by *repo-family × metric × domain*, banking run-plans, capture targets, conventions, and observed "known values" — so every verify makes the next one cheaper and more accurate. It is a compounding data moat: uncopyable without volume, and it strictly *narrows* the "unrecognized/unbindable" surface that forces fail-closed downgrades.

**SOTA & best practices (2026).**
- **Dual-modality experience units.** SetupX's XPU pairs *textual guidance* (symptom/reason — what makes it retrievable) with an *executable action* (the exact fix — what makes it portable), stored in pgvector with two-layer retrieval (vector coarse filter → LLM re-rank) and telemetry-based tier boosting on `hits/successes/failures` (https://github.com/OpenDataBox/SetupX/blob/main/README.md). **Pitfall it fixes:** low-abstraction, action-only memories cause *negative transfer* — dual-modality is the mitigation (https://agentpatterns.ai/workflows/experiential-setup-agents-snapshot-rollback/).
- **Skill libraries compound and resist forgetting.** Voyager's ever-growing library of *verified executable* routines, indexed by NL description and composed on the fly, drove 3.3× more items and 15.3× faster milestones, and *generalized to new worlds* (https://openreview.net/forum?id=ehfRiF0R3a). This is exactly Calma's validated-formula store — extend the shape, keep the "only bank verified code" discipline.
- **Experiential insight extraction.** ExpeL autonomously extracts success/failure "rules of thumb" from trajectory *contrasts* and retrieves them at inference — no fine-tuning, API-model-friendly (https://ojs.aaai.org/index.php/AAAI/article/view/29936). Retrieval-Augmented Reflexion diversifies retrieved trajectories via Maximum Marginal Relevance to avoid over-fitting to the most recent attempt (https://github.com/USD-AI-ResearchLab/reflexion). 2026 survey taxonomy (episodic/procedural/semantic memory) frames the store cleanly (https://arxiv.org/html/2603.07670v1).
- **CRITICAL pitfall — a cached "expected value" is a prior, not an answer.** Retrieval memory in all the above biases *what the agent tries*, never *what is true*. Verifiers that let prior answers leak into the judgment inflate false positives (see Feature 8 sources). So a banked known-value must be firewalled from the verdict.

**Fit to Calma (FCR=0-safe).**
- **Anchors.** `FormulaRecord` (`spike/synth/store.py:78-91`) becomes the base of a general `ExperienceRecord`; the `embed()`/`cosine()`/`_match()` retrieval (`spike/synth/store.py:32-69`), `LocalStore`/`HelixStore` backends (`:94,:141`), and `get_store()` (`:217`) are reused wholesale. Reuse of *validated code* already happens in `recompute_any()` via `store.lookup()` (`spike/synth/formula.py:387-395`) — note it executes the stored **code on this repo's captured inputs**, never returns a cached number. The plan pre-stage (`planner.plan_repo`, called at `spike/pipeline.py:386`) and binding candidate ranking are the *consumers* of banked plans/targets/conventions.
- **Pipeline slot.** (1) `planner.plan_repo` queries the bank by repo-family/domain signature for a warm-start plan (entry/deps/targets). (2) Binding uses banked conventions to *rank* candidate computations. (3) On a completed verify, a `bank_experience(result)` hook writes back plan+targets+conventions (and, separately namespaced, observed values) — analogous to XPU "promote successful sequence back to the store." All *pre-verdict*.
- **FCR-safety argument (known-values must not short-circuit).** Enforce a hard firewall: banked known-values live in a distinct `KnownValueHint` namespace consumed **only** by `planner` and binding-candidate ranking; they are *never* passed to `core.diff.diff_claim` or to `verdict.decide(claimed_raw, produced, recomputed, …)` (`spike/core/verdict.py:33`). The verdict's three inputs remain: the producer's claim, the *this-run* produced value, and the *this-run independent recompute*. A hint may make Calma pick the right computation to capture or the right convention — it can *never* stand in for `produced` or `recomputed`. Formula reuse is safe because it reuses *validated code re-executed on fresh inputs* (`spike/synth/formula.py:391`), not a cached scalar. Verdicts affected: **none directly** — the flywheel only shifts fail-closed downgrades (INCONCLUSIVE/DISCOVERED/REPRODUCED-ONLY) *upward toward a decidable CONFIRMED/REFUTED* by improving binding/coverage, and only through independent recompute.
- A dedicated **firewall test** (mirroring the existing edges/core CI firewall discipline) asserts no code path carries a `KnownValueHint` into `diff`/`verdict`.

**Build plan.**
- **P0 (generalize the record + keys).** Add `ExperienceRecord` to `spike/synth/store.py` with fields `{key: repo_family|metric|domain, kind: plan|targets|conventions|known_value, payload, telemetry:{hits,successes,failures}, validation}` and a `key_signature(repo_dir)` helper. Keep `FormulaRecord` as a subtype; keep "bank only after validation" (`spike/synth/store.py:15-16`).
- **P1 (write-back + warm-start).** `bank_experience(result)` called at the end of `verify_repo` (`spike/pipeline.py:489`); `planner.plan_repo` gains a store lookup for warm-start; binding consumes banked conventions as a ranking prior. Add telemetry-boosted composite scoring in `_match` (hits/successes tiering, per SetupX).
- **P2 (Helix at scale + insight extraction).** Promote the store to the HelixDB backend under `CALMA_HELIX` (already scaffolded, `spike/synth/store.py:141-206`); add an ExpeL-style offline `distill_insights()` that contrasts CONFIRMED vs fail-closed trajectories into reusable conventions.
- **Meta-eval instrument.** `spike/optimize/scorecard.py` extension: measure **coverage lift** (fewer INCONCLUSIVE/DISCOVERED per corpus run) and **cost lift** (fewer Exa calls via `formula.exa_call_count()`, `spike/synth/formula.py:299`; fewer planner tokens) at store sizes 0/50/500 — proving "better + cheaper with volume."
- **Tests.** `spike/tests/test_experience_store.py` (bank/retrieve/telemetry); `spike/tests/test_known_value_firewall.py` (**a `KnownValueHint` can never reach `diff_claim`/`verdict.decide`** — the FCR guard); reuse `spike/tests/test_source_corpus.py` harness for lift.
- **Green gate.** Full suite green + the firewall test + a scorecard run showing monotone coverage/cost lift with store size and **FCR unchanged (0)**.

**Effort & dependencies.** **M.** P0/P1 are stdlib + existing store. P2 depends on a running HelixDB (optional, auto-falls-back). Sequence: after Feature 8 (so banked bug-bounty counterexamples also feed the flywheel's negative memory), but P0/P1 can proceed in parallel since they touch different files.

---

## Feature 9 — FCR bug bounty

**What & why.** Pay a bounty for a *demonstrated false-CONFIRM*: a public program where anyone submits a repo+claim on which Calma emits CONFIRMED but the headline number is provably wrong. It is trivial to stand up, a maximal external trust signal ("we pay if our one sacred number is ever violated"), and it crowdsources precisely the hardening the founder obsesses over — each valid submission becomes a permanent regression fixture in the red-team gate and corpus.

**SOTA & best practices (2026).**
- **Impact-first, few-tier severity + mandatory PoC.** Immunefi uses a simplified 4-level scale (Critical/High/Medium/Low) driven by *consequence of exploit*, with a **PoC required for reward** and a *minimum* reward "to incentivize researchers against withholding a bug report" (https://immunefi.com/immunefi-vulnerability-severity-classification-system-v2-3/; https://immunefi.com/bug-bounty/immunefi/information/). For Calma there is effectively **one severity that matters: Critical = a false-CONFIRM**; everything else (a spurious REFUTE, a missed downgrade) is High/Medium.
- **Safe harbor + rules of engagement.** Immunefi ships a SEAL-based Safe Harbor legal framework and explicit prohibited-activity lists (no testing on prod, no third-party systems, KYC for payout) (https://immunefi.com/bug-bounty/immunefi/safe-harbor/; https://immunefi.com/rules/). Calma's ROE analogue: test only against *your own or provided* repos in the sandbox, never against another customer's private verify.
- **Triage state machine + regression discipline.** HackerOne's states (New → Triaged → Resolved) treat a Triaged bug as "live and reproducible," and crucially: **"Any regression or bypass of the fix must be submitted as a new report and referenced as a bypass/regression"** (+7 reputation) (https://docs.hackerone.com/en/articles/8475030-report-states). Agentic duplicate detection distinguishes a true duplicate from a *regression of a previously fixed issue* (https://docs.hackerone.com/en/articles/13703106-agentic-duplicate-detection). Coordinated disclosure defaults to public after fix (30-day window) (https://docs.hackerone.com/en/articles/8517457-disclosure-coordinated-vulnerability-disclosure). **Pitfall:** no-stealth-fixing — a fixed FCR bug must ship *with* a public regression fixture, not silently.

**Fit to Calma (FCR=0-safe).**
- **Anchors.** A valid submission is exactly a *breach* in the offline meta-eval: `confirmed = (v in VD.POSITIVE)` on a wrong number (`spike/optimize/redteam.py:96,99`). Triage = run the submitted repo/claim through `pipeline.verify_repo` (`spike/pipeline.py:364`) or, for construct-only cases, through `core.diff.diff_claim` (`spike/pipeline.py:336`, `spike/optimize/redteam.py:94`) and check for a CONFIRMED it shouldn't have gotten. The regression home is `attacks()` (`spike/optimize/redteam.py:51`) for construct-only counterexamples, and the **T4 tier** for full-repo cases — the corpus already reserves `T4 = "adversarial/negative — fabricated/leaked/trivial/…/coincidental"` (`spike/corpus.py`, `spike/repos.yaml:1-11`) with `capability:` tags (e.g. `cheating-formula`, `fabricated`, `version-drift`).
- **Pipeline slot.** No hot-path change. Off-path intake: (1) a web submission form (product surface, not landing — brand rule: landing = copy-only), (2) a triage script that runs the candidate and classifies, (3) on valid ⇒ auto-open a PR adding the fixture to `attacks()` or a `T4` `spike/repos.yaml` entry, which the existing `redteam.py:main()` gate then guards forever.
- **FCR-safety argument.** The program *operationalizes* FCR=0: the payout condition is definitionally "the adversarial-FCR gate was breached in the wild." Because each accepted counterexample is frozen as a construct-only fixture (pure, no execution — `spike/optimize/redteam.py:7`) and the CI gate asserts `adversarial_fcr == 0`, a fixed bug can never regress silently. This *only strengthens* the invariant. Verdicts affected: the whole taxonomy is in scope, but bounty tiers weight **false-CONFIRM (the CONFIRMED verdict) as the sole Critical**.

**Build plan.**
- **P0 (program spec + triage harness).** `spike/optimize/bounty.py`: `def triage(submission) -> {valid, verdict, is_false_confirm, dedup_key}` that runs `verify_repo`/`diff_claim` and computes a dedup signature (metric×capability×transform) to auto-detect duplicate vs regression (HackerOne-style). A `BOUNTY.md` policy doc: single-Critical severity table, PoC requirement, ROE/safe-harbor, no-stealth-fix, disclosure-after-fix.
- **P1 (fixture promotion).** `promote_to_fixture(submission)`: emits either a new `attacks()` tuple or a `repos.yaml` `T4` stub (reuse `source_corpus.repos_yaml_stub`, seen at `spike/optimize/source_corpus.py`) with `capability:` tag + per-claim `expect`. Opens a PR.
- **P2 (public intake + payout ledger).** Minimal web submission route + a signed submission receipt; payout tiers; KYC gate for payout only.
- **Meta-eval instrument.** `bounty.py` writes `bounty_ledger.json` (submissions, triage verdict, time-to-fixture, payout) and a rolling **"wild adversarial-FCR"** = false-confirms accepted ÷ submissions — the public trust metric, target 0.
- **Tests.** `spike/tests/test_bounty_triage.py`: a seeded known-bad submission triages as `is_false_confirm=True` and, once promoted, the redteam gate goes green again (round-trip: breach → fixture → 0).
- **Green gate.** After promoting any fixture, `python spike/optimize/redteam.py` exits 0 and the full pytest suite passes — the bug is *provably* closed and permanently guarded.

**Effort & dependencies.** **S (mechanism) / ongoing (program ops).** Depends on Feature 8's inline gate for maximum effect and reuses `source_corpus`/`corpus` tiering. Sequence: after Feature 8's P0; the public intake (P2) can wait behind a private beta with hand-triage.

---

## Feature 13 — Reproducibility badges + public registry

**What & why.** Emit an embeddable "verified by Calma" badge tied to a *signed verdict* and a public registry entry, and a searchable registry of verified repos. It is a distribution / network play — adoption-gated, GTM not tech — that turns every CONFIRMED into a discoverable, forgery-resistant proof and a backlink. Calma is structurally the *independent third party* that reproducibility badging schemes were designed to reward.

**SOTA & best practices (2026).**
- **ACM/NISO badging is the vocabulary to adopt.** ACM Artifact Review & Badging defines independent badges — *Artifacts Available*, *Artifacts Evaluated*, and **Results Reproduced = "main results obtained by a person or team other than the authors"** — harmonized with NISO RP-31-2021 (https://www.acm.org/publications/policies/artifact-review-and-badging-current; https://niso.org/publications/rp-31-2021-badging). Calma *is* the "different team, same setup" reproduction — map CONFIRMED to a Calma-flavored "Results Reproduced," never overclaim "Replicated."
- **Two-axis verification (machine score + human badge) with tolerance.** SOTAVerified scores papers on a machine-readable integer *and* a categorical badge, with an explicit **"reproduction within 5% of claimed metric" bonus** and confidence tiers 1–4 (Tier 4 = exact match on identical hardware) (https://github.com/sotarepro/sotaverified). Calma's tolerance layer + verdict taxonomy already encode this — expose both a verdict badge and a per-claim delta.
- **Community reproduction infra precedent.** Papers with Code's ML Code Completeness Checklist and the OpenReview/ReScience ML Reproducibility Challenge established the norm that independent reproduction is a first-class, citable artifact (https://ai.meta.com/blog/new-code-completeness-checklist-and-reproducibility-updates/; https://openreview.net/group?id=ML_Reproducibility_Challenge).
- **Dynamic badges via shields.io endpoint.** The shields.io **Endpoint Badge** renders from a JSON you host: `{ "schemaVersion": 1, "label": "…", "message": "…", "color": "…", "isError": … }`, consumed as `https://img.shields.io/endpoint?url=<your-json>` with configurable cache (https://shields.io/badges/endpoint-badge). This is the exact integration surface — Calma hosts the endpoint, shields renders it, the README embeds one line.

**Fit to Calma (FCR=0-safe).**
- **Anchors.** The badge is a projection of the verdict taxonomy (`spike/core/verdict.py:20-27`). `verify_repo`'s returned `claims`/`counts` (`spike/pipeline.py:490-500`) are the registry record; the per-claim `diff`/`determinism`/`validity`/`provenance` fields (`spike/pipeline.py:346-359`) become the auditable registry detail. The signed-proof story reuses the existing KMS ECDSA-P256 proof-signing from the prior engine (memory: "KMS proof signing (ECDSA-P256)").
- **Pipeline slot.** Post-verify, off the hot path: a `registry.publish(result, commit_sha, signature)` and a badge endpoint `GET /api/badge/{registry_id}` returning the shields JSON. Registry + badge routes live in `web/` product surface (brand: dark hero → light band, lotus; landing stays copy-only).
- **FCR-safety argument.** The badge is a *strict function of the verdict* — **green/"CONFIRMED" is emitted only for `verdict == CONFIRMED`**; REFUTED/INVALIDATED render red, and REPRODUCED-ONLY/NON-DETERMINISTIC/INCONCLUSIVE/DISCOVERED render amber with the honest reason (the fail-closed taxonomy maps 1:1 onto badge states, so a fail-closed verdict *cannot* surface as a green "verified"). To prevent a stale/forged confirm, every registry entry (and thus badge) is **pinned to `{repo, commit_sha, claim_id, verdict, signature}`**; a badge whose repo has moved past the pinned SHA renders "stale — re-verify" rather than green. The signature makes the claim un-forgeable; the pin makes it un-reusable. This *distributes* FCR=0 without ever creating a new confirm path. Verdicts affected: all — but only CONFIRMED yields the affirmative badge.

**Build plan.**
- **P0 (badge endpoint from a verdict).** `spike` API route `GET /api/badge/{id}` returning the shields endpoint JSON derived from a stored verdict; color/label map table with CONFIRMED⇒green only. Pure serialization, no verdict logic.
- **P1 (public registry + signing).** `registry.publish()` writing `{repo, commit_sha, claim_id, verdict, delta, signature, ts}`; a public read-only registry page + per-entry proof view; SHA-pin staleness check. Wire ECDSA signing on publish.
- **P2 (embeds + network loop).** One-line README embed generator ("verified by Calma"), an ACM/NISO-aligned badge taxonomy mapping, and a "reproduced within tolerance" delta badge (SOTAVerified-style).
- **Meta-eval instrument.** A `registry_audit` job that re-verifies a sample of live registry entries at their pinned SHA and asserts **badge state == recomputed verdict** (drift guard) and that **no amber/red verdict ever rendered as green** (the badge-side FCR guard).
- **Tests.** `spike/tests/test_badge_endpoint.py` (verdict→shields-JSON mapping, CONFIRMED-only-green property); `spike/tests/test_registry_signing.py` (signature verifies; tampered entry fails; moved-SHA ⇒ stale).
- **Green gate.** Suite green + the registry-audit "no false-green" property holding across the corpus + a `next build` clean for the web surface.

**Effort & dependencies.** **M (badge/registry) + L (web polish & GTM).** Depends on stable verdict output (present) and the KMS signing key (exists from prior engine). Sequence: independent of 8/9 but most credible *after* Feature 9 exists (a public "we pay if the green badge ever lies" pairs the badge with a bounty).

---

### Cluster throughline (5 lines)
1. One invariant, four leverage points: **8 hardens** the confirm (inline downgrade-only gate), **9 crowdsources** its counterexamples, **5 compounds** coverage without touching it, **13 distributes** proof of it.
2. Every feature is expressed relative to `verdict.POSITIVE = (CONFIRMED,)` — the codebase already has the exact monotone-downgrade precedent (`_apply_leakage_overlay`) to copy.
3. The recurring safety rule is **"AI/priors propose, determinism disposes"**: LLM critics and banked known-values may only *bias what we try*, never *what we confirm*.
4. The flywheel is bidirectional — bounty counterexamples become red-team fixtures *and* negative experience memory, so hardening and learning share one loop.
5. Net effect: FCR=0 moves from a passive lab property to a self-strengthening, externally-incentivized, publicly-provable franchise moat.
