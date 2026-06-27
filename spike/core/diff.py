"""calma.spike.core.diff — bind captured computations to claims and run the three-way diff.

Input: the claims (what was reported) + one-or-more capture *runs* (the calls the shim recorded each time
we executed the repo). Output: a verdict record per claim.

Binding (the hard part, guide §4.2) is what we are de-risking. For the spike we bind a claim to a captured
call by **metric identity** (never by value-proximity — matching on value would hide a REFUTED), with an
optional per-claim hint (`bind`) to disambiguate when a repo computes the same metric several times
(train vs test, per-fold). Exactly one candidate -> bound. Several with no hint -> ambiguous ->
INCONCLUSIVE (fail closed; "scope the claim"). Zero -> unbound -> INCONCLUSIVE ("what I'd need").
"""
from __future__ import annotations

from . import catalog as C
from . import tolerance as T
from . import validity as V
from . import verdict as VD


def _claim_cid(claim) -> tuple[str | None, str]:
    """(canonical metric id or None, raw metric string)."""
    raw = (claim.get("metric") or "").strip()
    return C.canonical(raw), raw


def _matches(call, cid, raw) -> bool:
    cm = call.get("metric") or ""
    if cid is not None:
        return C.canonical(cm) == cid
    return cm.strip().lower() == raw.strip().lower()


def _finite_float(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if (f == f and f not in (float("inf"), float("-inf"))) else None


def _bind(claim, calls) -> dict:
    """Select the captured call this claim refers to. Returns
    {"bound","ambiguous","reason","selector","call"} where selector = (kind, key) replays across runs."""
    cid, raw = _claim_cid(claim)
    cands = [c for c in calls if _matches(c, cid, raw)]
    hint = claim.get("bind") or {}
    if hint.get("sink"):
        cands = [c for c in cands if hint["sink"] in (c.get("sink") or "")]
    if hint.get("label"):
        cands = [c for c in cands if c.get("label") == hint["label"]]
    if not cands:
        return {"bound": False, "ambiguous": False,
                "reason": "no captured computation of %r%s" % (raw, " matching the hint" if hint else "")}
    occ = hint.get("occurrence")
    if occ is not None:
        cands_sorted = sorted(cands, key=lambda c: c.get("seq", 0))
        if 0 <= occ < len(cands_sorted):
            call = cands_sorted[occ]
            return {"bound": True, "ambiguous": False, "reason": "hint occurrence %d" % occ,
                    "selector": ("occ", cid, raw, occ), "call": call}
        return {"bound": False, "ambiguous": False,
                "reason": "hint occurrence %d out of range (%d candidates)" % (occ, len(cands_sorted))}
    if len(cands) == 1:
        return {"bound": True, "ambiguous": False, "reason": "unique candidate",
                "selector": ("occ", cid, raw, 0), "call": cands[0]}
    sinks = sorted({c.get("sink") or "?" for c in cands})
    return {"bound": False, "ambiguous": True,
            "reason": "%d candidate computations of %r (%s)" % (len(cands), raw, ", ".join(sinks))}


def _select(calls, selector):
    """Replay a binding selector against another run's calls (for the determinism check)."""
    kind, cid, raw, occ = selector
    cands = sorted([c for c in calls if _matches(c, cid, raw)], key=lambda c: c.get("seq", 0))
    return cands[occ] if 0 <= occ < len(cands) else None


def diff_claim(claim, runs) -> dict:
    """Three-way diff for one claim across `runs` (a list of capture-call lists; runs[0] is authoritative)."""
    cid, raw = _claim_cid(claim)
    base_calls = runs[0] if runs else []
    binding = _bind(claim, base_calls)
    rec = {"claim": claim, "binding": {k: binding[k] for k in ("bound", "ambiguous", "reason")}}

    if not binding.get("bound"):
        v = VD.decide(claimed_raw=claim.get("value"), produced=None, recomputed=None,
                      recompute_known=cid is not None, binding=binding,
                      determinism={"tested": False, "stable": False, "spread": 0.0, "k": len(runs)},
                      validity={"invalidating": [], "advisory": []})
        rec.update(v)
        return rec

    call = binding["call"]
    produced = _finite_float(call.get("result"))
    inputs = call.get("inputs") if call.get("captured_full", True) else None

    # independent recompute (only if we recognise the metric AND we captured the inputs)
    recomputed, recompute_known = None, cid is not None
    if cid is not None and inputs is not None:
        recomputed = C.recompute(cid, inputs, call.get("kwargs") or {})
    elif cid is not None and inputs is None:
        recomputed = {"value": float("nan"), "degenerate": True,
                      "note": "inputs not captured (too large)", "terms": {}}

    # validity overlay on the captured inputs
    validity = V.check(raw, inputs, produced) if inputs is not None else {"invalidating": [], "advisory": []}

    # determinism: is the produced value stable across runs?
    sel = binding["selector"]
    produced_each = []
    for r in runs:
        c = _select(r, sel)
        pv = _finite_float(c.get("result")) if c else None
        if pv is not None:
            produced_each.append(pv)
    if len(produced_each) >= 2:
        spread = max(produced_each) - min(produced_each)
        stable = all(T.close(produced_each[0], x) for x in produced_each[1:])
        determinism = {"tested": True, "stable": stable, "spread": spread, "k": len(produced_each)}
    else:
        determinism = {"tested": False, "stable": False, "spread": 0.0, "k": len(produced_each)}

    v = VD.decide(claimed_raw=claim.get("value"), produced=produced, recomputed=recomputed,
                  recompute_known=recompute_known, binding=binding,
                  determinism=determinism, validity=validity)
    rec.update(v)
    rec["sink"] = call.get("sink")
    rec["determinism"] = determinism
    rec["validity"] = validity
    return rec


def diff_repo(claims, runs) -> dict:
    """Diff every claim. Returns {"claims": [verdict record...], "counts": {verdict: n}}."""
    records = [diff_claim(cl, runs) for cl in claims]
    counts: dict[str, int] = {}
    for r in records:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"claims": records, "counts": counts}
