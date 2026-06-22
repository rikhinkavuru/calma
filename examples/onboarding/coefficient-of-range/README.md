# Onboard a bespoke metric: the coefficient of range

A worked example of `calma onboard` (M4). The **coefficient of range** -- `(max - min) / (max + min)`,
a standard textbook dispersion statistic -- is not one of calma's built-in recipes. Here calma onboards
it from nothing but a plain-language **methodology** and six of the firm's own **reference numbers**
(computed independently, by hand): an LLM proposes the pure-stdlib recipe, and the deterministic gate
admits it only when it reproduces every reference vector to 1e-9, holds the declared metamorphic
relations (scale-invariance, order-independence, bounds [0,1]), degrades on edge cases, and is bit-stable.

```bash
calma onboard \
  --metric-id coefficient_of_range --family stats \
  --methodology @examples/onboarding/coefficient-of-range/methodology.txt \
  --vectors examples/onboarding/coefficient-of-range/vectors.json \
  --metamorphic-hint "scale-invariant" \
  --metamorphic-hint "order-independent" \
  --metamorphic-hint "bounded between 0 and 1" \
  --model claude-haiku-4-5
```

Needs the edges deps + an `ANTHROPIC_API_KEY` for the proposer; the admission gate itself is offline.
On success the recipe is frozen into the compiled registry, gated by the SAME admission the built-in
recipes clear, and is then usable by `calma verify ... --metric coefficient_of_range`. (Pass
`--compiled-path <tmp>` to freeze into a throwaway registry instead of the production one.)
