# Validity families — handoff (next work: deflated_sharpe recipe · realism + contamination · benchmark)

**Status (2026-06-14):** Leakage + overfitting validity families and the new `INVALIDATED` verdict are
SHIPPED and merged to `main` (10 commits `c2fe213`..`444d3bb`, 27 suites green, 4 independent
fresh-verifiers). This doc hands off the three follow-ups.

---

## 0. Orientation — the architecture you'll extend

The whole pipeline is `re-execute → recompute → compare → verdict → gate → attest → registry`. A
"validity family" is an **additive findings rail** off the bound artifacts that can **promote** the
headline claim's verdict. Where things live (all under `.claude/skills/calma/`):

| Concern | File |
|---|---|
| The single verdict function (enum + the gap-free promotion inputs) | `scripts/verdict.py` |
| Gate, repo-verdict rollup, semantic validation | `scripts/ledger.py` |
| Per-claim `verdict_inputs` construction | `scripts/compare.py` |
| Ledger assembly + where families are wired | `scripts/calma.py` → `_assemble_ledger` |
| Pure-stdlib math kernels | `scripts/numeric.py` |
| Contract schema + auto-detect | `scripts/draft_contract.py` (`validate_contract`, `draft`) |
| Existing families to copy | `scripts/backtest_checks.py`, `scripts/leakage_checks.py`, `scripts/overfitting_checks.py` |
| Report rendering (verdict word/symbol/HTML) | `scripts/report.py` |
| Tests | `scripts/tests/test_*.py` (auto-discovered by `run_all.py`) |

**The verdict model (memorize this — every family uses it).** `verdict.py` has four conservative,
default-False "validity" inputs. A family **never** computes a verdict; it sets one of these on the
headline claim's `verdict_inputs` and the label is re-derived (byte-for-byte re-derivable, which
`ledger.semantic_validate` enforces):

| input set on `verdict_inputs` | resulting verdict | exit | when |
|---|---|---|---|
| `validity_invalidated` + `oos_claim_asserted` | **INVALIDATED** | 1 | authoritative finding, claim asserts the invalidated thing (OOS/survival) |
| `validity_unresolved` | **CAN'T-CONFIRM** (INCONCLUSIVE) | 1 | concern real but the scope can't be adjudicated as claimed |
| `soft_validity_caveat` | **CONFIRMED-WITH-CAVEATS** | 0 | heuristic / a bare reproduced number with a detected-but-unclaimed issue |
| (none) | CONFIRMED | 0 | clean |

**Plain REFUTED stays strictly gap-gated** — only a real numeric gap (incl. a *corrected re-run*, like
leakage's) yields REFUTED. A finding never manufactures it.

**The shape of a family** (copy `leakage_checks.py` / `overfitting_checks.py`):
1. `scripts/<fam>_checks.py` with `run_checks(contract, base, claim_id[, claim_text]) -> [finding,...]`
   (pure detection; each finding carries `validity_class` ∈ {authoritative, soft, ...}) and
   `apply_validity(claims, findings, contract, claim_text[, base])` (the scope-guarded promotion).
2. Findings are BC-shaped dicts; dimension must be in `ledger.DIMENSIONS`; it is an `EXEC_DIMENSION`
   so `reverify.kind` must be `artifact-recheck`/`requires-reexecution`, **never** `static-reread`.
3. Wire into `calma._assemble_ledger` beside leakage/overfitting: `findings.extend(FAM.run_checks(...))`,
   `FAM.apply_validity(...)`, set `scope.families[fam]`, and update `_not_verified`.
4. Contract surface → `draft_contract.validate_contract` (+ `draft` auto-detect), additive/optional.
5. Tests → `scripts/tests/test_<fam>_checks.py` (lattice through real ledgers + an e2e `_assemble_ledger`).
6. **Fresh-verifier**: a context-free agent that reproduces the lattice + magnitudes from its own probes.

**Invariants (non-negotiable):** pure stdlib at run/CI; no model in the decision path; degrade to
NOT-APPLICABLE/INCONCLUSIVE, never false-confirm/false-refute; fail-closed (`verdict.is_clean` is an
allowlist); the families compose order-safely (each `apply_validity` only promotes a still-clean
headline, downward — worst-wins). New verdict words, if any, must be added to `verdict.VERDICTS`,
`ledger.NONCLEAN_REPO`, the `report.py` render maps, the `calma.py` exit/cache/tally/publish switches
(use `verdict.CATCH_VERDICTS`/`is_clean`), and `hook_stop.py`.

---

## 2. The `deflated_sharpe` registered recipe (the REFUTED-via-recipe-rail path)

**Why deferred:** the findings rail already covers overfitting (INVALIDATED/CAVEAT/CAN'T-CONFIRM). A
registered recipe adds the *direct* path — a user claims a deflated number (`--metric deflated_sharpe`)
and it is recomputed → CONFIRMED/REFUTED. It was deferred only because it touches the **parallel recipe
session's curated registry**; do this when that session is settled.

**The kernels already exist** (`numeric.py`): `deflated_sharpe_ratio(sr, n_obs, skew, kurt_excess,
n_trials, var_sr)` and `pbo_cscv(matrix, n_splits)`. So registration is the only work.

**Files to touch (all the recipe session's curated domain — coordinate):**
1. `scripts/recipes.py` — `@register("deflated_sharpe", family="quant", required_tags=["return"],
   set_maturity="reviewed", ...)`. **Design point:** recipes receive `(cols, binding, convention)` only —
   not the contract — so `n_trials`/`var_sr` must be encoded in the `convention` string (e.g.
   `"trials=1000,var_sr=0.002"`) and parsed in the recipe. The recipe computes the per-period Sharpe
   from the return column (mean/std, NOT annualised — see overfitting_checks `_per_period_sharpe`), then
   calls `N.deflated_sharpe_ratio(...)`. Return the **raw probability**; the threshold (`1-DSR>0.05`) is
   a claim/decision matter, not the recipe's.
3. `scripts/tests/test_recipes_sota.py` — add the id to the hardcoded `EXPECTED` reviewed-recipe set
   (≈ line 1010-1038; currently "the 620 reviewed recipes") with a pack comment; add a `KINDS` dispatch
   entry + at least one reference-vector case (a DSR case already exists, frozen, in
   `assets/overfitting_reference_vectors.json` — mirror its numbers, or add one to
   `assets/reference_vectors.json` via `calibration/gen_reference_vectors.py`).
4. `assets/recipe_descriptions.json` — enrich it (the coverage/`suggest` gate requires every reviewed
   recipe to have a description; `test_suggest`/`sniff` fail otherwise).
5. `app/recipes/data.ts` — mirror the registry (the "data.ts mirrors the registry" gate) + the site
   `RECIPE_COUNT` bumps by one.
6. (Optional) `pbo_cscv` as a recipe needs a *matrix* artifact, so it's a worse fit for the single-column
   recipe rail — keep it findings-rail-only unless a trials-matrix `--metric` UX is wanted.

**Acceptance:** `python3 scripts/tests/run_all.py` green; `calma verify <dir> --metric deflated_sharpe
--claim "deflated sharpe 0.3 trials=1000"` produces a real CONFIRMED/REFUTED on the deflated number.

---

## 3. Realism deflators + contamination (the next two validity families)

These are the remaining M3–M4 ceiling. Follow the family shape in §0. Both produce INVALIDATED on an
authoritative finding when the claim asserts the thing being invalidated, CAVEAT for soft/heuristic, and
CAN'T-CONFIRM when the inputs needed to adjudicate aren't declared.

### 3a. Realism deflators (`scripts/realism_checks.py`)
**Idea:** an optimistic backtest assumes frictionless fills; deflate to realistic frictions and recompute
net — if the edge vanishes, the result is invalid as a *live* claim. This generalizes the three catches
already in `backtest_checks.py` (omitted costs / cherry-picked window / survivorship) — **coordinate with
that file; extend, don't duplicate.**
- Detectors (deterministic, off the artifacts/contract): transaction costs + slippage applied per
  turnover; **capacity / market-impact** (claimed size vs ADV → impact deflator); **borrow/short cost**
  for short legs; **fill assumptions** (close vs VWAP vs next-open); **turnover/leverage** sanity.
- The differentiator (like leakage's corrected re-run): **realism-deflated recompute** — re-run the
  metric with the friction model applied → "claimed Sharpe 2.1 → cost/impact-deflated 0.4" → REFUTED via
  the gap path (driving_dimension `execution-realism`), or INVALIDATED if not re-computable but the claim
  asserts net/live performance.
- Contract surface: a `frictions:{fee_bps, slippage_bps, borrow_bps, fill, adv, impact_model}` block
  (additive to `validate_contract`); absent → NOT-APPLICABLE (or use declared `costs`/`universe` already
  parsed by `backtest_checks`). **Never guess** a friction the author didn't declare.
- Reference: if any kernel is added (e.g. a square-root market-impact model), put it in `numeric.py`
  (append-only) + a SEPARATE frozen `assets/realism_reference_vectors.json` + manifest + a stdlib-only
  test — the decoupling pattern that kept overfitting off the recipe session's files.

### 3b. Contamination (`scripts/contamination_checks.py`)
**Idea:** broader than leakage's train/test overlap — the *evaluation itself* is contaminated. Most
salient for LLM/benchmark evals.
- Detectors: **benchmark/test-set memorization** (eval items present in a declared pretraining/corpus
  manifest — set/hash overlap, like leakage's row hash but eval-vs-corpus); **near-duplicate
  contamination** (n-gram / minhash overlap above a threshold → LABELED HEURISTIC → soft); **canary /
  known-leaked-benchmark** detection (eval == a public benchmark known to be in common crawl); **label
  contamination** (the answer key embedded in the prompt/features — overlaps target-leakage, coordinate).
- Verdict mapping: exact eval-in-corpus overlap on a "held-out/zero-shot/uncontaminated" claim →
  INVALIDATED; heuristic near-dup → CAVEAT; corpus manifest not declared → NOT-APPLICABLE (never guess).
- Contract surface: `corpus:{manifest: path}` (the pretraining/known-corpus hashes) + reuse `keys.id`.
  Pure stdlib (`hashlib` for exact; a stdlib minhash/shingling for near-dup). No new deps.

For both: add the dimension to `ledger.DIMENSIONS` + `EXEC_DIMENSIONS` if not present (`execution-realism`
and `data-integrity` already exist and may suffice; a new `contamination` dim is cleaner — mirror how
`leakage`/`overfitting` were already reserved). Flip the SKILL.md/`_not_verified` roadmap copy for each
family **only when it actually ships** (honesty invariant) — `SKILL.md` lines ~19 and ~151, and
`calma._not_verified`.

---

## 4. Benchmark / demo — exercise the INVALIDATED teardowns

The most sellable outputs the engine now produces. Three reproducible fixtures (the demo dirs used in
dev were ephemeral `/tmp` — recipes below rebuild them; consider committing them under
`assets/demos/` for the demo/benchmark session).

1. **Leakage → INVALIDATED** ("your held-out AUC isn't held-out"): `gen_fixture.py` emits `train.csv` +
   `test.csv` where 30% of test rows are exact duplicates of train rows; `verify.yaml` pins `auc` to
   `test.csv` with `split:{train,test}` + `keys:{id,target}`.
   `calma verify <dir> --claim "auc <V> on the held-out test set" --metric auc`
   → `✗ INVALIDATED ... 30 of 100 test rows (30.0%) are exact duplicates ... claimed V → recomputed V`, exit 1.
2. **Leakage-corrected → REFUTED** ("claimed → leakage-corrected"): same but the contaminated rows are
   "easy" (separable) and the clean rows are ties → de-contaminated recompute collapses the number.
   → `✗ REFUTED ... claimed 0.755 → leakage-corrected 0.5 (dropped 30 contaminated of 100 eval rows)`, exit 1.
3. **Overfitting → INVALIDATED** ("doesn't survive multiple-testing"): `returns.csv` with a weak
   per-period edge; `verify.yaml` declares `trials:1000` + `var_sr` (or a `trials_artifact` matrix).
   `calma verify <dir> --claim "sharpe <annualised> - the best of 1000 backtested configs" --metric sharpe`
   → `✗ INVALIDATED ... does not survive multiple-testing correction over N=1000 trials: DSR=0.149 (p=0.851)`, exit 1.

**What to show:** the distinct verdict word `INVALIDATED`, the evidence line, the "claimed X → Y" pair,
and exit 1. For a cross-model benchmark (`/benchmark-models`), feed the same fixtures and confirm the
verdict word + exit code are stable (the verdict is computed by deterministic scripts, never a model — so
all models should produce the identical stamp; that's the headline). The producer in any demo recording
must be a weak model (per the demo-video memory note) so the audit is adversarial.

---

## 5. Verify-as-you-go

- Suite: `python3 .claude/skills/calma/scripts/tests/run_all.py` (must stay green; ~27 suites).
- Reference-vector regen (only if you add numeric kernels): a fresh pinned venv (numpy/scipy/sklearn);
  see `calibration/gen_overfitting_vectors.py` for the gated pattern (constructed-truth → scipy
  reference → frozen vectors + manifest; CI imports no reference lib).
- After each new family: a context-free fresh-verifier that reproduces the lattice + exact magnitudes
  from its own fixtures (4 such agents validated the leakage/overfitting work — keep the bar).
- PLAN.md (`.claude/skills/calma/PLAN.md`) is the design of record for the shipped work; mirror its
  structure for the next families.
