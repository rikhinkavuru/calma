# Calma — repo-processing pipeline & the cost model

How a repo becomes verified numbers, designed so **cost-per-scan stays low even on repos with thousands of
claims.** This answers the "won't this be 1000s of Exa calls?" worry head-on.

## The reframe: two orthogonal problems (don't conflate them)

The two options on the table each solve a *different* problem:

| Problem | What it needs | Cost shape |
|---|---|---|
| **Make-runnable** — get the repo to execute | deps + run-plan ("Option B": an LLM writes a requirements.txt) | **once per repo**, cached per *stack* |
| **Formula resolution** — the trusted recompute math | the metric's definition + a validated implementation ("Option A": Exa-find the formula) | **once per distinct novel metric**, cached **globally** |

They have different cost profiles and different caches. Treating "every calculation → Exa" as one thing is
the cost trap. Keep them separate.

## The crux: **claims ≠ formulas**

A repo with "1000s of formulas" almost never has 1000s of distinct *metric types*. Your `gb_kmer_benchmark`
reports ~thousands of rows, but they're **3 metrics** (accuracy, AUROC, MCC) × many datasets × models × k.

- **Formula resolution is per-distinct-metric, not per-claim.** Dedupe first → resolve ~3 formulas, not 3000.
- **Recompute is pure arithmetic → free per claim.** 3000 claims recompute from 3 formulas instantly.
- So **cost scales with `distinct novel metrics × novel stacks`, not with claims.** The flywheels drive that
  toward zero.

## The cost-optimal pipeline (recommended — synthesizes A + B + the key saver)

```
1. DISCOVER + DEDUPE         claims → the set of DISTINCT metrics (cheap; static)
2. CLASSIFY (the key saver)  each distinct metric → catalog / recipes(626) / Helix?   ← ~95% land here, $0
                             only genuinely-novel survives to step 4
3. MAKE-RUNNABLE             env files present → use them; else ONE agent session writes
   (Option B, cached)        requirements.txt + run-plan (Repo2Run; 86% on Python repos).
                             cache by stack signature → reproduction flywheel ($0 next time)
4. RESOLVE NOVEL FORMULA     Helix vector lookup (seen before? → reuse, $0)
   (Option A, gated)         → else Exa the definition → LLM synthesizes code
                             → VALIDATE vs golden vectors → bank in Helix (global, forever)
5. CAPTURE / RECOMPUTE       committed predictions → recompute directly (no re-run);
                             else re-run + capture. Recompute ALL claims (free). Three-way diff.
```

### Why this is cheap

- **Step 2 is the lever.** Most "custom" metric code is a *reimplemented standard* (`def accuracy(...)`
  instead of sklearn). One cheap LLM **classify** call ("is this a known metric?") maps it to the catalog →
  **no Exa.** Exa is reserved for a *genuinely new* metric (a novel formula from a paper).
- **Exa fires once per distinct novel metric, ever** — then it's a `Formula` node in Helix, reused by every
  future repo (global cache). Per-repo Exa cost ≈ (novel metrics) × ~$0.005 → ~$0 as the catalog graph grows.
- **Make-runnable is one agent session per repo**, cached per stack. Feed it just the import graph + README
  (not the whole repo) to keep tokens minimal.
- The genuinely expensive bit is **sandbox execution** (re-running the code) — metered as sandbox-minutes in
  the pricing model — not the formulas.

## On the two options you floated

- **Option A (Exa every calculation):** right idea, wrong scope. Gate it behind catalog→recipes→Helix
  (steps 2 + 4). Exa only for the novel tail. The router already does this (`recompute_any`); the addition
  is the **classify-before-Exa** step.
- **Option B (LLM writes its own requirements.txt):** yes — this is make-runnable (step 3) for repos without
  env files. Your genomic repo *has* `requirements.txt`, so it's used directly; the agent only writes one
  when the repo lacks it. Cache it.

## A third idea worth taking: **ground from the repo, validate independently**

For a novel metric, the repo usually *defines* it (in code + the paper/README). So:
- **Ground the synthesis from the repo's own definition** (already cloned, free) — Exa is the *fallback* when
  the repo doesn't document it.
- But **validate independently** (golden vectors from the definition, or the repo's own published test
  vectors) — never trust the repo's implementation, since that's what's under test. This preserves the
  blackbox/anti-circularity guarantee while cutting Exa further.

## Where HelixDB (graph + vector) fits

Helix is the right store because the catalog is a *graph with semantic dedup*:
- **`Formula` nodes** (validated recompute code) + **alias edges** + **derived-from edges** → the catalog
  knowledge graph; **vector search dedups paraphrased metrics** ("MCC" ≈ "Matthews correlation" ≈ "phi") →
  near-zero re-synthesis.
- **`RunPlan` nodes** keyed by stack signature → the reproduction-flywheel cache (env reuse).
- **`Repo → metric → formula` edges** → provenance + the proprietary verification corpus (a moat that also
  visualizes as a graph).

A live instance is running (`helix start dev`, port 6969); formulas persist as graph nodes today.

## The one-line cost answer

> Verifying 1000s of claims costs ~the same as verifying the **handful of distinct metrics** behind them,
> because formulas are resolved once (catalog-first, Exa only for the novel tail) and banked in Helix
> forever, while recompute is free. The real meter is **sandbox-minutes**, which the pricing model already
> bills. The flywheels make month-N cheaper than month-1.
