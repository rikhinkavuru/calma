"""calma.suggest - the "did you mean?" surface for an unclear ask.

When a user's prompt or data does NOT clearly identify what to recompute, calma's
job is to REFUSE rather than verify against a merely-similar formula (a green stamp
off the wrong recipe is the one failure a verifier must never produce). This module
turns that bare refusal into a helpful one: given free text, it returns the most
likely recipes the user *might* have meant, ranked, with the command to run each.

It is a SUGGESTION layer only. It never picks a recipe, never auto-runs, never feeds
a verdict. The user (or the model) confirms an exact metric_id before anything is
verified; "no candidate fits" stays a clean NOT-VERIFIED.

Implementation is deterministic, pure-stdlib, offline: an exact lexical ranker
(idf-weighted token overlap + alias-phrase hits) over the in-process recipe catalog.
At several hundred short, jargon-dense recipes this is exact and instant - no embeddings, no
server, no network. The public surface is a single function:

    suggest(text, k=5, available_tags=None)
        -> [ {metric_id, family, score, why, required_tags, description, confidence?}, ... ]

`available_tags` lets a caller that knows the data's columns demote recipes whose inputs
aren't present; `confidence` (on the top result) flags a dominant match vs a tight field.
A heavier backend (a vendored embedding index, or an external graph-vector store) could be
swapped in behind this signature later WITHOUT changing callers - if and only if the corpus
ever grows large and relational enough to justify it. It is not, today; a char-trigram subword
tier and raw-formula indexing were both tried and measured net-negative (no recall gain, and
they risked the refuse-when-unsure guarantee), so the ranker stays lexical + alias + idf.
"""
import math
import re

import draft_contract as DC
import recipes as RCP

ALIAS_WEIGHT = 3.0           # an alias-phrase hit is a much stronger signal than a loose token
NAME_BONUS = 1.5             # a token from the recipe's OWN id outranks the same word in prose
NAME_IDF_GATE = 2.5          # ...but only when that token is DISTINCTIVE (rare), not "sum"/"rate"
MIN_SCORE = 0.75             # below this, we are not confident enough to suggest anything
_TOP_DEFAULT = 5

_STOP = frozenset((
    "the", "a", "an", "of", "is", "was", "were", "are", "to", "in", "on", "for", "and",
    "or", "my", "our", "its", "it", "this", "that", "these", "those", "with", "how",
    "what", "did", "do", "does", "i", "we", "be", "been", "value", "values", "number",
    "metric", "result", "data", "dataset", "got", "came", "out", "good", "looked", "look",
    "model", "models", "strategy", "strategies", "portfolio", "well", "strong", "acceptable",
    "many", "much", "really", "very", "quite", "pretty", "seems", "seem",
    # command verbs and generic data nouns - noise for identifying WHICH metric is meant
    "verify", "check", "confirm", "recompute", "compute", "calculate", "calculated",
    "validate", "double", "recheck", "measure", "measured", "get", "give", "want", "need",
    "column", "field", "set", "reading", "readings", "measurement", "measurements",
    "across", "these", "those", "per", "each", "between", "among", "really",
))


def _norm(text):
    """Lowercase; keep alphanumerics plus the few symbols that carry metric meaning (@ . -)."""
    return re.sub(r"[^a-z0-9@.\-]+", " ", (text or "").lower()).strip()


def _stem(tok):
    """Tiny deterministic suffix-stripper - enough to bridge volatile/volatility,
    deviation/deviate, calibrated/calibration without pulling in a stemmer dependency."""
    for suf in ("ization", "isation", "iveness", "ation", "ition", "ity", " ness",
                "ness", "ing", "ed", "ly", "es", "s"):
        if len(tok) > len(suf) + 2 and tok.endswith(suf):
            return tok[: -len(suf)]
    return tok


def _phrase_hit(phrase, norm):
    """True if `phrase` appears in `norm` on alphanumeric word boundaries - so a short alias
    like "ci" or "n" matches the word, never the inside of "specificity" or "and"."""
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", norm) is not None


def _tok_match(a, b):
    """Two tokens match if stem-equal or one is a >=4-char prefix of the other - bridges
    concentrated/concentration and calibrate/calibration that bare suffix-stripping misses."""
    if a == b:
        return True
    lo, hi = (a, b) if len(a) <= len(b) else (b, a)
    return len(lo) >= 4 and hi.startswith(lo)


def _tokens(text):
    out = []
    for raw in _norm(text).split():
        if raw in _STOP or len(raw) < 2:
            continue
        # split snake/descriptive ids into parts too ("downside-deviation" -> downside, deviation)
        for part in re.split(r"[\-.]", raw):
            if part and part not in _STOP:
                out.append(_stem(part))
    return out


def _load_descriptions():
    """Suggester-only enrichment: assets/recipe_descriptions.json maps metric_id ->
    {description, aliases}. This text feeds RANKING ONLY - it never touches the claim
    router (CLAIM_METRIC_HINTS) or any verdict, so LLM-authored phrasing here can make a
    suggestion better or worse but can never produce a false verification. Empty if absent."""
    import json
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "assets", "recipe_descriptions.json")
    if not os.path.exists(path):
        return {}
    try:
        return json.load(open(path)).get("recipes", {})
    except (OSError, ValueError):
        return {}


def _aliases_by_metric():
    """metric_id -> set of natural-language alias phrases. Two sources, both safe for a
    suggestion surface: the hand-curated CLAIM_METRIC_HINTS table calma already uses to
    route real claims (so suggestions stay consistent with matching), plus the softer,
    broader alias phrases from the enrichment asset (paraphrase coverage for every recipe)."""
    by = {}
    for phrase, mid in DC.CLAIM_METRIC_HINTS:
        by.setdefault(mid, set()).add(phrase)
    for mid, info in _load_descriptions().items():
        for phrase in info.get("aliases", ()):
            if phrase:
                by.setdefault(mid, set()).add(phrase.lower())
    return by


_CORPUS = None


def _build_corpus():
    """One pass over the in-process registry, cached. Returns (docs, idf, alias_pairs).

    docs[mid]   = {"family", "tokens": Counter, "required_tags", "aliases": [phrases]}
    idf[token]  = inverse document frequency (rare, specific tokens score higher)
    alias_pairs = [(phrase, mid)] sorted longest-first for the substring tier
    """
    global _CORPUS
    if _CORPUS is not None:
        return _CORPUS
    aliases = _aliases_by_metric()
    descs = _load_descriptions()
    docs, df = {}, {}
    for mid in RCP.ids():
        fn = RCP.get(mid)
        man = getattr(fn, "manifest", {}) or {}
        family = man.get("family") or "other"
        toks = {}
        # the metric_id itself is descriptive - the main signal for the un-aliased recipes
        for t in _tokens(mid.replace("_", " ")):
            toks[t] = toks.get(t, 0) + 2          # id tokens weighted: they ARE the name
        for t in _tokens(family):
            toks[t] = toks.get(t, 0) + 1
        for phrase in aliases.get(mid, ()):       # paraphrase vocabulary (hand + enrichment)
            for t in _tokens(phrase):
                toks[t] = toks.get(t, 0) + 2
        for t in _tokens(descs.get(mid, {}).get("description", "")):  # the one-line definition
            toks[t] = toks.get(t, 0) + 1
        docs[mid] = {"family": family, "tokens": toks,
                     "name_tokens": set(_tokens(mid.replace("_", " "))),
                     "required_tags": man.get("required_tags", []),
                     "description": descs.get(mid, {}).get("description", ""),
                     "aliases": sorted(aliases.get(mid, ()), key=len, reverse=True)}
        for t in toks:
            df[t] = df.get(t, 0) + 1
    n = max(1, len(docs))
    idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
    # substring tier draws on every alias phrase (hand-curated + enrichment), longest first
    pairs = [(p, m) for p, m in DC.CLAIM_METRIC_HINTS]
    pairs += [(p, m) for m, d in docs.items() for p in d["aliases"]]
    alias_pairs = sorted(set(pairs), key=lambda pm: len(pm[0]), reverse=True)
    _CORPUS = (docs, idf, alias_pairs)
    return _CORPUS


TAG_MISS_PENALTY = 0.35      # demote (don't drop) a recipe whose inputs the data can't supply


def suggest(text, k=_TOP_DEFAULT, available_tags=None):
    """Rank recipes the free-text ask most likely refers to. Deterministic; ties break
    alphabetically by metric_id. Returns [] when nothing clears MIN_SCORE - the caller
    must treat that as an honest 'still NOT VERIFIED', not as a match.

    available_tags: when the caller knows which binding tags the data can supply (e.g. verify
    inferred them from the columns present), recipes whose required_tags are NOT all satisfiable
    are demoted by TAG_MISS_PENALTY - so an inequality claim over one numeric column ranks
    `gini`/`atkinson` above `balanced_accuracy` (which needs label+prediction). Demote, never drop:
    a suggestion the data can't currently feed is still worth surfacing. None = no data context."""
    k = max(1, int(k))  # a non-positive k must not silently empty the ranking (Python [:0]/[:-n]
    #                     would render a clearly-recognizable ask as "no match")
    docs, idf, alias_pairs = _build_corpus()
    norm = _norm(text)
    qtokens = set(_tokens(text))
    if not qtokens and not norm:
        return []

    scores, why, qualifies = {}, {}, set()
    # tier 1 - alias phrase appears in the ask, on WORD BOUNDARIES (so "ci" doesn't match
    # "specificity", "n" doesn't match "and"). Strongest signal; most specific phrase first.
    seen_phrase = set()
    for phrase, mid in alias_pairs:
        if mid in docs and mid not in seen_phrase and _phrase_hit(phrase, norm):
            scores[mid] = scores.get(mid, 0.0) + ALIAS_WEIGHT * len(phrase.split())
            why[mid] = "matches \"%s\"" % phrase
            seen_phrase.add(mid)
            qualifies.add(mid)
    # tier 2 - idf-weighted token overlap, prefix-aware (catches asks with no full alias phrase)
    for mid, doc in docs.items():
        matched = {t for t in doc["tokens"] if any(_tok_match(q, t) for q in qtokens)}
        if matched:
            names = doc["name_tokens"]
            name_hit = bool(matched & names)
            scores[mid] = scores.get(mid, 0.0) + sum(
                idf.get(t, 1.0) * (NAME_BONUS if (t in names and idf.get(t, 1.0) >= NAME_IDF_GATE)
                                   else 1.0) for t in matched)
            if mid not in why:
                why[mid] = "matches " + ", ".join(sorted(matched))
            # confidence gate: a single stray prose word is not a suggestion. Qualify only on an
            # alias hit, a match against the recipe's OWN name, or >=2 distinct matched tokens.
            if name_hit or len(matched) >= 2:
                qualifies.add(mid)

    # data-aware re-rank: demote recipes whose required inputs the data can't supply
    if available_tags is not None:
        avail = set(available_tags)
        for mid in list(scores):
            need = set(docs[mid].get("required_tags") or [])
            if need and not need <= avail:
                scores[mid] *= TAG_MISS_PENALTY

    ranked = sorted(((s, mid) for mid, s in scores.items()
                     if mid in qualifies and s >= MIN_SCORE),
                    key=lambda sm: (-sm[0], sm[1]))[:k]
    out = [{"metric_id": mid, "family": docs[mid]["family"], "score": round(s, 3),
            "why": why.get(mid, ""), "required_tags": docs[mid]["required_tags"],
            "description": docs[mid]["description"]} for s, mid in ranked]
    # confidence: "high" when the top candidate stands clearly apart (a dominant match the caller
    # can lead with), "low" when the field is a tight cluster (genuinely ambiguous - ask, don't assume)
    if out:
        top = out[0]["score"]
        second = out[1]["score"] if len(out) > 1 else 0.0
        out[0]["confidence"] = "high" if (second == 0.0 or top >= 1.8 * second) else "low"
    return out


def render(text, results, invocation="calma"):
    """Plain-text 'did you mean?' block for the CLI. Numbered, with each recipe's one-line
    description + required inputs so the user RECOGNIZES the right one, and a confidence-aware
    header (lead with a dominant match; ask plainly when it's a tight field). Honest (still NOT
    VERIFIED), one runnable command per candidate, never auto-runs anything."""
    if not results:
        return "\n".join((
            "NOT VERIFIED - couldn't tell which metric \"%s\" refers to." % (text or "").strip(),
            "  Browse all %d recipes:  %s recipes" % (len(RCP.ids()), invocation),
            "  Then pin one:            %s verify <folder> \"<claim>\" --metric <id>" % invocation))
    if results[0].get("confidence") == "high":
        lines = ["NOT VERIFIED yet - most likely you mean #1 below; pick another if not:"]
    else:
        lines = ["NOT VERIFIED yet - did you mean one of these? (pick one, then re-run)"]
    for i, r in enumerate(results, 1):
        tags = (" [needs: %s]" % ", ".join(r["required_tags"])) if r["required_tags"] else ""
        lines.append("\n  %d. %-22s %s%s" % (i, r["metric_id"], r["family"], tags))
        if r.get("description"):
            lines.append("       %s" % r["description"])
        lines.append("       (%s)   %s verify <folder> \"<claim>\" --metric %s"
                     % (r["why"], invocation, r["metric_id"]))
    lines.append("\n  Not it?  Full catalog:  %s recipes" % invocation)
    return "\n".join(lines)
