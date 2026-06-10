# Calma — session handoff (2026-06-10)

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

- **118 SOTA recipes** across 11 packs: trading, classification (incl. macro/micro/weighted F1,
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
- **Test suite: 13 suites, ~940 checks, pure stdlib** — `python3 .claude/skills/calma/scripts/tests/run_all.py`.
  The big one is `test_recipes_sota.py` (reference vectors + conventions + degenerate paths +
  e2e + claim-parser regressions + registry↔site sync).
- **Site** (Next.js, static): landing (hero → problem → how-it-works → features w/ marquee +
  9-card grid + 118-recipe band → benefits → about → FAQ → outro), `/recipes` (all 118, grouped,
  per-recipe claim/how/reference/conventions), `/lab` (the capital-allocation surface per
  FINAL.md option 1: thesis, who engages, 4-step engagement ending in the registry, adversarial
  terms, positioning one-liners). Design: warm-black + cream + amber, film grain + warm paper
  texture overlay (`.paper`, mounted in layout), glow ONLY in hero + outro sunrise, hover
  language = corner-square + tint on grid cells, lift + flat offset shadow on benefit cards.

## Key invariants (machine-enforced — do not violate)

- No statistic or verdict label is ever computed by a model. `verdict()` in `verdict.py` is the
  single pure function; `ledger.py` re-derives every label byte-for-byte.
- Recompute reads ONLY raw machine-readable outputs, on deterministic kernels (`numeric.py` —
  no numpy, no platform libm; it has its own log/exp/lgamma/incomplete-beta/gamma/erfc kernels).
- No REFUTED on ambiguous bindings / failed re-runs / flaky outputs / unconfirmed claim targets
  → degrade to INCONCLUSIVE with a `fix:` line. Bias caveat over false alarm, always.
- New recipes ship ONLY with reference-vector validation. Honesty in copy: don't claim signing,
  insurers, accreditation, or a named methodologist — none exist yet.

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

1. **Attestation chain** — sign the ledger+manifest (local Ed25519 first, bundle format designed
   so a Sigstore countersignature can be added later); `calma attest verify <bundle>` for the
   counterparty: checks signature, re-derives all verdicts, optionally replays, offline. Tests
   against tampered bundles. Then upgrade site copy ("Forensic replay & attestation" card,
   lab Report step) to "signed".
2. **Catch history** — opt-in `calma publish`: a redacted (claim/verdict/gap only), attested,
   static registry entry; in-repo `registry/` rendered by the site; git history = tamper
   evidence. This is also the engagement-registry machinery for /lab.
3. **Recipe compiler** — model DRAFTS a recipe offline as a constrained composition of existing
   deterministic kernels; admission gate = auto-generated reference vectors + property tests; only
   then frozen, content-hashed, registered. Execution stays deterministic — generation is the only
   ML. v1 scope: kernel compositions only. ("Compiled, validated, frozen — never improvised at
   verify time.")

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
