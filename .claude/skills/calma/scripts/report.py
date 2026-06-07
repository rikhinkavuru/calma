"""calma.report - strictly-progressive render. Default surface is ~3 lines regardless of how many
families/tiers were stamped: line 1 = a plain-words trust signal + a 0-100 confidence; line 2 = the one
thing most limiting it; everything else collapses behind 'show full breakdown'.
"""
import verdict as V

_TOPLINE = {
    V.CONFIRMED: ("CONFIRMED", "reproduces and recomputes to the claim"),
    V.CAVEATS: ("CONFIRMED, with caveats", "holds, but narrower than claimed"),
    V.REFUTED: ("BROKEN", "the result does not hold"),
    V.INCONCLUSIVE: ("CAN'T CONFIRM", "not enough to verify - here's the fix"),
    "MIXED": ("MIXED", "some claims hold, at least one is broken"),
}


def _confidence(led):
    c = led["claims"][0] if led.get("claims") else {}
    base = int(round((c.get("headline_confidence", 0.8)) * 100))
    return max(0, min(100, base))


def render(led, diff=None):
    rv = led.get("repo_verdict", V.INCONCLUSIVE)
    word, gloss = _TOPLINE.get(rv, _TOPLINE[V.INCONCLUSIVE])
    lines = ["%s  (%d/100)  -  %s" % (word, _confidence(led), gloss)]
    # line 2: the single most-limiting thing
    limiter = None
    blockers = [f for f in led.get("findings", []) if f.get("severity") == "blocker"]
    if blockers:
        limiter = blockers[0].get("locator")
    elif diff and diff.get("metrics"):
        limiter = diff["metrics"][0].get("reason")
    if limiter:
        lines.append("  - " + limiter)
    # for REFUTED/MIXED: show the numeric collapse + reproduction
    if rv in ("REFUTED", "MIXED") and led.get("claims"):
        c = led["claims"][0]
        if c.get("claimed_value") is not None and c.get("recomputed_value") is not None:
            lines.append("  claimed %s  ->  recomputed %s" % (c["claimed_value"], c["recomputed_value"]))
        rep = c.get("reproduction_or_reverify", {})
        if rep.get("command"):
            lines.append("  reproduce: " + rep["command"])
    # scope one-liner (the honest 'what we checked')
    sc = led.get("scope", {})
    if sc:
        fams = sc.get("families", {})
        checked = [k for k, v in fams.items() if str(v).startswith("checked")]
        nv = sc.get("not_verified", [])
        lines.append("  scope: %s | isolation: %s | determinism: %s%s"
                     % (", ".join(checked) or "-", sc.get("isolation_tier", "?"),
                        sc.get("determinism_mode", "?"),
                        (" | not verified: " + "; ".join(nv)) if nv else ""))
    return "\n".join(lines)
