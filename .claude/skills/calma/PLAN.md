# PLAN — LEAKAGE + OVERFITTING detectors, and the `INVALIDATED` verdict

Status: **APPROVED (v3) — implementing serially, leakage-first. Decisions locked below.**
Recon: direct reads of `verdict.py`, `ledger.py`, `compare.py`, `registry.py`, `attest.py`,
`report.py`, `calma.py`, `backtest_checks.py`, `recipes.py`, `numeric.py`, `draft_contract.py`,
`served_fraction.py`, `calibration/*`, the `assets/leakage/` fixture.

Two detectors on the existing findings rail + a new first-class verdict **`INVALIDATED`**. The whole
design routes through **existing verdict machinery** — no new exit path. The verdict follows the
**claim's own scope** (mirrors the leakage OOS scope-guard).

---

## 0. Invariants (never broken)
1. Deterministic / bit-stable; **pure stdlib only**. No numpy/scipy/new deps in any shipped/run/CI path.
2. No model in the decision path. Stats only from `numeric.py`; label only from `verdict.verdict()`.
3. Honesty: degrade to **NOT-APPLICABLE** (no finding) or **CAN'T-CONFIRM**, never false-confirm /
   false-refute. **Never auto-infer N**; **never block a literally-true reproduced number.**
4. The stamp never lies. **Plain REFUTED stays strictly gap-gated.** Every new verdict shape is reached
   only by a conservative *degrade* (toward CAVEATS / INCONCLUSIVE / INVALIDATED), never by inflating.
5. Redaction-by-construction (`_redact_home`; registry `ALLOWED_FIELDS` unchanged).

Baseline (captured): `python3 scripts/tests/run_all.py` → **23 suites, 0 failed (~2,965 checks)**.
Stays green at every step. Acceptance = exact command + real output.

---

## 1. The verdict model (LOCKED)

New verdict **`INVALIDATED`** = "the number reproduces while the result is invalid." Exit 1. Severity-
peer of REFUTED (headline → repo `INVALIDATED`; non-headline → repo `MIXED`, like REFUTED — verified
`MIXED` is **not** overloaded: `compute_repo_verdict` returns MIXED *only* for `nonheadline_refuted`,
caveat-only repos return `CONFIRMED-WITH-CAVEATS`).

Everything is produced by **promoting the headline claim's verdict in `_assemble_ledger`** — set a
conservative input on the claim's `verdict_inputs` and re-derive `V.verdict(vi)` (preserving the
byte-equal re-derivation invariant). Four new conservative-default inputs in `verdict.py`:

| Input (default False) | Within-budget (number reproduces) → | Exit | Finding |
|---|---|---|---|
| `validity_invalidated` + `oos_claim_asserted` | **INVALIDATED** | 1 | authoritative `blocker` of the driving dim |
| `validity_unresolved` | **INCONCLUSIVE** (displays CAN'T-CONFIRM) + fix line | 1 | `major` of the driving dim (carries the fix `unblock`) |
| `soft_validity_caveat` | **CONFIRMED-WITH-CAVEATS** | 0 | `minor` of the driving dim (names the concern) |
| (none) | CONFIRMED | 0 | — |

`_decide` within-budget order: `validity_invalidated`+`oos` → INVALIDATED; elif `validity_unresolved` →
INCONCLUSIVE; elif sign/`soft_validity_caveat`/`_caveat_reasons` → CAVEATS; else CONFIRMED. Placed
AFTER G1/G1b/G1c/G2/G3 so a failed/flaky/degenerate run still goes INCONCLUSIVE, and it **never
overrides a numeric REFUTED** (exceeds-budget path is untouched). The specific fix text comes from the
finding's `unblock` via `report._fix_line`; `verdict()`'s reason stays generic.

### Scope-guard (claim-scope drives severity — anti-over-fire)
- **OOS asserted** + authoritative contamination, not correctable → INVALIDATED.
- **In-sample** declared + contamination → `soft_validity_caveat` → CAVEATS, exit 0.
- **OOS indeterminate** + contamination → `validity_unresolved` → CAN'T-CONFIRM, exit 1, fix
  "declare whether the claim is out-of-sample." Never a manufactured INVALIDATED, never buried.
- Authoritative contamination **correctable** → REFUTED via the corrected recompute (numeric gap path).

### Fail-closed (the load-bearing safety property)
Convert verdict checks to an **allowlist**: `clean ⇔ repo_verdict ∈ {CONFIRMED, CAVEATS}` (already how
`ledger.gate` works). Add `verdict.is_clean(rv)` + `verdict.CATCH_VERDICTS = (REFUTED, "MIXED",
INVALIDATED)`. Replace every `rv in ("REFUTED","MIXED")` "is-broken?" test with the shared set / `not
is_clean`. A missed switch-site then degrades to over-cautious (exit 1, no clean badge), never
false-confirm. **Fresh-verifier property test: no code path maps an unknown verdict to exit 0 / a clean
badge.**

### Exhaustive plumbing checklist
- **`verdict.py`** — `INVALIDATED` in enum + `VERDICTS`; 4 inputs in `DEFAULTS`; `_decide` branches;
  `is_clean`/`CLEAN_VERDICTS`/`CATCH_VERDICTS`; `confidence` treats INVALIDATED as definite (not 0.0).
- **`ledger.py`** — `NONCLEAN_REPO += {"INVALIDATED"}`; `compute_repo_verdict` (headline INVALIDATED →
  INVALIDATED, non-headline → MIXED); `semantic_validate` INVALIDATED branch (driving_dimension + linked
  `blocker` of that dim + `oos_claim_asserted`; **no gap/reproduction required**); generalize the
  non-waivable-REFUTED-vs-clean guard to include INVALIDATED. `gate`/`CLEAN_REPO` already fail-closed.
- **`calma.py`** — `1384` `--fail-on refuted` → `CATCH_VERDICTS`; cache guards `486,496` add INVALIDATED;
  tally `1049`; catch counters `1052,1190`; batch clean `1178`; render tail `1406` (INVALIDATED copy);
  publish note `1661` → `CATCH_VERDICTS`. Default gate path (`gate_exit`) already fail-closed.
- **`report.py`** — `_TOPLINE`/`_SYMBOL`/`_ANSI`/`_html_verdict_class` + `.v-INVALIDATED` CSS;
  render: INVALIDATED shows "claimed X → recomputed X (reproduces)" + the blocker locator; add
  INVALIDATED to the fix-line render condition; `_DIMENSION_GLOSS` leakage/overfitting; surface
  `minor` validity caveats + the CAN'T-CONFIRM overfitting note even on a CONFIRMED/CAVEATS headline.
  **Teardown/SVG card: evidence-driven** (decision c) — lead with the finding magnitude (overlap count
  / PBO), NOT an empty gap field; built in the leakage step when real INVALIDATED data exists.
- **`hook_stop.py`** — `425` agent guardrail → `CATCH_VERDICTS` (INVALIDATED blocks the agent).
- **`attest.py`/`registry.py`** — **no schema change** (`verify_bundle` re-derives any label byte-for-
  byte; entry `verdict` is a whitelisted string, `opened_entry` already stores `"PENDING"`). Replay
  bundle already ships `ledger.py`+`verdict.py`. Verify the verdict-count rendering surfaces INVALIDATED.

`SOUNDNESS_CAVEAT_DIMENSIONS` is **left unchanged** — the soft path now goes through
`soft_validity_caveat` per-claim (exit 0), not the blocking dimension-downgrade (which is exit 1).

---

## 2. WS1 — LEAKAGE (`scripts/leakage_checks.py`)
Reserved EXEC dim → findings are `artifact-recheck`/`requires-reexecution`, never `static-reread`.
Existing `assets/leakage/` fixture is the manual leakage-re-run (honest held-out preds + leaked claim →
standard recompute REFUTES, `test_m2.py:86`).

### Contract surface (additive, optional) — `draft_contract.py`
`split:{train,test}` (or `{file,column,test_value}`), `keys:{id,time,target}`, `features:[...]`.
Auto-detect `train/test.csv` or `*_train/*_test`, a `split`/`fold` col, `y_true`/`target`, a date col,
an id col. None inferrable → leakage NOT-APPLICABLE (`scope.families.leakage="not-applicable"`).

### Detectors (`run_checks`, fail-soft, BC-identical schema) → verdict via §1 promotion
1. row overlap (canonical `hashlib.sha256`, contract col order) — magnitude `overlap/len(test)` —
   authoritative `blocker`.
2. id overlap (`keys.id`) — authoritative `blocker`.
3. temporal look-ahead (`keys.time`, optional `embargo`) — authoritative `blocker`.
4. duplicate-inflation — `minor` (`soft_validity_caveat`).
5. target leakage — exact feature==target → authoritative; `|pearson_r|≥0.999`/deterministic-fn →
   HEURISTIC `minor` (`soft_validity_caveat`).

### Leakage-corrected recompute (→ REFUTED) — the differentiator
Row/id overlap with per-row preds in the artifact: recompute the **same recipe** on the
contamination-filtered eval rows; `|clean−claimed|>budget` → REFUTED via existing path
(`m["refutation_dimension"]="leakage"` → `driving_dimension` + linked blocker, locator "claimed 0.94 →
leakage-corrected 0.88"). Artifact-recheck subset recompute (no full re-run). Not localizable → INVALIDATED
(if OOS) / CAN'T-CONFIRM (if OOS-indeterminate) per §1.

### Tests — `assets/leakage_fixtures/` + `test_leakage_checks.py`
(a) exact row-overlap, **OOS-asserted** → INVALIDATED, exit 1, reason+registry row.
(b) same contamination, **in-sample** declared → CAVEAT, exit 0.
(c) contamination, **OOS-indeterminate** → CAN'T-CONFIRM + "declare OOS" fix (NOT INVALIDATED).
(d) 30%-overlap, per-row preds, correctable → REFUTED with gap; magnitude **exactly 0.30**.
(e) clean split → NOT-APPLICABLE, no finding.
(f) heuristic `|r|≈0.9995` → CONFIRMED-WITH-CAVEATS, exit 0.
Assert verdict word, exit code, reason, **registry row value** each.

---

## 3. WS2 — OVERFITTING (`scripts/overfitting_checks.py`, kernels in `numeric.py`, recipes in `recipes.py`)

### Engagement lattice (LOCKED)
- **No search signal** → NOT-APPLICABLE, **silent** (no finding/output). The ordinary single backtest.
- **Signal + valid N** → DSR/PBO → verdict per §1 (PBO>0.5/DSR p>0.05 → INVALIDATED if OOS / REFUTED via
  recipe rail; survives → clean).
- **Signal + uncountable N + claim ASSERTS survival/selection/OOS** ("best of N", "robust edge",
  "out-of-sample X", "optimized") → `validity_unresolved` → **CAN'T-CONFIRM, exit 1**, fix "declare
  trials:N, or emit the grid-search log."
- **Signal + uncountable N + claim is a bare reproduced number** (sweep only detected, not asserted) →
  `soft_validity_caveat` → **CONFIRMED-WITH-CAVEATS, exit 0**, caveat names the unaccountable selection.

**Search signal** (deterministic, any of): `trials:N` declared; a `trials.csv`/grid-search log present;
multiple result rows for one strategy; claim selection language. Else NOT-APPLICABLE. A present
`trials.csv` auto-counts to a valid N. **Never auto-infer N.** Sharpe-family gate via `QUANT_METRICS`
(`calma.py:36`). Helpers: `_claim_asserts_survival(contract, claim)`, `_count_trials(contract, base)`.

### Kernels (`numeric.py`, append; pure stdlib)
- `deflated_sharpe_ratio(...)` — Bailey–LdP 2014; expected-max-Sharpe via Euler–Mascheroni γ + Gaussian
  quantiles (`z_ppf`/`normal_sf`); Φ via `normal_sf`, Φ⁻¹ via `z_ppf`/`_bisect_inv`.
- `pbo_cscv(matrix, S)` — Bailey 2016 CSCV; `math.comb` exact enumeration, rank IS vs OOS.

### Recipes — `deflated_sharpe` (the only honest REFUTED path), optional `pbo_cscv`.

### Tests — reference vectors (§4) + `test_overfitting_checks.py`
(a) single-strategy, no N/sweep → NOT-APPLICABLE, **silent, zero findings** (assert nothing emitted).
(b) "best Sharpe of 200 configs", no countable log → CAN'T-CONFIRM, exit 1, fix line.
(c) "+340% return" reproduces, sweep detected but no `trials.csv` → CONFIRMED-WITH-CAVEATS, exit 0,
   caveat present.
(d) `trials:N=500`, PBO>0.5, OOS → INVALIDATED.
(e) `trials.csv` present, valid N, survives → clean (no finding).
Assert engagement state, verdict, exit code, registry row.

---

## 4. Reference-vector trust hierarchy (LOCKED)
**EXCLUDE `mlfinlab`** (license + telemetry). Root = published **paper worked examples** (Bailey–LdP
2014 DSR; Bailey-Borwein-LdP-Zhu 2016 CSCV) pinned as MUST-MATCH. Dense coverage from an open reference
**validated against the paper first**: PBO → `pypbo` if permissive-licensed; DSR → a scipy/numpy
reference written from the paper formulas, **gated** on reproducing the 2014 worked examples before it
mints vectors. No family ships vectors on a self-reference alone (forbidden circularity).

**Freeze once, stdlib forever:** generate vectors a single time in a version-pinned venv via
`gen_reference_vectors.py` → `assets/reference_vectors.json` + a new
`assets/reference_vectors.manifest.json` (lib versions, Python version, input hashes). CI validates
pure-stdlib against the frozen file via `test_recipes_sota.py`'s `approx(...)` at rtol 1e-9; **a test
asserts the CI path imports no reference lib.**

---

## 5. Serial order (green every step; small commits; CHANGELOG each; fresh-verifier per family)
1. **`INVALIDATED` verdict core + fail-closed** — `verdict.py` + `ledger.py` + the §1 plumbing checklist
   + `test_verdict.py`/`test_ledger.py` (4 inputs re-derive; REFUTED still gap-gated; unknown-verdict
   property test). *(no detector yet — tested via hand-crafted verdict_inputs/ledgers.)*
2. **Contract surface** — `split`/`keys`/`features` + `draft()` auto-detect + `test_draft.py`.
3. **Leakage additive detectors** + 6 fixtures + scope-guard helpers + hook + families/`_not_verified` +
   evidence-driven INVALIDATED card. **Fresh-verifier #1.**
4. **Leakage-corrected recompute** → REFUTED + `refutation_dimension`. **Fresh-verifier #2.**
5. **Overfitting kernels + reference vectors** (paper-anchored; manifest; CI-imports-no-lib test).
   **Fresh-verifier #3.**
6. **Overfitting recipes + findings rail** (engagement lattice + num-trials integrity + survival/OOS
   helpers + render surfacing). **Fresh-verifier #4.**
7. **Copy flips** (§6) — only after 1-6 are actually true.

Fresh-verifier: a context-free subagent confirms verdict word + exit code + registry row (WS1) and
bit-closeness + paper-example + CI-imports-no-reference-lib (WS2), independently.

---

## 6. Copy flips (after the features are real)
`SKILL.md:19-20`, `:149-150` (roadmap → delivered, keep realism/contamination honest); `calma.py:203-208
_not_verified()` (drop the leakage/overfitting roadmap strings; reflect actual run state); `/lab`
leakage-re-run + deflation "Shipping" → "Today"; note for the benchmark session.

---

## 7. Open sub-decision still flagged (proceeding on default; cheap to flip)
- **Target leakage exact `feature==target` on a non-OOS / indeterminate claim** — default: route via the
  same scope-guard (correctable → REFUTED; OOS → INVALIDATED; indeterminate → CAN'T-CONFIRM;
  explicit in-sample with a literal target-as-feature → still surfaced, `soft_validity_caveat`). Flag:
  whether an exact target==feature on an explicitly in-sample claim should be a hard catch regardless.
