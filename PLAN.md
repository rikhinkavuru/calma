# Calma — Pilot-Readiness Hardening Plan

## Context

Calma's OSS skill/CLI already re-executes a result in a **macOS Seatbelt** sandbox and recomputes
the headline number on deterministic kernels (`verdict.py` is the single label authority; no model in
the decision path). That is enough to *demo*, but not enough to run an **untrusted counterparty's**
quant code for a **paid pilot**. The gap to pilot-ready is delivery-hardening, not new deep features:

- Isolation is Seatbelt-only (shared host kernel, no escape isolation). `run()` already *refuses*
  untrusted third-party code because no container tier exists. We need a real containerized runner.
- The deliverable is a terminal render + a signed bundle. We need a **branded report (HTML→PDF)** and
  a **one-command offline replay bundle**.
- Intake does not install deps (it reuses a pre-existing `.calma_venv`). Real managers' repos
  (pandas/vectorbt/backtrader/zipline, R) need robust env capture + pinning + data-binding.
- Trading recipes recompute from a return column but assume costs are pre-applied; there are no
  recipe-level convention/window/survivorship/walk-forward catches.
- Non-determinism is detected statically; we need runtime variance handling that degrades to
  can't-confirm with an actionable unblock.
- The registry chain works but has never been driven by a realistic redacted engagement end-to-end.

**Host reality (confirmed):** Docker CLI is present via **colima** (a Linux VM); daemon is currently
stopped (`colima start` brings it up). Inside colima, containers get real Linux primitives —
`--network=none`, read-only overlay FS, non-root, `--cap-drop=ALL`, seccomp, pid/mem/cpu limits.
This makes WS1 viable **today** for the egress + secret-exfil walls. **What still needs the funded
microVM tier:** kernel-level escape isolation (containers share the colima VM kernel). The container
stamp must say so honestly and never claim "escape-proof."

**Invariants that may never break (carried through every workstream):** deterministic recompute; no
model in the decision path; honesty guards degrade to can't-confirm and never false-confirm;
registry redaction-by-construction (whitelist enforced at append + audit).

**Execution discipline:** implement WS1→WS6 **serially** (shared pipeline surface; no parallel agent
team). Small commits, update `CHANGELOG.md` + `docs/internal/HANDOFF.md`, keep the suite green at
every step (`python3 .claude/skills/calma/scripts/tests/run_all.py`, ~1,588 checks). Every acceptance
criterion is met only with the **exact command + its real output** shown — never "this should work."

---

## WS1 — Hardened, disposable, network-denied execution (GATING)

**Current:** `run_hermetic.py` has one real tier (Seatbelt), stamped `seatbelt-verified` only after
`doctor()` proves a planted-secret read AND egress (raw IP / DNS / curl) both fail under the profile.
Untrusted third-party code is refused (exit 3) because `isolation_tier not in ("container","vm")`.
`verdict.py`/`compare.py` already treat `isolation_tier=="container"` + `container_present` as a
verified tier — so WS1 only has to *produce* that stamp honestly.

**Target:** a pluggable backend abstraction in `run_hermetic.py` — `_BACKENDS = {seatbelt, docker,
firecracker-stub}` with a `(available, doctor, exec)` protocol. `run()` gains an `isolation` param;
`calma.py verify` gains `--isolation auto|seatbelt|docker|firecracker`.

- **Selection:** explicit `--isolation` honored exactly (fail loud, no fallback, if unavailable);
  else `--trust third-party` auto-escalates to `docker`; else default `seatbelt` (today's behavior,
  byte-identical for own-code on macOS).
- **Docker hardening (every flag deliberate):** `--rm --network=none --read-only
  --tmpfs /tmp:rw,noexec,nosuid,size=64m --user 65534:65534 --cap-drop=ALL
  --security-opt no-new-privileges --pids-limit=512 --memory=2g --memory-swap=2g --cpus=2
  --ipc=none -w /work -v <base>:/work:ro`, plus a single writable overlay `-v <base>/runs:/work/runs:rw`
  so outputs reach the host for recompute while the rest of base (incl. `.calma`) stays read-only.
  Default seccomp (never `unconfined`). Image pinned by digest (`python:3.11-slim@sha256:…`),
  pre-pulled (because `--network=none` forbids a runtime pull). Env via the existing `_child_env`
  whitelist passed as `-e K=V` + the determinism env (`PYTHONHASHSEED=0`, `TZ=UTC`, …).
- **In-container doctor GATES the stamp:** the same `_PROBE` runs inside the container (no writable
  mount on the probe); `LEAKS=` empty → stamp `container`; any leak → `host-not-isolated` (untrusted
  → exit-3 refusal; own-code → CAVEAT). Container killed on timeout (`docker kill`) and removed
  (`--rm`).
- **Fail loud:** `DockerBackend.available()` distinguishes CLI-missing / daemon-down (names
  `colima start`) / image-not-present; explicit `--isolation docker` when unavailable → refuse exit 3,
  **never** silently fall back to host.
- **Honest stamps:** `isolation_tier="container"`, `container_present=True`, `run_network="off"`,
  `hermeticity="container-readonly-overlay"`, doctor note: "shares the colima VM kernel; NOT
  escape-isolated (microVM = WS-future)." Firecracker backend is a registered stub that fails loud.
- **WS1 language scope:** Python + shell in-container; other languages under `--isolation docker`
  refuse honestly ("verify under --isolation seatbelt if own-code"). Seatbelt path keeps all languages.

**Files:** `run_hermetic.py` (backends, argv, doctor, run dict), `calma.py` (`--isolation` flag, thread
through), `tests/test_hermetic.py`. Compat watch-item: keep `H._profile/_ancestors/_run_sandboxed/
_venv_python/doctor` callable with identical signatures (the suite imports them by name).

**Acceptance (evidence required):** with `colima start`, a hostile temp repo that (a) opens sockets to
raw IP + DNS + curls out, (b) reads a planted host secret, (c) writes outside `runs/` (incl. `.calma`),
(d) fork-bombs → is fully contained: egress blocked, secret unreadable, out-of-`runs` writes fail,
pids capped, container gone after (`docker ps -a` clean). Run stamped `container`. **Independent
verification:** after I build WS1, a **fresh verification subagent with no implementation context**
attempts to break isolation on the hostile repo (egress, planted-secret read, write outside the
engagement dir). Stamp "isolated" **only if it fails on ALL walls**; otherwise stamp non-isolated and
report what breached. Docker-less CI still runs the dispatch + fail-loud tests (skip-if-unavailable
for the container assertions).

---

## WS2 — The deliverable (signed report + replay bundle)

**Current:** `report.py` renders a strictly-progressive terminal view + an SVG teardown card. `seal`
signs (DSSE + SSHSIG + RFC 3161) and writes `VERIFY-THIS.txt`. `replay` re-runs a saved verification.
A run dir holds `ledger.json/manifest.json/run.json/recompute.json/diff.json/attestation.bundle.json`.

**Target:** a new `calma report <run_dir>` command (new subparser + `report.py:render_html(led, diff)`)
that emits a **self-contained branded HTML** (Calma warm-black/cream/amber, inline CSS, no external
assets, `@media print` for clean PDF) containing: claim under test; verdict + confidence; measured gap
(claimed → recomputed); **explicit scope-of-verification** ("verified X by re-execution; did NOT assess
Y" sourced from `scope.not_verified`); limits statement; isolation + determinism stamps; and the
hashes (`manifest_sha256`, `ledger_sha256`, `contract_sha256`, keyid). PDF via headless print if a
renderer exists, else clear instructions (HTML always prints to PDF from any browser). Plus a
**replay bundle**: `report.py` writes a `replay/` dir (or tar) with the ledger, manifest, contract,
inputs needed, attestation bundle, OpenSSH sidecars, and a `replay.sh` that runs **offline** and
re-derives the verdict byte-for-byte (wrapping existing `replay()` + `attest verify`).

**Files:** `report.py` (`render_html`, `write_replay_bundle`), `calma.py` (`report` subparser),
`tests/test_e2e.py` or new `test_report.py`. Reuse `attest.verify_bundle`, `replay()`, `_TOPLINE`,
`fmt_value`. Keep DSSE/in-toto + RFC 3161 untouched; verifiable with stock OpenSSH.

**Acceptance:** `calma report <run>` on the BTC REFUTED fixture emits a clean HTML that prints to PDF
(show the file + a rendered screenshot) and a replay bundle whose `replay.sh`, run on a fresh dir with
**no network**, reproduces the same verdict (show the command + output).

---

## WS3 — Robust intake for the quant wedge

**Current:** `draft_contract.py` infers a contract read-only; `run_hermetic._venv_python` reuses a
pre-existing `.calma_venv` but nothing **creates** one. No interpreter/dep pinning, no R, no explicit
data-binding capture.

**Target:** an intake/restore step (new `intake.py`, invoked by `verify` before `run`, opt-in via
`--restore`/auto when a manifest is present) that: detects the interpreter (python/R) and pins it;
detects + pins deps from `requirements.txt`/`pyproject`/`environment.yml`/lockfile (or `pip freeze`
into `<base>/.calma_venv`; `renv`/`DESCRIPTION` for R), capturing the resolved env to
`run.json`/manifest; and **binds claimed data explicitly** (record the data file + sha256 into the
contract so the recompute reads the same bytes). Network is needed only for dep install → it happens
**before** the network-denied run, in a clearly-marked restore phase (never inside the verified run).
Honest stamps when restore is partial.

**Files:** new `intake.py`; `draft_contract.py` (data-binding capture); `run_hermetic.py` (consume
the restored venv — path already supported); `calma.py` (`--restore`); tests + 3 vendored messy repos
under `assets/corpus/`.

**Acceptance:** intake succeeds unattended on **3+ messy public repos** with declared-but-loose deps
(at least one pandas/numpy backtest, one backtrader/vectorbt, one R) — show each repo restoring +
running to a recompute.

---

## WS4 — Backtest checks that catch the common inflated-deck failures

**Current:** `recipes.py` recomputes `total_return/sharpe/max_drawdown/...` from a return column;
Sharpe annualizes with `periods` (252/365/52) and rf=0; costs assumed pre-applied; walk-forward is a
contract/data concern (the BTC fixture bakes it into the entrypoint). No recipe-level convention,
window, survivorship, or net-vs-gross catches.

**Target:** make the boring catches reliable, each **stating its assumption** (not the M3–M4 forensic
battery):
- **Net-of-cost returns:** apply the stated fee/slippage model to a position/trade column; flag
  **gross-sold-as-net** when the claim's return omits declared costs. New recipe + binding tags.
- **Sharpe convention:** verify rf, annualization, and periodicity against the claim; flag mismatched
  convention rather than silently rescaling.
- **Period/window checks:** claimed window vs available history; flag cherry-picked sub-windows.
- **Universe checks:** point-in-time vs survivorship (flag when the universe is survivorship-biased).
- **Walk-forward / OOS re-run** where the claim implies it (in-sample claim vs OOS recompute — the
  BTC pattern, generalized to a recipe-level check).

Each catch emits a finding with a concrete locator + unblock and degrades conservatively (never
REFUTE on an unconfirmed assumption — honesty guard).

**Files:** `numeric.py` (cost/window kernels), `recipes.py` (new recipes + tags), `draft_contract.py`
(claim hints + convention inference), `verdict.py`/`compare.py` (finding dimensions), reference
vectors in `calibration/gen_reference_vectors.py`, `tests/test_recipes_sota.py`. **Discipline:** new
recipes ship only with reference-vector validation or compiler-gate admission.

**Acceptance:** **planted** versions of each failure (omitted costs, wrong window, survivorship,
deck≠code) are each caught and clearly explained — show the verify output for all four.

---

## WS5 — Graceful handling of THEIR non-determinism

**Current:** `--check-determinism` re-runs and flags FLAKY → INCONCLUSIVE; `verdict.py` blocks REFUTED
on uncontrolled/insufficient-K. Static AST detection exists; runtime variance handling is thin.

**Target:** detect when the counterparty's code won't reproduce (seeds, threads, timestamps) via
**repeated-run variance detection** (already partly present — strengthen `k`-spread thresholds and
make `--check-determinism` the default for third-party trust), set seeds where the contract allows,
and when it still won't reproduce, **degrade to can't-confirm with a precise, actionable fix line**
(e.g. "outputs differ across identical re-runs by X; set seed=… / pin thread count / freeze the
timestamp, then re-run"). Messaging frames it as **rigor, not failure**.

**Files:** `run_hermetic.py`/`recompute.py` (variance capture), `verdict.py` (`outputs_unstable` path,
already present — wire the fix line), `report.py` (`_FIXES` line), `tests/test_hermetic.py`/`test_verdict.py`.

**Acceptance:** a deliberately non-deterministic repo yields **can't-confirm + the exact unblock**,
never a false-confirm or false-refute — show the output.

---

## WS6 — Registry end-to-end dry run

**Current:** `registry.py` append-only hash chain, SSHSIG-signed entries + HEAD, `ALLOWED_FIELDS`
whitelist enforced at append + audit, `registry verify`. Genesis entry exists.

**Target:** push **one realistic REDACTED mock engagement** through the full pipeline: intake (WS3) →
isolated run (WS1) → recompute (WS4) → signed bundle (WS2/seal) → `publish` append to the chain.
Verify redaction-by-construction holds (claim/metric/gap/verdict/hashes only — never code, data, or
positions) and the chain still verifies.

**Files:** no new code expected (exercise existing `seal --publish` + `registry verify`); a scripted
dry-run under the rehearsal harness; possibly a `--registry` scratch dir to avoid touching the real
genesis chain.

**Acceptance:** a mock entry lands, `registry verify` still passes, and an explicit field-scan shows
no sensitive field leaked — show the entry JSON + the verify output.

---

## Dress rehearsals (ties it together)

A repeatable harness (`rehearsals/run_rehearsal.sh` or `benchmark/`-adjacent) that runs the WHOLE
pilot pipeline on **real public quant repos with published return claims**: the existing BTC
walk-forward, a **backtrader** strategy, and an **R** one. Each produces: an isolated run, a recompute,
a signed bundle, a report (WS2), and a redacted registry entry (WS6). Capture what broke, fix it,
write **`REHEARSALS.md`** with the catches found (these double as outreach case studies).

---

## Sequencing & priority

1. **WS1** (gating) → fresh-verifier isolation audit before stamping isolated.
2. **WS2** (gating deliverable).
3. **WS3 → WS4 → WS5**.
4. **WS6** + **dress rehearsals** (+ `REHEARSALS.md`).

Flag explicitly in each commit what colima-Docker delivers vs what needs the funded Linux/microVM
tier. Keep the ~1,588-check suite green at every step; update `CHANGELOG.md` + `HANDOFF.md`; bump
version when WS1 lands. After approval, I'll also commit a repo-root `PLAN.md` mirroring this.

## Verification (end-to-end)

- Full suite: `python3 .claude/skills/calma/scripts/tests/run_all.py` (must stay green).
- WS1: `colima start`; hostile-repo containment test + fresh-subagent break attempt.
- WS2: `calma report <run>` → HTML/PDF + offline `replay.sh` re-derives verdict.
- WS3: 3 messy public repos restore + run unattended.
- WS4: four planted failures each caught.
- WS5: non-deterministic repo → can't-confirm + unblock.
- WS6: mock redacted entry appends; `registry verify` passes; no field leak.
- Rehearsals: BTC + backtrader + R each produce run/recompute/bundle/report/registry-entry.
