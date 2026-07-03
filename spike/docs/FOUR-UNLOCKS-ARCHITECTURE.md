# Four-Unlocks — Architecture & Implementation Notes

Companion to `FOUR-UNLOCKS-BUILD-PLAN.md`. What was built, the folder structure, the clean-architecture
decisions, the performance characteristics, and the debugging notes. Everything below is **implemented, tested
(902 passed), and lint-clean (ruff/mypy/vulture)** — the E2B/Modal *image builds* are the only remaining ops
step (they need cloud API keys; the code that drives and consumes them is done and flag-gated inert).

---

## 1. What shipped

| Unlock | Mechanism | Status |
|---|---|---|
| **Notebooks (E2B)** | `capture/run_notebook_e2b.py` runs in-sandbox; `run_e2b` routes `nb:` entries to it; kernel-armed capture | code done; needs image rebuild (`e2b_template.py` adds nbclient/nbformat/ipykernel/papermill) |
| **Conda (E2B)** | `run_e2b` solves `environment.yml` via micromamba in-sandbox (lockfile-preferred), then runs under that python | code done; needs micromamba in the image (added to `e2b_template.py`) |
| **Non-Python (R/Julia)** | `find_lang_entrypoints` ranks `lang:` candidates; `run_e2b`/`run_lang` run the interpreter; verdict via Python artifact-recompute (capture is Python-only, stated honestly → INCONCLUSIVE without a recomputable artifact) | code done; needs the `-polyglot` image variant |
| **GPU (Modal)** | E2B can't do GPU → new `runner/modal_runner.py` backend; reactive `needs-gpu` escalation + static hint; `allow_gpu` enterprise gate + GPU-minute meter | code done; inert until `MODAL_TOKEN_*` + `CALMA_ENABLE_GPU` |
| **Data-behind-auth** | `runner/secrets.py` per-tenant store (inject into ACQUIRE only), `runner/egress.py` default-deny allowlist, disk-budget tier field, `/api/secrets` endpoints | code done |
| **Metric-bind / entrypoint** | already solved on paid (AI-plan + orchestrator ranking) — verified by test, no build | done |

---

## 2. Folder structure (the runner layer, after refactor)

```
runner/
  effector.py     NEW  backend-agnostic RUN CONTRACT — capture-env arming, sandbox-lifetime sizing,
                       result/setup-error shaping, the canonical LANG_INTERP map. Pure stdlib.
  e2b_runner.py        E2B TRANSPORT — now imports the contract from effector (no inline copy).
                       Adds: _command_for (entry→command router), _build_conda_env, egress helpers.
  modal_runner.py NEW  MODAL GPU TRANSPORT — same contract, GPU image, GPU-seconds telemetry. Import-guarded.
  gpu.py          NEW  GPU DECISION — needs_gpu_from_failure (reactive) + scan_repo_for_gpu (static hint). Pure.
  secrets.py      NEW  per-tenant CREDENTIAL STORE — acquire-phase injection, redaction, owner-env seeding. Pure.
  egress.py       NEW  acquire-phase ALLOWLIST — default-deny + data hosts, widened per stored credential. Pure.
  build.py             unchanged (failure taxonomy reused by gpu.py — single source of truth)
  acquire.py           unchanged (detection); its E2B execution now secret-injected + egress-limited
capture/
  run_notebook_e2b.py NEW  in-sandbox notebook entrypoint (nbclient, kernel-armed capture)
```

## 3. Clean-architecture decisions (separate concerns · increase modularity · reduce coupling)

**Concern split: CONTRACT vs TRANSPORT.** A sandbox runner was really two things fused inside `e2b_runner`:
the backend-independent *contract* (how a capture run is armed, how long the box must live, the exact result
dict the verify consumes) and the backend-specific *transport* (boot/upload/install/exec/pull). A second
backend would have had to copy the contract and drift from it. `runner/effector.py` extracts the contract once;
`e2b_runner` and `modal_runner` both import it. **Coupling between the two backends is now zero** — they share a
module, not a copy. The FCR surface (the guarantee that no verdict leaks through the transport) lives in one
place and is asserted structurally (`test_modal_runner_has_no_verdict_surface`, mirroring the orchestrator
firewall test).

**Single responsibility per new module.** `gpu.py` decides, `secrets.py` stores, `egress.py` allowlists,
`effector.py` contracts. Each is pure stdlib, no cross-import except `egress → secrets.KNOWN_SECRETS` (a
credential's egress scope is a property of the credential, so that dependency is correct and one-directional).

**Dependency direction preserved.** The orchestrator layer imports the runner layer (never the reverse). The
`LANG_INTERP` map was duplicated across `tools_exec` (orchestrator) and `e2b_runner` (runner); it now lives in
`runner.effector` and both import it — dedup WITHOUT inverting the dependency (orchestrator→runner stays the
only direction).

**Router centralization.** Entry-kind → command mapping (`nb:`/`r:`/`julia:`/script) is one function,
`e2b_runner._command_for`, reused by both transports — a notebook needing a GPU routes correctly on Modal too.

**Behavior unchanged where it must be.** The extraction is byte-identical on the existing path: the 13
`test_e2b_runner` cost/lifetime/streaming assertions and the full 879-test baseline pass untouched; the new
capabilities are purely additive and flag/tier-gated.

## 4. Performance

- **No hot-path cost added.** `gpu.scan_repo_for_gpu` runs ONLY on the reactive GPU-escalation branch (after a
  run already failed), never per-run; it is bounded (`max_files=400`, `max_bytes=400k`) so a monorepo can't
  stall it. `secrets`/`egress`/`effector` helpers are O(1)/O(hosts).
- **One-round-trip staging reused.** `modal_runner._stage_repo` uses the same tar→single-write→extract as E2B
  (not per-file), so GPU staging inherits the pre-install latency win.
- **Install-once / run-k preserved on both backends.** The dominant cost (deps) is paid once per sandbox; the
  k determinism runs reuse it (the shared contract enforces the sandbox lifetime that makes this safe).
- **Conda lockfile fast-path.** `_build_conda_env` prefers a committed lockfile → micromamba skips the solver
  (deterministic + much faster) when the repo commits one.

## 5. Debugging / edge cases handled

- **GPU notebook:** `run_modal` uses the shared `_command_for`, so a `nb:` entry that escalates to GPU runs
  through the notebook runner, not `python nb:file` (which would fail).
- **Acquire egress vs behavior:** the allowlist is applied for the acquire window (where the credential is
  live), then **cleared** (not denied) so the eval run returns to its prior network posture — the credential is
  gone by eval time, so this is behavior-preserving, not a silent regression that would break acquire-corpus
  repos that fetch at eval time.
- **False GPU escalation:** the static-scan secondary trigger fires only on `errored`/`too-heavy` failures,
  never `missing-dep`/`missing-data`/`missing-entrypoint` (a GPU wouldn't fix those) — a CPU repo is never
  billed for a GPU it didn't need.
- **Honest degradation everywhere:** missing Modal SDK/token, missing micromamba, missing R/Julia, absent
  `update_network` — each returns an honest empty/failed run or keeps the prior posture; never a crash, never a
  fabricated verdict (FCR holds by construction).
- **Secret hygiene:** values are process-memory only, never returned by any endpoint, injected into the acquire
  step only (never the eval run → recompute stays credential-free), redactable from logs, and egress-scoped so
  a leak can't exfiltrate off the data host.

## 6. Rollout (ops, in order)

1. Rebuild the E2B image: `python spike/e2b_template.py` (+ the `-polyglot` variant). Point Fly at it.
2. `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` + `CALMA_ENABLE_GPU=1` when GPU is wanted (inert until then).
3. Per-tenant secrets via `POST /api/secrets` (paid tiers).
4. Run the corpus gate after each step — FCR==0 + heuristic-parity must stay green before enabling in prod.
