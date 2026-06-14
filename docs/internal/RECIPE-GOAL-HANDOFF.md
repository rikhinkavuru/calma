# Recipe-expansion goal — handoff

**Goal (active `/goal` with a persistent Stop hook):** "add 400 more SOTA-level
recipes, make sure they are relevant, properly validated, perfectionately executed
and sorted into the recipes pages; when done update the count; do as much research as
needed so everything is up to date and top of the line. Recipes MUST be accurate
otherwise Calma recompute will be off."

**Buyer targeting (who the recipes are weighted toward):** ODD firms (Castle Hall,
Corgentum, Mercer Sentinel), seeders (NewAlpha, PivotalPath), pod shops (Millennium,
Citadel, Walleye, Point72, Balyasny, ExodusPoint, Schonfeld, Eisler), Kroll, and bank
model-risk teams (JPMorgan, Goldman, Morgan Stanley). Model-based evals are explicitly
out of scope (user confirmed). Packs are fine "as long as they're all built at the
highest quality." User does not care what order packs are added in.

---

## Where things stand (as of commit `8a5555d`) — 622 total, +122 this run (paused on a quality call)

- **Engine: 622 total recipes** = **620 reviewed** + **2 compiled-validated** (up from 500).
  Test suite green: `recipes-sota: 2244 checks, 0 failures`; `test_suggest: OK`
  (recall@8 ALL 96.9% / named 99.7% / paraphrase 94.1% on a 1230-row blind gold set);
  `npx tsc --noEmit` clean. `RECIPE_COUNT` auto-derives to 622.
- **Why paused here (READ THIS before resuming):** the user interrupted and asked to
  "stop the goal if quality of recipes is degrading." Honest assessment: the *validation*
  bar held perfectly (every one of the 122 new recipes was prototyped against an
  independent reference — scipy / scipy.spatial / scipy.stats.contingency / scikit-learn /
  statsmodels / numpy-financial / rapidfuzz / numpy closed forms — and matches to ≤1e-7,
  with three blind-benchmark re-enrichment rounds). But the *SOTA-distinctiveness* bar
  softened on a few late packs as the easy library veins got tapped: REL (reliability /
  Six-Sigma ops ratios), BD3 (niche boolean-vector distances) and the in-flight PERF pack
  (geometric-mean return / average win / average loss are near-trivial) drifted toward
  simple definitional ratios rather than research-grade or canonical-named metrics. **Pack
  PERF was reverted** (it was half-applied) to leave the tree green at 622. The GIPS Dietz
  returns in it (`simple_dietz_return` / `modified_dietz_return` / `holding_period_return`)
  ARE on-brand and worth redoing; the three return-stat components are skippable.
- **Quality bar for resuming (the lesson):** only add a recipe if it is (a) genuinely
  distinct from every existing kernel — NOT a reskin (e.g. a weighted-mean rebinding, a
  `1 - x` of an existing metric, or `payoff_ratio` which equals the existing
  `gain_loss_ratio`), and (b) has a *named paper / canonical library function / documented
  closed form* as its independent reference. When the clean veins run dry, SLOW DOWN and
  find truly novel validatable metrics rather than padding to hit the count. The Stop-hook
  count target is secondary to this.
- **New infrastructure this run:** a deterministic pure-stdlib OLS solver lives in
  `numeric.py` (`_solve_linear` Gauss-Jordan + `_ols_fit` normal equations) — it backs the
  heteroskedasticity tests (Pack HET) and OLS inference (Pack OLS) and unlocks more
  regression-based recipes. New reusable helpers: `_xy_ok`, `_xy_recipe`, `_str_recipe`,
  `_bool_counts`, `_grp_confusion`, `_anova_ss`, `_het_recipe`.
- **The 20 packs added this run** (each green + committed; family in parens): GM generalized
  means/k-stats (analytics/stats), NT normality+nonparametric tests (stats), FE4 forecasting/
  hydrology skill (forecasting), DEC diversity/entropy/welfare (analytics), CR3 distress
  models + Basel ratios (credit), EFF effect sizes/association (stats), MS microstructure
  spreads (liquidity/execution), SK sklearn classification/regression depth (classification/
  regression), CF corporate finance/capital budgeting (finance), TSF time-series/signal
  features (stats), REL reliability/Six-Sigma (engineering), RC2 robust correlation/slopes
  (stats), VD vector distances (analytics), IT information-theoretic association (stats),
  CAL2 calibration/decision-curve (classification), FAIR2 group-fairness depth (classification),
  HET heteroskedasticity tests (regression), STR string similarity vs rapidfuzz (llm-eval),
  BD3 boolean/set distances (analytics), OLS regression inference (regression). Plus three
  `suggest:` consolidation commits (blind gold set 1000→1230, +244 blind asks).
- **⚠️ Parallel session is ACTIVE and collided this run.** Another session is editing
  `scripts/calma.py`, `references/recipes.md`, `assets/reference_vectors.json` and adding
  `scripts/leakage_checks.py` + `tests/test_leakage_checks.py` (uncommitted right now). It
  regenerated `reference_vectors.json` while this session's generator still held an
  uncommitted PERF block, leaving the on-disk vectors file inconsistent with HEAD. Keep using
  pathspec-scoped commits; treat `reference_vectors.json` as shared and regenerate-then-commit
  it atomically inside your own pack; never `git checkout` a file the other session owns.

## Where things stood at the 500 milestone (commit `94cb5cd`) — 🎯 500 MILESTONE REACHED

- **Engine: 500 total recipes** = **498 reviewed** + **2 compiled-validated**. The
  "~500" marketing target is met (started this multi-session run at 274).
- **Website `RECIPE_COUNT` = 500** (auto-derived; see "Counter" below).
- Test suite: `recipes-sota: 1878 checks, 0 failures`. Typecheck clean.
- To go further, the open-pack list below still has untapped veins; the 8-step
  workflow is unchanged and every pattern is proven. Keep each metric SOTA +
  fully validatable (named paper / canonical library / documented closed form).
- Final packs to 500: `9df6cf3` QR; `004252e` RV realized vol/jump; `44ffc64` BR2
  Brinson-Fachler; `ba729c7` FE3 Nash-Sutcliffe/KGE/Willmott; `c1b9337` RL trimean/
  Hodges-Lehmann; `65d20d1` AC margin ratios; `bd74920` CX recovery/exposure-weighting;
  `18db126` HU Hurst R/S; `94cb5cd` DM Gini-mean-difference/L-moments.
- Newest packs: `679282d` DD drawdown depth (422→425); `6366b78` FC2 MAAPE/GMAE/CFE (425→428);
  `e70f529` DV diversity Shannon/Hill (428→432); `0aeb93d` WIN winsorized/trimmed (432→435);
  `1ebc704` BD2 spread duration/DV01/Z-spread (435→438); `351e93b` TS2 Box-Pierce/PACF/perm-entropy (438→441);
  `f5b02bb` OPT2 higher-order Greeks speed/zomma/charm/color (441→445);
  `e9cc0e5` CR2 Basel ASRF capital/RWA/Vasicek (445→448); `2e62980` CLU purity/B-cubed (448→452).
- Most recent 14 packs (commit · pack · range): `addeefa` TX transaction-cost (367→372);
  `4aa138b` PME KS-PME/Direct-Alpha (372→375); `b6b8a55` IC AIC/BIC/HQIC (375→380);
  `e2c6d03` INE inequality (380→384); `24bd602` EF effect sizes (384→388);
  `994028f` VOL range vol Parkinson/GK/RS/YZ (388→392); `09bec66` RGD GLM deviance/Tweedie (392→396);
  `8a387b8` FCI prediction-interval PICP/Winkler (396→400); `94eb4eb` AG inter-rater Scott/Gwet (400→404);
  `2b2584a` CO distance-corr/Somers-D (404→407); `a15165d` RNK ERR/Success/ARHR (407→410);
  `6ea7d86` SH robust shape Bowley/Moors/L-moments (410→414); `744bd19` TL tail-risk Hill/Pickands (414→417);
  `d5f0348` BIZ return-on-capital ROE/ROA/ROIC (417→422).
  New family since SV: `execution` (TX). PME/BIZ→`finance`, IC/RGD→`regression`,
  INE→`analytics`, EF→`stats`, VOL→`quant`, FCI→`forecasting`.
- Earlier packs this session (commit · pack · range):
- Packs shipped this session (buyer-weighted — risk/options/credit/PE/liquidity/ODD):
  - `f122c9c` Pack OPT — Black-Scholes options pricing + Greeks (274→283)
  - `d6346c9` Pack ES — expected-shortfall / VaR backtesting (283→290)
  - `a4b4f51` Pack CR — credit / default risk: EL/Altman/Merton (290→298)
  - `1c4abcc` Pack PA — portfolio construction & attribution: Brinson (298→305)
  - `f785aa0` Pack RC — rates / curve analytics (305→311)
  - `df0875b` Pack FM — fund / LP economics: TVPI/DPI/RVPI/carry (311→317)
  - `5b8f216` Pack LQ — liquidity / microstructure: Amihud/Roll/Kyle (317→323)
  - `e79b6b4` Pack AB — multiple-testing: Bonferroni/Šidák/Hochberg/BY (323→328)
  - `90da6fd` Pack TS — time-series: variance ratio / runs / ARCH-LM (328→331)
  - `6c5314e` Pack OPS — exposure / leverage / ODD metrics (331→338)
  - `6f89b43` Pack FX — market-model: idio vol / alpha-beta t-stats / bull-bear (338→344)
  - `30b8f5e` Pack AR — credit-quality / covenant ratios (344→351)
  - `f530ebd` Pack CAL — probability-calibration: Brier decomp/Spiegelhalter (351→358)
  - `e4a7194` Pack DIST — distribution distances: Hellinger/TV/Bhattacharyya (358→363)
  - `a1d662e` Pack SV — survival: KM / Nelson-Aalen / RMST (363→367)
- New registry+site families this session: `derivatives`, `credit`, `portfolio`,
  `fund`, `liquidity`, `exposure`. Others slotted into existing `finance`,
  `stats`, `quant`, `classification`.
- Prior packs: `70a8689` Pack IR (259→267), `01cac9c` Pack FI (267→274).
- Validation sources: scipy.stats.norm (BS Greeks), scipy.optimize.brentq
  (implied vol / YTM), statsmodels (multipletests, runstest_1samp, het_arch,
  OLS tvalues/mse_resid), lifelines (KM/NA/RMST), and documented closed forms
  (Acerbi-Szekely, Basel, Brinson, Lo-MacKinlay, Murphy/Brier decomposition,
  distribution distances) recomputed in numpy. All deterministic; venv unchanged.
- **NOTE the commit gotcha (step 8): use `git commit -- <8 files>` pathspec form** (now
  includes `recipe_descriptions.json` — the suggester enrichment; see step 4b).

**Target:** the marketing intent was "100+" → "500+", i.e. **~500 total recipes** — **now
reached (500 total).** To push past 500, keep going on the same workflow: there is no hard
rule that packs are exactly 8 — they've ranged 2–25. Build whatever size keeps each metric
genuinely SOTA and fully validatable (named paper / canonical library / documented closed form).

---

## The Stop hook / how the goal loop behaves

This is a `/goal`, so a Stop hook re-prompts every time you stop, reporting "X of 400
done" and nagging until the counter target is met. **Do not fight it** — just keep
shipping one fully-validated pack per pass. Each pass = one pack, committed green.
When the user wants to pause, they interrupt (as they did to request this doc).

---

## ⚠️ NEW since the 500 milestone — the suggester (READ THIS FIRST)

Calma now has a recipe **suggester** (`calma suggest` + auto-"did you mean?" inside
`verify`). It is backed by `assets/recipe_descriptions.json` (a description + aliases per
recipe), and **`tests/test_suggest.py` FAILS CLOSED if any registered recipe is missing an
entry or has <2 aliases.** So the per-pack workflow below now has an extra mandatory
touchpoint (step 4b) and an extra test in step 5, and the commit list is **8 files, not 7**.
A pack that skips enrichment will not pass tests. The authoritative spec is the
**"Definition of done for a NEW recipe"** block at the top of
`.claude/skills/calma/references/recipes.md` — this handoff mirrors it; if they ever
disagree, recipes.md wins.

The lesson baked in there (don't relearn it): enrich with **conceptual paraphrases** (how a
user describes the quantity WITHOUT its name), not just the formal term. Formal-name-only
enrichment measured 88.8% paraphrase recall@8; adding everyday phrasings lifted it to 94.4%.

## The non-negotiable per-pack workflow (6 touchpoints + website + commit)

Every recipe touches exactly these files. Skipping the reference-vector validation breaks
Calma's verdict; skipping the suggester enrichment (4b) breaks `calma suggest` AND fails the
test suite. Never skip either.

Paths are relative to repo root `/Users/rikhinkavuru/calma`.

1. **Kernel** → `.claude/skills/calma/scripts/numeric.py`
   - Pure-stdlib deterministic function. Guard up top:
     `if not xs or _has_nan(xs): return float("nan")` (and length-match guards).
   - Reuse existing helpers: `fmean`, `fstd(xs, ddof=1)`, `math.fsum`, `quantile(xs,q)`,
     `chi2_sf(x,df)`, `normal_sf(z)`, `z_ppf`, `betainc_reg`, `pearson_r`, `_confusion`,
     `_drawdown_series` (peak floored at 1.0), `_by_query`, `_em_normalize` (SQuAD),
     `skewness`, `kurtosis_excess`, `autocorrelation`. Grep before writing a new helper.
   - Append after the previous pack's last kernel (tail of file).

2. **Recipe registration** → `.claude/skills/calma/scripts/recipes.py`
   - `@register("metric_id", family=..., required_tags=[...], string_tags=[...],
     set_maturity="reviewed", accepted_conventions=["k=<int>"], periodicity_param=...)`
   - Body: `def recipe(cols, binding, convention=None): return _result(N.kernel(...), {...})`
   - Convention parsing helpers: `_conv_int(convention,key,default)`,
     `_conv_float(convention,key,default)`, `_conv_str`, `_conv_q`,
     `_periods(convention,binding,default)`. They parse both `"k=5"` and bare `"5"`.
   - Loop-registration is fine for families of near-identical recipes — see the
     `_qrr`/`_pr`/`_fi_y` closures at the bottom of recipes.py for the pattern.

3. **Test wiring** → `.claude/skills/calma/scripts/tests/test_recipes_sota.py`
   - Add one `KINDS["kind"] = lambda a: N.kernel(a["..."])` per metric. The `a` dict
     keys must match the arg names you put in the generator `case(...)` args.
   - Add each new `metric_id` to the `EXPECTED` set.
   - Bump the count literal in the final `truth(...)` line:
     `"registry holds exactly the NNN reviewed recipes"` — NNN must equal the new
     reviewed count (498 now → +N).
   - Invariants the suite enforces: `EXPECTED == _reviewed` exactly, every `KINDS`
     kind has ≥1 reference vector, and `data.ts` mirrors the registry (so the website
     entry in step 6 is mandatory, not optional).

4. **Reference vectors** → `.claude/skills/calma/calibration/gen_reference_vectors.py`
   - Add `case(cid, kind, args, expected, atol=..., rtol=...)` blocks **before** the
     `# ====== write ======` marker (near line 1365+).
   - `expected` must come from an INDEPENDENT reference: numpy / scipy / sklearn /
     statsmodels / numpy-financial / jiwer / fairlearn / lifelines, OR a documented
     closed-form computed in plain Python when no library implements it (that's what
     Pack IR and Pack FI did — definitional formulas, plus `scipy.optimize.brentq` as
     the independent solver for YTM). Per-pack `import` inside the file is fine.
   - Deterministic data only: `uniforms(seed,n,lo,hi)` LCG, or fixed literal fixtures.
     Reuse module-level fixtures where they exist (`queries`/`ranks`/`rels_bin`/`RETR`
     for retrieval; `qr`/`qbench`/`ddq` floored drawdown series for quant).
   - **NEVER** use `Date.now()`/`random` — determinism is the whole point.

4b. **Suggester enrichment (MANDATORY)** → `.claude/skills/calma/assets/recipe_descriptions.json`
   - Under the top-level `"recipes"` object, add one entry per new `metric_id`:
     ```json
     "your_metric_id": {
       "description": "one plain-language sentence (<=16 words) of what it measures",
       "aliases": ["full spelled-out name", "common abbreviation",
                   "<3-6 CONCEPTUAL paraphrases: how a user describes it WITHOUT the name>"]
     }
     ```
   - The conceptual paraphrases are the part that carries paraphrase recall — write them as a
     user who forgot the term would (lowercase, 5-8 aliases total). e.g. for a Brinson
     allocation effect: `["did over/underweighting sectors help","value added by where i put money",
     "allocation contribution to outperformance"]`, not just `["brinson allocation"]`.
   - `>=2 aliases` and a non-empty `description` are HARD requirements (the test enforces them).
   - **Claim routing (only when the metric has a common SPOKEN name a report would use):** also
     add a `("phrase", "metric_id")` pair to `CLAIM_METRIC_HINTS` in
     `.claude/skills/calma/scripts/draft_contract.py` so a written claim auto-routes to it. This
     is SEPARATE from enrichment (enrichment feeds only the suggester; this feeds the zero-touch
     hook / `--metric`-free verify). Skip it for obscure metrics nobody states by name.

5. **Run the harness until green** (must use the reference venv for the generator):
   ```
   cd /Users/rikhinkavuru/calma/.claude/skills/calma
   /Users/rikhinkavuru/calma-refvenv/bin/python calibration/gen_reference_vectors.py
   python3 scripts/tests/test_recipes_sota.py        # want: "N checks, 0 failures"
   python3 scripts/tests/test_suggest.py             # enrichment coverage + recall floors
   ```
   The generator writes `assets/reference_vectors.json` (commit it). A `data.ts mirrors
   the registry` FAIL just means step 6 isn't done yet — finish it, rerun. A `test_suggest`
   coverage FAIL means a new recipe has no `recipe_descriptions.json` entry — finish step 4b.

6. **Website entry** → `app/recipes/data.ts`
   - Add one object `{ id, name, claim, what, how, ref, conv? }` per recipe into the
     matching `FAMILIES` entry (`trading`, `classification`, `regression`, `analytics`,
     `engineering`, `retrieval`, `stats`, `finance`, `compiled`). `id` MUST equal the
     registry `metric_id`. Create a new family object only if no existing one fits.
   - `claim` is the quoted report sentence ("“mod duration 4.32”"); `how` is the
     one-line recompute recipe; `ref` names the authority. Match the surrounding voice.
   - Typecheck: `npx tsc --noEmit` (from repo root) → exit 0.

7. **Catalog header** → `.claude/skills/calma/references/recipes.md`
   - Bump line 1: `# Recipe catalog (NNN recipes, all SOTA-validated)` to the new total
     (500 now). NNN here is the TOTAL (reviewed + compiled), not just reviewed.

8. **Commit ONLY these 8 files** (never stage parallel-session pilot-hardening files).
   **Use a pathspec-scoped commit** — `git commit -- <the files>` — so it can't absorb
   changes a parallel session has staged in the index. (Plain `git add … && git commit`
   bit us once: between two packs the other session staged a batch of `rehearsals/` +
   `PLAN.md` deletions, and the no-pathspec commit swept them in. Fixed with a mixed reset
   + re-commit; pathspec form avoids it entirely.)
   ```
   git commit -- \
     .claude/skills/calma/scripts/numeric.py \
     .claude/skills/calma/scripts/recipes.py \
     .claude/skills/calma/scripts/tests/test_recipes_sota.py \
     .claude/skills/calma/calibration/gen_reference_vectors.py \
     .claude/skills/calma/assets/reference_vectors.json \
     .claude/skills/calma/assets/recipe_descriptions.json \
     .claude/skills/calma/references/recipes.md \
     app/recipes/data.ts
   ```
   (Add `.claude/skills/calma/scripts/draft_contract.py` as a 9th file in any pack where you
   added a `CLAIM_METRIC_HINTS` pair. You can `git add` first for review, but the pathspec on
   `commit` is the guard.)
   Message: `recipes: Pack XX — <topic> (OLD→NEW)` + a body line on what was validated
   against, ending with:
   `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
   Do **not** push unless asked (the user pushes / a parallel session may own `main`).

---

## The two count numbers (don't confuse them)

- **Total** = reviewed + compiled = **500** (498 reviewed + 2 compiled). Goes in the
  `recipes.md` header and is what `RECIPE_COUNT` shows on the site.
- **Reviewed** = **498**. Goes in the `test_recipes_sota.py` `truth(...)` literal and the
  `EXPECTED` set. Compiled-validated recipes (the 2) are NOT in `EXPECTED`.
- Each pack of N reviewed recipes: total += N, reviewed += N, both literals move by N.
  (Also +N entries in `recipe_descriptions.json`, enforced by `test_suggest.py`.)

## Counter on the website — already dynamic, no manual bump

`app/recipes/data.ts` line ~2378: `export const RECIPE_COUNT = FAMILIES.reduce((n,f)
=> n + f.recipes.length, 0)`. The recipes page and meta description render this live, so
adding the step-6 entries updates the displayed number automatically. There is **no
hardcoded "100+"/"500+" string** anywhere in `app/` (verified). The original goal text
said "update 100+ to 500+" but that refactor already happened — the number is derived.
If the user later wants a literal "500+" hero badge, none exists today and would need to
be added to `app/page.tsx` deliberately; don't invent one.

---

## What's already covered (so you don't duplicate) — 500 recipes by family

Run this to get the live, authoritative list any time:
```
cd /Users/rikhinkavuru/calma/.claude/skills/calma && python3 -c "
import sys; sys.path.insert(0,'scripts'); import recipes
from collections import defaultdict
fam=defaultdict(list)
for i,fn in recipes._REGISTRY.items(): fam[fn.manifest.get('family','?')].append(i)
for f in sorted(fam): print('## %s (%d): '%(f,len(fam[f]))+', '.join(sorted(fam[f])))
"
```
Current family totals (registry families; the site groups them differently): analytics 62,
classification 66, credit 21, derivatives 16, engineering 22, execution 5, exposure 7,
finance 40, forecasting 24, liquidity 6, llm-eval 7, portfolio 9, quant 90, regression 24,
retrieval 14, stats 87. **Total 500.**

Already-registered diagnostics people often re-propose by accident: `durbin_watson`,
`jarque_bera`, `autocorrelation`, `ljung_box`, plus full VaR backtesting (`kupiec_pof`,
`christoffersen_cc`/`_independence`), Sharpe/Sortino/Calmar/Omega/ulcer family, fairness
(demographic parity, equalized odds), survival (`concordance_index`), causal (ATE,
CUPED, NNT). **Always grep `numeric.py` and dump `_REGISTRY` before building a kernel.**

---

## High-value pack ideas still open (buyer-weighted, all validatable, non-model)

Pick from these or research better ones. Each must be deterministic and checkable
against a published reference or a documented closed form.

1. **Options / derivatives risk (analytic, not simulated).** Black-Scholes price +
   Greeks (delta/gamma/vega/theta/rho) and implied vol via bisection. Column model:
   per-position params → **portfolio-aggregate** claim (e.g. book delta = Σ qty·delta),
   since recipes return one scalar. Validate against a manual BS built on
   `scipy.stats.norm`, or `py_vollib` if added to the ref venv. Huge for pod shops /
   bank model-risk (option-pricing model validation).
2. **More rates / curve analytics.** Spot-vs-par yield, forward rate from two zeros,
   key-rate duration, spread duration, effective duration via bump-and-reprice.
3. **Credit / default risk.** Expected loss (PD·LGD·EAD), loss-given-default stats,
   altman-z, merton distance-to-default (closed form), CECL-style weighted EL.
4. **Expected-shortfall backtests.** Acerbi–Székely Z1/Z2, ES quantile loss, Basel
   traffic-light zones, dynamic-quantile (Engle–Manganelli) test. Complements the
   existing Kupiec/Christoffersen VaR suite — directly what model-risk teams run.
5. **Portfolio construction / attribution.** Brinson attribution (allocation vs
   selection), risk contribution / component VaR, diversification ratio, effective
   number of bets, turnover, concentration (already have HHI — extend to active share).
6. **NLP / text-gen overlap (no model).** BLEU, ROUGE-N/L, chrF, METEOR-lite, TER via
   `sacrebleu`/`rouge_score` (add to ref venv). Extends llm-eval beyond token-overlap.
7. **Time-series model diagnostics.** ADF / KPSS stationarity (hard — tabulated crit
   values; consider returning the statistic only), ARCH-LM heteroskedasticity, runs
   test, Theil-Sen already exists. Validate vs statsmodels.
8. **Experiment / AB depth.** Sequential-test bounds, sample-ratio already done (SRM),
   minimum detectable effect, power, Benjamini-Yekutieli, Sidak correction.

When unsure whether a metric is "real enough," prefer ones with a named paper or a
canonical library implementation — that's both the validation source and the SOTA proof.

---

## Gotchas learned the hard way this session

- **Drawdown peak convention.** Kernels floor the running equity peak at initial
  capital 1.0 (matches the engine's `max_drawdown`). Any reference must use
  `np.maximum(np.maximum.accumulate(eqc), 1.0)`, not raw `accumulate`. Got ulcer/pain/
  martin wrong once because of this.
- **metric_id collisions.** Pack CR's classification NPV (`npv`) silently overwrote the
  net-present-value `npv`. It was renamed to `negative_predictive_value`. Before naming
  a recipe, confirm the id is free in `_REGISTRY`.
- **`numeric.py` "File has not been read yet"** on Edit → Read the tail first, then edit.
- **Reference venv only for the generator.** `gen_reference_vectors.py` needs
  `/Users/rikhinkavuru/calma-refvenv/bin/python` (numpy 2.4.6, scipy 1.17.1, sklearn
  1.9.0, statsmodels 0.14.6, numpy-financial, jiwer, fairlearn 0.14.0, lifelines). The
  test suite (`test_recipes_sota.py`) is pure stdlib — run with plain `python3`. The
  venv lives OUTSIDE the repo so it's never committed.
- **scipy FutureWarning** on `anderson` is benign noise; ignore.
- **Don't stage unrelated files.** A parallel session works pilot-hardening + legal in
  this repo. Stage only the 7 recipe files listed above.

---

## First action in the new session

1. `cd /Users/rikhinkavuru/calma && git log --oneline -3` and `git status` — confirm a clean
   tree at the current `main` HEAD (the suggester + handoff work landed; do NOT expect the old
   `01cac9c`/274 state — the engine is at **500** now).
2. Dump `_REGISTRY` (command above) to see the live 500 by family.
3. Read the **"Definition of done for a NEW recipe"** block at the top of
   `.claude/skills/calma/references/recipes.md` — that plus this handoff is the full workflow,
   now including suggester enrichment (step 4b) and `test_suggest` (step 5).
4. Pick the next pack, build it through the workflow (all 8/9 files), and confirm BOTH
   `test_recipes_sota.py` AND `test_suggest.py` are green before committing.
5. For a large run, give the new recipes the same blind-benchmark treatment the 500 got:
   after the packs land, generate 2 blind asks per new recipe (named + conceptual paraphrase,
   by agents who don't see the ranker), append to `tests/suggest_bench/gold.json`, re-run
   `bench.py`, and re-enrich whatever the weak-recipe report flags. Coverage alone (the test
   guard) guarantees every recipe HAS enrichment; the benchmark is what makes it GOOD.
6. The Stop hook keeps you honest on the count.
