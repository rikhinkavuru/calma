# Extending calma — add a metric or a validity family (the adaptability SDK)

calma's moat is breadth + adaptability: a new metric or a firm-specific validity check should be a small,
**eval-gated** contribution, never a fork. Everything below lands in the pure-stdlib engine
(`.claude/skills/calma/scripts/`), is firewalled from any LLM/edges code, and is admitted only when it
passes `make eval`. This is the same path the 625 recipes and the 13 validity families took.

## The non-negotiable contract (nothing merges without all three)

1. **A golden vector** — at least one fixed input with the expected output, tier-labeled:
   - *Tier-1* = the value comes from an **independent** reference (a closed-form, an arbitrary-precision
     computation, or a foreign-language/library engine run as a black box). Provably correct.
   - *Tier-2* = a characterization snapshot of calma's own output, **honestly labeled** "reproducibility
     only, not independently verified." (Never let a self-generated value masquerade as a correctness test.)
2. **A test** that runs in the core suite (`scripts/tests/test_*.py`, auto-discovered by `run_all.py`).
3. **`make eval` stays green** — the standing net (core suite + framework golden vectors + the recompute
   baseline + the byte-identical determinism check).

## Add a metric (a recipe)

Recipes live in `recipes.py` and register with a decorator. Pure stdlib, deterministic, no third-party
imports on the verdict path (heavy math goes in `numeric.py`, also pure-stdlib).

```python
@register("my_metric", family="stats", required_tags=["prediction", "target"],
          set_maturity="reviewed", accepted_conventions=["p95", "p99"])
def my_metric(cols, binding, convention=None):
    pred, tgt = cols[binding["prediction"]], cols[binding["target"]]
    return _result(N.some_kernel(pred, tgt), {"n": len(pred)})   # _result wraps value + terms
```

- `required_tags` are the binding inputs the recipe needs; `string_tags=[...]` marks group/id columns kept
  as raw strings (e.g. `era`) instead of coerced to float — and these MUST also be in
  `draft_contract.STRING_KEY_TAGS` so the binding grader treats them as keys (a mismatch silently pins the
  verdict to author-asserted — a real bug this engine has already paid for).
- Add a **golden vector**: either a `benchmark/gen_framework_vectors.py` entry (Tier-1, asserts calma ==
  an independent reference == the live framework under `--check-live`) or a unit test with a hand-derived
  value. A new metric in a delicate family (Sharpe/VaR/Greeks/log-loss/ECE) wants a Tier-1 vector.
- **Metamorphic relations** are the cheap unlock when no reference oracle exists: assert the family
  invariant instead of a value — monotone-invariance for ranking metrics (AUC/NDCG), scale-equivariance for
  RMSE/MAE, fee-monotonicity + cash-invariance for backtests, permutation-invariance for aggregations. One
  MR validates a recipe with no golden value at all.

## Add a validity family (the 3-function protocol)

A validity family **degrades** a reproduced verdict (it never inflates one): the number recomputes, but the
*result* is invalid. Mirror an existing one — `model_leakage_checks.py` is the minimal template;
`embargo_checks.py` and `simulation_assumptions_checks.py` are the two newest, full examples.

A family is one module exposing exactly three functions:

```python
def run_checks(contract, base, claim_id="c1", claim_text=None) -> [finding, ...]:
    """SILENT (return []) unless your contract block is declared. Fail-soft: wrap every check in
    try/except (OSError, ValueError, KeyError, TypeError, ArithmeticError, IndexError, AttributeError)
    -> the rail NEVER raises a traceback to the verdict. Read artifacts via pathsafe (containment +
    the byte-cap): `PS.within_cap(PS.safe_join(base, rel))`."""

def apply_validity(claims, findings, contract, claim_text, base=None) -> None:
    """Promote the headline DOWN only. Touch it ONLY if it is already CONFIRMED/CAVEATS (a reproduced
    number). An authoritative finding UNDER A SCOPE-ASSERTING claim -> set vi["validity_invalidated"]=True
    and vi["oos_claim_asserted"]=True -> INVALIDATED; otherwise a soft caveat. Never upgrade."""

def family_status(contract, findings) -> str:   # "not-applicable" | "checked" | "flagged"
```

Wiring (one place, `calma.py:_assemble_ledger`):
1. `import your_checks as YC` with the other families.
2. Add `your_fam = None` to the init line; call `run_checks` → `apply_validity` → `family_status` in the
   family block; add `your_fam` to the `families` dict and the `_not_verified(...)` honesty list.
3. If you add a new top-level contract block, validate its **shape** in `draft_contract.validate_contract`
   (scalars finite, unknown keys rejected — a typo'd key must fail loudly, never be silently ignored), and
   document it in `SKILL.md`'s "Validity blocks" reference.

Findings are dicts with `dimension`, `severity`, `validity_class` ("authoritative" | "soft" |
"uncountable" | "indeterminate"), a plain-English `locator`, an actionable `unblock`, and a `reverify`. The
**locator must be byte-stable** for byte-identical input (total-order any tie-break; never iterate a set or
rely on dict-insertion order — the locator feeds `ledger_sha256`).

## The eval gate, run it

```bash
make eval     # core suite + framework golden vectors + recompute baseline + determinism — all must pass
```

Your test is auto-discovered. A recipe or family that can't clear `make eval` does not merge. This is what
makes "onboard a firm's bespoke methodology in hours" a moat rather than a liability: the auto/LLM-drafted
path (in the firewalled `edges/` proposer) clears the **same** gate as the hand-built families — attested ≠
correct, but *gated-by-the-deterministic-core* == correct.
