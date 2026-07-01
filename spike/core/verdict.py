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

import math

from . import tolerance as T

CONFIRMED = "CONFIRMED"
CONFIRMED_STOCHASTIC = "CONFIRMED-STOCHASTIC"
REFUTED = "REFUTED"
INVALIDATED = "INVALIDATED"
REPRODUCED_ONLY = "REPRODUCED-ONLY"
NON_DETERMINISTIC = "NON-DETERMINISTIC"
INCONCLUSIVE = "INCONCLUSIVE"

ALL = (CONFIRMED, CONFIRMED_STOCHASTIC, REFUTED, INVALIDATED, REPRODUCED_ONLY, NON_DETERMINISTIC, INCONCLUSIVE)

# Verdicts that assert the claim is GOOD as a HARD deterministic confirm — a false one of these is the cardinal
# sin. CONFIRMED-STOCHASTIC is deliberately NOT here: it is a distinct, weaker "consistent with the repo's
# run-to-run distribution" claim (feature 6), kept out of the moat's hard-confirm count — mirroring how
# `deterministic-by-construction` is labelled distinctly. A downstream that needs "any affirmative verdict"
# uses AFFIRMATIVE; the FCR gates use POSITIVE.
POSITIVE = (CONFIRMED,)
AFFIRMATIVE = (CONFIRMED, CONFIRMED_STOCHASTIC)

# Verdict strength for the downgrade-only gates (feature 8 red-team, feature 11 anomaly, any monotone
# overlay). CONFIRMED is the UNIQUE top: no other verdict shares its rank, so `monotone` can only ever
# return CONFIRMED when the incumbent was already CONFIRMED. The relative order of the non-positive verdicts
# below it is cosmetic (none is a false-confirm), but is set so a more-informative charge wins a tie-break
# down: REFUTED/INVALIDATED (a hard negative statement) < NON-DETERMINISTIC < REPRODUCED-ONLY < INCONCLUSIVE
# < DISCOVERED (least committed). `min` by this rank = the weakest of the two.
_STRENGTH = {
    CONFIRMED: 100,
    CONFIRMED_STOCHASTIC: 90,
    REFUTED: 55, INVALIDATED: 50,
    NON_DETERMINISTIC: 40,
    REPRODUCED_ONLY: 30,
    INCONCLUSIVE: 20,
    "DISCOVERED": 10,
}


def monotone(old: str, proposed: str | None) -> str:
    """Return the WEAKER of `old` and a `proposed` downgrade — never the stronger. Structurally cannot
    upgrade: the result equals CONFIRMED only if `old` was already CONFIRMED (CONFIRMED is the unique rank-100
    verdict, and a strictly-lower proposal is required to move off `old`). `proposed is None` → no charge →
    `old` unchanged. This is the one primitive every downgrade-only overlay routes through, so FCR-safety is
    proven once, here, and reused."""
    if proposed is None:
        return old
    ro = _STRENGTH.get(old, 0)
    rp = _STRENGTH.get(proposed, 0)
    return proposed if rp < ro else old


def decide(*, claimed_raw, produced, recomputed, recompute_known,
           binding, determinism, validity, distribution=None, seed_injected=False) -> dict:
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

    # 2. Reproduction gate — we must have a FINITE runtime-produced value to compare against (reject None/NaN
    # AND ±inf — an infinite "score" is never a confirmable number; defense-in-depth beside diff's _finite_float).
    if produced is None or not (isinstance(produced, (int, float)) and math.isfinite(produced)):
        return out(INCONCLUSIVE, "the computation did not yield a capturable value at runtime", "n/a")

    # For an UNSTABLE run with enough power (feature 6), the claim is judged against the run-to-run
    # DISTRIBUTION further down (a single sample `produced` is not the claim's reference), so the point
    # claimed-vs-produced check below is skipped. Requires a trusted recompute so the distribution branch is
    # actually reached; seed-injected runs are excluded (feature 15).
    stochastic = bool(recompute_known and distribution and distribution.get("enough")
                      and determinism.get("tested") and not determinism.get("stable") and not seed_injected)

    # 3. claimed vs produced -> REFUTED (deterministic case only)
    if not stochastic:
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
        if seed_injected:
            # feature 15 — the run was made deterministic with an INJECTED seed the author never set, so it
            # computed a DIFFERENT number (a different split/init) than the claim. It can never confirm the
            # claimed value; hard-cap at REPRODUCED-ONLY regardless of how stable the seeded runs are.
            caveats.append("determinism achieved via an injected seed (not the author's) — this run verifies a "
                           "different number than the claim; capped below CONFIRMED")
            return out(REPRODUCED_ONLY,
                       "reproduced under an injected seed the author did not set — the claimed number was "
                       "produced under the author's unknown seed, so it cannot be confirmed")
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
            # feature 6 — statistical/distribution verification. When there are enough runs to have power, a
            # claim CONSISTENT with the repo's run-to-run distribution earns the DISTINCT CONFIRMED-STOCHASTIC
            # (not a hard CONFIRMED); one clearly outside is REFUTED; a near-edge / low-power case stays
            # INCONCLUSIVE. `seed_injected` disqualifies it entirely (feature 15: a seeded run computes a
            # DIFFERENT number than the author's, so it can never confirm the claim, even stochastically).
            if distribution and distribution.get("enough") and not seed_injected:
                iv = distribution.get("interval", {})
                if distribution.get("contains"):
                    return out(CONFIRMED_STOCHASTIC,
                               "the claim is consistent with the repo's run-to-run distribution "
                               "(k=%d, %.0f%% prediction interval [%.4g, %.4g]) — non-deterministic but "
                               "statistically confirmed" % (iv.get("n", 0), 100 * iv.get("coverage", 0.99),
                                                            iv.get("lo", float("nan")), iv.get("hi", float("nan"))),
                               confidence="stochastic")
                if distribution.get("outside"):
                    return out(REFUTED,
                               "the reported value %r is outside the repo's run-to-run distribution "
                               "(k=%d, prediction interval [%.4g, %.4g]) — misreported"
                               % (claimed_raw, iv.get("n", 0), iv.get("lo", float("nan")), iv.get("hi", float("nan"))))
                return out(INCONCLUSIVE,
                           "the claim sits near the edge of the repo's run-to-run distribution (k=%d) — "
                           "cannot confirm or refute; report a seed or a value distribution" % iv.get("n", 0))
            return out(NON_DETERMINISTIC,
                       "the produced value is not stable across %d runs (spread=%.3g) — seeds/time/urandom "
                       "uncontrolled; no hard CONFIRMED" % (determinism.get("k", 0), determinism.get("spread", 0.0)))
        return out(CONFIRMED, "claim == runtime value == independent recompute, deterministic"
                   + (", with caveats" if caveats else ""))

    # 5. No trusted oracle (metric unrecognised or recompute degenerate) -> reproduced-only, never CONFIRMED.
    # Prefer the recompute's own note when present (e.g. a LEARNED/embedding metric explains WHY no
    # independent recompute is possible), so the honest reason surfaces instead of a generic one.
    _rc_note = (recomputed or {}).get("note")
    if not recompute_known:
        why = _rc_note or "metric not in the trusted catalog"
    else:
        why = "independent recompute degenerate (%s)" % (_rc_note or "")
    if validity.get("invalidating"):
        return out(INVALIDATED, "reproducible but invalid: %s" % "; ".join(validity["invalidating"]))
    if determinism.get("tested") and not determinism.get("stable"):
        return out(NON_DETERMINISTIC, "produced value unstable across %d runs (spread=%.3g)"
                   % (determinism.get("k", 0), determinism.get("spread", 0.0)))
    caveats.append(why)
    return out(REPRODUCED_ONLY,
               "reproduced the reported number, but no independent correctness check was possible (%s)" % why)
