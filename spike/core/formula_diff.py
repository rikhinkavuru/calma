"""calma.spike.core.formula_diff — feature 2 ("fuzz-the-formula") host-side differential.

The three-way diff checks the repo's metric on the ONE real captured input. This turns "the number matches"
into "the function IS the metric": it re-runs the repo's OWN callable (via capture.reinvoke's `.fuzz` emit) on
many random inputs and checks each output against the trusted catalog. A formula that only coincidentally hits
the claimed value on the real data — a hard-coded return, a wrong denominator, a cheat keyed to the eval set —
diverges on fresh inputs and is caught.

FCR-safety: DOWNGRADE-ONLY. A majority divergence appends to `validity.invalidating` → the would-be CONFIRMED
becomes INVALIDATED; it never contributes to a CONFIRM. Two guards stop it over-flipping (a trust cost, not an
FCR breach): (1) an INVALIDATED needs a MAJORITY of clean, non-degenerate cases to diverge (a lone NaN/exception
case is discarded); (2) before calling a case "diverged" we let a recognized, cited, size-capped CONVENTION try
to reproduce the repo output — a legitimate ddof/annualization/gain choice reproduces EVERY random case, so it is
accepted, not flagged (and, as a bonus, fuzz DISAMBIGUATES the convention the single-input search left open).
"""
from __future__ import annotations

from . import catalog as C
from . import conventions as CONV
from . import tolerance as T


def differential(metric: str, cases: list[dict], base_kwargs: dict | None = None) -> dict:
    """Differential-test a target's fuzz `cases` (each {inputs, outputs:{base,...}}) against the catalog.
    Returns {diverged, n_clean, n_diverged, counterexample, convention}. `diverged` is True only when a
    MAJORITY of clean cases diverge from BOTH the default recompute and every standard convention."""
    cid = C.canonical(metric)
    if cid is None:
        return {"diverged": False, "n_clean": 0, "n_diverged": 0, "counterexample": None, "convention": None}
    kw = base_kwargs or {}
    clean = 0
    diverged = 0
    counterexample = None
    conv_hits: dict[str, int] = {}
    for case in cases or []:
        inputs = case.get("inputs")
        repo = case.get("outputs", {}).get("base")
        if inputs is None or repo is None or not (isinstance(repo, float) and repo == repo):
            continue
        oracle = C.recompute(cid, inputs, kw)
        if not oracle or oracle.get("degenerate"):
            continue                                          # degenerate synthetic input — discard the case
        clean += 1
        if T.close(repo, oracle["value"]):
            continue                                          # matches the default recompute exactly
        # not the default — can a recognized standard convention reproduce this repo output on THIS input?
        match = None
        if CONV.has_grid(cid):
            match = CONV.search(cid, inputs, repo, kw, C.recompute, T.close)
        if match and match.get("convention") is not None:
            ckey = str(match["convention"])                   # the convention cell may be a dict — key by its repr
            conv_hits[ckey] = conv_hits.get(ckey, 0) + 1
            continue                                          # a legitimate convention explains it
        diverged += 1
        if counterexample is None:
            counterexample = {"inputs": {k: (v[:8] if isinstance(v, list) else v) for k, v in inputs.items()},
                              "repo": repo, "recomputed": oracle["value"]}
    # a convention only "explains" the formula if it reproduced it CONSISTENTLY (on ≥ a majority of clean cases).
    convention = None
    if clean and conv_hits:
        top, hits = max(conv_hits.items(), key=lambda kv: kv[1])
        if hits >= (clean + 1) // 2:
            convention = top
    is_diverged = clean >= 3 and diverged >= (clean + 1) // 2
    return {"diverged": is_diverged, "n_clean": clean, "n_diverged": diverged,
            "counterexample": counterexample, "convention": convention}
