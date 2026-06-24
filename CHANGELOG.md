# Changelog

All notable changes to the calma skill/CLI. Dates are UTC.

## Unreleased — `FLAG_FOR_DECLARATION` · OTel-eval wedge · streaming recompute · IDD/ODD report · input lineage

- **Input-lineage / content-hash provenance attestation** (`lineage.py`, W8(d)) — the operational form of the
  L2 "input-data authenticity" ceiling. A three-tier in-toto Statement v1 (`predicateType
  https://calma.dev/InputLineage/v1`): tier-1 content hash (what we have), tier-2 a declared source manifest
  (uri / retrieved-at·by / the transport digest hashed AT FETCH TIME / provider immutability handles), tier-3
  an optional fund-admin-NAV corroboration (`corroborate_nav` recomputes the period return implied by an
  administrator's NAV and diffs it against the headline under the recompute tolerance → matched / mismatch /
  unavailable — the only tier touching external reality). Every statement carries a FIXED, always-present
  `proves` / `does_not_prove` honesty block so the deliverable can never over-claim provenance (hashing ≠
  truth). `transport_integrity` chains tier-1↔tier-2 to flag tamper. `evidence_json` gains a `provenance`
  field (the W7 connector's `lineage.json`, else the honest tier-1-only default that says exactly that no
  source manifest was recorded), surfaced in IDD-REPORT §6. The W7 BYOC connector that *populates* tier-2/3 at
  fetch time + the attest/Rekor signing of the predicate land with W7; this ships the layer + the math.
  `tests/test_lineage.py` (18 checks); `test_evidence_bundle.py` → 46.

- **Evidence bundle → the IC-acceptable IDD/ODD deliverable** (`evidence_bundle.py`, M-8c.1). The bundle
  graduates from a one-page cover sheet into a multi-section IDD/ODD report — still a **pure re-projection**
  (no verdict is decided; no number is recomputed). `evidence_json` gains five fields: an `examination_statement`
  (GIPS-scoped: "a metric-level performance examination, not a firm-wide GIPS verification"), `input_data_treatment`
  (the GIPS Input-Data #9 row — net-of-fees / costs-included / survivorship / look-ahead, each `declared` or
  `not declared`, surfaced from the contract blocks), a `ddq_performance_module` (the AIMA Performance-Presentation
  Q&A), an `odd_analyst_checklist` (a signable per-family ✅ checked / ⚠️ flagged / 🚩 flag-for-declaration / ⛔
  not-assessed table — the **inferred-flags** from M-8b.2 surface here as 🚩), and three fixed, always-present
  `limitations` clauses (L1 reproducible≠correct · L2 input-data authenticity · L3 scope-is-the-declared-scope —
  the load-bearing ceilings that keep the report from over-claiming, i.e. what makes it signable). `build_evidence`
  now also writes `IDD-REPORT.md` + a styled `IDD-REPORT.html` (8 sections) alongside the existing `EVIDENCE.md`
  cover (back-compat). `tests/test_evidence_bundle.py` extended (42 checks).

- **Streaming recompute past the 256 MB artifact cap** (constant-memory folds). A recipe opts in via a
  `streaming` block in its manifest; when its artifact is over the streaming threshold (default: the eager
  byte cap) the recompute runs as a constant-memory fold instead of a whole-file load — so a legitimate
  multi-GB artifact verifies instead of degenerating to CAN'T-CONFIRM at the cap. **Bit-identical** to the
  in-memory recipe (the additive reducers use an incremental Shewchuk exact-sum accumulator — the same
  algorithm `math.fsum` implements — so `column_sum`/`column_mean` match to the bit; `max_drawdown` is an
  order-stable online fold; `row_count` is an exact count), K-run spread stays 0, and the 600+ recipes that
  don't opt in are unchanged. The DoS guarantee is preserved differently for the streaming path: a
  regular-file check, a per-field byte cap, and a row wall (`CALMA_MAX_STREAM_ROWS`) — the 256 MB cap still
  guards the eager path and a non-streaming recipe over the cap still degenerates. New `scripts/stream_reduce.py`
  + `pathsafe.iter_csv_chunks` + a `recompute._run_streaming` branch (parquet via the existing
  `io_parquet.iter_batches`). Also a **grouped per-era fold** (`streaming.class == "grouped"`): a contiguous-
  group regrouper streams the multi-GB **era-sorted Numerai validation** file one era at a time (memory = one
  era + one float per era), computing each era's CORR in-memory and aggregating — so `numerai_corr` /
  `numerai_sharpe` verify over the cap, bit-identical to the in-memory per-era recipe (`fmean`/`fstd` over the
  exact `fsum` are order-free); a non-group-sorted file degenerates honestly. And a **Class-B fold**
  (`streaming.class == "quantile"`): `column_median` / `percentile` stream via an EXACT external merge-sort
  (`ExternalSortQuantile` — each chunk is sorted + spilled to a temp run, then a k-way heap-merge streams the
  globally-sorted sequence to the target rank), bit-identical to `numeric.quantile` over the fully-sorted
  vector (a merge of sorted runs is the same total order; `struct` round-trips doubles losslessly) — exact,
  not a t-digest approximation. `tests/test_streaming.py` (50 checks: bit-identity per kernel incl.
  median/percentile, exact-sum vs `math.fsum`, the grouped Numerai fold, the external-sort spill+cleanup,
  over-cap verification, the DoS guards). Only `total_return` (its pairwise-product tree differs at chunk
  boundaries — bit-stable but not bit-equal; and a >256 MB single return column is unrealistic) remains deferred.
- **New verdict: `FLAG_FOR_DECLARATION`** (closes the "declare-nothing → only soft smells fire" hole).
  When the headline number reproduces but the artifacts carry positive, multi-signal structure that would
  invalidate it if it is what it looks like (an inferred train/test split with real row-overlap; a strong
  regime break; an undeclared trials matrix) and the producer declared **nothing**, the verdict is a
  louder-than-caveat, weaker-than-`INVALIDATED`, IC-visible **demand to declare the block** — resolvable in
  one move, never a guessed verdict-flip (`INVALIDATED` stays declaration-gated). Rank
  `REFUTED ≥ INVALIDATED > FLAG_FOR_DECLARATION > MIXED > CAVEATS`; it blocks the gate / Stop hook and
  renders with an amber-red `⚑`. Threaded through `verdict.py`, `ledger.py`, `report.py`, `calma.py`,
  `hook_stop.py`, the OTel mapping, the IDD/ODD checklist, and the **PR-bot + MCP merge gate** (CANONICAL §3:
  `pr/render.py` `check_conclusion` now maps FLAG → a failing GitHub Check-Run, so a flag blocks the merge —
  the gating claim is enforced, not just asserted). +9 verdict + +9 ledger unit-checks; pr 30/0, mcp 10/0.
- **The inference detectors that PRODUCE `FLAG_FOR_DECLARATION`** (`infer_validity.py`, M-8b.2) — the
  declare-nothing kill-shot closer. Runs in `_assemble_ledger` after plausibility (so a soft CAVEAT is in
  place first; the flag overrides it). Three governed detectors, each reusing existing machinery and each
  suppressed when the authoritative family was declared: (1) an undeclared train/test split with real
  row-overlap on an OOS claim → flag the split; (2) a strong regime break (two-sample KS p≪α + a variance
  shift) on a forward/robust claim → flag a `windows:` block; (3) an undeclared trials matrix alongside an
  implausibly-high Sharpe → flag the trials. Each names the exact block to declare; `apply_validity` sets
  `flag_for_declaration` but **never** `validity_invalidated` (the verdict-flip stays declaration-gated),
  and only ever promotes a reproduced (CONFIRMED/CAVEATS) headline. `tests/test_infer_validity.py` (21
  checks). Zero false-flags on the benchmark corpus (no honest case asserts the OOS/forward scope the
  detectors require); benchmark `_predict` maps FLAG→flawed.
- **OTel-eval distribution wedge** (`calma verify --emit-otel [URL]`, `from calma.otel import emit_verdict`).
  Emit each verdict as a standard **OpenTelemetry GenAI evaluation result** (`gen_ai.evaluation.name=`
  `calma.<metric>`, `.score.value`=the recomputed number, `.score.label`/`.outcome` from the verdict, plus
  `calma.*` differentiators) over OTLP/HTTP — **pure stdlib, zero dependency on the OTel SDK** — so any
  agent-observability backend (Braintrust / LangSmith / Langfuse / Phoenix) ingests Calma as a **drop-in
  deterministic eval source**. Redaction-by-construction (no raw data leaves), idempotent (keyed by run id),
  optional native-namespace dual-emit, honors `OTEL_EXPORTER_OTLP_ENDPOINT/HEADERS`. New
  `scripts/otel_eval.py` + `src/calma/otel.py` facade (adds the optional OTel-SDK span-event mode);
  `tests/test_otel_eval.py` (44 checks, incl. a hermetic `http.server` OTLP-capture ingest test). The
  **TypeScript half** ships too — `@calma/otel` (`packages/calma-otel/`, `import { emitVerdict,
  CalmaSpanProcessor } from "@calma/otel"`): a faithful mirror so JS/Next agents + apps emit the same span
  (same mapping, same redaction, `fetch`-based OTLP, no OTel-SDK dependency). 9/9 via `node --test` incl. its
  own hermetic node-http ingest test; `tsc` clean (the root Next build excludes `packages/`).
- Firewall preserved: both are engine-pure and only ever *consume* a finished verdict — no model in any
  verdict path. `make eval` green.

## 0.12.0 — M4 bespoke-metric onboarding · live agent-arm benchmark · transparency-log + e2b

- **M4 — CEGIS bespoke-metric onboarding** (`calma onboard`): point calma at a one-paragraph
  methodology + a handful of your own reference numbers for a metric it doesn't already cover; an AI
  drafts a checker and the deterministic gate (`compiler.admit`) proves it against those reference
  vectors (+ metamorphic + degeneracy + bit-stability) before it is ever allowed to run. Front door
  `calma onboard` + a worked example (coefficient-of-range).
- **Live agent-arm benchmark, measured**: a code-running agent (Claude Haiku 4.5 + GPT-4o-mini) that
  re-runs the math and judges the number ties calma on raw accuracy (~84% catch) but flips its verdict
  on 10–52% of identical reruns, misses half-to-four-fifths of the reproduces-but-invalid cases, and
  costs ~$5 / ~38s a check — vs calma's deterministic ~0.2s, $0, with a signed replayable proof.
- **Benchmark hardening**: a cited validity catalog (≥8 INVALIDATED per family with cited provenance,
  honest misses written down).
- Also folded in from the prior `Unreleased` blocks (full notes below):
  - Optional **Sigstore Rekor** transparency-log backing for the catch-history registry.
  - The **`e2b` remote-microVM isolation tier** (Docker-less untrusted-code verification).

### optional Sigstore Rekor transparency-log backing for the catch-history registry

Additive, belt-and-suspenders **on top of** the registry's custom hash-chain — never a replacement.
When a Rekor endpoint is configured (default: **none**), each published registry entry is also logged
to a [Sigstore Rekor](https://github.com/sigstore/rekor) transparency log (Apache-2.0, self-hostable),
and the returned inclusion proof is stored alongside the entry so third parties can verify the
append-only property **offline** with `rekor-cli` or `calma registry verify`. Full suite green,
incl. the new `tests/test_rekor.py` (32 checks: unit + a stub-Rekor-over-HTTP integration arm).

- **New `scripts/rekor.py`** (pure stdlib): RFC 6962 Merkle inclusion-proof verification, `hashedrekord`
  + `dsse` entry construction, the networked `log_entry` (the only egress), and the offline verifier.
  The RFC 6962 math is cross-checked against a reference Merkle tree over tree sizes 1..129.
- **Rekor v2 entry-type constraint enforced.** v2 (GA Oct 2025) supports only `hashedrekord` + `dsse`;
  it dropped `intoto`/`rfc3161`. Calma logs registry entries as `hashedrekord` over the entry's content
  address and **hard-rejects** the dropped types (`assert_v2_entry_type`). v2 is the default; a pinned
  self-hosted v1 is opt-in via `--rekor-v1`.
- **Offline, log-independent verification.** The stored proof re-verifies with pure local Merkle math,
  cross-checked against the registry entry's content address — tamper the entry, the proof, the root, or
  the witnessed digest and it fails. Two honesty tiers (mirroring the RFC 3161 discipline): `merkle`
  (proof folds, root self-asserted) and `anchored` (a pinned `--rekor-log-key` verifies the checkpoint
  signature). `calma registry verify` re-checks every stored proof offline and fails the audit on a
  present-but-broken one.
- **Hermetic ordering is explicit and load-bearing.** Logging happens strictly **after** the verdict is
  finalized and the entry is signed; `registry.append_entry` builds the wrapper in memory, logs to Rekor,
  and only **then** commits the files — so under the **fail-closed default** a Rekor failure writes nothing
  (no silently un-logged entry). `--rekor-optional` opts into fail-open. The Rekor block is wrapper-level,
  so the entry's content address and SSHSIG bytes are byte-identical with or without it (redaction
  whitelist untouched). Rekor can never alter a verdict, recompute, or determinism stamp.
- **CLI.** `calma publish … --rekor <URL> [--rekor-optional] [--rekor-log-key HEX|FILE] [--rekor-v1]`
  (also `seal --publish` and `$CALMA_REKOR_URL`); `calma registry verify … --rekor-log-key HEX|FILE`.
- **Docs.** New `docs/rekor.md` (self-hosting via docker-compose, the v2 constraint, offline verification,
  the `rekor-cli` equivalent for third parties); README + SKILL + `references/script-interfaces.md` updated.

### `e2b` remote-microVM isolation tier (Docker-less untrusted-code verification)

Purely additive. A host **without Docker** can now run `--trust third-party` workloads under
hardware-grade isolation instead of the exit-3 refusal, by selecting a remote Firecracker microVM.

- **New tier `--isolation e2b`** (`scripts/run_hermetic.py`): a remote Firecracker microVM behind the
  SAME `(config, doctor, exec)` protocol as the Docker tier (`_run_e2b_backend` mirrors
  `_run_docker_backend`). The verdict layer treats it as a verified VM tier with no special-casing.
- **Two deployments, one code path, zero vendor lock-in.** E2B **cloud** OR a **self-hosted** E2B / raw
  Firecracker cluster, selected by config — **no hard-coded vendor endpoint**. Required config (env or a
  JSON file at `CALMA_E2B_CONFIG`): `CALMA_E2B_ENDPOINT`, `CALMA_E2B_API_KEY`/`_TOKEN`,
  `CALMA_E2B_TEMPLATE`; optional `CALMA_E2B_SELF_HOSTED=1`.
- **Stamp values:** `e2b-firecracker` (cloud) and `e2b-firecracker (self-hosted)` — registered in all
  five verified-tier sites (run_hermetic, calma, hook_stop, compare, verdict). The self-hosted stamp
  records provenance **without ever leaking the endpoint URL**.
- **Network DENIED in-guest, fail-closed.** The tier is stamped verified ONLY after the in-VM `_PROBE`
  egress battery (raw IP, DNS, curl) all fail; if the SDK can't even express network-deny at construct
  time, it **refuses (exit 3)** rather than boot with the network up. Missing/invalid config → exit 3
  naming exactly what's absent. No secrets in logs, stamps, or the replay bundle.
- **Determinism path untouched.** The microVM only *produces* raw outputs (retrieved to the host run
  subtree); recompute/compare run host-side over those bytes — the VM never participates, so the tier
  adds no nondeterminism.
- **Optional dependency.** The E2B SDK is lazily imported only when `e2b` is selected (`pip install
  e2b`); core installs without it keep working and simply can't pick the tier. E2B is Apache-2.0 and
  Terraform-self-hostable.
- **Tests** (`tests/test_e2b.py`, 40 checks): interface completeness, the network-deny assertion
  (verified + both fail-closed paths), missing-config → exit 3, a **no-Docker smoke path** (Docker
  absent → `--trust third-party --isolation e2b` reaches a verdict, not exit 3), recompute-over-
  retrieved-outputs == `e2b-firecracker` end-to-end with secret-hygiene scan, and the anti-drift
  lockstep across all five tier sites. A live spawn/exec/recompute pass is gated behind `CALMA_E2B_LIVE`
  so credential-less CI skips it. Full suite green (34 suites, 0 failed).

## 0.11.0 — engineering roadmap: tournament ICP · distribution · transparency log

The research-backed engineering roadmap, executed end-to-end (22 commits), plus a full adversarial
stress-test loop. `make eval` is now a **5-gate** standing net (core suite + framework golden-vectors +
the recompute-only validity-gap baseline + a byte-identical determinism check + a recipe-coverage
no-regression gate); **71 core suites / 0 failed**; the verdict stays one byte-re-derivable deterministic
function.

- **Two new validity families (now 13).** **Era-embargo / purged-CV** (`embargo_checks.py`) — the Numerai
  8-era/20-day · 16-era/60-day purge gate (the López de Prado purge+embargo form) + the leading-era CORR
  inflation premium; INVALIDATES an un-purged tournament split whose metric still reproduces. **Risk-sim
  `simulation_assumptions`** (`simulation_assumptions_checks.py`) — Chaos/Gauntlet per-block invariants:
  ≤1 liquidation/account/block, a VaR labeled p99 that is really the p95, calibration-window look-ahead,
  the close-factor bound.
- **New tournament recipes (625 → 628).** `mmc`, `feature_neutral_corr`, `max_feature_exposure` —
  Tier-1-validated against the official **numerai-tools** to ≤1e-9 (a pure-stdlib Gaussian-elimination
  neutralize/lstsq + a feature-SET binding); plus a **deflated-AUC** selection-overfit haircut beside the
  Deflated-Sharpe rail.
- **Distribution + ingestion.** `pip install calma` (library-first: `from calma import verify`) + a
  non-root multi-stage Dockerfile + a packaging CI that smoke-tests the installed wheel + the firewall;
  **optional parquet** (`pip install calma[parquet]`, lazy/firewalled pyarrow) for tournament data, with
  a CI test asserting the pure-stdlib core import graph stays third-party-free.
- **The proof model upgraded — calma is now its own RFC 6962 transparency log.** `calma registry
  proof|verify-proof` emits self-contained **`.proof` bundles** (inclusion proof + a signed checkpoint +
  external-witness cosignatures) that re-verify **offline**, with no calma server, years later.
- **Coverage, made legible.** `benchmark/coverage_report.py`: **597/628 = 95.1% of recipes are
  independently verified (Tier-1)** — live framework / numerai-tools / a frozen numpy·scipy·sklearn vector
  — with a `make eval` gate that won't let the ratio regress.
- **Adversarial stress-test loop (clean).** A path-traversal in `regrade_committed` (out-of-base read)
  closed + the artifact byte-cap unified across all 13 detector readers (DoS defense-in-depth); the
  flagship `calma init numerai` permanent-CAN'T-CONFIRM dead-end fixed (`era` → `STRING_KEY_TAGS`); crash
  + a `ledger_sha256` determinism bug in the new families fixed; 3 HIGH false-advertising lines corrected
  with a new README `## Limitations` (reproducible ≠ right; not investment advice).

### Also in 0.11.0 — the earlier producer-side guardrail work

Repositioned as **an automatic guardrail for AI-generated results** (catch your own wrong number
before it ships):

- **V6 — statistical plausibility (`plausibility_checks.py`)**, the first **thin-input** validity
  family: flags an implausibly-high Sharpe and a too-smooth (lag-1 serial-correlation) equity curve
  from the bound return series **alone**, with no declared block. SOFT-ONLY — degrades a reproduced
  number to CONFIRMED-WITH-CAVEATS with a precise `fix:`, never INVALIDATED/REFUTED. (11 families now.)
- **CAN'T-CONFIRM → a structured `needs` demand** (`report.needs_demand`): an INCONCLUSIVE `--json`
  verdict now carries a typed `needs` (what could not be verified + exactly what to provide to resolve
  it), alongside the existing `fix:` line.
- **`calma draft <repo>`**: point Calma at a messy repo and get a runnable `verify.yaml` — heuristic
  by default (detects entrypoint/metric/split/trials + prints a coverage map of detected & suggested
  blocks); `--ai` runs the LLM drafter + counterexample-repair loop (`python -m edges.contract`),
  falling back to the heuristic when the edges deps / API key are unavailable.
- **Conservative block auto-inference in the drafter**: auto-declares the safe, degrade-only blocks
  (a `trials_artifact` when a trials/grid-search CSV is present; split already detected) and *suggests*
  the verdict-flipping ones (a date column → `windows`/`availability`; a return metric → `frictions`).

Tests: `test_plausibility_checks` 14, `test_needs_demand` 12, `test_draft_cmd` 9, `test_draft` 43;
full core suite **43/0**.

## 0.10.0 — pilot-readiness: autonomy modes, agent-arm benchmark, hardening

Pilot-hardening cut after an end-to-end audit (every CLI surface, the validity teardowns, the offline
attest/handover chain + tamper-resistance, the Stop hook, publish/registry, all five languages, real
repos). Full suite green (31 suites, 0 failed).

- **Autonomy modes.** `--mode ask|suggest|auto` (also `CALMA_MODE` / `.calma/config.json {"mode"}`), in
  `scripts/autonomy.py`. The mode governs follow-on ACTIONS only (seal/RFC-3161-timestamp on a catch;
  retry a missing dep under `--restore`), never the verdict; the verdict is identical across all three
  modes. Outward actions (publish/send) need an explicit opt-in even in `auto`, and every decision is
  logged to `.calma/auto_history.jsonl`. New `tests/test_autonomy.py`.
- **`attest verify <dir>`** resolves the bundle inside a run/project dir, not only the bundle file path.
- **Missing-dependency** run failures now name the fix (`--restore`) instead of a generic message.
- **Verdict reason reconciliation.** After a leakage/realism/overfitting/contamination promotion the
  claim's human reason is recomputed from the final `verdict_inputs`, so a REFUTED/INVALIDATED no longer
  shows a stale "matches within budget" in `--json`, the report, or the Stop hook. Label re-derivation
  (and thus attestation/tamper-resistance) is unchanged.
- **Benchmark: code-running-agent arm** (`benchmark/run_agent.py`): the honest comparison to the
  no-exec judge; measures verdict-instability across reruns, cost, latency, and validity-blind cases.
  `score.py` includes it when `results/agent.json` is present.
- **Recipe count corrected to 623** in the README/SKILL (the registry, `calma recipes`, and the tests
  all agree on 623).
- **The four validity families ship** — leakage, overfitting, execution-realism, and eval/benchmark
  contamination now run on the findings rail, plus the `deflated_sharpe` recipe and the new
  **INVALIDATED** verdict ("the number reproduces, but the result is invalid"). The full mechanics are in
  the four subsections below (previously tracked as two `Unreleased` blocks); nothing remains "named
  roadmap (M3–M4)".
- **Repo hygiene.** Internal/dev docs are no longer shipped to skill/CLI users (kept local).

### Native-Linux own-code isolation tier (bubblewrap)

A no-daemon **bubblewrap** own-code tier beside the macOS Seatbelt tier, gated by the SAME `doctor`
probe battery — so Linux stops being capped at `host-not-isolated` / CONFIRMED-WITH-CAVEATS. Distinct
from the `--isolation docker` path (that one is for *untrusted* third-party code and needs a daemon).
Pure stdlib (shells out like `sandbox-exec`); each step kept the full suite green.

- **bubblewrap wrapper + `bwrap_doctor`.** `_bwrap_argv` builds an unprivileged, no-daemon namespace:
  network OFF by construction (`--unshare-net`), filesystem ALLOWLIST-by-construction (only `/usr`,
  `/lib*`, `/bin`, `/sbin` read-only + the run base are visible, so `$HOME`/secrets/`/root` are simply
  absent — strictly stronger than Seatbelt's denylist), writes confined to the base, and `<base>/.calma`
  re-bound read-only *after* the base (last-mount-wins) so code under test can never plant verdict state.
  `bwrap_doctor` reuses the EXACT secret-read + egress probe battery under bwrap and stamps
  `bwrap-verified` ONLY when the probe ran AND leaked nothing.
- **The stamp never lies.** bwrap absent, the self-test leaking, or unprivileged user namespaces disabled
  (so the probe never runs) → `host-not-isolated`, never a silent verified claim. An EXPLICIT
  `--isolation bwrap` that does not verify is REFUSED (exit 3), never a host fallback; the auto path still
  runs but stamps `host-not-isolated` honestly.
- **Verdict lift.** `bwrap-verified` is wired into every verified-tier consumer (`run_hermetic`,
  `calma.VERIFIED_TIERS`, `hook_stop.VERIFIED_TIERS`, `compare`, `verdict.confidence`); a clean Linux
  reproduction now reaches CONFIRMED (network stamp `off`, hermeticity `vendored-snapshot`) instead of the
  CAVEAT cap, and `calma doctor` + the agent Stop hook auto-pick this OS's native tier.
- **Dispatch.** `--isolation` gains `bwrap`; auto own-code selects bwrap on Linux, Seatbelt on macOS
  (byte-identical on macOS). One mechanism-generic `_exec_native` routes the compile + run steps to the
  achieved tier — the doctor proves the exact wrapper the run uses.
- **Cross-language parity.** Python/shell/C/C++/Rust all run under bwrap. The compiler is re-bound into
  the namespace (the `/usr/bin/cc → /etc/alternatives/cc → gcc` linker hop, and `/etc/alternatives`),
  and the toolchain depots under `$HOME` are re-bound read-only (the same set Seatbelt re-allows:
  `.rustup`/`.cargo`/`.pyenv`/`.conda`/`.julia`/…) so a `$HOME`-rooted rustup/pyenv/conda toolchain
  resolves — `~/.ssh`/`~/.aws` and the planted doctor secret are NOT depots, so the positive-control
  still proves zero leaks.
- **Defence in depth + UX.** Each sandboxed process runs `--cap-drop ALL` + a pure-stdlib seccomp syscall
  denylist (mount/namespace/module/kexec/bpf/ptrace/keyctl/io_uring/… for x86_64 + aarch64) + setrlimit
  caps (file-size/fds/core, opt-in memory) that actually hold (cap-drop removes CAP_SYS_RESOURCE), and
  `/proc/sys` is re-bound read-only so a sandboxed write to a global sysctl (`core_pattern`) can't escape
  to host-root. The doctor reports the applied `hardening` layers and, where the tier can't verify, emits
  the exact fix-line (the `sudo sysctl` to enable unprivileged userns, or `apt-get install bubblewrap`).
- **Adversarially verified, closed-loop.** An in-suite anti-drift guard + a hostile-own-code marquee
  (egress, host-secret reads, out-of-base/`.calma` writes, and global-sysctl writes all denied), an
  `ubuntu-latest` CI job that asserts the lift, and independent fresh red-team/audit agents across
  security / edge / dev / UX / token run to CLEAN — the loop caught and closed a real `/proc/sys`
  host-escape and an rlimit-bypass before sign-off. Verified on real Linux (Ubuntu 24.04 + bubblewrap).

### Validity families (3-4): execution-realism + contamination + the deflated_sharpe recipe

The remaining M3–M4 validity ceiling, built on the leakage/overfitting findings-rail architecture in the
next subsection. Two more validity families plus the direct deflated-Sharpe recipe path. Each keeps the
full suite green. SKILL.md now lists all four families — leakage, overfitting, **execution-realism**, and
**eval/benchmark contamination** — as DELIVERED; nothing remains "named roadmap (M3-M4)".

- **Execution-realism deflators** (`scripts/realism_checks.py`, dimension `execution-realism`, on the
  findings rail) — an optimistic backtest assumes frictionless fills; this deflates the per-period returns
  to declared frictions (transaction cost + slippage **per turnover**, short-**borrow** carry, and a
  square-root **market-impact** term from claimed size vs ADV) and **re-runs the headline recipe net-of-
  friction**. The verdict follows the claim's NET/GROSS scope (`apply_validity` + `net_status`): a
  **net/live** claim whose friction-deflated recompute lands outside budget → **REFUTED** via the gap path
  (the claimed "net" number is really gross — e.g. *claimed Sharpe 3.13 → friction-deflated −0.05*); a
  net/live claim that is **uninvestable at size** (participation = size/ADV ≥ 1) → INVALIDATED; a **gross/
  paper** claim → CONFIRMED-WITH-CAVEATS; an **indeterminate** claim + a material friction → CAN'T-CONFIRM
  ("declare net vs gross"). Activates only on a declared `frictions:{...}` block — a friction the author
  did not declare is never guessed; the older `costs`/`universe` surface stays with `backtest_checks` (no
  double-counting). The REFUTED path clears `convention_capped` (the deflation is convention-identical, so
  a Sharpe annualization choice cannot explain the gap). Square-root impact (`sqrt_impact`) is elementary
  closed-form arithmetic (no special functions → no reference-vector ceremony; exact unit magnitudes).
- **Eval/benchmark contamination** (`scripts/contamination_checks.py`, new dimension `contamination`) —
  broader than leakage's train/test overlap: the *evaluation itself* is contaminated by the model's
  pretraining / a known corpus. Two stdlib detectors: **exact memorization** (an eval item whose
  whitespace-canonical sha256 is present in a declared `corpus:{manifest}` — authoritative) and
  **near-duplicate** (a 32-function minhash over word 3-shingles, Jaccard ≥ 0.80 — LABELED HEURISTIC →
  soft). The verdict follows the claim's HELD-OUT scope (`contamination_status`): exact memorization on a
  **held-out / zero-shot / uncontaminated** claim → INVALIDATED (*the number reproduces, but it is not a
  held-out measurement*); a claim that **allows** contamination (few-shot / in-context) → CONFIRMED-WITH-
  CAVEATS; an **indeterminate** claim → CAN'T-CONFIRM; a heuristic near-dup → always a caveat. Manifest
  absent → NOT-APPLICABLE (the corpus is never guessed). `contamination` added to `ledger.DIMENSIONS` +
  `EXEC_DIMENSIONS`.
- **`deflated_sharpe` registered recipe** (`recipes.py`, family `quant`, the **direct REFUTED path**) —
  a user claims a deflated number (`--metric deflated_sharpe`) and it is recomputed → CONFIRMED/REFUTED,
  complementing the overfitting findings rail. The search is carried in the convention
  (`trials=1000,var_sr=0.002`); per-period Sharpe is computed from the raw returns (never annualised) and
  fed to the frozen `numeric.deflated_sharpe_ratio` kernel. Returns the raw probability (the decision rule
  `1-DSR>0.05` lives in the claim, not the recipe); under-specified search (no trials / N<2) → degenerate
  → CAN'T-CONFIRM, never a guessed pass. Registry → 621 reviewed recipes; `recipe_descriptions.json` and
  the site `app/recipes/data.ts` mirror it.
- **Wiring + composition.** All four families are wired into `_assemble_ledger` and compose **order-safely
  / worst-wins**: each `apply_validity` only ever degrades a still-clean (CONFIRMED/CAVEATS) headline,
  never resurrects a worse one — covered by an extended order-safety test across all four. New
  context-free fresh-verifiers adversarially probed realism + contamination. Reproducible INVALIDATED/
  REFUTED demo fixtures committed under `assets/demos/` (5 fixtures + a README of exact commands).
- **Perf: contamination near-dup is now near-linear (LSH banding).** The minhash near-duplicate pass was
  an O(eval × corpus) all-pairs scan (≈7s for 2000 × 4000, and the eval side was uncapped). It now bands
  the 32-minhash signature into 8 bands of 4 (an `O(eval + corpus)` LSH candidate index), so only items
  sharing a band are compared — the all-pairs compare drops to near-instant, and the old silent
  `_NEARDUP_CAP=4000` corpus truncation is **removed**. The decision is unchanged (exact estimated-Jaccard
  ≥ 0.80 on candidates); the band geometry gives ~98.5% recall at the boundary (~100% for real ≥0.9
  paraphrases) — a soft heuristic, so the rare boundary miss only ever under-flags.
- **UX: INVALIDATED gets a first-class shareable teardown.** `report.teardown_card` + `svg_card` (and the
  `calma teardown` CLI) previously fired only for REFUTED/MIXED, so the new families' headline output —
  the most sellable one — produced no card. INVALIDATED now renders its own framing: *the number
  reproduces (recomputed shown == claimed), but the result is invalid*, led by the evidence (the blocker
  locator + magnitude) and the fix. REFUTED keeps the *claimed X → really Y* framing.
- **Realism depth: sortino + calmar deflation, leverage financing.** The friction-deflated recompute now
  covers `sortino` (a ratio → a clean gap-gated REFUTED when the net collapses) and `calmar` (path-
  dependent via max-drawdown, so a gap-REFUTED is blocked → it routes to INVALIDATED — "the live result
  is invalid" — instead). The net-branch promotion was restructured to *try a gap-gated REFUTED, else
  INVALIDATED*, which also routes a non-finite deflated net correctly. New `frictions.leverage`: a book
  run at Lx pays `(L-1)·borrow` financing per period (folded into the net recompute when a borrow rate is
  declared) and a soft leverage caveat surfaces the un-levered figure + the L× drawdown (no arbitrary
  threshold — any leverage > 1 is noted).
- **`deflated_sharpe` CONFIRMED demo + a multi-family integration test.** A `deflated-sharpe-survives`
  fixture (strong edge → DSR ≈ 0.996 CONFIRMED) mirrors the REFUTED one, so the recipe is shown to be
  two-sided. `test_validity_integration.py` locks the cross-family composition: one contract declaring
  frictions + split + corpus at once assembles to a valid, worst-wins, byte-re-derivable ledger with no
  double-promotion. (Suite: 30 green.)
- **Adversarial audit + hardening (security · UX · token · DX).** A four-axis adversarial audit of the
  whole session's work, fixed closed-loop:
  - *Security.* The new detectors now route every file read (`corpus.manifest`/`eval`, `split.test`, the
    metric `artifact`) through a `_safe_join` containment guard — an attacker-authored `verify.yaml` can
    no longer read or exfiltrate files outside the contract base. The minhash near-dup pass is bounded
    against DoS (a degenerate-band short-circuit + shingle/line caps) so an adversarial near-identical
    corpus stays near-linear instead of O(eval×corpus). A 64-hex eval item that equals a corpus line is
    no longer a false-clean (hex manifest lines also store their content-hash). Terminal output strips
    ANSI/control chars from attacker-derived strings (no verdict-spoofing). `deflated_sharpe` no longer
    raises on `trials=1e999`; manifests read fail-soft on invalid UTF-8.
  - *Correctness.* The `deflated_sharpe` recipe bound a *shadowing* duplicate `_conv_kv` (a finance-pack
    float parser) instead of its own — renamed to `_conv_kv_str` so it provably binds the intended parser.
  - *UX.* A CONFIRMED-WITH-CAVEATS verdict now surfaces the actual caveat (leverage / capacity / fill /
    near-dup) instead of a contradicting "matches the claim" line; every broken stamp (family REFUTED *and*
    INVALIDATED) carries a runnable `reproduce:` replay command; the SVG share-card footer no longer clips
    off the card; the limiter "why" line wraps like the scope lines; the doubled deflation locator and the
    teardown gloss/locator restatement are removed; INVALIDATED's identical claimed==recomputed pair is
    annotated "(reproduces — the result, not the number, is invalid)".
  - *DX.* Unknown `frictions`/`corpus` keys are now rejected (a typo'd friction was silently un-applied);
    the validity surfaces (`split`/`keys`/`features`/`trials`/`var_sr`/`frictions`/`corpus`) are documented
    in `verify.schema.json`; the `deflated_sharpe` convention format is in `recipe_descriptions.json`.
  - *Token.* The doubled locator (~220 B/run), the `not_verified` parentheticals, and a null `magnitude`
    field were trimmed with no signal loss; the hot path stays zero-overhead when no surface is declared.
  - A 7th demo (`realism-soft-caveats`, CONFIRMED-WITH-CAVEATS) rounds out the showcase. Two fresh
    adversaries re-verified the fix set holds with no exploitable bugs and no regressions; the three LOW
    residuals they then noted were also closed: a `_plain` regex-ordering bug (it stripped the ESC byte
    before the CSI match, leaving inert `[31m` litter — now ordered correctly + applied to the SVG card),
    an honest rewrite of the near-dup recall docstring (LSH loses zero recall *vs all-pairs*; the boundary
    is MinHash estimate variance, not a banding effect), and a degenerate-net guard so an unphysical
    friction (a per-period net return below −100% that compounds total_return/calmar to a nonsensical
    large-positive) routes to INVALIDATED instead of a garbage REFUTED. Each is locked by a regression
    test. (Suite: 30 green.)

### Validity families (1-2): leakage + overfitting + the INVALIDATED verdict

The foundation the two families above build on: two validity-family detectors on the findings rail, plus
the new `INVALIDATED` verdict shape they need. Serial, leakage-first; each step keeps the full suite
green. SKILL.md no longer lists leakage/overfitting as "named roadmap (M3-M4), not yet delivered" — they
are delivered.

- **New verdict `INVALIDATED`** — "the number reproduces while the result is invalid." A first-class,
  gap-free third shape (distinct from `CONFIRMED` and the gap-gated `REFUTED`), reached only by a
  conservative *degrade*: a validity detector sets one of four new `verdict_inputs` and the claim
  verdict is re-derived — `validity_invalidated`+`oos_claim_asserted` → INVALIDATED;
  `validity_unresolved` → CAN'T-CONFIRM (e.g. OOS-indeterminate / uncountable-N); `soft_validity_caveat`
  → CONFIRMED-WITH-CAVEATS. Plain REFUTED stays **strictly gap-gated** (the override is consulted only on
  the within-budget / number-reproduces paths). `semantic_validate` gives INVALIDATED its own precondition
  (a linked `blocker` of the driving dimension + an out-of-sample assertion; no numeric gap required).
- **Fail-closed verdict classification.** `clean` is now an allowlist (`verdict.is_clean`,
  `CLEAN_VERDICTS`/`CATCH_VERDICTS`): any unknown/future verdict is treated as non-clean (exit 1, no clean
  badge), so a missed switch-site degrades to over-cautious, never to a false-confirm. INVALIDATED is
  plumbed through the gate, repo rollup (headline → INVALIDATED, non-headline → MIXED), report (headline
  word/symbol/HTML class + an evidence-led render), the CLI exit/cache/tally/batch/publish paths, and the
  agent guardrail hook.
- **Registry/attestation: no schema change.** An INVALIDATED bundle verifies (the embedded ledger
  re-derives the label byte-for-byte) and the redacted, hash-chained registry entry records the verdict
  string verbatim — never serialized as a CONFIRMED-anything.
- **Contract surface for leakage** — three new optional `verify.yaml` keys, auto-detected by
  `draft_contract.draft()` and shape-validated by `validate_contract`: `split` ({train,test} paths,
  `*_train`/`*_test` pairs, or a single file + a `split`/`fold` column), `keys` ({id, time, target}),
  and `features` (the model-input columns). All absent → the leakage family is NOT-APPLICABLE (an honest
  abstention, never a false pass); an ordinary single-metric artifact stays clean (no noisy keys).
- **Leakage detectors** (`scripts/leakage_checks.py`, dimension `leakage`, on the findings rail) — five
  deterministic catches off the bound artifacts: train/test **row overlap** (canonical sha256 row hash),
  **entity/id overlap**, **temporal look-ahead** (with optional embargo), **duplicate inflation** in the
  eval set, and **target leakage** (a feature identical to the target → authoritative; `|pearson_r|≥0.999`
  → LABELED HEURISTIC). Wired into `_assemble_ledger` beside `backtest_checks`. The verdict follows the
  claim's scope (`apply_validity` + `oos_status`): authoritative contamination on an **out-of-sample**
  claim → INVALIDATED; **in-sample** or heuristic → CONFIRMED-WITH-CAVEATS (exit 0); **indeterminate**
  scope → CAN'T-CONFIRM ("declare whether out-of-sample"). The honest "did NOT assess" list drops
  leakage once it runs (overfitting stays roadmap).
- **Leakage-corrected recompute** (the differentiator) — when a row/id overlap is *correctable* from the
  bound artifact (the headline metric is computed on the test split, so the contaminated eval rows are
  identifiable), Calma recomputes the SAME recipe on the de-contaminated eval rows. If the corrected
  number falls outside budget the claim is REFUTED through the ordinary **gap-gated** path
  (`driving_dimension=leakage`), reporting "claimed 0.755 → leakage-corrected 0.5 (dropped 30
  contaminated of 100 eval rows)"; if it survives correction the result stays INVALIDATED (the held-out
  set was still contaminated) and the surviving number is reported. An artifact subset recompute — no
  full re-execution. REFUTED is still never manufactured by a finding alone.
- **Overfitting kernels** (`numeric.py`, pure stdlib, append-only) — the Deflated Sharpe Ratio
  (Bailey–López de Prado 2014: `normal_cdf`, `expected_max_sharpe`, `probabilistic_sharpe_ratio_vs`,
  `deflated_sharpe_ratio`) and PBO via CSCV (Bailey-Borwein-LdP-Zhu 2016: `pbo_cscv`, exact
  `C(S,S/2)` combinatorics, deterministic). Built on the existing deterministic kernels
  (`derfc`/`normal_sf`/`z_ppf`, `fmean`/`fstd`, `math.comb`); no numpy, no new deps. Validated against
  analytic + constructed-truth anchors (`test_overfitting_kernels`, +27): Φ symmetry; PSR=0.5 at the
  benchmark; E[max SR] increasing in N and ∝√var; DSR == PSR(SR0); **N<2 refused** (no search to
  deflate — never the Φ⁻¹(0)=−∞ garbage pass); PBO **always-overfit → 1.0**, **rank-preserving → 0.0**,
  and an **exact-tie fixture** pinning the `w ≤ 0.5` boundary (all exact), symmetric noise → mean in
  [0.45,0.55] over 200 **seeded** realisations. Conventions pinned to scipy defaults (skew g1, kurt g2,
  V=sample variance). A gating accuracy check vs scipy passed before any freeze: **Φ⁻¹ vs
  `scipy.special.ndtri` to 1.5e-15 across the deep tail (N up to 1000)**, and the full DSR composition +
  PBO bit-close to scipy/numpy references.
- **Frozen overfitting reference vectors** (`assets/overfitting_reference_vectors.json` + `.manifest.json`,
  generated once by `calibration/gen_overfitting_vectors.py` in a pinned venv) — 14 cases: 7 DSR
  (scipy-from-paper), 3 PBO constructed-truth (always-overfit→1.0, rank-preserving→0.0, exact-tie→0.5),
  4 PBO seeded-noise (vs a numpy CSCV reference). The from-paper reference is **gated on reproducing the
  constructed-truth before it mints any vector**. `test_overfitting_vectors` (+20) validates the stdlib
  kernels against the frozen file at rel-tol 1e-9, checks the manifest sha256 (tamper-evident), and
  asserts the **CI path imports no reference lib**. These vectors live in their own file (not the recipe
  library's `reference_vectors.json`) so the freeze never touches the parallel recipe session's
  generator. *(The registered `deflated_sharpe` recipe — the REFUTED-via-recipe-rail path for a
  user-claimed deflated number — is deferred to avoid entangling with that session's recipe-count /
  enrichment / site-mirror gates; DSR/PBO ship as kernels + frozen vectors + the findings rail.)*
- **Overfitting findings rail** (`scripts/overfitting_checks.py`, dimension `overfitting`) — the
  engagement lattice, **silent by design** unless a multiple-testing search signal is present (a
  `trials:N` declared, a trials/grid-search artifact, or selection language in the claim): no signal →
  NOT-APPLICABLE/silent; signal + **countable N** → run DSR + PBO/CSCV and fire only if the edge fails
  (PBO>0.5 or 1−DSR>0.05); signal + **uncountable N** → an explicit finding carrying the "declare
  trials:N / emit the grid-search log" fix. **N is never guessed** (it is the declared count or the
  trials-artifact column count). The verdict follows the claim scope, same as leakage: a failed edge on
  a **survival/selection/OOS** claim → INVALIDATED; a **bare reproduced number** + a detected sweep →
  CONFIRMED-WITH-CAVEATS (never block a literally-true number); an uncountable N on a survival claim →
  CAN'T-CONFIRM. The rail feeds the kernels a **per-period** Sharpe with n = period count (not an
  annualised SR). Contract gains optional `trials`/`trials_artifact`/`var_sr`. Wired into
  `_assemble_ledger`; `scope.families.overfitting` + the honest `_not_verified` reflect it. The
  registered `deflated_sharpe` recipe (REFUTED-via-recipe-rail) stays deferred (recipe-session coupling).
- Tests: +14 `test_verdict`, +12 `test_ledger`, +3 `test_registry` (attest→registry round-trip), incl. a
  fail-closed unknown-verdict property; +17 `test_draft` (split/keys/features detection + validation);
  +22 `test_overfitting_checks` (the engagement lattice + num-trials integrity + per-period-SR wiring +
  an e2e `_assemble_ledger` check);
  +53 `test_leakage_checks` (five detectors with exact magnitudes, the OOS scope-guard, the full verdict
  lattice through real ledgers, the leakage-corrected recompute → REFUTED/INVALIDATED, and an end-to-end
  `_assemble_ledger` wiring check). Kernels and reference vectors land in the following steps. Design of
  record: `.claude/skills/calma/PLAN.md`.

## 0.9.1 — 2026-06-14

### Robustness hardening (closed-loop audit: never traceback, never a wrong verdict)

A full adversarial pass over the skill + CLI; every input now degrades to a clean verdict or `error:`,
and no reachable false-CONFIRM/false-REFUTE survives.

- **Soundness.** A fabricated INFINITE claim (`"1e999"`) no longer false-CONFIRMs (it made the tolerance
  budget `inf`); it is rejected as not-a-finite-number, with defense-in-depth guards in `compare` and
  `verdict()`. A Unicode-minus claim (`"−14%"`, U+2212 — what editors/PDFs/LLMs emit) no longer false-REFUTEs
  a correct negative claim; minus/hyphen codepoints normalize to ASCII `-` (en/em dash stay separators).
- **No more tracebacks.** 165 of the 500 recipe kernels could raise an uncaught `OverflowError`/
  `ZeroDivisionError` on extreme-but-valid data — they now degrade to CAN'T-CONFIRM. Same for an empty
  0-byte output file, a bad `--out`/`--key`/bundle path (every `OSError`), an `inf` in a graded column, and
  a pathologically deep `verify.yaml`. A literal `inf`/`Infinity` CSV cell now degenerates the recompute
  instead of an order-statistic (median/percentile) silently returning a finite-from-corrupt number.
- **Privacy.** The reproduce command no longer leaks the producer's absolute `$HOME` path into the SIGNED,
  counterparty-facing attestation bundle (it is `~`-redacted, as the bundle invariant always promised).
- **Claim parsing.** Spelled-out "percent"/"pct" is read as `%` ("accuracy 87 percent" → 0.87, was
  REFUTING); NPV's leading discount rate ("npv at 10% 5000") is treated as a parameter, not the value.
- **Terminal UI / agents.** Batch table columns size to their values (no more overflow); the long
  `scope:`/`not verified:` line wraps with a hanging indent; `recipes` wraps to `$COLUMNS`; `NO_COLOR`
  suppresses the stderr trace + spinner styling; `--json` is strict JSON (NaN/Inf → null) and its
  `gate_exit` matches the 3/4 refused/killed exit; a precise "column X not found" surfaces in the fix line;
  large non-integer money/counts render with thousands separators (not `1.235e+06`); plus "1 target"
  pluralization, batch dedup, `registry verify` erroring on a missing dir, and assorted wording fixes.
- **Cache.** An explicit `--isolation` is now part of the cache key (a different tier re-runs rather than
  serving a verdict achieved under another tier).
- **Docs.** README/recipes.md counts corrected (120 → 500; reference vectors 385 → 774); the recipes.md
  catalog is described honestly as a representative-families reference with the full id list via
  `calma recipes`; the SKILL.md `--json` field list completed.
- **Tests.** New `test_robustness.py` (51 checks) pins the whole cluster. Full suite: 23 suites, ~2,890
  checks, 0 failures. Version is the cache key, so these verdict-behavior changes invalidate stale entries.

## 0.9.0 — 2026-06-13

### WS6 + dress rehearsals — end-to-end pilot pipeline + registry dry-run

- New `rehearsals/run_rehearsal.py`: drives the WHOLE pilot pipeline (intake +restore → isolated run
  → recompute → signed bundle → branded report + offline replay bundle → a redacted hash-chained
  registry entry) on quant repos across stacks, using a THROWAWAY key + a SCRATCH registry so the
  founder lab key and the committed genesis chain are never touched. Writes `REHEARSALS.md`.
- Ran on 5 repos / 4 stacks: BTC inflated backtest (container isolation → **REFUTED**, the walk-forward
  catch), a real MIT pandas momentum repo (**CONFIRMED**), a backtrader strategy (restored →
  **CONFIRMED**), an R strategy (**CONFIRMED-WITH-CAVEATS**, R determinism uncontrolled), and an
  omitted-costs deck (**CONFIRMED-WITH-CAVEATS**, the WS4 gross-sold-as-net catch). Each produced a
  signed bundle, a report + replay bundle, and a redacted registry entry.
- Registry dry-run (WS6): all 5 redacted entries appended, the **hash chain verifies offline**, and an
  independent leak scan confirms **redaction-by-construction** — every entry carries only
  claim/metric/claimed/recomputed/verdict/hashes/keyid/dates; no code, data, or positions.

### WS5 — Graceful handling of THEIR non-determinism

- The determinism recheck (re-execute, diff the artifact bytes) now **fires automatically** when it
  matters — not just under `--check-determinism`: on untrusted counterparty code (`--trust
  third-party`), and whenever bit-determinism could NOT be proven statically (measured-band /
  uncontrolled) AND a claim is being judged. This closes a real false-confirm hole: an **unseeded
  flaky repo whose output happened to land near the claim previously CONFIRMED-WITH-CAVEATS**; it now
  degrades to CAN'T-CONFIRM. Provably bit-deterministic runs skip the second execution (no wasted cost),
  and a stable-but-measured-band run (e.g. seeded RNG) still CONFIRMS — no false-refute.
- The FLAKY message reads as a **measurement, not a failure**: it names which artifacts drifted and
  **quantifies the swing on the headline metric** ("total_return moved -0.10% → +10.2% across two runs,
  Δ 10.3%"), and the unblock names the **likely source + the exact knob to pin** (random.seed /
  np.random.seed / torch deterministic + CUBLAS_WORKSPACE_CONFIG / OMP_NUM_THREADS=1 / drop timestamps),
  inferred from the static determinism note. Still degrades to INCONCLUSIVE, never a false REFUTED.
- Tests: `test_dx.py` extended — the flaky repo auto-degrades to CAN'T-CONFIRM without
  `--check-determinism`, and the fix names the precise source.

### WS4 — Backtest checks that catch the common inflated-deck failures

- New `backtest_checks.py`, run additively in the verify pipeline, each catch stating the assumption
  it made:
  - **omitted costs (gross-sold-as-net):** applies the declared fee/slippage model (a `costs`
    `{fee_bps, turnover_col}` block, or a per-period cost column) to the bound returns and flags when
    the claimed return tracks the GROSS series while net-of-cost is materially lower — with the exact
    gross, net, and cost-drag numbers.
  - **cherry-picked window:** compares the claimed window (`claimed_periods` / `claimed_window`) to the
    history actually present in the bound artifact; flags when the claim implies more periods/range
    than the data covers.
  - **survivorship universe:** flags a declared survivors-only / non-point-in-time universe (returns
    upward-biased) with the point-in-time rebuild as the unblock.
- These emit ledger findings on the existing dimensions (execution-realism / selection /
  data-integrity). An open blocking soundness finding now degrades a clean CONFIRMED to
  **CONFIRMED-WITH-CAVEATS** (the number reproduces, but it is gross-not-net / cherry-picked /
  survivorship-biased) — never up to REFUTED (that stays the `verdict()` path on a bound metric).
  Deck-vs-code mismatch was already caught by the core recompute+verdict path.
- Tests: `test_backtest_checks.py` (15 checks) — each catch FIRES on the planted failure and stays
  SILENT on the honest deck (no false alarms), and the findings keep the ledger valid. Verified on
  three planted CLI decks (omitted costs, wrong window, survivorship), each correctly degraded.

### WS3 — Robust intake for the quant wedge

- New `intake.py` + `calma verify --restore`: detect the interpreter, **restore + PIN** the repo's
  declared dependencies into `<target>/.calma_venv` (requirements.txt / pyproject PEP 621 / setup /
  conda for Python; renv.lock / DESCRIPTION for R), capture the resolved environment, and **bind the
  claimed input data by content hash** — all written to `<run_dir>/intake.json`. The restore step is
  the ONE phase that may touch the network; it runs BEFORE the verified, network-denied re-execution,
  so the run's hermeticity stamp is unaffected. Fail-soft: an incomplete restore degrades to
  can't-confirm with the missing-dependency reason, never a false CONFIRM.
- Isolation fix uncovered by intake: a **restored venv's base interpreter** (uv / pyenv / conda)
  lives under `$HOME`, reached through nested `$HOME` symlinks that the Seatbelt profile denied —
  so the venv python could not be exec'd (`execvp EPERM`). The profile now re-allows the interpreter
  DEPOT roots (`~/.local/share/uv`, `~/.pyenv`, `~/.conda`, `~/miniconda3`, …) — broad but safe,
  the same pattern as the existing `~/.julia` / `~/.cargo` re-allows; `~/.ssh` / `~/.aws` / keychains
  stay denied. Verified on 3 messy public-style repos (pandas/numpy, backtrader, R) restoring + running
  unattended to a recompute.
- Tests: `test_intake.py` (16 checks: detection, PEP 621 parse, source precedence, data-binding hash,
  fail-soft restore) + `test_hermetic.py` depot/symlink-chain structural locks.

### WS2 — The deliverable: signed report + offline replay bundle

- New `calma report <run_dir>`: renders a **branded, self-contained HTML report** (Calma warm-black /
  cream / amber, inline CSS, `@media print` so it saves to a clean PDF from any browser) stating the
  claim under test, the verdict + confidence, the **measured gap** (claimed → recomputed), an
  **explicit scope-of-verification** ("verified X by re-execution; did NOT assess Y"), the limits
  statement, the isolation + determinism stamps, and the content hashes (ledger / manifest / contract
  sha256 + signing keyid). Best-effort headless-browser PDF when one is present; the HTML is the
  always-works fallback.
- The same command writes a **self-contained replay bundle** (`<run_dir>/replay/`): the signed
  attestation + sidecars, the run artifacts, the report, the pure-stdlib dependency closure of
  `attest.verify_bundle`, and a one-command `replay.sh`. On a fresh machine, **offline, with no calma
  install**, it re-derives every verdict label byte-for-byte (`verdict.verdict()` re-run over the
  stored inputs) and verifies the DSSE + SSHSIG signatures. A forged-verdict bundle fails the replay.
  Stock-OpenSSH `ssh-keygen -Y verify` remains the zero-install signature check (VERIFY-THIS.txt).
- New `test_report.py` (33 checks): the report's content contract, the bundle structure, the
  **offline re-derivation acceptance test** (run out-of-repo with a scrubbed env), and the tamper
  rejection.

### WS1 — Hardened, disposable, network-denied execution (pilot tier)

- New **container isolation backend** in `run_hermetic.py`, selectable via `calma verify --isolation
  auto|seatbelt|docker|firecracker`. A real Linux tier (Docker via colima) for running an **untrusted
  counterparty's** code, with every wall deliberate: `--network=none` (egress denied — no DNS/IP/curl),
  `--read-only` root + a single writable `runs/` overlay (the engagement source and `.calma` are
  immutable), non-root `--user`, `--cap-drop=ALL`, default seccomp, `--security-opt no-new-privileges`,
  `--pids-limit`, `--memory`/`--cpus` bounds, `--ipc=none`, and `--rm` + explicit kill-on-timeout so the
  container is gone after the run.
- **The self-proving check now runs INSIDE the container and gates the verdict.** `docker_doctor()`
  plants a host secret and, under the hardened container, attempts egress (raw IP, DNS, curl) and
  host-secret reads — the tier is stamped `container` **only if all attempts fail**; any leak (or a probe
  that never ran) → `host-not-isolated`. Untrusted code on a leaking container is refused.
- **Backend selection:** explicit `--isolation` wins and **fails loud** if that backend is unavailable
  (CLI missing / daemon down — names `colima start` / image not pre-pulled) — it **never** silently
  falls back to the host. `--trust third-party` (own-code default unchanged) now **auto-escalates** to the
  container tier instead of refusing outright; a `firecracker`/microVM backend is a registered stub that
  fails loud ("not built yet").
- **Honest stamps:** the container note says it shares the colima VM kernel and is **NOT** escape-isolated
  to microVM strength — kernel-escape isolation is the funded Firecracker tier, explicitly not claimed.
  WS1 covers Python + shell in-container; other languages stamp honestly and refuse under `--isolation
  docker` (use the seatbelt tier for own-code).
- Tests: `test_hermetic.py` grows from 25 → 57 checks — backend dispatch + structural hardening locks
  (docker-free), a fail-loud path (missing image / firecracker stub), and a **marquee hostile-repo
  containment battery** (egress, planted-secret read, writes outside `runs/`, `.calma` tamper — all
  contained; container removed) behind a skip-if-no-docker gate so docker-less CI stays green.

## 0.8.0 — 2026-06-12

### Coverage — value-family metrics can now REFUTE a clear lie

- A pinned/named generic-numeric metric (column_sum, mean, median, percentile, rmse, mae, r2, mape,
  correlation, npv, irr, cagr, latency_p*, …) now REFUTES a material misreport instead of degrading to
  INCONCLUSIVE. The fix is gated to stay safe: the binding upgrades to `independently-bound` only when
  the metric is **forced** (named/`--metric`) AND the column is the **unique** candidate for its tag AND
  clean-finite. Bare-number + auto-picked metric, or an ambiguous (multi-column) binding, stays
  conservative → INCONCLUSIVE (the verdict gate is unchanged; the FP-guard's zero-false-refute holds).
- **Committed multi-metric contracts** no longer swallow a fabricated SECONDARY metric: each committed
  metric is re-graded from the emitted data + confirmed as a target (never downgrading a declared
  status), and `claim_confirmed_target` no longer requires `headline` → a broken secondary metric makes
  the repo **MIXED**. Existing committed fixtures + the served-fraction corpus (9/9) are unchanged.

### Multi-result / batch usage

- `calma batch <dir>… | --manifest <TSV>` verifies many targets in one run and prints ONE summary table
  (target | metric | claimed | recomputed | verdict) with a roll-up exit (1 if any fails). `--json`
  emits a per-target array.
- The report and `--json` now show **every** metric of a multi-metric contract (a per-metric ✓/✗ table;
  `--json` gains a `metrics: […]` array), not just the first.

### Presentation & packaging

- A live **while-running spinner** (`⠹ re-executing <entrypoint> (Ns)`) on an interactive stderr, so a
  long re-execution no longer looks frozen (no-op in pipes/CI/`--json`).
- **On-PATH installer**: `./install.sh` / `make install` symlink `bin/calma` (pure stdlib, no pip); the
  wrapper sets `CALMA_INVOKED_AS` so echoed hints read `calma replay …` (copy-pasteable).

### Site

- Next 14 → 15, React 18 → 19, framer-motion 12, `@types` bumped, `engines.node >=20` pinned
  (build verified clean).

### Benchmark

- `benchmark/` "catch a wrong number" (Calma vs LLM-as-judge vs trust-the-number), rebuilt to **v2: 117
  labeled cases** (77 flawed + 40 honest) across 3 tracks (synthetic / external-UCI / real-world), 30
  metrics, 8 families, oracles cross-validated 28/28 exact against scikit-learn/SciPy/NumPy. After the
  value-family fix: **Calma 100% catch (77/77), 0 false-confirms, 0 false-alarms** vs LLM-as-judge 82%
  (63/77) with **26 wrong verdicts** (14 false-confirms + 12 false-alarms), and trust-the-number 0%.

## 0.7.0 — 2026-06-12

### Served-fraction corpus 6/9 → 9/9 (served_fraction = 1.0)

- **Isolation fix (node + any realpath-resolving runtime):** the Seatbelt profile now grants
  `file-read-metadata` (lstat/stat/readlink) on the run base's exact ancestor chain, so a runtime
  can resolve its entrypoint while directory listing and file-content reads under `/Users` stay
  denied. Doctor still proves zero secret-reads + zero egress; an adversarial probe confirms the
  boundary (lstat allowed, `listdir`/`open` denied).
- **Restore/run interpreter consistency:** a Python repo whose deps restore into `<base>/.calma_venv`
  now runs under that venv, not the host interpreter.
- **Whole-program determinism:** `controlled-to-bit` now requires every `.py` in the program tree
  (not just the entry file) to be free of RNG/GPU/scientific-stack imports; the numpy-backed stack
  (pandas/scipy/sklearn/statsmodels) is treated as non-bit-deterministic.
- **Two vendored real MIT repos** under `assets/corpus/` (each with `VENDORED.md` provenance):
  `momentum-strategy` (yfinance → frozen snapshot) and `btc-sma-crossover` (Coinbase via the
  `calma_vendor` record/replay shim). The latter replaces the retired `crypto-backtester` (deleted
  upstream + binance HTTP 451 = unreproducible).
- **calma_vendor shim:** forwards request headers on record (Coinbase 403s without a User-Agent),
  honors requests `params`, and patches `requests.Session`/ccxt — not just module-level helpers.

### Zero-touch guardrail — engages on far more real projects

- **Widened the verifiable-target gate** (`hook_stop.py`): recognizes Parquet/JSON-lines/npy/feather/
  sqlite/tsv artifacts (not just `.csv`), excludes config JSONs (package.json, tsconfig.json, …), and
  broadens the entrypoint candidate list (evaluate/eval/score/experiment/benchmark/analysis). The
  CSV-only gate was the dominant reason the hook never fired on real repos.
- **Host-level sandbox-tier cache:** the ~30s `doctor` positive-control runs once per machine
  (`~/.calma`), not once per project (override dir via `CALMA_STATE_DIR`).

### UX & performance

- Bad-`--metric` error now points to `calma recipes` (the actual list) instead of `--help`.
- CONFIRMED output leads with a plain "verified by re-execution" line and keeps the honest
  "not verified" scope limit on its own quiet line, instead of a wall of families/isolation jargon.
- Memoized NA-policy lookup in `recompute._numeric_cols` (no longer re-walks `contract.artifacts`
  per bound column).

### 0.6.2 (folded in) — Stop-hook transcript-flush fix

- The Stop hook prefers the harness-provided `last_assistant_message`; on current Claude Code the
  transcript file isn't flushed when Stop runs, which had silently killed every real-session catch.

## 0.6.1 — 2026-06-11

- Site: the request-verification form now actually delivers (with an honest failure
  fallback and a visible direct email); contact, founder, and entity surface on every page;
  mobile navigation; favicon, Open Graph image, sitemap, robots; registry page shows
  human-readable numbers, a self-test badge on the genesis entry, and links to verify the
  chain yourself.
- CLI: a committed `verify.yaml` can no longer substitute a different claim than the one you
  typed — metric conflicts degrade to CAN'T-CONFIRM with a fix line; `calma demo` gives a
  zero-to-verdict path; `calma recipes` lists the library; bare `calma` prints guidance;
  verdict vocabulary is consistent (CAN'T-CONFIRM everywhere a human reads).
- Engine hardening: the verdict cache is validated against the ledger it points at (a stale
  run-dir can never serve the wrong verdict); the sandbox denies writes to the verifier's own
  state directory and passes a whitelisted environment; `--trust third-party` refuses to
  execute counterparty code without a verified sandbox; `--timeout` is configurable; the
  Stop hook checks the sandbox tier before auto-executing anything.
- Attestation identity migrated to GitHub-rooted URIs we control
  (`github.com/rikhinkavuru/calma/verdict/v1`); bundles signed under the legacy URI remain
  valid forever.
- Docs: SECURITY.md, this changelog, copy-pasteable stock-OpenSSH verification recipe in
  registry/README.md, accurate quickstart.

## 0.6.0 — 2026-06-11

- Zero-touch guardrail: plugin-registered Stop hook + precision-first claim sniffer.
  Checkable numeric claims in an agent's final message are auto-verified before the turn
  ends; the stop is blocked only on definitive REFUTED/MIXED. Fail-open everywhere,
  never-nag cache, kill switches. Survived a 270-case adversarial round; the contract is
  "a missed claim is free, a false fire is a release blocker."

## 0.5.0 — 2026-06-10

- Attestation chain to the full 3-layer spec: DSSE/in-toto bundle with a SLSA-VSA-shaped
  predicate, double-signed (raw DSSE + OpenSSH SSHSIG verifiable with stock `ssh-keygen`),
  RFC 3161 trusted timestamps, optional Sigstore/Rekor countersignature.
- Catch history: `calma publish` appends redacted, signed entries to a hash-chained public
  registry; `calma registry verify` audits it offline; `/registry` renders it.
- Recipe compiler: typed JSON expression DSL + deterministic CEGIS admission gate
  (differential vs reference implementation, metamorphic suite, degeneracy, bit-stability).
  First two compiled recipes admitted — the library reaches 120.

## 0.4.x and earlier — 2026-06

- 118 reviewed recipes across 11 packs, each validated against its published reference
  implementation via byte-reproducible reference vectors.
- Deterministic recompute kernels (no numpy, no platform libm), calibrated tolerance
  budgets, honesty guards (REFUTED structurally blocked on ambiguity), auto-drafted graded
  contracts, sandbox self-proof (plants a fake secret and tries to steal it before any run),
  content-hash verification cache, GitHub Action, cross-language black-box support
  (Python, R, Julia, C++, Rust).
