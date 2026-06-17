"""Episodic repair memory. Each accepted repair stores a normalized failure signature -> the patch
shape that fixed it; a new catch retrieves the nearest prior by (dimension + locator_signature) to SEED
the diagnosis prompt. Memory only ACCELERATES the proposer -- Calma still re-verifies every patched
result from scratch and owns the verdict (the judge never reads memory). Imports no verdict-core."""
import hashlib
import re

from edges.common import store


def locator_signature(locator):
    """Normalize a finding locator so semantically-equal bugs collide: lowercase, strip the concrete
    numbers/paths/quotes, collapse whitespace. The retrieval key, not a verdict input -- over-collapsing
    only changes which prior is suggested, never a verdict."""
    s = (locator or "").lower()
    s = re.sub(r"-?\d[\d,]*\.?\d*%?", "<num>", s)             # numbers / percentages
    s = re.sub(r"(/[\w.\-/]+)|([\w\-]+\.(csv|json|py|parquet))", "<path>", s)  # paths / files
    s = re.sub(r"[\"'`]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _code_context_hash(goalposts):
    """A coarse fingerprint of WHAT was being verified (metric + the bound artifact names), so two
    episodes on the same metric+artifact shape are 'closer' than two that merely share a dimension."""
    key = "%s|%s" % (goalposts.metric_id, ",".join(sorted(goalposts.artifact_paths or ())))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _patch_shape(unified_diff):
    """The reusable SHAPE of a patch (not the literal bytes): the touched files + the +/- line skeleton
    with concrete literals masked, so a prior fix guides a new one without copy-pasting numbers."""
    files = re.findall(r"^\+\+\+ b/(.+)$", unified_diff, re.M)
    skel = []
    for ln in unified_diff.splitlines():
        if ln[:1] in "+-" and not ln.startswith(("+++", "---")):
            masked = re.sub(r"-?\d[\d,]*\.?\d*", "N", ln)
            skel.append(masked[:200])
    return {"files": files, "skeleton": "\n".join(skel[:40])}


def record(path, claim, finding, goalposts, accepted_hr, *, ts=None):
    """Store one accepted-repair episode."""
    import time
    rec = {
        "driving_dimension": claim.get("driving_dimension"),
        "locator_signature": locator_signature((finding or {}).get("locator", "")),
        "code_context_hash": _code_context_hash(goalposts),
        "metric_id": goalposts.metric_id,
        "patch_shape": _patch_shape(accepted_hr.diagnosis.unified_diff),
        "one_shot": bool(accepted_hr.index == 0),
        "iterations_to_fix": accepted_hr.index + 1,
        "ts": ts if ts is not None else int(time.time()),
    }
    store.append(path, rec)
    return rec


def retrieve(path, *, dimension, locator, k=1):
    """Nearest prior episode(s) by (dimension exact-match THEN locator_signature similarity). Returns the
    single best patch_shape dict to seed the diagnosis prompt, or None. Similarity = Jaccard over the
    signature tokens (dependency-free; no embeddings needed for this retrieval)."""
    sig = set(locator_signature(locator).split())
    best, best_score = None, 0.0
    for rec in store.iter_records(path):
        if rec.get("driving_dimension") != dimension:
            continue
        toks = set((rec.get("locator_signature") or "").split())
        if not toks:
            continue
        score = len(sig & toks) / max(1, len(sig | toks))
        if score > best_score:
            best, best_score = rec, score
    return (best.get("patch_shape") if best and best_score >= 0.34 else None)


def one_shot_fix_rate(path):
    """The KPI: fraction of accepted repairs that landed on the first hypothesis. Climbs as memory fills."""
    n = hits = 0
    for rec in store.iter_records(path):
        n += 1
        hits += 1 if rec.get("one_shot") else 0
    return {"episodes": n, "one_shot": hits, "rate": (hits / n) if n else 0.0}
