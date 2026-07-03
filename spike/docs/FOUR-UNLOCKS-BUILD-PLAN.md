# Build Plan — The Four Unlocks (Notebooks · Conda · Non-Python · GPU) + Data-Behind-Auth

> **STATUS: IMPLEMENTED (2026-07-02).** All phases coded, tested (904 passed / 3 skipped), and lint-clean
> (ruff/mypy/vulture). See `FOUR-UNLOCKS-ARCHITECTURE.md` for the as-built structure. Only the cloud *image
> builds* (E2B templates, Modal token) remain — ops steps that need API keys; the code that drives and consumes
> them is done and flag-gated inert (`CALMA_ENABLE_GPU` off by default). New tests: `tests/test_four_unlocks.py`.

Status: PLAN (2026-07-02). Author: build-planning pass with codebase grounding + Exa SOTA research.
Anchors: `spike/e2b_template.py`, `spike/runner/e2b_runner.py`, `spike/orchestrator/tools_exec.py`,
`spike/orchestrator/types.py`, `spike/core/limits.py`, `spike/runner/acquire.py`, `spike/pipeline.py`.
Invariant that governs every phase: **FCR == 0** (the agent/runner never touches the verdict; recompute stays
independent) and the corpus gate (heuristic-parity, no false-confirms) must stay green.

---

## 0. The one correction that reshapes the plan

The premise — *"one image-build unlocks four"* — is right for **three** and wrong for **one**.

> **E2B cannot do GPU.** Firecracker microVMs do not do GPU passthrough. Confirmed across four independent 2026
> sources (ZenML, Beam sandbox guide, Particula, AICraftGuide): *"E2B and CodeSandbox do not [support GPU] —
> their Firecracker microVMs don't do GPU passthrough."*

So the real shape is:

| Bucket | Backend | Nature |
|---|---|---|
| **Notebooks + Conda + Non-Python (run)** | ONE E2B image rebuild + dispatch wiring | the true "one unlocks three" |
| **GPU** | a **second runner backend (Modal)** | new subsystem, not an image line |
| **Data-behind-auth / huge downloads** | secret store + egress allowlist + disk/UI | real subsystem |
| **Custom-metric bind / entrypoint** | already solved on paid | zero build |

A second, favorable correction the original table missed:

> **E2B egress allowlisting now exists** (`network.allowOut` / `denyOut`, domain filtering via SNI on 443 / Host
> on 80, plus `updateNetwork` on a live sandbox — E2B API `PUT /sandboxes/{id}/network`, SDK `update_network`).
> So the acquire-phase allowlist is a **config task on our existing runner**, not a proxy we have to build.

Net effort re-estimate: notebooks/conda ≈ small (image + thin dispatch), non-Python-run ≈ small-medium,
GPU ≈ medium (new Modal effector, mirrors `run_e2b`), data-auth ≈ medium (secret store + allowlist + upload UI).

---

## 1. Provider decision — why Modal for GPU (researched)

Only three sandbox providers put a GPU *inside* the isolation boundary: Modal, Beam, Daytona. Decision:

| Provider | GPU-in-sandbox | Isolation | Secrets | Egress control | Verdict |
|---|---|---|---|---|---|
| **Modal** | **Yes** (T4→B200; `gpu="A100"`) | gVisor | `secrets=[Secret]` | `block_network`, `cidr_allowlist` | **Pick.** Python-first SDK mirrors our `run_e2b` effector 1:1 (`Sandbox.create(image, gpu, timeout, secrets, block_network, cidr_allowlist, workdir, volumes)`; `sb.exec(...)`). Only one with H100/A100 in a sandbox. |
| Beam | Yes (4090/A10G/H100) | gVisor+runc | yes | yes | viable fallback; smaller agent ecosystem |
| Daytona | limited/regional | Docker (Kata opt-in) | yes | yes | GPU "listed but limited regions" as of 2026-05; weaker default isolation |
| E2B | **No** | Firecracker | env only | allow/deny lists | keep for all CPU work |

**Modal GPU pricing (verified modal.com/pricing, per-second):** T4 `$0.000164`, L4 `$0.000222`, A10 `$0.000306`,
A100-40 `$0.000583`, A100-80 `$0.000694`, H100 `$0.001097`, H200 `$0.001261`, B200 `$0.001736`. Sandbox CPU
bills at `$0.00003942/core/s` (3× the Function rate — the multiplier that surprises people; also a 3× non-preempt
and 1.25× US-region multiplier). Default sandbox lifetime 5 min, configurable to 24 h. → **A100-40 ≈ $2.10/hr,
H100 ≈ $3.95/hr.** This is why GPU is enterprise-gated + metered.

Keep E2B the default for everything CPU (notebooks, conda, polyglot, acquire). Modal is a *targeted second
backend* only reached when a run needs a GPU. Two backends, one effector contract.

---

## 2. Phase map

```
Phase 0  Rebuild the E2B image        → unlocks notebooks + conda + polyglot-RUN   [ops, small]
Phase 1  Wire E2B notebook dispatch    → nb: runs in the sandbox, not just local    [wiring, small]
Phase 2  Wire E2B conda dispatch       → conda-micromamba builder runs in E2B        [wiring, small]
Phase 3  Wire run_lang dispatch        → R/Julia run; verdict via artifact-recompute [wiring, small-med]
Phase 4  Modal GPU runner              → new effector, detect→route, gate, meter     [subsystem, medium]
Phase 5  Data-behind-auth hardening    → secret store + egress allowlist + disk + UI [subsystem, medium]
Phase 6  Verify the two "no-build" wins → AI-plan bind + orchestrator entrypoint      [verify only]
```

Phases 0–3 ship as one PR train (all ride the single image). Phase 4 and Phase 5 are independent, parallelizable.

---

## 3. Phase 0 — Rebuild the E2B image (`spike/e2b_template.py`)

The builder is already on E2B Build System 2.0 (SDK `Template()`, no Dockerfile — this is the current, correct
path; ignore `e2b.Dockerfile`/`e2b.toml`, they're legacy). We add package lines + a micromamba binary + (behind
a variant flag) R/Julia.

### 3.1 Add notebook + conda tooling to the default template

Edit `e2b_template.py` — extend the pinned stack and the builder chain:

```python
# new pinned groups
_NOTEBOOK = ["nbclient", "nbformat", "ipykernel", "jupyter-client", "papermill"]
# micromamba is a static binary, not pip — installed via a run step below.

builder = (
    t.from_python_image(py)
    .apt_install(["git", "build-essential", "curl", "bzip2", "ca-certificates"])
    .pip_install(["uv"])
    .pip_install(_ML)
    .pip_install(_TORCH_CPU)
    .pip_install(_GENOMICS)
    .pip_install(_NOTEBOOK)                                   # ← notebooks
    # micromamba into /usr/local/bin (static musl binary, ~5MB, no solver at image time)
    .run_cmd("curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest "
             "| tar -xj -C /usr/local/bin --strip-components=1 bin/micromamba")  # ← conda
    .run_cmd("python -m ipykernel install --name python3 --sys-prefix")          # pin kernelspec
    .set_envs({"PIP_PREFER_BINARY": "1", "UV_SYSTEM_PYTHON": "1",
               "UV_CACHE_DIR": "/root/.cache/uv", "MAMBA_ROOT_PREFIX": "/opt/micromamba"})
)
```

- **Confirm the run-step method name against the installed e2b SDK** (`run_cmd` vs `run` vs `exec`). If the
  installed builder lacks a raw-command step, fall back to a tiny `COPY`+script step or bake micromamba via a
  pre-baked base. This is the only API-uncertainty in Phase 0 — verify first with a 3-line probe build.
- `notebook_available()` (`tools_exec.py:284`) and `micromamba_bin()` (`tools_exec.py:357`) already degrade
  honestly when absent, so a partial image never false-confirms — it just reports "ships in the E2B image."

### 3.2 Template family (keep the base lean)

R (`r-base` ≈ 300 MB) and Julia (≈ 500 MB) bloat cold-start for the 95% Python case. Build **three named
templates from the same script**, selected by env, so the base stays fast:

| Template | Contents | Env var | Routed when |
|---|---|---|---|
| `calma-verify` | current ML/genomics + `_NOTEBOOK` + micromamba | `CALMA_E2B_TEMPLATE` | default (all Python, nb, conda) |
| `calma-verify-small` | 2-core variant of the above | `CALMA_E2B_TEMPLATE_SMALL` | `cpu_cores<=2` (already wired in `_route_template`) |
| `calma-verify-polyglot` | above + `r-base` + Julia + `Rscript`/`julia` on PATH | `CALMA_E2B_TEMPLATE_POLYGLOT` | entry kind is `lang` (Phase 3) |

Parameterize `e2b_template.py` with a `--variant` / `CALMA_TEMPLATE_VARIANT` switch that toggles the extra
`apt_install(["r-base"])` + a Julia download `run_cmd`. One script, three `Template.build` targets.

### 3.3 Build + roll out

```bash
export CALMA_E2B_API_KEY=<key>
python spike/e2b_template.py                              # rebuild calma-verify (nb + conda)
CALMA_TEMPLATE_VARIANT=polyglot CALMA_TEMPLATE_NAME=calma-verify-polyglot python spike/e2b_template.py
flyctl secrets set -a calma-engine CALMA_E2B_TEMPLATE=calma-verify \
    CALMA_E2B_TEMPLATE_POLYGLOT=calma-verify-polyglot
```

Rollout safety: **don't overwrite the live template name in place.** Build under a new suffix
(`calma-verify-v2`), point the Fly secret at it, and keep the prior template name for instant rollback (revert
the secret). E2B layer-caches, so the rebuild only re-runs changed layers.

**Phase-0 gate:** rebuild → run the corpus gate → FCR==0 + heuristic-parity still green. Notebook/conda repos
that were previously INCONCLUSIVE-for-tooling should now execute.

---

## 4. Phase 1 — Wire E2B notebook dispatch

Today `run_notebook` (`tools_exec.py:296`, nbclient + nbformat, kernel-armed capture, `allow_errors=False`,
per-cell timeout — already SOTA per the papermill/nbclient field guides) runs **only locally**
(`pipeline.py:522-525`, comment: "the E2B notebook image is future"). Now the image exists, so route `nb:` to E2B.

Design — reuse the existing effector, don't fork it:

1. Ship a **1-file notebook runner module** into the sandbox alongside the capture shim (add to `_SHIM_FILES`
   staging in `e2b_runner.py:301`). It wraps the same `NotebookClient` call as `run_notebook`, reading the
   notebook path from argv and inheriting `CALMA_CAPTURE_*` from env (kernel-armed capture auto-arms because the
   kernel inherits `os.environ` — same mechanism as `tools_exec.py:323-331`).
2. In the E2B run loop (`e2b_runner.py:355`, the `for i in range(k)` block), when `entry[0]` starts with `nb:`,
   set the command to `python /capture/run_notebook_e2b.py <nb_path>` instead of `pybin + entry`. The capture
   file plumbing (`CALMA_CAPTURE_OUT`, per-run `calls_i.jsonl`, `_pull_capture`) is unchanged.
3. Flip `pipeline.py:520-525` so a `nb:` entry with `runner == "e2b"` goes to `run_e2b` (it currently forces
   local). The FORCE_E2B backend path (`server.py`, `CALMA_FORCE_E2B=1`) then covers notebooks automatically.

Result: notebooks verify inside the microVM with the same k-run determinism + capture + recompute the script
path already gets. No verdict-path change → FCR untouched.

**Tests:** a fixture repo whose headline metric is computed in a `.ipynb` cell → CONFIRMED via E2B; an erroring
cell → honest run-failure with the real traceback (not a false verdict).

---

## 5. Phase 2 — Wire E2B conda dispatch

`build_conda` (`tools_exec.py:425`) + the `conda-micromamba` builder (`orchestrate.py:81`) already resolve an
`environment.yml`, but dispatch only runs it **locally** (`pipeline.py:546-553`) — and the E2B image had no
micromamba. Phase 0 adds the binary; now run the conda build *inside* the sandbox.

1. In `e2b_runner.py`, before the run loop, if `builder == "conda-micromamba"` (thread the builder tag through
   `run_e2b`, or detect `environment.yml` present), run micromamba **in the sandbox**:
   `micromamba create -y -p /opt/env -f /work/environment.yml` (SOTA reproducibility: if the repo commits a
   conda lockfile, prefer `micromamba create -f <lock>` — no solver, deterministic, faster). Then set
   `pybin = "/opt/env/bin/python"` for the k runs. Activation caveat from the micromamba-docker docs: use the
   explicit prefix python, not shell activation — `docker exec`-style non-login shells don't auto-activate.
2. Route `pkg_manager=conda` → E2B (it's already detected in `tools_static.py:269` and mapped in
   `orchestrate.py:81`). No new detection needed; just honor it in the E2B path instead of forcing local.

**Gating:** conda is CPU-only and cheap — **no hard tier gate.** The existing wall-time CLAMP
(`limits.py:382`) already bounds a slow solve. (If solves prove pathological, add a `conda_solve_timeout`
knob later; don't gate the capability.)

**Tests:** a repo pinned via `environment.yml` (e.g. a pandas/bioconda pin) → env builds in-sandbox → CONFIRMED.

---

## 6. Phase 3 — Wire `run_lang` (R / Julia) + the honesty boundary

Two parts, and the second is the crux.

**6.1 Running it (ops + a dispatch line).** `run_lang` (`tools_exec.py:374`, interpreter map
`{"r":"Rscript","julia":"julia",...}`) is defined but **never dispatched** — the pipeline run loop
(`pipeline.py:520-564`) handles `nb:`/`make:`/e2b/conda/local but not `lang`. Add a branch: when the ranked entry
kind is `lang` (`types.py:23`, e.g. `r:analyze.R`), route to the **polyglot template**
(`CALMA_E2B_TEMPLATE_POLYGLOT` from Phase 0) and exec `Rscript`/`julia`. Mechanically identical to the script
path minus the Python interpreter.

**6.2 Capturing the metric — the catch, stated honestly.** Our capture shim
(`capture/calma_capture.py`: monkeypatches `sklearn.metrics.*` + PEP-669 `sys.monitoring` + import-patch;
auto-arms via `sitecustomize.py` on `PYTHONPATH`) operates on **CPython's own objects** — it is structurally
blind to an R or Julia process. So there are exactly two verdict routes for non-Python:

- **Artifact-recompute (works today, language-agnostic).** If the repo commits `predictions.csv` (or the R/Julia
  run writes one), `core/artifacts.py` (`recompute_from_artifacts`, `find_prediction_files`) recomputes the
  headline number **in Python** from the raw outputs → CONFIRMED/REFUTED, driven by `pipeline.py:611-641`. This
  is the intended non-Python path: **run R/Julia, harvest its output artifact, recompute in Python.** No R
  capture needed. Wire Phase 3 so a `lang` run's fresh outputs are re-scanned by `rescan_outputs`
  (`tools_exec.py:181`) and fed to `_artifact_verify`.
- **No committed/emitted predictions → INCONCLUSIVE, by design.** We do not guess a number we can't recompute.
  This is the correct, franchise-safe boundary — surface it in the report ("R run succeeded; no recomputable
  artifact → INCONCLUSIVE. Emit predictions.csv or name the metric in Advanced").

**Explicitly out of scope for this plan:** a live R/Julia trace subsystem (a language-specific capture that sees
`caret`/`MLJ` metric calls). That's a large, separate build; the artifact path covers the real demand first.
Note it in the roadmap, don't start it here.

**Tests:** (a) R repo that writes `predictions.csv` → CONFIRMED via recompute; (b) R repo with the metric only
printed to stdout → INCONCLUSIVE with the honest "emit an artifact" message; (c) Julia repo w/ artifact → CONFIRMED.

---

## 7. Phase 4 — GPU via a Modal runner (the real second subsystem)

`RUNNERS = ("local","e2b","e2b-gpu")` (`types.py:20`) declares `e2b-gpu` but **nothing dispatches it** — every
site checks `== "e2b"` (`pipeline.py:350,531`, `run_spike.py:61`, `server.py:396`). Since E2B has no GPU, back
the GPU runner with **Modal** and rename the vocab to `modal-gpu` (keep `e2b-gpu` as a deprecated alias so no
config breaks).

### 7.1 New effector `runner/modal_runner.py` — mirror `run_e2b`'s contract

Same return shape (`{"runs","meta","ran_ok","hooks_armed","n_calls","cost"}`) so the pipeline is backend-agnostic.

```python
import modal
def run_modal(repo_dir, entry=None, *, k=2, hooks="sklearn", targets=None, timeout=1800,
              gpu="A100", pip_install=None, python_version=None, cpu_cores=0,
              secrets=None, allow_out=None, log=None, resolve=None, **kw):
    app = modal.App.lookup("calma-verify-gpu", create_if_missing=True)
    image = _gpu_image(python_version, pip_install)          # CUDA torch, capture shim baked
    sb = modal.Sandbox.create(
        app=app, image=image, gpu=gpu, timeout=_life(timeout, k),
        cpu=cpu_cores or 4.0, memory=16384,
        block_network=not (allow_out or resolve or pip_install),   # deny by default
        cidr_allowlist=allow_out or None,
        secrets=[modal.Secret.from_dict(secrets)] if secrets else [],
        workdir="/work",
    )
    # stage /capture shim + /work repo, then the SAME k-run loop as e2b_runner:
    for i in range(max(1, k)):
        p = sb.exec("python", *entry, env={"PYTHONPATH": "/capture",
              "CALMA_CAPTURE_OUT": f"/capture/calls_{i}.jsonl", "CALMA_CAPTURE_HOOKS": hooks,
              "PYTHONHASHSEED": "0", "TZ": "UTC", **({"CALMA_CAPTURE_TARGETS": json.dumps(targets)} if targets else {})})
        ...  # pull capture file, same recompute path
```

The capture shim, env vars, per-run capture file, and downstream recompute are **identical** to E2B — the only
new surface is the Modal transport. Factor the shared "stage + k-run + pull capture" loop out of `e2b_runner.py`
into a small `runner/_effector_common.py` so E2B and Modal share it (avoids drift; keeps FCR logic in one place).

### 7.2 GPU image (`_gpu_image`)

Modal `Image.debian_slim(python_version).pip_install(_ML, _GENOMICS, _NOTEBOOK).pip_install("torch",
index_url="https://download.pytorch.org/whl/cu121")` — mirror `e2b_template.py` but with **CUDA wheels** instead
of `_TORCH_CPU`. Add `cupy-cuda12x`, and detect `jax[cuda]`/`tensorflow` from the repo's pins at runtime (same
residual-install pattern). Build once, Modal caches it.

### 7.3 Detect the GPU need → route

Two triggers, both already half-present:

- **Reactive (primary).** `runner/build.py:333` `_FAILURE_TAXONOMY` already classifies `CUDA`/`nvidia` failures as
  `needs-gpu` (also `run_spike.py:36`; `cache.py:99` marks it non-cacheable). Wire: a CPU E2B run that fails with
  `needs-gpu` **and** `tier.allow_gpu` **and** Modal configured → automatically **retry on `modal-gpu`**. This is
  the cleanest UX: try cheap CPU first, escalate to GPU only when the code truly needs it.
- **Proactive (cheap static hint).** In `tools_static.py`, scan for `import torch` + `.cuda`/`.to("cuda")`,
  `cupy`, `jax[cuda]`, `tensorflow-gpu`, or `nvidia-*`/`+cu` in requirements → mark the approach `needs_gpu` so
  the orchestrator ranks a GPU approach first instead of paying a doomed CPU attempt. Keep it a *hint*, not a
  gate (determinism-first: CPU still tried unless the static signal is strong).

Add `modal-gpu` branches to the four dispatch sites (`pipeline.py:350,531`, `run_spike.py:61`, `server.py:396`).

### 7.4 Tier gate + GPU-minutes meter

- **`core/limits.py`:** add `allow_gpu: bool = False` and `gpu_minutes_month: int = 0` to the `Tier` dataclass
  (near `cpu_cores`, `limits.py:54`); set `allow_gpu=True`, `gpu_minutes_month=120` (say) on `enterprise` (and
  `owner`); leave `free`/`pro` at `False/0`. Add a **hard GATE** branch in `clamp_request` (`limits.py:402`,
  mirror the `acquire_data` gate at `:412`) keyed on a `needs_gpu` request flag → refuse for non-enterprise with
  the standard upgrade message. GPU is the most expensive capability we run — gate it like `fetch_data`.
- **Meter.** Extend the existing `/api/cost` telemetry (already emits `sandbox_seconds`). Modal exposes GPU
  seconds; multiply by the per-second rate table (§1) for a dollar estimate, accumulate a per-tenant
  `gpu_seconds_used` (same store as rate-limits, `calma-security-ratelimits`), and **refuse once
  `gpu_minutes_month` is exhausted** (clamp, not crash). Surface remaining GPU minutes in the tier chip.

### 7.5 Config + rollout

`fly secrets set MODAL_TOKEN_ID=... MODAL_TOKEN_SECRET=... CALMA_MODAL_GPU=A100`. Flag-gate the whole runner
behind `CALMA_ENABLE_GPU` (default off) so it's inert until proven — same discipline as the orchestrator flag.

**Tests / gate:** a GPU-only repo (CUDA-required) → routes to Modal → CONFIRMED with GPU-seconds metered;
same repo on `pro` tier → hard GATE refuse; a CPU repo → never touches Modal (cost guard). FCR==0 across all.

---

## 8. Phase 5 — Data behind auth / huge downloads (acquisition hardening)

The acquisition phase exists (`runner/acquire.py` finds `01_download.py`/Makefile `data` targets; runs them
bounded, `_MAX_STEPS=12`; tier-gated via `allow_data_acquisition`, `limits.py:58`). Today it runs with **full
internet** and **no secret injection** (`e2b_runner.py:321-334` runs `python <script>` with only the sandbox's
own env; `:360` builds `envs` with no creds). Three gaps to close, in priority order.

### 8.1 Per-tenant secret store → inject into the ACQUIRE sandbox only

- **Store.** Encrypted-at-rest per-tenant secrets (`HF_TOKEN`, `AWS_*`, `GCP_*`, `KAGGLE_*`), keyed by tenant,
  reusing the security layer from `calma-security-ratelimits`. API returns names + metadata only, never values
  (SOTA convention — opencomputer/Deno pattern).
- **Injection.** Add the tenant's secrets to `envs` **only for the acquire commands** (`e2b_runner.py:321-334`),
  **not** the eval run loop (`:355`) — the recompute stays credential-free, preserving FCR. In E2B this is env
  injection (the acquire code *does* see the token). Mitigate the exposure two ways below.
- **Gold-standard note (defer).** The strongest model (Deno Sandbox / iron-proxy / Cagent / opencomputer) never
  lets the VM see the raw token — a host-side proxy swaps a placeholder for the real value at the network layer,
  scoped per host. That's a proxy subsystem; **v1 uses scoped-token env injection + egress allowlist** (below),
  which gets ~90% of the protection for ~10% of the build. Put network-layer injection on the roadmap.

### 8.2 Egress allowlist during acquire (use E2B's real feature)

This is the mitigation that makes env-injected tokens safe: **a leaked token can only egress to the data host.**
E2B supports it natively (research-confirmed):

- Create/`update_network` the acquire sandbox with `allow_out = [<data hosts>]` + `deny_out = ["0.0.0.0/0"]`
  (domain filtering works on 443 via SNI / 80 via Host). Default allowlist for HF: `huggingface.co`,
  `*.hf.co`, `cdn-lfs.huggingface.co`, `*.amazonaws.com` (HF LFS backing). Per-tenant/per-job extensible.
- Wire it at `e2b_runner.py:297` (`_create_sandbox`) — pass an `allow_out` alongside the existing
  `allow_internet` toggle; or flip to `update_network` right before the acquire loop and clear it right after,
  so the **eval** run is fully network-denied again. (E2B's `update_network` replaces rules on a live sandbox —
  no restart.) Caveat: domain filtering is 80/443 only; anything exotic falls back to CIDR.
- Honesty: log the effective allowlist in the job log ("acquire egress limited to: huggingface.co, …").

### 8.3 Disk budget + streaming

- Bigger ephemeral disk for acquire (E2B template `disk`, or Modal `ephemeral_disk`), tier-scaled
  (free: none, pro: N GB, enterprise: more) — add a `disk_gb` field to `Tier`.
- Prefer **not** downloading the world: for HF, `datasets` streaming (`streaming=True`) or `hf-mount` lazy
  filesystem fetches only the bytes touched (research-confirmed: FineWeb 45 TB usable without full download).
  Recommend/rewrite acquire scripts toward streaming where the recompute only needs a slice.
- Use **fine-grained, short-lived, read-scoped** HF tokens (HF best practice for CI) so a leak is low-blast-radius.

### 8.4 Connect / upload UI — the safe alternative (web)

The zero-in-sandbox-creds path: let the user **upload the dataset** or **connect a bucket** (pre-signed URL /
read-only role) so no tenant secret ever enters an untrusted sandbox. Medium web work in `web/` (a
dashboard "Data" step: upload or paste a connection). This is the *preferred* path for the security-conscious;
secret-injection (8.1) is the convenience path. Ship the upload path first — it's safer and simpler than secrets.

**Tests:** gated HF dataset with a scoped token → acquires under the allowlist → recompute CONFIRMED; the same
token proven unable to egress off-allowlist (a `curl evil.com` in the acquire step is blocked); upload path →
CONFIRMED with zero secrets used.

---

## 9. Phase 6 — The two "no-build" wins (verify, then document)

Neither needs code; both need a test that proves they work + a doc line.

- **Custom metric bound by name-match → CONFIRMED on paid.** Enterprise has `allow_ai_plan` on
  (`limits.py`), so the AI plan identifies the metric function → trusted bind → CONFIRMED (or name it in
  Advanced → `targets`). Free stays INCONCLUSIVE by design. **Action:** one integration test on the enterprise
  tier proving a name-matched custom metric lifts INCONCLUSIVE→CONFIRMED; a doc line in the tier matrix.
- **No clear entrypoint.** The orchestrator (`orchestrate.py:133` `rank_approaches` + `planner.plan_repo` on
  ambiguity) already ranks entrypoint candidates and uses the AI plan to pick. **Action:** confirm the
  orchestrator flag is on for paid (`allow_orchestrator`, `limits.py:61`), and that truly-ambiguous repos fall
  back to Advanced → name-the-entrypoint. Numbers only in a PDF/figure = a discovery gap → roadmap item
  (PDF/figure extraction), not this plan.

---

## 10. Cross-cutting: invariants, sequencing, risks

**FCR guard (non-negotiable).** Every phase keeps the recompute independent of the runner/agent. Notebooks,
conda, R/Julia, and GPU all change *how code runs*, never *how the verdict is computed* — the verdict always
comes from `core/artifacts.py` recompute or the capture-then-recompute path. Run the FCR firewall test + corpus
gate after **each** phase; a red gate blocks the merge.

**Sequencing.**
1. Phase 0 (image) — foundation; nothing else lands without it.
2. Phases 1–3 ride Phase 0 as one PR train (thin dispatch wiring each).
3. Phase 4 (Modal GPU) and Phase 5 (data-auth) are independent — parallelize across two work streams.
4. Phase 6 is a test-and-doc pass, do it last.

**Flag discipline.** Every new capability ships flag-gated + inert by default (`CALMA_ENABLE_GPU`,
polyglot template env, secret-store env), mirroring the orchestrator rollout — deploy dark, prove on the corpus,
then enable per tier.

**Risk register.**

| Risk | Mitigation |
|---|---|
| E2B builder run-step API name differs (`run_cmd`?) | 3-line probe build before the full Phase 0 rebuild |
| Image bloat from R/Julia slows all cold starts | separate `-polyglot` template; base stays lean |
| Modal cost blowout (3× sandbox multiplier + GPU $) | enterprise-gate + GPU-minute meter + CPU-first, escalate-only routing |
| Env-injected token exfiltrated by untrusted acquire code | egress allowlist (deny 0.0.0.0/0) + scoped short-lived tokens + prefer upload UI |
| R/Julia run "succeeds" but no recomputable number | INCONCLUSIVE by design; never guess (franchise-safe) |
| GPU routing false-triggers on CPU repos → cost | reactive (needs-gpu failure) primary; static scan is a hint only |
| Template overwrite breaks prod | build under new suffix, flip Fly secret, keep old for rollback |

**Effort (rough).** Phase 0: 0.5d ops. Phases 1–3: ~1–1.5d wiring + tests. Phase 4: ~2–3d (new effector +
gate + meter). Phase 5: ~2–3d (secret store + allowlist + upload UI). Phase 6: 0.5d. Total ≈ 1.5–2 weeks solo,
less if 4 and 5 run in parallel.

**Definition of done.** All phases: corpus gate green + FCR==0; each capability has a CONFIRMED fixture + an
honest-boundary fixture; GPU + data-auth flag-gated and metered; tier matrix + docs updated; nothing enabled in
prod until its corpus run is green.
