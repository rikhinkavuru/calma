"""calma.report - strictly-progressive render. Default surface is a few lines regardless of how many
families/tiers were stamped: line 1 = the verdict + a deterministic confidence; line 2 = the one thing
most limiting it; an INCONCLUSIVE always carries a concrete `fix:` line; everything else stays in the
ledger ('show full breakdown').

Verdict vocabulary (one enum, one display): CONFIRMED / CONFIRMED-WITH-CAVEATS / REFUTED /
CAN'T-CONFIRM (the display name of INCONCLUSIVE) / MIXED (multi-claim, at least one REFUTED).
"""
import verdict as V

_TOPLINE = {
    V.CONFIRMED: ("CONFIRMED", "reproduces and recomputes to the claim"),
    V.CAVEATS: ("CONFIRMED-WITH-CAVEATS", "holds, but narrower than claimed"),
    V.REFUTED: ("REFUTED", "the result does not hold"),
    V.INCONCLUSIVE: ("CAN'T-CONFIRM", "not verifiable yet"),
    "MIXED": ("MIXED", "some claims hold, at least one is broken"),
}

# metrics whose natural display is a percentage of the raw ratio
PERCENT_METRICS = {"total_return", "max_drawdown"}

# INCONCLUSIVE reason -> the concrete unblock ('who-can-act' fix). Substring-matched, first hit wins.
_FIXES = [
    ("exited non-zero", "make the entrypoint run to completion (exit 0), then re-run calma verify"),
    ("determinism is uncontrolled", "set a fixed seed and write outputs deterministically, then re-run"),
    ("determinism is measured-band", "set a fixed seed (or run calibration) so the band is controlled"),
    ("claim target is unconfirmed", "name the metric in the claim (e.g. \"accuracy 0.99\") or pass --metric"),
    ("not statistically distinguishable", "the gap is within the claim's own noise - a finer-grained claim or more data is needed"),
    ("no recomputed numeric", "write the result's raw numbers to a machine-readable file (e.g. predictions.csv with y_true,y_pred)"),
    ("untrusted code", "third-party code needs a verified container/VM tier - or set trust: own-code if you wrote it"),
    ("killed or isolation was refused", "the run was killed or refused - raise the timeout, or check `run_hermetic.py doctor`"),
    ("degenerate recompute", "the recompute hit NaN/Inf - check for missing values in the output file"),
    ("outputs differ across identical re-runs", "set a fixed seed (and write outputs deterministically), then re-run"),
    ("plausibly-bound", "confirm which column is the metric: pass --metric, or pin the binding in verify.yaml"),
    ("author-asserted", "the input binding could not be independently sanity-checked - pin it in verify.yaml"),
]


def fmt_value(value, metric_id=None):
    """Human formatting, deterministic: percent metrics render as %, everything else to 4 significant
    digits. The ledger keeps the full-precision floats; this is display only."""
    if value is None:
        return "?"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    v = float(value)
    if v != v:
        return "NaN"
    if metric_id in PERCENT_METRICS:
        pct = v * 100.0
        if abs(pct) >= 100:
            return "{:+,.0f}%".format(pct)
        if abs(pct) >= 1:
            return "{:+.1f}%".format(pct)
        return "{:+.2f}%".format(pct)
    if v.is_integer() and abs(v) < 1e15:
        return "{:,.0f}".format(v)
    return "%.4g" % v


def _fix_line(led, diff=None):
    """The actionable unblock for a non-CONFIRMED outcome. Sources, in order: an explicit `unblock` on a
    finding, then the reason->fix table applied to the claim/diff reason."""
    for f in led.get("findings", []):
        if f.get("unblock"):
            return f["unblock"]
    reasons = []
    for c in led.get("claims", []):
        if c.get("reason"):
            reasons.append(c["reason"])
    if diff:
        for m in diff.get("metrics", []):
            if m.get("reason"):
                reasons.append(m["reason"])
    for reason in reasons:
        for needle, fix in _FIXES:
            if needle in reason:
                return fix
    return None


def render(led, diff=None):
    rv = led.get("repo_verdict", V.INCONCLUSIVE)
    word, gloss = _TOPLINE.get(rv, _TOPLINE[V.INCONCLUSIVE])
    c0 = led["claims"][0] if led.get("claims") else {}
    conf = c0.get("headline_confidence") or 0.0
    head = "%s  (confidence %d/100)" % (word, int(round(conf * 100))) if conf > 0 else word
    lines = ["%s  -  %s" % (head, gloss)]
    # line 2: the single most-limiting thing. On a REFUTED the numeric-collapse line below already
    # carries the metric-mismatch, so prefer a DIFFERENT blocker (e.g. baseline) over repeating it.
    limiter = None
    blockers = [f for f in led.get("findings", []) if f.get("severity") == "blocker"]
    majors = [f for f in led.get("findings", []) if f.get("severity") == "major"]
    if rv in ("REFUTED", "MIXED"):
        others = [f for f in blockers + majors if f.get("dimension") != "metric-mismatch"]
        if others:
            limiter = "also: " + (others[0].get("locator") or "")
    elif blockers:
        limiter = blockers[0].get("locator")
    elif rv == V.INCONCLUSIVE and (c0.get("reason") or majors):
        limiter = c0.get("reason") or majors[0].get("locator")
    elif diff and diff.get("metrics"):
        limiter = diff["metrics"][0].get("reason")
    if limiter:
        lines.append("  - " + limiter)
    # the numeric collapse + reproduction for a break
    if rv in ("REFUTED", "MIXED") and led.get("claims"):
        c = led["claims"][0]
        if c.get("claimed_value") is not None and c.get("recomputed_value") is not None:
            mid = c.get("metric")
            lines.append("  claimed %s  ->  recomputed %s" % (fmt_value(c["claimed_value"], mid),
                                                              fmt_value(c["recomputed_value"], mid)))
        rep = c.get("reproduction_or_reverify", {})
        if rep.get("command"):
            lines.append("  reproduce: " + rep["command"])
    # the fix line: an INCONCLUSIVE (or any not-clean outcome with a known unblock) names who-can-act
    if rv != V.CONFIRMED:
        fix = _fix_line(led, diff)
        if fix and rv in (V.INCONCLUSIVE, V.CAVEATS):
            lines.append("  fix: " + fix)
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
        if sc.get("binding_note"):
            lines.append("  checked: " + sc["binding_note"])
    return "\n".join(lines)


fix_line = _fix_line  # public alias (agent/JSON consumers)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def svg_card(led, width=820):
    """A self-contained dark SVG share card for a REFUTED result - the local, no-SaaS version of an
    OG image. Deterministic output (no timestamps)."""
    if led.get("repo_verdict") not in ("REFUTED", "MIXED"):
        return None
    c = (led.get("claims") or [{}])[0]
    mid = c.get("metric")
    claimed = fmt_value(c.get("claimed_value"), mid)
    recomputed = fmt_value(c.get("recomputed_value"), mid)
    blockers = [f for f in led.get("findings", []) if f.get("severity") in ("blocker", "major")]
    why = _DIMENSION_GLOSS.get(blockers[0].get("dimension"), blockers[0].get("dimension")) \
        if blockers else "the number doesn't recompute"
    sc = led.get("scope", {})
    h = 430
    return """<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">
  <rect width="%d" height="%d" rx="16" fill="#0A0A0B"/>
  <rect x="1" y="1" width="%d" height="%d" rx="15" fill="none" stroke="#26262B" stroke-width="2"/>
  <text x="48" y="64" font-family="ui-monospace,Menlo,monospace" font-size="15" fill="#71717A" letter-spacing="3">CALMA TEARDOWN — %s</text>
  <text x="48" y="120" font-family="ui-monospace,Menlo,monospace" font-size="17" fill="#A1A1AA">CLAIMED</text>
  <text x="48" y="172" font-family="ui-monospace,Menlo,monospace" font-size="44" font-weight="700" fill="#FAFAFA">%s</text>
  <text x="48" y="218" font-family="ui-monospace,Menlo,monospace" font-size="17" fill="#A1A1AA">RECOMPUTED — by re-running the code</text>
  <text x="48" y="272" font-family="ui-monospace,Menlo,monospace" font-size="44" font-weight="700" fill="#F87171">%s</text>
  <rect x="48" y="300" width="%d" height="1" fill="#26262B"/>
  <text x="48" y="336" font-family="ui-monospace,Menlo,monospace" font-size="15" fill="#FCA5A5">REFUTED — %s</text>
  <text x="48" y="372" font-family="ui-monospace,Menlo,monospace" font-size="13" fill="#71717A">verified by RE-EXECUTION, not opinion · isolation: %s · determinism: %s</text>
  <text x="48" y="398" font-family="ui-monospace,Menlo,monospace" font-size="13" fill="#4ADE80">$ calma verify · github.com/rikhinkavuru/calma</text>
</svg>
""" % (width, h, width, h, width, h, width - 2, h - 2,
       _esc(led.get("target", "result")), _esc(claimed), _esc(recomputed),
       width - 96, _esc(why),
       _esc(sc.get("isolation_tier", "?")), _esc(sc.get("determinism_mode", "?")))


_DIMENSION_GLOSS = {
    "metric-mismatch": "the number doesn't recompute",
    "baseline": "loses to the trivial baseline",
    "reproducibility": "doesn't re-run",
    "contract-grounding": "not enough structure to verify",
}


def teardown_card(led, diff=None):
    """A copy-pasteable shareable card for a REFUTED result.
    'claimed X -> really Y, here is why, here is the repro.'"""
    if led.get("repo_verdict") not in ("REFUTED", "MIXED"):
        return None
    c = (led.get("claims") or [{}])[0]
    mid = c.get("metric")
    lines = ["CALMA TEARDOWN  -  %s" % led.get("target", "result"), ""]
    if c.get("claimed_value") is not None and c.get("recomputed_value") is not None:
        lines.append("  CLAIMED:     %s" % fmt_value(c["claimed_value"], mid))
        lines.append("  RECOMPUTED:  %s   <- re-ran the code, recomputed from raw outputs"
                     % fmt_value(c["recomputed_value"], mid))
        lines.append("")
    blockers = [f for f in led.get("findings", []) if f.get("severity") in ("blocker", "major")]
    if blockers:
        lines.append("  why it breaks:")
        for f in blockers[:4]:
            gloss = _DIMENSION_GLOSS.get(f.get("dimension"), f.get("dimension"))
            lines.append("   - %s: %s" % (gloss, f.get("locator")))
        lines.append("")
    rep = c.get("reproduction_or_reverify", {})
    if rep.get("command"):
        lines.append("  reproduce:  %s" % rep["command"])
    sc = led.get("scope", {})
    lines.append("  verified by RE-EXECUTION, not opinion  -  isolation: %s | determinism: %s"
                 % (sc.get("isolation_tier", "?"), sc.get("determinism_mode", "?")))
    return "\n".join(lines)
