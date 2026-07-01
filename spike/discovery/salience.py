"""calma.spike.discovery.salience — feature 4 (P0): deterministic claim salience / legibility.

Discovery finds every number in a repo; salience answers "which of these is the headline a human would
quote?" so the UI can lead with the real result instead of a wall of table cells. It is a pure re-ranking
over fields discovery already produced (source, confidence, split hint, location) — it adds a `salience`
score and an `is_metric_claim` flag and SORTS; it never deletes a claim, never touches `metric`/`value`/`id`.

FCR surface: none. `verdict.decide` is never called here, and a claim's numeric identity is untouched, so a
mis-ranking can only change *what is shown first*, never *what is confirmed*. A real claim mis-scored as
noise still verifies exactly as before (it stays in the list, just lower); noise mis-scored as headline still
has to pass binding + reproduction + recompute + determinism to reach CONFIRMED. Pure stdlib.
"""
from __future__ import annotations

# How much a discovery SOURCE signals "headline a human would quote": a structured results.json key beats a
# markdown table cell beats a sentence in prose beats a line scraped from stdout. `stated` (a user-supplied
# claim) ranks high — the user pointed at it on purpose.
_SOURCE_RANK = {
    "results-json": 1.00, "results-csv": 0.90, "stated": 0.88, "table": 0.80,
    "text": 0.60, "prose": 0.45, "stdout": 0.40,
}
_HEADLINE_SPLITS = {"test", "val", "holdout", "eval", "oos", "dev"}
_TRAIN_SPLITS = {"train", "training"}


def _clamp(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def score_one(claim: dict) -> float:
    """Transparent 0..1 salience from fields already on the claim. Higher = more headline."""
    src = (claim.get("source") or "stated").lower()
    base = _SOURCE_RANK.get(src, 0.5)
    conf = claim.get("confidence")
    conf = float(conf) if isinstance(conf, (int, float)) else 0.5
    split = (claim.get("split") or "").lower()
    # a held-out eval is the number people report; a train-split score is rarely the headline.
    split_adj = 0.12 if split in _HEADLINE_SPLITS else (-0.30 if split in _TRAIN_SPLITS else 0.0)
    loc = (claim.get("location") or "").lower()
    loc_adj = 0.05 if ("readme" in loc or "results.json" in loc or "metrics.json" in loc) else 0.0
    return round(_clamp(0.55 * base + 0.30 * conf + split_adj + loc_adj), 4)


def score_claims(claims: list[dict], repo_dir: str | None = None, *, use_llm: bool = False,
                 model: str | None = None) -> list[dict]:
    """Annotate each claim with `salience` (0..1) + `is_metric_claim`, then return the list SORTED most-salient
    first (stable tie-break on metric/value). Optionally refine with the best-effort LLM classifier (P1) when
    `use_llm` and a key are available — it can only re-weight salience, never mutate `metric`/`value`."""
    for c in claims:
        c["salience"] = score_one(c)
        c.setdefault("is_metric_claim", True)   # a discovered claim exists only if it mapped to a catalog metric
    if use_llm:
        try:
            from . import claim_classifier as CC
            CC.merge(claims, repo_dir, model=model)
        except Exception:  # noqa: BLE001 — best-effort; the P0 ranking stands on any failure
            pass
    claims.sort(key=lambda c: (-c.get("salience", 0.0), c.get("metric") or "", str(c.get("value"))))
    return claims


def head(claims: list[dict], n: int | None = None) -> list[dict]:
    """The verify-head — the top-N most salient claims (all, if n is None). The UI verifies/leads with these;
    the tail stays discoverable behind a show-all affordance."""
    ranked = sorted(claims, key=lambda c: -c.get("salience", 0.0))
    return ranked if n is None else ranked[:n]
