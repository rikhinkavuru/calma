# Calma — session handoff (2026-06-13)

Onboarding for a fresh Claude Code session. Read this, then `.claude/skills/calma/SKILL.md`
(what the skill is) and `.claude/skills/calma/BUILD-NOTES.md` (build log, newest entries last).

## What Calma is (two layers — don't conflate them)

1. **The OSS skill/CLI** (this repo): verifies a computational result by re-executing it in a
   sandbox and recomputing the headline number from raw outputs. Deterministic scripts compute
   every statistic and the verdict — never a model. Free, MIT, "loud" — it is the demo, brand,
   and live proof the engine is real. **Never the sales pipeline.**
2. **The company = the lab**: forensic/adversarial verification for capital allocation —
   re-execution verification sold to allocator ODD teams, seeders, diligence consultancies
   (manager-pays attestation is the secondary SKU under hard terms). Strategy source of truth:
   `~/calma-strategy/FINAL.md` (v3, supersedes everything; ROADMAP/GROWTH/FUNDING-GAPS/STACK/
   REVIEW-STAGED-FRAMEWORK live there too; superseded drafts are in `archive/`).

## Current state (all pushed to origin/main)

- **120 SOTA recipes** (118 reviewed + 2 compiled) across 11 packs: trading, classification (incl. macro/micro/weighted F1,
  PR-AUC, log-loss, MCC, ECE, κ, KS, Gini), regression + forecasting (incl. MSLE, WAPE, adjusted
  R², Durbin-Watson), analytics (incl. group-bys, distinct/null/dupes, HHI, Gini coefficient,
  entropy, outliers), engineering (latency p50–p99, Apdex, uptime, coverage, error rates),
  retrieval/LLM (recall@k, NDCG, MRR, MAP@k, pass@k, exact-match, perplexity, WER/CER), stats
  (p-values, Mann-Whitney, ANOVA, Fisher exact, chi-square, effect sizes, normality), quant risk
  (Sortino, Calmar, VaR/CVaR, beta/alpha/IR/TE), finance (CAGR, NPV/IRR, churn, margin,
  reconciliation).
- **Every recipe is validated against its published reference implementation** (scikit-learn,
  SciPy, NumPy, numpy-financial, statsmodels, jiwer, HumanEval estimator, SQuAD normalizer, Guo
  ECE) via **385 byte-reproducible reference vectors** in `assets/reference_vectors.json`.
- **Test suite: 18 suites, ~1,620 checks, pure stdlib** — `python3 .claude/skills/calma/scripts/tests/run_all.py`.
  The big one is `test_recipes_sota.py` (reference vectors + conventions + degenerate paths +
  e2e + claim-parser regressions + registry↔site sync); also `test_registry.py` (chain tamper
  matrix), `test_compiler.py` (DSL + gate + frozen-asset tamper + compiled-recipe e2e),
  `test_sniff.py` + `test_hook.py` (the zero-touch guardrail, incl. the adversarial regressions).
- **Attestation chain (SHIPPED to the full 3-layer spec, calma 0.5.0)**: DSSE/in-toto bundle,
  predicate `calma.dev/verdict/v1` (SLSA-VSA-shaped: verifier+version, policy = contract +
  calibration hashes, verdict, claims). The same Ed25519 key signs twice: raw DSSE (Sigstore-
  countersignable) + OpenSSH SSHSIG (`sshsig.py`, namespace calma-attest@v1) with sidecars, so a
  counterparty verifies with stock `ssh-keygen -Y verify`, zero installs (interop tested both
  directions). Layer 1: `calma attest timestamp` = RFC 3161 token (`rfc3161.py`, freetsa default,
  offline verification, openssl chain-check when present). Layer 2 (lab): `calma attest sigstore`
  via optional sigstore-python -> Rekor. `calma attest verify` = both signatures + subject digests
  + byte-for-byte verdict re-derivation + claims-binding + timestamp checks, fully offline.
- **Catch history (SHIPPED)**: `calma publish <run_dir>` appends a REDACTED entry (whitelist
  enforced at append + audit; never code/data) derived from a VERIFIED bundle into `registry/`
  (hash chain, every entry + HEAD SSHSIG-signed); `calma publish --open <id>` logs engagements at
  signing (missing outcome = visible); `calma registry verify` audits offline. Site: `/registry`.
- **Zero-touch guardrail (SHIPPED 2026-06-11, calma 0.6.0)**: plugin-registered Stop hook
  (`hooks/hooks.json` → `scripts/hook_stop.py`) + precision-first claim sniffer
  (`scripts/sniff_claims.py`). When an agent's final message states a checkable numeric claim in
  a verifiable project, the claim is auto-verified before the turn ends; the stop is blocked ONLY
  on definitive REFUTED/MIXED (verdict + reporting contract injected), silent otherwise.
  Fail-open everywhere, never-nag cache, no-shell subprocess, kill switches (CALMA_HOOK=0 /
  .calma/hook-off / config). Breadcrumbs to `.calma/auto_history.jsonl`, surfaced by
  `calma stats`. Survived a 270-case multi-agent adversarial round: 12 confirmed false fires,
  all fixed (config-assignment guard, finance-subject gate on the `returned` alias, counted
  units, per-term context-deny lists, log-loss-never-percent) and pinned as regressions;
  0 code-attack findings. The contract: a missed claim is free, a false fire is a release blocker.
- **Recipe compiler (SHIPPED)**: `dsl.py` (typed JSON expression DSL over numeric.py kernels, no
  loops — total by construction, depth/size budgets) + `compiler.py admit` (deterministic CEGIS
  gate: differential vs named oracle in the reference venv, metamorphic suite, degeneracy,
  bit-stability; failures = structured counterexamples). Frozen into `assets/compiled_recipes.json`
  (content hash re-validated at load — fails closed), maturity `compiled-validated`. Two real
  recipes admitted: `sem`, `coefficient_of_variation` → registry is 120. Draft schema:
  `references/recipe-draft.schema.json`.
- **Site** (Next.js, static): landing (hero → problem → how-it-works → features w/ marquee +
  9-card grid + 120-recipe band → benefits → about → FAQ → outro), `/recipes` (all 120, grouped,
  per-recipe claim/how/reference/conventions, incl. the compiled family), `/registry` (the catch
  history, rendered from `registry/` at build), `/lab` (the capital-allocation surface per
  FINAL.md option 1: thesis, who engages, 4-step engagement ending in the registry, adversarial
  terms, positioning one-liners). Design: warm-black + cream + amber, film grain + warm paper
  texture overlay (`.paper`, mounted in layout), glow ONLY in hero + outro sunrise, hover
  language = corner-square + tint on grid cells, lift + flat offset shadow on benefit cards.

- **Production-readiness pass (2026-06-11 evening, calma 0.6.1)**: four-surface audit → fixes.
  Site: request form actually delivers (FormSubmit + honest fallback + visible email — founder
  must click the one-time FormSubmit activation email), founder/contact everywhere, mobile nav,
  Rekor copy honest, SEO pack (icon/OG/sitemap/robots/next-font), registry page verifiable +
  human numbers. CLI: user's claim is never substituted by the committed contract (conflicts →
  CAN'T-CONFIRM + fix), `calma demo`/`recipes`, CAN'T-CONFIRM vocabulary everywhere. Engine:
  verdict cache validated against its ledger (A/B/A collision fixed), sandbox denies writes to
  .calma + env whitelist, `--trust third-party` refusal gate, `--timeout`, hook checks sandbox
  tier. Attestation URIs migrated to github.com/rikhinkavuru/calma/* (legacy calma.dev bundles
  stay valid). SECURITY.md + CHANGELOG.md added. Suite: 18 suites green (~1,540 checks).

- **Served-fraction 9/9 + zero-touch/UX/perf pass (2026-06-12, calma 0.7.0)**: the
  real-repo + cross-language served-fraction corpus reached **9/9** (`served_fraction = 1.0`) via
  three general engine fixes (isolation metadata-ancestor reads so node serves; restore→run venv
  consistency; whole-program determinism) and two newly-vendored real MIT repos under
  `assets/corpus/` (momentum-strategy via data snapshot, btc-sma-crossover via the calma_vendor
  HTTP record/replay shim on Coinbase — replaces the dead/geo-blocked crypto-backtester). Zero-touch
  guardrail now engages on far more projects (gate accepts Parquet/JSON-lines/npy/sqlite/…, not just
  CSV; broader entrypoint list; host-level sandbox-tier cache so the 30s probe runs once per machine).
  UX/perf: bad-metric error points to `calma recipes`, CONFIRMED output de-jargoned, NA-policy lookup
  memoized, shim forwards headers/params + patches requests.Session/ccxt. All versions reconciled to
  0.7.0 (plugin/marketplace/calma.py/site). See CALIBRATION.md + CHANGELOG.md. Suite: 18 suites
  green on py3.13 + py3.14. (Its open follow-ups around the site bump + on-PATH installer were
  closed in 0.8.0 — see below.)

- **Value-family REFUTE + batch/multi-metric + packaging pass (2026-06-12, calma 0.8.0 — last release on main)**:
  a pinned/named generic-numeric metric (column_sum, mean, median, percentile, rmse, mae, r2, mape,
  correlation, npv, irr, cagr, latency_p*, …) now **REFUTES** a material misreport instead of degrading
  to INCONCLUSIVE — gated to stay safe: the binding upgrades to `independently-bound` only when the
  metric is **forced** (named/`--metric`) AND its column is the **unique** clean-finite candidate;
  bare-number / auto-picked / ambiguous (multi-column) stays conservative → INCONCLUSIVE (the verdict
  gate is unchanged; the zero-false-refute FP-guard holds). **Committed multi-metric contracts** no
  longer swallow a fabricated SECONDARY metric — each declared metric is re-graded from the emitted
  data and confirmed as a target, so a broken secondary makes the repo **MIXED**; the report + `--json`
  now show EVERY metric (per-metric ✓/✗ table; `--json` gains a `metrics: […]` array). **Batch**:
  `calma batch <dir>… | --manifest <TSV>` verifies many targets in one run → ONE summary table (target
  | metric | claimed | recomputed | verdict) with a roll-up exit (1 if any fails); `--json` emits a
  per-target array. **UX/packaging**: a live while-running spinner (`⠹ re-executing <entrypoint> (Ns)`)
  on interactive stderr (no-op in pipes/CI/`--json`); an on-PATH installer (`./install.sh` / `make
  install` symlink `bin/calma`, pure stdlib, no pip; `CALMA_INVOKED_AS` so echoed hints read `calma
  replay …`); site Next 14→15, React 18→19, framer-motion 12, `engines.node >=20` (build clean).
  **Benchmark v2** (`benchmark/`): 117 labeled cases across 3 tracks (synthetic 84 / external 29 on
  UCI + Diabetes via 5-fold OOF / real-world 4), 30 metrics, 8 families, oracles cross-validated
  **28/28 exact** against scikit-learn/SciPy/NumPy → **Calma 100% catch (77/77), 0 false-confirms, 0
  false-alarms** vs LLM-as-judge 82% (63/77) with **26 wrong verdicts** (14 false-confirms + 12
  false-alarms) vs trust-the-number 0% (the authoritative v2 numbers from
  `benchmark/results/summary.json`; an earlier pre-v2 generation had reported 71%/7+3, now corrected
  everywhere). All versions reconciled to 0.8.0. Suite: 18 suites, **1,588 checks** green on py3.13 +
  py3.14 (1,620 on the 0.9.0 branch). See
  CHANGELOG.md. **Open follow-ups (proposed, not done):** AUC/DeLong O(n²)→O(n log n) kernel rewrite
  (needs reference-vector bit validation), sniffer recall on backticked metrics, a real `pip install`
  to PyPI (the on-PATH symlink installer shipped; PyPI distribution did not). (The README demo-GIF
  embed — `docs/demo.gif` — was completed 2026-06-13.)

- **Pilot-hardening WS1 (2026-06-13, calma 0.9.0 — branch `pilot-hardening`)**: a real **container
  isolation tier** for untrusted counterparty code lands in `run_hermetic.py` behind a backend
  abstraction (`_select_backend` → seatbelt | docker | firecracker-stub), exposed as `calma verify
  --isolation auto|seatbelt|docker|firecracker`. Docker (via colima on this host) runs the code
  network-denied (`--network=none`), read-only-root with a single writable `runs/` overlay (engagement
  source + `.calma` immutable), non-root, cap-drop-ALL, seccomp, pid/mem/cpu-bounded, `--rm` + kill-on-
  timeout. `docker_doctor()` runs the egress+secret-read self-test INSIDE the container and stamps
  `container` only if every wall holds. Explicit `--isolation` fails loud when unavailable (never a host
  fallback); `--trust third-party` auto-escalates to the container tier; firecracker is a fail-loud stub.
  Honest stamp: shares the colima VM kernel, NOT escape-isolated (microVM = funded tier, stubbed).
  `test_hermetic.py` 25→57 checks incl. a hostile-repo containment battery (egress / planted-secret /
  out-of-`runs` writes all contained, container removed). A fresh no-context red-team subagent failed
  on ALL walls → stamped isolated.

- **Pilot-hardening WS2–WS6 + rehearsals (2026-06-13, calma 0.9.0 — branch `pilot-hardening`)**, plan
  at `PLAN.md` / `~/.claude/plans/mighty-dancing-hammock.md`:
  - **WS2** `calma report <run_dir>`: branded HTML (prints to PDF; claim / verdict / measured gap /
    explicit scope-of-verification / limits / hashes) + a self-contained **offline replay bundle**
    (`replay/`) that re-derives the verdict byte-for-byte on a fresh machine with no calma install
    (pure-stdlib `attest.verify_bundle` closure + `replay.sh`); a forged-verdict bundle fails it.
    `report.py` + `test_report.py` (33 checks).
  - **WS3** `intake.py` + `calma verify --restore`: detect interpreter, restore+pin deps
    (requirements/pyproject/setup/conda; renv/DESCRIPTION) into `.calma_venv`, bind input data by hash
    → `intake.json`. Fixed a Seatbelt gap: restored-venv base interpreters (uv/pyenv/conda) live under
    `$HOME` via nested symlinks the profile denied — profile now re-allows interpreter DEPOT roots
    (`~/.local/share/uv`, `~/.pyenv`, …; `~/.ssh`/`~/.aws` stay denied). Verified on pandas, backtrader,
    R. `test_intake.py` (16 checks).
  - **WS4** `backtest_checks.py`: omitted-costs (gross-sold-as-net), cherry-picked window, survivorship —
    each states its assumption; an open blocking soundness finding degrades a clean CONFIRMED to
    CONFIRMED-WITH-CAVEATS (never up to REFUTED). `test_backtest_checks.py` (15 checks). deck≠code is the
    core catch.
  - **WS5**: the determinism recheck fires AUTOMATICALLY on third-party trust and whenever determinism
    isn't statically provable + a claim is judged — closes a false-confirm hole (unseeded flaky repo near
    the claim). FLAKY message quantifies the headline swing + names the precise knob. Never false-refute
    (a seeded run still CONFIRMS).
  - **WS6 + rehearsals**: `rehearsals/run_rehearsal.py` drives the whole pipeline on 5 repos / 4 stacks
    into a SCRATCH registry with a THROWAWAY key (founder key + genesis chain untouched) →
    `REHEARSALS.md`. Chain verifies offline; redaction-by-construction independently confirmed.
  - Suite: **21 suites green**. Container tier needs colima running (`colima start`); the funded
    microVM/Firecracker tier is stubbed and fails loud.

## Key invariants (machine-enforced — do not violate)

- No statistic or verdict label is ever computed by a model. `verdict()` in `verdict.py` is the
  single pure function; `ledger.py` re-derives every label byte-for-byte.
- Recompute reads ONLY raw machine-readable outputs, on deterministic kernels (`numeric.py` —
  no numpy, no platform libm; it has its own log/exp/lgamma/incomplete-beta/gamma/erfc kernels).
- No REFUTED on ambiguous bindings / failed re-runs / flaky outputs / unconfirmed claim targets
  → degrade to INCONCLUSIVE with a `fix:` line. Bias caveat over false alarm, always.
- New recipes ship ONLY with reference-vector validation (reviewed recipes) or compiler-gate
  admission (compiled recipes). Honesty in copy: signing, SSHSIG/ssh-keygen verification,
  RFC 3161 timestamps, and the hash-chained registry are real and may be claimed. Sigstore is
  "ready / lab-tier optional" — do NOT claim verdicts are IN Rekor until a real engagement has
  actually run `calma attest sigstore`. Still never claim insurers, accreditation, or a named
  methodologist — none exist yet.

## How to work on it

```bash
python3 .claude/skills/calma/scripts/tests/run_all.py        # full suite (pure stdlib)
npm run build                                                # site (static, must stay green)
python3 .claude/skills/calma/scripts/calma.py verify <dir> "<claim>" --json   # CLI dogfood
```

- **Adding recipes**: kernel in `scripts/numeric.py` → registration in `scripts/recipes.py`
  (manifest: family, required_tags, string_tags, accepted_conventions) → claim hints + tag
  patterns + `infer_convention` in `scripts/draft_contract.py` (ORDER MATTERS in
  CLAIM_METRIC_HINTS — specific before generic; there are collision tests) → reference cases in
  `calibration/gen_reference_vectors.py` → regenerate vectors with the reference venv → dispatch
  entry + registry EXPECTED in `tests/test_recipes_sota.py` → card in `app/recipes/data.ts`
  (sync test enforces ids match the registry) → counts in Features band / README / SKILL.md /
  `references/recipes.md`.
- **Reference venv** (NOT committed): `/tmp/calma-ref-venv` with numpy, scipy, scikit-learn,
  numpy-financial, statsmodels, jiwer. If gone:
  `uv venv /tmp/calma-ref-venv --python 3.12 && uv pip install --python /tmp/calma-ref-venv/bin/python numpy scipy scikit-learn numpy-financial statsmodels jiwer`
  then `/tmp/calma-ref-venv/bin/python .claude/skills/calma/calibration/gen_reference_vectors.py`
  (output is byte-reproducible — fixed LCG, no timestamps).
- **Dogfood discipline**: after building, verify a TRUE claim (must CONFIRM) and an INFLATED one
  (must REFUTE) via the CLI. This has caught real bugs every time (level-prefix parsing, prob-tag
  binding, percent precision).

## Next work (agreed with the founder, in order)

1. ~~**Attestation chain**~~ — SHIPPED 2026-06-10, completed to the full 3-layer spec same day
   (VSA predicate + SSHSIG + RFC 3161 + Sigstore wrapper; see Current state + BUILD-NOTES tail).
2. ~~**Catch history**~~ — SHIPPED 2026-06-10 (`calma publish` / `registry verify`, `registry/`
   + `/registry` page). The committed registry is EMPTY until the founder publishes the genesis
   entry with the lab key (see founder actions below).
3. ~~**Recipe compiler**~~ — SHIPPED 2026-06-10 (dsl.py + compiler.py CEGIS gate; sem +
   coefficient_of_variation admitted; 120 recipes).

**Founder setup DONE 2026-06-10 evening** (commit 7c53f12): lab key created via
`calma attest keygen` (keyid ebf722e19cf7016d…, pubkey published in registry/README.md), git
commit signing configured (SSH format, allowed_signers set), genesis registry entry published
(the BTC fixture REFUTED, RFC 3161 timestamped, entry 00001-dc236f5759bb), both compiled
recipes re-admitted signed ([True, True]). If key rotation is ever wanted, do it BEFORE the
first real engagement is signed, while the chain is short.

**Still pending:**
- GitHub "Verified" badge: upload ~/.ssh/id_ed25519.pub in GitHub Settings → SSH and GPG keys
  as a SIGNING key (separate from the auth entry).
- Lab tier when needed: `pip install sigstore` and `calma attest sigstore <bundle>` on the
  FIRST REAL ENGAGEMENT only — the OIDC identity in Rekor is permanent and public.

**Next build candidates (in rough order):** ~~Linux isolation tier~~ — landed as **WS1 (0.9.0,
branch `pilot-hardening`)**: Docker/colima container tier for untrusted code (microVM/Firecracker
still a fail-loud stub); see the 0.9.0 bullet above. Remaining: the rest of the pilot-hardening
workstreams (WS2–WS6, in-flight), registry v2 (tlog-tiles Merkle tree + C2SP checkpoints + public
witness cosigs — additive, entries already hash-addressed), more compiled-recipe drafts through the gate.

**Demo & strategy assets:** the worked demo project lives at `~/calma-demo/btc-momentum/`
(real 10y BTC-USD data; a genuine walk-forward bug, verified REFUTED→fix→CONFIRMED
end-to-end). All strategy, outreach, and application material lives in `~/calma-strategy/`
— NOT in this repo. Served-fraction experiment RAN and reached **9/9 (served_fraction = 1.0)**
across 6 languages (`assets/served_fraction.json`; cleared the 70–80% target — see the 0.7.0
bullet above).
**Known issues:** site is live at calma1.vercel.app (auto-deploys from GitHub; /registry
renders the genesis entry). The `calma.dev` predicate-URI problem is RESOLVED — the 0.6.1 pass
migrated active predicate/subject URIs to `github.com/rikhinkavuru/calma/*` (legacy `calma.dev`
bundles stay valid and `attest.py` still accepts them), so no schema bump is owed before real
engagements. README demo embed DONE (2026-06-13): `docs/demo.gif` (a clean VHS recording of `calma
demo` catching the +14,698% → −32.4% backtest) is embedded in the README Demo section, replacing the
"coming soon" placeholder. Source is committed at `docs/demo.tape` — regenerate from the repo root
with `vhs docs/demo.tape` (needs `brew install vhs ttyd ffmpeg`; `CALMA_TRACE` controls the verbose
re-exec trace shown). The longer narrated zero-touch cut
(`~/calma-strategy/demo-video-raw-2026-06-12.mp4`, +19,971% staged scenario) is still the asset for a
hosted/launch video if wanted.

## Gotchas

- `$HOME` is itself a git repo — never `git clean` outside this repo; `~/calma-strategy` is
  untracked (deletions there are unrecoverable; superseded docs go to its `archive/`).
- The browse daemon doesn't reload a tab on same-URL goto — `location.reload()` after rebuilds,
  and chain hover+screenshot in ONE `browse chain` call (pointer state doesn't persist).
- `compare.py` conv-capping uses exact accepted_conventions strings; parameterized conventions
  ("k=10") never cap — intended.
- `ks_test` validates against the CLASSICAL Kolmogorov asymptotic (kstwobign), not scipy's
  newer finite-n refinement — documented in recipes.md.
- MAP@k uses the min(R,k) denominator (recsys convention), documented; Sortino is target-0
  full-sample; VaR/CVaR are loss-positive; alpha is simple rf=0 CAPM.
- The deep quant stats (deflated Sharpe, PBO/CSCV, Harvey-Liu, MinBTL) stay OUT of the skill on
  purpose — they're the paid-lab engine (R1).
- Memory dir (auto-loaded each session): `~/.claude/projects/-Users-rikhinkavuru-calma/memory/`.
