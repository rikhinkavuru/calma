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


# split tokens that name a HELD-OUT evaluation vs the training set (for size-based disambiguation)
_HELDOUT = ("test", "testing", "val", "valid", "validation", "holdout", "heldout", "dev", "oos", "eval")
_TRAIN = ("train", "training")


def _candidates(claim, calls):
    """Calls matching the claim's metric, after any explicit sink/label hint. (raw, cid, list, hint)."""
    cid, raw = _claim_cid(claim)
    cands = [c for c in calls if _matches(c, cid, raw)]
    hint = claim.get("bind") or {}
    if hint.get("sink"):
        cands = [c for c in cands if hint["sink"] in (c.get("sink") or "")]
    if hint.get("site"):
        cands = [c for c in cands if c.get("site") == hint["site"]]
    if hint.get("label"):
        cands = [c for c in cands if c.get("label") == hint["label"]]
    return cid, raw, cands, hint


def _bound_call(claim, calls):
    """Pick the ONE captured call a claim refers to — identically across runs (so the determinism replay is
    consistent). Disambiguation order, NONE of which looks at the value (that would hide a REFUTED):
      1. explicit occurrence hint;
      2. collapse library-internal calls — prefer the repo's OWN computation (GridSearchCV / CV scorers run
         the metric dozens of times inside sklearn; the headline is the one the repo's code computed);
      3. split-by-size — a held-out split is the smaller eval, train the larger (size, not value; worst case
         is a false REFUTED, never a false CONFIRMED).
    Returns (call | None, status, reason) with status in {bound, ambiguous, unbound}."""
    cid, raw, cands, hint = _candidates(claim, calls)
    if not cands:
        return None, "unbound", "no captured computation of %r%s" % (raw, " matching the hint" if hint else "")

    occ = hint.get("occurrence")
    if occ is not None:
        s = sorted(cands, key=lambda c: c.get("seq", 0))
        if 0 <= occ < len(s):
            return s[occ], "bound", "hint occurrence %d" % occ
        return None, "unbound", "hint occurrence %d out of range (%d candidates)" % (occ, len(s))

    if len(cands) == 1:
        return cands[0], "bound", "unique candidate"

    pfx = ""
    user = [c for c in cands if c.get("user_site")]
    if user and len(user) < len(cands):
        pfx = "bound to the repo's own computation (collapsed %d library-internal call(s)); " % (len(cands) - len(user))
        cands = user
        if len(cands) == 1:
            return cands[0], "bound", pfx + "unique repo-code candidate"

    split = (claim.get("split") or "").lower()
    sizes = [c.get("n") for c in cands]
    if split and all(isinstance(n, int) for n in sizes) and len(set(sizes)) == len(sizes):
        s = sorted(cands, key=lambda c: c.get("n"))
        if split in _HELDOUT:
            return s[0], "bound", pfx + "split=%s → the smaller held-out computation (n=%d)" % (split, s[0].get("n"))
        if split in _TRAIN:
            return s[-1], "bound", pfx + "split=%s → the larger training computation (n=%d)" % (split, s[-1].get("n"))

    sinks = sorted({c.get("sink") or "?" for c in cands})
    return None, "ambiguous", pfx + "%d candidate computations of %r (%s) — scope the claim (split/occurrence)" % (
        len(cands), raw, ", ".join(sinks))


def scope_options(claim, calls):
    """The distinguishable computations a user can SCOPE an ambiguously-bound claim to — by SEMANTIC identity
    (call site, sink, sample size), NEVER by value. Offering the values would let a misreport be "confirmed"
    by picking whichever computation happens to match — the binding hole we proved unsafe. The user picks the
    computation their claim is ABOUT (e.g. the held-out eval at model.py:42); re-verifying with
    bind={"site": ...} binds exactly that one and the value is revealed only in the resulting verdict.
    Returns [] when no scoping is needed (a unique binding already exists)."""
    cid, raw, cands, _hint = _candidates(claim, calls)
    if len(cands) <= 1:
        return []
    user = [c for c in cands if c.get("user_site")]
    pool = user if (user and len(user) < len(cands)) else cands   # the headline computations, same as binding
    seen, opts = set(), []
    for c in sorted(pool, key=lambda c: c.get("seq", 0)):
        site = c.get("site")
        if site in seen:                          # one option per distinct call site
            continue
        seen.add(site)
        opts.append({"site": site, "sink": c.get("sink"), "n": c.get("n"),
                     "user_site": bool(c.get("user_site"))})
    return opts if len(opts) > 1 else []


def diff_claim(claim, runs, resolver=None) -> dict:
    """Three-way diff for one claim across `runs` (a list of capture-call lists; runs[0] is authoritative).

    `resolver(metric, inputs, kwargs) -> Result` is an optional injected recompute for metrics the curated
    catalog doesn't know (the synth/store flywheel). Keeping it injected leaves core pure-stdlib."""
    cid, raw = _claim_cid(claim)
    base_calls = runs[0] if runs else []
    call, status, reason = _bound_call(claim, base_calls)
    binding = {"bound": status == "bound", "ambiguous": status == "ambiguous", "reason": reason}
    if status == "ambiguous":
        binding["candidates"] = scope_options(claim, base_calls)   # the choices for the scope-the-claim UX
    rec = {"claim": claim, "binding": dict(binding)}

    if status != "bound":
        v = VD.decide(claimed_raw=claim.get("value"), produced=None, recomputed=None,
                      recompute_known=cid is not None, binding=binding,
                      determinism={"tested": False, "stable": False, "spread": 0.0, "k": len(runs)},
                      validity={"invalidating": [], "advisory": []})
        rec.update(v)
        return rec

    produced = _finite_float(call.get("result"))
    inputs = call.get("inputs") if call.get("captured_full", True) else None

    # independent recompute: catalog (recognised) → resolver (synth/store) → none. Needs captured inputs.
    recomputed, recompute_known = None, cid is not None
    kw = call.get("kwargs") or {}
    if inputs is None:
        if cid is not None:
            recomputed = {"value": float("nan"), "degenerate": True,
                          "note": "inputs not captured (too large)", "terms": {}}
    elif cid is not None:
        recomputed = C.recompute(cid, inputs, kw)
    elif resolver is not None:
        rr = resolver(raw, inputs, kw)            # the flywheel: store hit / Exa-synth / none
        if rr and not rr.get("degenerate"):
            recomputed, recompute_known = rr, True
        elif rr:
            recomputed = rr                       # degenerate resolver result → stays reproduced-only

    # validity overlay on the captured inputs
    validity = V.check(raw, inputs, produced) if inputs is not None else {"invalidating": [], "advisory": []}

    # determinism: is the produced value stable across runs? Reapply the SAME binding logic to each run
    # (same code → same call structure → the corresponding computation), so we compare like with like.
    produced_each = []
    for r in runs:
        c, st, _ = _bound_call(claim, r)
        pv = _finite_float(c.get("result")) if (st == "bound" and c) else None
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
    rec["recompute_provenance"] = (recomputed or {}).get("provenance")   # catalog | store | synth
    return rec


def diff_repo(claims, runs, resolver=None) -> dict:
    """Diff every claim. Returns {"claims": [verdict record...], "counts": {verdict: n}}."""
    records = [diff_claim(cl, runs, resolver=resolver) for cl in claims]
    counts: dict[str, int] = {}
    for r in records:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"claims": records, "counts": counts}
