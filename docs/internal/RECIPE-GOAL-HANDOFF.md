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

## Where things stand (as of commit `94cb5cd`) — 🎯 500 MILESTONE REACHED

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
- **NOTE the commit gotcha (step 8): use `git commit -- <7 files>` pathspec form.**

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

## The non-negotiable per-pack workflow (5 touchpoints + website + commit)

Every recipe touches exactly these files. Skipping the reference-vector validation is
the one thing that breaks Calma, so never skip it.

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

5. **Run the harness until green** (must use the reference venv for the generator):
   ```
   cd /Users/rikhinkavuru/calma/.claude/skills/calma
   /Users/rikhinkavuru/calma-refvenv/bin/python calibration/gen_reference_vectors.py
   python3 scripts/tests/test_recipes_sota.py        # want: "N checks, 0 failures"
   ```
   The generator writes `assets/reference_vectors.json` (commit it). A `data.ts mirrors
   the registry` FAIL just means step 6 isn't done yet — finish it, rerun.

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

8. **Commit ONLY these 7 files** (never stage parallel-session pilot-hardening files).
   **Use a pathspec-scoped commit** — `git commit -- <the 7 files>` — so it can't absorb
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
     .claude/skills/calma/references/recipes.md \
     app/recipes/data.ts
   ```
   (You can `git add` the 7 first for review, but the pathspec on `commit` is the guard.)
   Message: `recipes: Pack XX — <topic> (OLD→NEW)` + a body line on what was validated
   against, ending with:
   `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
   Do **not** push unless asked (the user pushes / a parallel session may own `main`).

---

## The two count numbers (don't confuse them)

- **Total** = reviewed + compiled = **274**. Goes in `recipes.md` header and is what
  `RECIPE_COUNT` shows on the site.
- **Reviewed** = **272**. Goes in the `test_recipes_sota.py` `truth(...)` literal and
  the `EXPECTED` set. Compiled-validated recipes (the 2) are NOT in `EXPECTED`.
- Each pack of N reviewed recipes: total += N, reviewed += N, both literals move by N.

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

1. `cd /Users/rikhinkavuru/calma && git log --oneline -3` to confirm you're on
   `01cac9c` (Pack FI) and the tree is clean.
2. Dump `_REGISTRY` (command above) to see the live 274.
3. Pick the next pack (Options/Greeks #1 and ES-backtests #4 are the highest-value
   open items for the buyer list), build it through the 8-step workflow, commit green.
4. Repeat until ~500. The Stop hook will keep you honest on the count.
