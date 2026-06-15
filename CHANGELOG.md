# Changelog

All notable changes to the calma skill/CLI. Dates are UTC.

## Unreleased — validity families (leakage + overfitting)

In progress: two new validity-family detectors on the findings rail, plus a new verdict shape they
need. Serial, leakage-first; each step keeps the full suite green.

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
- Tests: +14 `test_verdict`, +12 `test_ledger`, +3 `test_registry` (attest→registry round-trip), incl. a
  fail-closed unknown-verdict property; +17 `test_draft` (split/keys/features detection + validation);
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
