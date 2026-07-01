"""calma.spike.core.verdict — the fail-closed verdict taxonomy and decision (rebuild guide §4, §14).

The three-way diff operationalised (guide §4.4):
  claimed   the number the producer REPORTED (README/table/results.json)
  produced  the number the REPO actually computed at runtime (captured at the metric call site)
  recomputed  our INDEPENDENT recompute of the metric from the *same captured inputs* (trusted catalog)

  claimed ≠ produced                  -> REFUTED       (misreported / hallucinated)
  produced ≠ recomputed               -> INVALIDATED   (the repo's formula is wrong / cheating)
  all agree + deterministic + valid   -> CONFIRMED

FAIL CLOSED (guide §4.7): inputs unbindable, recompute unrecognised/degenerate, or determinism not
proven -> we DO NOT confirm. We downgrade to REPRODUCED-ONLY / NON-DETERMINISTIC / INCONCLUSIVE and say
what blocked it. ~0 false-confirm is the entire franchise — the router refuses rather than guesses.
"""
from __future__ import annotations

from . import tolerance as T

CONFIRMED = "CONFIRMED"
REFUTED = "REFUTED"
INVALIDATED = "INVALIDATED"
REPRODUCED_ONLY = "REPRODUCED-ONLY"
NON_DETERMINISTIC = "NON-DETERMINISTIC"
INCONCLUSIVE = "INCONCLUSIVE"

ALL = (CONFIRMED, REFUTED, INVALIDATED, REPRODUCED_ONLY, NON_DETERMINISTIC, INCONCLUSIVE)

# verdicts that assert the claim is GOOD — a false one of these is a "false confirm" (the cardinal sin)
POSITIVE = (CONFIRMED,)


def decide(*, claimed_raw, produced, recomputed, recompute_known,
           binding, determinism, validity) -> dict:
    """Return the per-claim verdict dict. All inputs are already computed by the diff layer.

    binding      {"bound": bool, "ambiguous": bool, "reason": str, "confidence": float}
    determinism  {"tested": bool, "stable": bool, "spread": float, "k": int}
    validity     {"invalidating": [..notes..], "advisory": [..notes..]}
    recomputed   a catalog Result dict {"value","degenerate","note",...} or None
    """
    diff = {"claimed": claimed_raw, "produced": produced,
            "recomputed": (recomputed or {}).get("value")}
    caveats: list[str] = []

    def out(verdict, reason, confidence="deterministic"):
        return {"verdict": verdict, "reason": reason, "confidence": confidence,
                "diff": diff, "caveats": caveats}

    # 1. Binding gate — we must have located the inputs unambiguously, or we refuse.
    if not binding.get("bound"):
        return out(INCONCLUSIVE, "could not bind the metric inputs: %s"
                   % binding.get("reason", "no matching captured computation"), "n/a")
    if binding.get("ambiguous"):
        return out(INCONCLUSIVE, "ambiguous binding: %s — scope the claim to disambiguate"
                   % binding.get("reason", "multiple candidate computations"), "n/a")

    # 2. Reproduction gate — we must have a runtime-produced value to compare against.
    if produced is None or not (isinstance(produced, float) and produced == produced):
        return out(INCONCLUSIVE, "the computation did not yield a capturable value at runtime", "n/a")

    # 3. claimed vs produced -> REFUTED
    ok_claim, claim_detail = T.claim_close(claimed_raw, produced)
    diff["claim_match"] = claim_detail
    if not ok_claim:
        return out(REFUTED, "the reported value %r is not what the code produced (%.6g); Δ=%.3g"
                   % (claimed_raw, produced, claim_detail.get("delta", float("nan"))))

    # 4. With a trusted independent recompute available:
    if recompute_known and recomputed is not None and not recomputed.get("degenerate"):
        rv = recomputed["value"]
        if not T.close(produced, rv):
            return out(INVALIDATED,
                       "the repo produced %.6g but an independent recompute of the same inputs gives "
                       "%.6g — the formula is wrong or cheating (Δ=%.3g)" % (produced, rv, abs(produced - rv)))
        if validity.get("invalidating"):
            return out(INVALIDATED, "reproducible but invalid: %s" % "; ".join(validity["invalidating"]))
        if validity.get("advisory"):
            caveats.extend(validity["advisory"])
        if not determinism.get("tested"):
            if determinism.get("proven"):
                # A single run, but static analysis proved determinism BY CONSTRUCTION (every RNG the code
                # touches is explicitly seeded) under the enforced env — so the empirical k≥2 re-run isn't
                # needed to rule out a flaky number. Distinctly labelled so it's never conflated with the
                # reproduced-twice CONFIRMED. This is the ONLY way k=1 can reach CONFIRMED.
                return out(CONFIRMED,
                           "claim == runtime value == independent recompute; determinism proven by "
                           "construction (all randomness seeded)" + (", with caveats" if caveats else ""),
                           confidence="deterministic-by-construction")
            caveats.append("determinism not tested (single run) — re-run k≥2 to lift to CONFIRMED")
            return out(REPRODUCED_ONLY,
                       "claim, runtime value and independent recompute all agree, but determinism was not "
                       "proven (k=1)")
        if not determinism.get("stable"):
            return out(NON_DETERMINISTIC,
                       "the produced value is not stable across %d runs (spread=%.3g) — seeds/time/urandom "
                       "uncontrolled; no hard CONFIRMED" % (determinism.get("k", 0), determinism.get("spread", 0.0)))
        return out(CONFIRMED, "claim == runtime value == independent recompute, deterministic"
                   + (", with caveats" if caveats else ""))

    # 5. No trusted oracle (metric unrecognised or recompute degenerate) -> reproduced-only, never CONFIRMED.
    why = "metric not in the trusted catalog" if not recompute_known else \
        "independent recompute degenerate (%s)" % (recomputed or {}).get("note", "")
    if validity.get("invalidating"):
        return out(INVALIDATED, "reproducible but invalid: %s" % "; ".join(validity["invalidating"]))
    if determinism.get("tested") and not determinism.get("stable"):
        return out(NON_DETERMINISTIC, "produced value unstable across %d runs (spread=%.3g)"
                   % (determinism.get("k", 0), determinism.get("spread", 0.0)))
    caveats.append(why)
    return out(REPRODUCED_ONLY,
               "reproduced the reported number, but no independent correctness check was possible (%s)" % why)
