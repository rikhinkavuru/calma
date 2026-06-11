# Calma — session handoff (2026-06-11)

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
- **Test suite: 18 suites, ~1488 checks, pure stdlib** — `python3 .claude/skills/calma/scripts/tests/run_all.py`.
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

**Next build candidates (in rough order):** Linux isolation tier (top roadmap item per README
limitations), registry v2 (tlog-tiles Merkle tree + C2SP checkpoints + public witness cosigs —
additive, entries already hash-addressed), more compiled-recipe drafts through the gate.

**Demo & strategy assets:** the worked demo project lives at `~/calma-demo/btc-momentum/`
(real 10y BTC-USD data; a genuine walk-forward bug, verified REFUTED→fix→CONFIRMED
end-to-end). All strategy, outreach, and application material lives in `~/calma-strategy/`
— NOT in this repo. Served-fraction experiment RAN: 6/9 (66.7%) across 5 languages
(`assets/served_fraction.json`; target was 70–80% — state it honestly).
**Known issues:** site is live at calma1.vercel.app (auto-deploys from GitHub; /registry
renders the genesis entry) but `calma.dev` — used in predicate URIs and across docs — is
OWNED BY SOMEONE ELSE; buy a domain we control and migrate the predicate type (schema bump)
BEFORE real engagements. README line 17 still has the demo-GIF placeholder (fill from the
video's 10s cut).

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
