# Changelog

All notable changes to the calma skill/CLI. Dates are UTC.

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

- `benchmark/` "catch a wrong number" (Calma vs LLM-as-judge vs trust-the-number). After the value-family
  fix: **Calma 100% catch, 0 false-confirms, 0 false-alarms** vs LLM-judge 71% with 7 false-confirms +
  3 false-alarms, and trust-the-number 0%.

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
