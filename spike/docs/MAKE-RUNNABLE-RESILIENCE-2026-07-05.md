# Make-runnable resilience + the reproduction flywheel

**Problem (from a real run — `ebv-ms-structural-mimicry`):** Calma *found* the entrypoint (`src/cli.py`) but
the **env build** failed: declared Python 3.10 vs `numpy==2.4.6` which needs ≥3.11 → unsatisfiable → the run
died, and the UI mislabeled it an *entrypoint* problem. The log also showed the dep list installed twice
(`numpy==2.4.6 … numpy`) and the fallback entrypoint re-provisioning a fresh microVM to re-install the same
broken deps. So "99% can't find a runnable entrypoint" is mostly **make-runnable (env build) + discovery**,
not entrypoint discovery.

Everything here is **FCR-safe**: it only changes *whether/how* a repo runs (the HOW), never a captured value,
binding, or verdict. A still-broken env fails closed to DISCOVERED — never a false CONFIRM.

## Slices

| # | Slice | What | Files | Status |
|---|-------|------|-------|--------|
| **1** | **Dedup + env-repair retry** | `dedup_pip` (kills `numpy==2.4.6 … numpy`); on an install failure, parse the resolver's required Python and **reprovision + retry** (bump 3.10→3.11), else **relax pins** and retry once — bounded, can't-regress (only fires on a currently-fatal error). | `runner/build.py`, `runner/e2b_runner.py`, `pipeline.py`, `tests/test_make_runnable.py` | ✅ **landed** (pure helpers unit-tested; the E2B retry path needs a live-E2B smoke test to confirm end-to-end) |
| **2** | **Relax ladder + tolerant-path repair** | Full ladder: exact pins → `~=`/compatible → unpinned → latest, and detect the required-Python signal in the *tolerant* (per-package) install path too (today the bump only triggers on the strict path). | `runner/e2b_runner.py`, `runner/build.py` | ▢ next |
| **3 (C)** | **Ground the run from the repo** | Add entrypoint/dep/python/system-dep sources the repo already states: README run block, `pyproject [project.scripts]`, `Makefile` targets, and **`.github/workflows` run steps** (CI = the ground-truth command + Python + apt packages). Feed these to `detect_entrypoint` + the planner. | `runner/build.py`, `planner.py` | ▢ |
| **4 (A)** | **conda/micromamba for binaries** | Repos needing system binaries (this one: Foldseek + HMMER) can't be solved by pip. Wire the existing `orchestrator/tools_exec` conda-env path into the default pipeline when an `environment.yml`/bioconda hint is present. | `runner/e2b_runner.py` (`conda-micromamba` builder), `orchestrator/tools_exec.py` | ▢ |
| **5 (Helix flywheel)** | **RunPlan cache in the DEFAULT path** | The `ApproachCache`/`HintStore` (`orchestrator/cache.py`) exist but are orchestrator-only. Add a **RunPlan cache keyed by stack-signature** (python + sorted deps + entrypoint) usable in the default path: **positive** cache (a known-good env → reuse, no re-resolve) **and negative** cache (a proven-unsatisfiable set → don't retry it). Reuse within a session (the 2nd entrypoint) *and* across repos. Local-JSON first (zero-infra), HelixDB `RunPlan` node backend after (mirror `synth/store.py`'s local↔Helix swap). **This is the flywheel + it also kills the re-install duplication.** | new `runner/runplan_cache.py`, `pipeline.py`, later `helix/` schema | ▢ (the ask: "automatically have what we've seen — same session, and over time") |
| **6 (D)** | **Env-repair loop wired to the default path** | The `HintStore` learns error-signature → fix (e.g. `ModuleNotFoundError: cv2` → add `opencv-python-headless`). Extend `error_signature` to cover the python-version conflict, and let the *heuristic* path (not just `orchestrate=True`) consult/record it. | `orchestrator/cache.py`, `pipeline.py` | ▢ |
| **7 (E)** | **Honest failure messages** | Say *"dependency install failed: numpy==2.4.6 needs Python≥3.11 — retried on 3.11"*, not *"the entrypoint errored"*. Distinguish env-build failure vs entrypoint-errored vs missing-data in the summary. | `pipeline.py` summary/verdict text | ▢ |
| **8 (B)** | **Lean on the no-run path** | This repo *commits a predictions file* but discovery found **0 claims**, so there was nothing to check without running. Invest in discovery (README/results.json/notebook-output/log parsing) so `claimed-number + committed-predictions → recompute` with **zero execution** — the biggest coverage lever for un-runnable repos. | `discovery/extract.py`, `core/artifacts.py` | ▢ (separate, larger effort) |

## Priority
Slice 5 (flywheel) + Slice 8 (no-run/discovery) are the biggest coverage levers. Slices 1–4 make the *run*
path resilient (fix this repo's class). Slice 7 is a same-day UX win. Slice 6 ties it together.

## Guardrails
- Every retry/repair is **bounded** (no unbounded loops; caches are size-capped — CWE-770).
- **HOW-only**: caches/repairs replay an approach or a fix, never a value/binding/verdict. A stale entry can
  only cost *coverage* (a failed run → DISCOVERED), never cause a false CONFIRM. A changed repo → different
  fingerprint → automatic miss.
- The FCR franchise gates (`optimize/*`) must stay 11/11 through every slice.
