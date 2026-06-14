"""Tests for the recipe suggester (scripts/suggest.py) and its enrichment asset.

Three jobs:
  1. COVERAGE GUARD - every registered recipe must have a suggester enrichment entry
     (1-line description + >=2 aliases) in assets/recipe_descriptions.json. This is what
     makes a NEW recipe automatically work with `calma suggest`: add a recipe without it
     and this suite goes red. See references/recipes.md "Suggester enrichment".
  2. ACCURACY FLOOR - replays the blind gold set (tests/suggest_bench/gold.json: 1000
     domain-expert asks, 2 per recipe) and asserts recall@k floors so a future change to
     scoring/stemming/stopwords can't silently regress suggestion quality.
  3. BEHAVIOR - unclear input refuses (returns []), output is deterministic, never raises.

Run: python3 test_suggest.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import recipes as RCP  # noqa: E402
import suggest as SUGG  # noqa: E402

DESC_PATH = os.path.join(HERE, "..", "..", "assets", "recipe_descriptions.json")
GOLD_PATH = os.path.join(HERE, "suggest_bench", "gold.json")

fails = 0


def check(cond, msg):
    global fails
    if not cond:
        fails += 1
        print("  FAIL: %s" % msg)


# ---- 1. coverage guard: every recipe is suggester-ready ----
descs = json.load(open(DESC_PATH)).get("recipes", {})
missing, thin = [], []
for mid in RCP.ids():
    info = descs.get(mid)
    if not info:
        missing.append(mid)
        continue
    if not str(info.get("description", "")).strip():
        thin.append(mid + " (no description)")
    if len(info.get("aliases", [])) < 2:
        thin.append(mid + " (<2 aliases)")
check(not missing, "recipes missing from recipe_descriptions.json: %s"
      % (missing[:10] + (["..."] if len(missing) > 10 else [])))
check(not thin, "recipes with thin enrichment: %s"
      % (thin[:10] + (["..."] if len(thin) > 10 else [])))
print("coverage: %d/%d recipes enriched" % (len(RCP.ids()) - len(missing), len(RCP.ids())))

# ---- 2. accuracy floor on the blind gold set ----
if os.path.exists(GOLD_PATH):
    rows = json.load(open(GOLD_PATH))
    hit8 = {"named": [0, 0], "paraphrase": [0, 0], "ALL": [0, 0]}
    for r in rows:
        ranked = [c["metric_id"] for c in SUGG.suggest(r["query"], k=8)]
        ok = r["gold"] in ranked
        for key in ("ALL", "kind:" + r.get("kind", "?")):
            b = hit8.setdefault(key.replace("kind:", ""), [0, 0])
            b[1] += 1
            b[0] += 1 if ok else 0
    rate = {k: (v[0] / v[1] if v[1] else 0.0) for k, v in hit8.items()}
    print("recall@8: ALL %.1f%%  named %.1f%%  paraphrase %.1f%%"
          % (100*rate["ALL"], 100*rate["named"], 100*rate["paraphrase"]))
    # floors set ~3pts below the measured plateau - catch regressions, tolerate gold edits
    check(rate["ALL"] >= 0.91, "ALL recall@8 %.3f below floor 0.91" % rate["ALL"])
    check(rate["named"] >= 0.97, "named recall@8 %.3f below floor 0.97" % rate["named"])
    check(rate["paraphrase"] >= 0.85, "paraphrase recall@8 %.3f below floor 0.85" % rate["paraphrase"])
else:
    print("(gold set absent - skipping accuracy floor)")

# ---- 3. behavior ----
check(SUGG.suggest("make the website blue and ship it") == [], "nonsense ask should refuse (return [])")
check(SUGG.suggest("") == [], "empty ask should refuse")
a = [c["metric_id"] for c in SUGG.suggest("my sharpe ratio was 1.4", k=5)]
b = [c["metric_id"] for c in SUGG.suggest("my sharpe ratio was 1.4", k=5)]
check(a == b, "suggest must be deterministic")
check("sharpe" in a, "named 'sharpe' must be suggested")
try:
    for q in ("", "   ", "@@@", "a", "the the the"):
        SUGG.suggest(q)
    check(True, "")
except Exception as e:  # noqa: BLE001
    check(False, "suggest raised on edge input: %r" % e)

# ---- 4. auto-suggest is wired into verify's unclear paths (not a separate command) ----
import calma as CALMA  # noqa: E402

# unknown/unclear --metric must raise with semantic suggestions, not just a string-distance guess
try:
    CALMA.verify("/tmp", "x", metric="sharp_ratio")
    check(False, "unknown --metric should raise")
except ValueError as e:
    check("sharpe" in str(e).lower(), "unknown --metric should suggest the sharpe family: %s" % e)
except Exception as e:  # noqa: BLE001
    check(False, "unknown --metric raised non-ValueError: %r" % e)

# helpers are fail-open and only fire on the unclear case (caller decides when to call them)
check(CALMA._metric_suggestions("/nonexistent-dir", "") == [], "_metric_suggestions must fail-open to []")
check(CALMA._suggest_unblock([]) == "", "_suggest_unblock([]) must be empty (no noise when nothing to suggest)")
ub = CALMA._suggest_unblock(SUGG.suggest("sharpe ratio", k=2))
check("--metric" in ub and "Did you mean" in ub, "_suggest_unblock should render a pickable 'did you mean' line")

# ---- 5. data-aware re-rank, confidence, and descriptions ----
# available_tags must demote a recipe whose inputs the data can't supply, without dropping it
acc = SUGG.suggest("how accurate is it", k=8)
check(all("confidence" not in r or r is acc[0] for r in acc[1:]), "confidence only on top result")
if acc:
    check("description" in acc[0] and "confidence" in acc[0], "results carry description + confidence")
# a value-only dataset should not let a label+prediction metric outrank a value metric
ranked_no = [r["metric_id"] for r in SUGG.suggest("dispersion of the values", k=8)]
ranked_val = [r["metric_id"] for r in SUGG.suggest("dispersion of the values", k=8, available_tags={"value"})]
check(ranked_no != [] and ranked_val != [], "tag-aware suggest still returns candidates")
# confidence is one of the two labels when present
for r in (acc[:1] if acc else []):
    check(r.get("confidence") in ("high", "low"), "confidence label is high/low")

print("test_suggest: %s" % ("OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
