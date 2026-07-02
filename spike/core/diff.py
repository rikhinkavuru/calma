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
from . import conventions as CONV
from . import formula_diff as FZ
from . import interval as I
from . import intervals as ITV
from . import metamorphic as MM
from . import perturb as PB
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

    # EXACTLY two candidates, SAME sink (the same computation run twice — not two different models/methods,
    # which stays ambiguous below), no hint, but distinct sizes: the GridSearchCV/train-vs-test shape after
    # collapsing library-internal calls to 2 user-site evals. Default to the ML reporting convention — the
    # headline number is the HELD-OUT evaluation, not the training-set score — and bind the smaller one.
    #
    # This is a HEURISTIC bind, status "bound_heuristic" (not "bound"): sizing, never value, so it can still
    # REFUTE a genuine misreport (bound to a real-but-possibly-wrong candidate, claim doesn't match it — a
    # real catch). But it must NEVER be allowed to CONFIRM — the redteam corpus's `value_coincidence` attack
    # proves why: an attacker (or an unlucky repo shape) can arrange for the claimed value to coincidentally
    # equal the smaller candidate's actual output even when the claim was really about the larger one, and a
    # bare CONFIRMED here would be indistinguishable from binding-by-value, the exact hole this file's module
    # docstring rules out. diff_claim() caps any AFFIRMATIVE reached via this status back to INCONCLUSIVE —
    # downgrade-only, the same pattern every other advisory/heuristic overlay in this codebase follows.
    same_sink = len({c.get("sink") for c in cands}) == 1
    if len(cands) == 2 and same_sink and all(isinstance(n, int) for n in sizes) and len(set(sizes)) == 2:
        s = sorted(cands, key=lambda c: c.get("n"))
        return s[0], "bound_heuristic", pfx + (
            "no split hint; 2 differently-sized computations of the same call (n=%d, n=%d) — bound to the "
            "smaller as the held-out/headline evaluation by convention (catches a mismatch; can't confirm)"
        ) % (s[0].get("n"), s[1].get("n"))

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


def _fuzz_overlay(cid, raw, call, fuzz) -> list[str]:
    """Downgrade-only re-invocation checks (features 2/7/10) on the repo's OWN callable, fed by
    capture.reinvoke's `.fuzz` emit. Returns invalidating notes; the caller folds them into `validity`, so
    they route through the EXISTING INVALIDATED path in verdict.decide — they can only fail a number closed,
    never open one. Matches the fuzz record to the claim by the bound call's target sink, else by metric."""
    if not fuzz:
        return []
    # The fuzz emit re-invokes a specific TARGET callable, so it may only judge a claim bound to THAT target.
    # A claim bound elsewhere (e.g. a sklearn.metrics call) must NOT inherit another target's divergence —
    # that would false-INVALIDATE a legitimate number that happens to share the metric name. Match by exact
    # target; only fall back to a metric match when it is UNIQUE (a lone fuzzed target of that metric).
    sink = (call or {}).get("sink") or ""
    if not sink.startswith("target:"):
        return []
    target = sink.split("target:", 1)[1]
    recs = [r for r in fuzz if r.get("target") == target]
    if not recs and cid:
        by_metric = [r for r in fuzz if C.canonical(r.get("metric") or "") == cid]
        recs = by_metric if len(by_metric) == 1 else []
    notes: list[str] = []
    for r in recs:
        cases = r.get("cases") or []
        metric = r.get("metric") or raw
        fd = FZ.differential(metric, cases)
        if fd.get("diverged"):
            ce = fd.get("counterexample") or {}
            notes.append("formula-fuzz: the repo's function diverges from an independent recompute on random "
                         "inputs (%d/%d cases; e.g. repo=%.6g vs recompute=%.6g) — not the metric it claims"
                         % (fd["n_diverged"], fd["n_clean"], ce.get("repo", float("nan")),
                            ce.get("recomputed", float("nan"))))
            continue                                  # already invalidating; skip the redundant MR/fab notes
        mm = MM.check_record(metric, cases)
        if mm.get("invalidating"):
            v0 = mm["violations"][0]
            notes.append("metamorphic: the repo's function violates %s (an exact property of %s) — not the "
                         "metric it claims" % (v0["relation"], C.canonical(metric) or metric))
        fab = PB.fabrication_from_fuzz(cases)
        if fab:
            notes.append(fab)
    return notes


def diff_claim(claim, runs, resolver=None, static_deterministic=False, fuzz=None, seed_injected=False,
               shadow=None) -> dict:
    """Three-way diff for one claim across `runs` (a list of capture-call lists; runs[0] is authoritative).

    static_deterministic: the adaptive-k gate proved the run deterministic-by-construction (core.determinism).
    It ONLY has effect when determinism wasn't tested empirically (k=1); with k≥2 the empirical check wins.

    `resolver(metric, inputs, kwargs) -> Result` is an optional injected recompute for metrics the curated
    catalog doesn't know (the synth/store flywheel). Keeping it injected leaves core pure-stdlib."""
    cid, raw = _claim_cid(claim)
    base_calls = runs[0] if runs else []
    call, status, reason = _bound_call(claim, base_calls)
    # Two distinct sources of a non-certain bind, both capped below CONFIRMED (see the cap after VD.decide):
    # (1) status "bound_heuristic" — a sizing-only guess between 2 same-sink candidates (Cycle-1, train-vs-
    #     held-out, see _bound_call); (2) a "static:"-prefixed sink — a NAME-matched (not planner/user
    #     specified) capture target for a hand-rolled metric function with no library call to hook (Cycle-2,
    #     runner/target_discovery.py). Both can still REFUTE/INVALIDATE a real mismatch; neither may CONFIRM.
    heuristic_bind = status == "bound_heuristic" or bool((call or {}).get("sink", "").startswith("static:"))
    bound = status in ("bound", "bound_heuristic")
    binding = {"bound": bound, "ambiguous": status == "ambiguous", "reason": reason}
    if status == "ambiguous":
        binding["candidates"] = scope_options(claim, base_calls)   # the choices for the scope-the-claim UX
    rec = {"claim": claim, "binding": dict(binding)}

    if not bound:
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

    # convention-search: Sharpe & other convention-dependent metrics recompute to different values under
    # different STANDARD conventions (annualization ×√252/12/…, sample-vs-population stdev, downside-
    # denominator, correlation type). The repo's convention lives in its own code and isn't captured, so the
    # DEFAULT recompute can falsely disagree with a correct number. If it does, try the recognized, CITED,
    # size-capped conventions (core.conventions, the hard contract) against the REAL captured inputs; if one
    # reproduces the produced value at the SAME confirm tolerance, THAT is the recompute — a valid metric, not
    # "cheating". FCR-safe: a fabricated value matches no standard convention (proven by the coincidental-
    # value fuzz gate), so this can only rescue genuine numbers, never confirm a wrong one. Runs only after
    # the default recompute disagrees (gated on prior reproduction, rule 5).
    _conv_rcv = _finite_float(recomputed.get("value")) if recomputed else None
    if (recomputed and produced is not None and inputs is not None and not recomputed.get("degenerate")
            and _conv_rcv is not None and not T.close(produced, _conv_rcv)):
        match = None
        if cid and CONV.has_grid(cid):                       # catalog metric with a grid — recompute via C
            match = CONV.search(cid, inputs, produced, kw, C.recompute, T.close)
        elif recompute_known and resolver is not None:       # recipe/synth metric with a grid (guide §B.3)
            rkey = (raw or "").strip().lower()
            if CONV.has_grid(rkey):
                match = CONV.search(rkey, inputs, produced, kw,
                                    lambda m, i, k: resolver(raw, i, k), T.close)
        if match:
            recomputed = match

    # feature 17 — differential recompute (inline, downgrade-only): fold an optional INDEPENDENT `shadow`
    # recompute in. Disagreement → the recompute is degenerate (fail-closed); agreement changes nothing (no
    # upgrade, per Knight–Leveson). See synth.xcheck for the same discipline applied to the synth flywheel.
    if shadow is not None and recomputed and inputs is not None and not recomputed.get("degenerate"):
        try:
            sr = shadow(raw, inputs, kw)
        except Exception:  # noqa: BLE001
            sr = None
        sval = _finite_float(sr.get("value")) if (sr and not sr.get("degenerate")) else None
        if sval is not None:
            _rcv = _finite_float(recomputed.get("value"))
            agree = T.close(_rcv, sval)
            rec["xcheck"] = {"agree": bool(agree), "primary": _rcv, "independent": sval}
            if not agree:
                recomputed = {**recomputed, "degenerate": True,
                              "note": "recompute paths disagree (primary=%.8g vs independent=%.8g) — cannot "
                                      "trust the oracle" % (_rcv if _rcv is not None else float("nan"), sval)}

    # feature 19 — certified enclosure at the tolerance boundary. When the recompute would confirm (close to
    # produced) on a cancellation-prone metric (variance/stdev/mean/sum), certify it: if the rigorous enclosure
    # of OUR recompute does not lie ENTIRELY within the produced tolerance band (ill-conditioning straddling
    # the boundary), we cannot certify agreement → fail closed (mark the recompute degenerate). Only downgrades.
    _enc_rcv = _finite_float(recomputed.get("value")) if recomputed else None
    if (recomputed and produced is not None and inputs is not None and not recomputed.get("degenerate")
            and cid in ITV.ENCLOSED and _enc_rcv is not None and T.close(produced, _enc_rcv)):
        rv = _enc_rcv
        tol = T.ATOL + T.RTOL * max(abs(produced), abs(rv))
        enc = ITV.enclosure(cid, inputs, kw)
        if enc:
            rel = ITV.band_relation(enc, produced, tol)
            rec["enclosure"] = {**enc, "relation": rel}
            if rel == "straddle":
                recomputed = {**recomputed, "degenerate": True,
                              "note": "recompute enclosure [%.6g, %.6g] straddles the confirm tolerance under "
                                      "ill-conditioning — cannot certify" % (enc["lo"], enc["hi"])}

    # validity overlay on the captured inputs
    validity = V.check(raw, inputs, produced) if inputs is not None else {"invalidating": [], "advisory": []}
    # un-foolability overlay (features 2/7/10): re-invoke the repo's OWN callable on fresh inputs and fold any
    # formula divergence / broken metamorphic relation / input-invariance into the validity invalidations. It
    # only ever ADDS an invalidation (downgrade-only) — a would-be CONFIRMED becomes INVALIDATED, never the
    # reverse. Runs only on a reproduced claim (produced present) where it could change a positive verdict.
    if fuzz and produced is not None:
        for note in _fuzz_overlay(cid, raw, call, fuzz):
            if note not in validity["invalidating"]:
                validity["invalidating"].append(note)

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
        # empirical proof from k≥2 is authoritative; a static "deterministic" claim can't override an
        # observed instability (if the runs actually disagree, it's NON-DETERMINISTIC, full stop).
        determinism = {"tested": True, "stable": stable, "spread": spread, "k": len(produced_each),
                       "proven": bool(static_deterministic)}
    else:
        determinism = {"tested": False, "stable": False, "spread": 0.0, "k": len(produced_each),
                       "proven": bool(static_deterministic)}

    # feature 6 — when the runs are unstable, build a prediction interval from the repo's OWN run-to-run
    # values so a claim consistent with that distribution can reach CONFIRMED-STOCHASTIC (and one clearly
    # outside, REFUTED). Only has power at k ≥ k_min; at the default k=2 it is `enough=False` and inert.
    distribution = None
    if determinism.get("tested") and not determinism.get("stable") and len(produced_each) >= 2:
        iv = I.predict_interval(produced_each)
        # "too unstable to verify" guard: if the run-to-run spread exceeds the value itself, the repo is so
        # unstable (e.g. an unseeded value ~ uniform random) that its distribution would swallow ANY in-range
        # claim — a meaningless confirm. Fold that into `enough=False` so the verdict stays NON-DETERMINISTIC.
        center = iv.get("center") or 0.0
        width = (iv.get("hi") or 0.0) - (iv.get("lo") or 0.0)
        # flag only EGREGIOUS spread: wider than 2× the value AND wider than an absolute floor. This catches a
        # ~uniform-random value (interval swallows the whole range) without harming a legitimately noisy
        # near-zero or large-magnitude metric.
        too_wide = width > max(abs(center) * 2.0, 0.5)
        distribution = {"enough": bool(iv["enough"] and not too_wide), "interval": iv, "too_wide": too_wide,
                        "contains": I.contains(iv, claim.get("value")),
                        "outside": I.outside_by_margin(iv, claim.get("value"))}

    v = VD.decide(claimed_raw=claim.get("value"), produced=produced, recomputed=recomputed,
                  recompute_known=recompute_known, binding=binding,
                  determinism=determinism, validity=validity, distribution=distribution,
                  seed_injected=seed_injected)
    if heuristic_bind and v.get("verdict") in VD.AFFIRMATIVE:
        # Downgrade-only cap (never open, only close — the same pattern as the redteam gate / anomaly /
        # agent-modified caps elsewhere): a NAME- or SIZE-matched guess (never a value match — see _bound_call
        # and runner/target_discovery.py) may REFUTE/INVALIDATE a real mismatch, but must never CONFIRM on its
        # own say-so. This is what closes the `value_coincidence` redteam attack for the size-convention bind,
        # and the equivalent risk for a static-heuristic capture target. Preserves diff/confidence/caveats —
        # only the verdict + reason change; the produced/recomputed numbers stay visible for audit.
        v = {**v, "verdict": VD.INCONCLUSIVE,
             "reason": "bound by a name/size heuristic (not a hint, not a known library call) and it matched "
                       "the claim — capped at INCONCLUSIVE rather than confirmed on a guess; %s"
                       % v.get("reason", "")}
    rec.update(v)
    rec["sink"] = call.get("sink")
    rec["determinism"] = determinism
    rec["validity"] = validity
    if inputs is not None:                                    # feature 16: content-address the data the number
        from . import datahash as DH                          # lazy import — avoids a core/__init__ eager cycle
        rec["data_digest"] = DH.canonical_sha256(inputs)      # was computed on (a field, never a verdict gate)
    rec["recompute_provenance"] = (recomputed or {}).get("provenance")   # catalog | store | synth
    # audit surface (guide §B.2 rule 7): a confirm reached via convention-search is never a BARE CONFIRMED —
    # record WHICH standard convention matched so a human can sanity-check the inferred convention.
    if isinstance(recomputed, dict) and recomputed.get("convention"):
        rec["convention"] = recomputed["convention"]
        if rec.get("verdict") == VD.CONFIRMED and recomputed.get("note"):
            rec["reason"] = (rec.get("reason", "") + " — " + recomputed["note"]).strip()
    return rec


def diff_repo(claims, runs, resolver=None, fuzz=None) -> dict:
    """Diff every claim. Returns {"claims": [verdict record...], "counts": {verdict: n}}."""
    records = [diff_claim(cl, runs, resolver=resolver, fuzz=fuzz) for cl in claims]
    counts: dict[str, int] = {}
    for r in records:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"claims": records, "counts": counts}
