"""calma.report - strictly-progressive render. Default surface is a few lines regardless of how many
families/tiers were stamped: line 1 = the verdict + a deterministic confidence; line 2 = the one thing
most limiting it; an INCONCLUSIVE always carries a concrete `fix:` line; everything else stays in the
ledger ('show full breakdown').

Verdict vocabulary (one enum, one display): CONFIRMED / CONFIRMED-WITH-CAVEATS / REFUTED /
CAN'T-CONFIRM (the display name of INCONCLUSIVE) / MIXED (multi-claim, at least one REFUTED).
"""
import hashlib
import os
import re
import shutil
import subprocess
import textwrap

import verdict as V

_CSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _plain(s):
    """Strip ANSI escapes + control chars from an ATTACKER-DERIVED string (a finding locator, a target
    name, a column) before it goes to the terminal, so a crafted value can't repaint a fake green
    'CONFIRMED' over the real verdict line. Color the verifier adds itself is applied AFTER this, to its
    own symbols - never to attacker content. Order matters: drop the CSI sequences FIRST (while the ESC
    byte is intact) THEN replace any remaining control chars with a space, else stripping the ESC first
    would leave the inert `[31m` literal behind."""
    return re.sub(r"[\x00-\x1f\x7f]", " ", _CSI.sub("", str(s)))


def _wrap(text, width=96):
    """Wrap a prose report line to a fixed sane width with a hanging indent, so a long scope /
    not-verified list reads as a few lines, not a 240-char wall. Fixed (not terminal-derived) so
    the stored report.txt is byte-stable across terminals. NEVER used for command/reproduce lines
    (wrapping would break copy-paste)."""
    return textwrap.fill(text, width=width, initial_indent="  ", subsequent_indent="      ",
                         break_long_words=False, break_on_hyphens=False)

_TOPLINE = {
    V.CONFIRMED: ("CONFIRMED", "reproduces and recomputes to the claim"),
    V.CAVEATS: ("CONFIRMED-WITH-CAVEATS", "holds, but narrower than claimed"),
    V.REFUTED: ("REFUTED", "the result does not hold"),
    V.INVALIDATED: ("INVALIDATED", "the number reproduces, but the result is invalid"),
    V.FLAG_FOR_DECLARATION: ("FLAG_FOR_DECLARATION",
                             "reproduces, but undeclared structure could invalidate it - declare to resolve"),
    V.INCONCLUSIVE: ("CAN'T-CONFIRM", "not verifiable yet"),
    "MIXED": ("MIXED", "some claims hold, at least one is broken"),
}


def display(repo_verdict):
    """The user-facing name of a verdict enum value (INCONCLUSIVE displays as CAN'T-CONFIRM).
    The internal enum and every --json value stay unchanged; this is for human surfaces only."""
    return _TOPLINE.get(repo_verdict, (str(repo_verdict), ""))[0]

# metrics whose natural display is a percentage of the raw ratio: signed (direction matters)
# vs unsigned (rates/fractions)
PERCENT_METRICS = {"total_return", "max_drawdown", "growth_rate", "cagr", "irr", "lift"}
UNSIGNED_PERCENT_METRICS = {"test_coverage", "error_rate", "ratio_share", "null_fraction",
                            "churn_rate", "margin_pct", "mape"}

# INCONCLUSIVE reason -> the concrete unblock ('who-can-act' fix). Substring-matched, first hit wins.
_FIXES = [
    ("exited non-zero", "make the entrypoint run to completion (exit 0) - check the captured stderr in .calma/run/run.json - then re-run calma verify"),
    ("determinism is uncontrolled", "set a fixed seed (e.g. np.random.seed(42) / torch.manual_seed(42) / random.seed(42), or R set.seed(42)) and write outputs deterministically (sort rows before writing, pin float formatting), then re-run"),
    ("determinism is measured-band", "set a fixed seed (e.g. np.random.seed(42) / torch.manual_seed(42)), or run a calibration pass, so the determinism band is controlled"),
    ("claim target is unconfirmed", "name the metric in the claim (e.g. \"accuracy 0.99\") or pass --metric (e.g. --metric accuracy)"),
    ("not statistically distinguishable", "the gap is within the claim's own noise - a finer-grained claim or more data is needed"),
    ("no recomputed numeric", "write the result's raw numbers to a machine-readable file (e.g. predictions.csv with y_true,y_pred)"),
    ("untrusted code", "third-party code needs a verified container/VM tier (--isolation docker, or --isolation e2b for a remote microVM) - or set trust: own-code in verify.yaml if you wrote it"),
    ("killed or isolation was refused", "the run was killed or refused - raise the budget with --timeout SECONDS, or check `run_hermetic.py doctor`"),
    ("degenerate recompute", "the recompute hit NaN/Inf - check for missing/blank cells in the output file, or declare an na_policy in verify.yaml"),
    ("outputs differ across identical re-runs", "set a fixed seed (e.g. np.random.seed(42) / torch.manual_seed(42) / random.seed(42), or R set.seed(42)) and write outputs deterministically, then re-run"),
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
    if v == 0:
        v = 0.0  # collapse negative zero (a cancelled recompute) so it never renders as "-0"
    if metric_id in PERCENT_METRICS or metric_id in UNSIGNED_PERCENT_METRICS:
        # a return of >= ~5 reads cleaner as a multiple, but keep the raw percent alongside it so the
        # scale still lands: 10.3258 -> "10.3x (+1,033%)"; 146.98 -> "147.0x (+14,698%)".
        if metric_id in PERCENT_METRICS and abs(v) >= 5:
            return "{:,.1f}x ({:+,.0f}%)".format(v, v * 100.0)
        pct = v * 100.0
        sign = "+" if metric_id in PERCENT_METRICS else ""
        if abs(pct) >= 100:
            return ("{:" + sign + ",.0f}%").format(pct)
        if abs(pct) >= 1:
            return ("{:" + sign + ".1f}%").format(pct)
        return ("{:" + sign + ".2f}%").format(pct)
    av = abs(v)
    if av >= 1e15 or (av != 0 and av < 1e-4):
        return "%.4g" % v                       # extreme magnitudes read clearest in scientific
    if v.is_integer():
        return "{:,.0f}".format(v)
    if av >= 1000:
        # large non-integer money/counts: thousands separators beat "1.235e+06" (display only;
        # the ledger keeps full precision). Round to the integer the separators imply.
        return "{:,.0f}".format(round(v))
    return "%.4g" % v


def fmt_pair(claimed, recomputed, metric_id=None):
    """Format a claimed->recomputed pair so a REFUTED never prints two IDENTICAL-looking numbers for a
    real gap (e.g. 100.04 vs 100.00 -> 'claimed 100 -> recomputed 100', which hides the catch). When
    the default display collapses two GENUINELY-different values, escalate precision until they differ.
    Identical values (e.g. an INVALIDATED that reproduces) are left as-is."""
    cs, rs = fmt_value(claimed, metric_id), fmt_value(recomputed, metric_id)
    if (cs == rs and isinstance(claimed, (int, float)) and isinstance(recomputed, (int, float))
            and not isinstance(claimed, bool) and not isinstance(recomputed, bool)):
        c, r = float(claimed), float(recomputed)
        if c == c and r == r and c != r:
            for p in range(4, 13):
                cs2, rs2 = "%.*g" % (p, c), "%.*g" % (p, r)
                if cs2 != rs2:
                    return cs2, rs2
            return repr(c), repr(r)
    return cs, rs


def _fix_line(led, diff=None):
    """The actionable unblock for a non-CONFIRMED outcome. Sources, in order: a precise recompute/binding
    error (the ROOT blocker), then an explicit `unblock` on a finding, then the reason->fix table."""
    # a precise recompute/binding error (artifact not found / column missing / non-finite cell) is the ROOT
    # blocker and leads: if the headline number could NOT even be recomputed, that beats any validity
    # finding's unblock - a validity family can't meaningfully assess a number that didn't reproduce, and a
    # secondary "the split files couldn't be read" message would bury the real "artifact <X> not found"
    # cause (the misleading-fix bug). REFUTED/INVALIDATED reproduce, so they carry no recompute_error and
    # fall through to the finding unblock unchanged. Check claims (always present, so --json sees it) then diff.
    for m in led.get("claims", []):
        if m.get("recompute_error"):
            return m["recompute_error"]
    if diff:
        for m in diff.get("metrics", []):
            if m.get("recompute_error"):
                return m["recompute_error"]
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


# FLAG_FOR_DECLARATION gets the ⚑ glyph (distinct from REFUTED/INVALIDATED's ✗ "wrong" and INCONCLUSIVE's
# ▲ "can't tell") and a 256-color amber-red (38;5;208) - a catch that reads as action-required, NOT the
# neutral yellow of CAN'T-CONFIRM. The web UI carries the matching amber-red badge.
_SYMBOL = {V.CONFIRMED: "✓", V.CAVEATS: "✓", V.REFUTED: "✗",
           V.INVALIDATED: "✗", V.FLAG_FOR_DECLARATION: "⚑", V.INCONCLUSIVE: "▲", "MIXED": "✗"}
_ANSI = {V.CONFIRMED: "32", V.CAVEATS: "33", V.REFUTED: "31",
         V.INVALIDATED: "31", V.FLAG_FOR_DECLARATION: "38;5;208", V.INCONCLUSIVE: "33", "MIXED": "31"}
_DET_GLOSS = {"controlled-to-bit": "bit-exact", "measured-band": "stable within tolerance",
              "uncontrolled": "not bit-reproducible"}


def _det(mode):
    g = _DET_GLOSS.get(mode)
    return ("%s (%s)" % (mode, g)) if g else (mode or "?")


def _cross_engine_line(ce):
    """M3: the cross-engine line shown right under the verdict. Agreement, divergence, OR - the case
    that used to print NOTHING (read as a pass) - an explicit 'no independent kernel' note."""
    n = ce.get("n_checked") or 0
    ext = ce.get("external_available") or []
    ext_note = (" (host can also cross-check via %s)" % ", ".join(ext)) if ext else ""
    if n:
        if ce.get("any_divergence"):
            d = next((m for m in ce.get("metrics", []) if not m.get("agree")), {})
            return ("cross-engine: DIVERGENCE on %s - primary %s vs independent kernel %s "
                    "(implementation-dependent; reconcile the definition)%s"
                    % (d.get("metric"), fmt_value(d.get("primary"), d.get("metric")),
                       fmt_value(d.get("second"), d.get("metric")), ext_note))
        verb = "agrees" if n == 1 else "agree"
        unit = "metric" if n == 1 else "metrics"
        return ("cross-engine: %d %s %s with a second independent kernel%s" % (n, unit, verb, ext_note))
    # n_checked == 0: never read as a pass. Distinguish two cases so the line can't contradict itself:
    unc = ce.get("uncovered") or []
    if unc:
        # genuinely no second kernel for this metric family
        return ("cross-engine: no independent kernel for %s (covered: %s) - the single-engine result "
                "stands" % (", ".join(unc[:3]), ", ".join(ce.get("covered", []))))
    # the metric HAS a kernel but it didn't apply here (unsupported convention / binding) - say THAT,
    # not "no kernel for X" while X is in the covered list (the old self-contradiction).
    req = ce.get("requested") or []
    who = ", ".join(req[:3]) if req else "the recomputed metric"
    return ("cross-engine: the second kernel did not apply to %s (unsupported convention or binding) "
            "- the single-engine result stands" % who)


_DATA_AUTH_CEILING_SHORT = ("input-data authenticity (Calma recomputes the declared output, not whether "
                            "the upstream input data is authentic / untampered)")


def _short_nv_label(item):
    """The leading family label of a not-verified phrase, before its parenthetical hint
    ('data leakage (no train/test split...)' -> 'data leakage')."""
    return item.split(" (", 1)[0].strip()


def _not_verified_lines(nv, why=True):
    """Render the honest 'not verified' scope limit.

    why=True  (the durable report.txt, --why, and --json): the full enumerated family list plus the
              data-authenticity ceiling, as one wrapped block - the complete record.
    why=False (default terminal): a one-line summary (count + the first few family names + how to
              expand) plus the always-on ceiling, terse - so the verdict the user came for is never
              buried under a 14-item wall on every single run.

    The data-authenticity ceiling (K4) is surfaced in BOTH modes: it can never be resolved by
    declaring a block, so a clean CONFIRMED must never read as a provenance blessing."""
    if why:
        full = list(nv) + [_DATA_AUTH_CEILING]
        return [_wrap("not verified: " + "; ".join(full))] if full else []
    out = []
    if nv:
        labels = [_short_nv_label(x) for x in nv]
        head = ", ".join(labels[:3])
        more = ", +%d more" % (len(labels) - 3) if len(labels) > 3 else ""
        out.append(_wrap("not verified: %d deeper check%s not run (%s%s) - declare the relevant "
                         "block, or re-run with --why / --json for the full list"
                         % (len(nv), "" if len(nv) == 1 else "s", head, more)))
    out.append(_wrap("not attested: " + _DATA_AUTH_CEILING_SHORT))
    return out


def render(led, diff=None, color=False, why=True):
    rv = led.get("repo_verdict", V.INCONCLUSIVE)
    word, gloss = _TOPLINE.get(rv, _TOPLINE[V.INCONCLUSIVE])
    c0 = led["claims"][0] if led.get("claims") else {}
    # no-claim mode: a clean verdict with no claimed number is a REPRODUCTION check, and the
    # render says so instead of pretending a claim was diffed
    scope_repro = (rv in (V.CONFIRMED, V.CAVEATS) and c0
                   and c0.get("claimed_value") is None and c0.get("recomputed_value") is not None)
    if scope_repro:
        word += " (scope=reproduction)"
        gloss = "no claim was given - the result re-runs and the number recomputes"
    conf = c0.get("headline_confidence") or 0.0
    # headline: a ✓/✗/▲ symbol + (on a tty) one ANSI color, so the answer is unmistakable at a glance.
    label = "%s %s" % (_SYMBOL.get(rv, "·"), word)
    if color and rv in _ANSI:
        label = "\x1b[1;%sm%s\x1b[0m" % (_ANSI[rv], label)
    head = "%s  (confidence %d/100)" % (label, int(round(conf * 100))) if conf > 0 else label
    lines = ["%s  -  %s" % (head, gloss)]
    if scope_repro:
        lines.append("  recomputed %s = %s  (state a claim to check a number against it)"
                     % (c0.get("metric"), fmt_value(c0.get("recomputed_value"), c0.get("metric"))))
    # multi-metric contract: show EVERY metric's verdict, not just the headline - a per-row table so a
    # broken secondary metric is visible at a glance (claimed -> recomputed, aligned).
    claims = [c for c in led.get("claims", []) if c.get("metric")]
    if len(claims) > 1:
        w = max(len(str(c.get("metric"))) for c in claims)
        for c in claims:
            cv, rvv, mid = c.get("claimed_value"), c.get("recomputed_value"), c.get("metric")
            sym = _SYMBOL.get(c.get("verdict"), "·")
            if color and c.get("verdict") in _ANSI:
                sym = "\x1b[%sm%s\x1b[0m" % (_ANSI[c["verdict"]], sym)
            if cv is not None:
                cs, rs = fmt_pair(cv, rvv, mid)
                num = "claimed %s -> recomputed %s" % (cs, rs)
            else:
                num = "recomputed %s" % fmt_value(rvv, mid)
            lines.append("  %s %-*s  %s  [%s]" % (sym, w, mid, num, display(c.get("verdict"))))
    # M3: cross-engine agreement/divergence/empty, surfaced HERE (right under the verdict) instead of
    # appended after the whole report + the exit line, where a REFUTED's detail buried it.
    if led.get("cross_engine") is not None:
        lines.append("  " + _cross_engine_line(led["cross_engine"]))
    # line 2: the single most-limiting thing. On a REFUTED the numeric-collapse line below already
    # carries the metric-mismatch, so prefer a DIFFERENT blocker (e.g. baseline) over repeating it.
    limiter = None
    blockers = [f for f in led.get("findings", []) if f.get("severity") == "blocker"]
    majors = [f for f in led.get("findings", []) if f.get("severity") == "major"]
    minors = [f for f in led.get("findings", []) if f.get("severity") == "minor"]
    if rv in ("REFUTED", "MIXED", V.INVALIDATED, V.FLAG_FOR_DECLARATION):
        others = [f for f in blockers + majors if f.get("dimension") != "metric-mismatch"]
        if others:
            prefix = "also: " if rv not in (V.INVALIDATED, V.FLAG_FOR_DECLARATION) else ""
            limiter = prefix + (others[0].get("locator") or "")
    elif blockers:
        limiter = blockers[0].get("locator")
    elif rv == V.CAVEATS and minors:
        # CAVEATS driven by soft findings (leverage / capacity / near-dup / in-sample contamination):
        # surface the CAVEAT itself, never the clean-pass "matches the claim" reason (which contradicts
        # the verdict word and hides the material caveat).
        extra = " (+%d more caveat%s)" % (len(minors) - 1, "s" if len(minors) > 2 else "") if len(minors) > 1 else ""
        limiter = (minors[0].get("locator") or "") + extra
    elif rv == V.INCONCLUSIVE and (c0.get("reason") or majors):
        limiter = c0.get("reason") or majors[0].get("locator")
    elif diff and diff.get("metrics"):
        limiter = diff["metrics"][0].get("reason")
    if limiter:
        lines.append(_wrap("- " + _plain(limiter)))
    # the numeric collapse + reproduction for a break. With a multi-metric table above, the per-row
    # numbers are already shown - skip the single collapse (claims[0] may be a CONFIRMED row, which
    # would mislead) and just point reproduce at the first broken metric.
    if rv in V.CATCH_VERDICTS and led.get("claims"):
        broken = next((c for c in led["claims"]
                       if c.get("verdict") in (V.REFUTED, V.INVALIDATED, V.FLAG_FOR_DECLARATION)),
                      led["claims"][0])
        if len(claims) <= 1:
            c = led["claims"][0]
            if c.get("claimed_value") is not None and c.get("recomputed_value") is not None:
                mid = c.get("metric")
                # INVALIDATED and FLAG_FOR_DECLARATION both reproduce (claimed == recomputed) - annotate so
                # the identical pair doesn't read as a no-op; the point is the RESULT (invalid) or the
                # UNDECLARED STRUCTURE (flag), not the number.
                if c.get("verdict") == V.INVALIDATED:
                    note = "   (reproduces - the result, not the number, is invalid)"
                elif c.get("verdict") == V.FLAG_FOR_DECLARATION:
                    note = "   (reproduces - undeclared structure flagged; declare the block to resolve)"
                else:
                    note = ""
                cs, rs = fmt_pair(c["claimed_value"], c["recomputed_value"], mid)
                lines.append("  claimed %s  ->  recomputed %s%s" % (cs, rs, note))
        rep = broken.get("reproduction_or_reverify", {})
        if rep.get("command"):
            lines.append("  reproduce: " + rep["command"])
    # the fix line: an INCONCLUSIVE (or any not-clean outcome with a known unblock) names who-can-act
    if rv != V.CONFIRMED:
        fix = _fix_line(led, diff)
        fix_txt = _plain(fix) if fix else None
        if fix_txt and rv in (V.INCONCLUSIVE, V.CAVEATS, V.INVALIDATED, V.FLAG_FOR_DECLARATION):
            lines.append(_wrap("fix: " + fix_txt))
        # CAN'T-CONFIRM -> a structured demand: name what could not be verified + exactly what to provide
        if rv == V.INCONCLUSIVE:
            nd = needs_demand(led)
            if nd and nd.get("provide"):
                provide_txt = "; ".join(_plain(p) for p in nd["provide"])
                # de-dup: when the structured 'needs' restates the fix verbatim (e.g. both say "name your
                # script main.py/run.py..."), one line is enough - don't print the same sentence twice.
                if provide_txt and provide_txt != fix_txt:
                    lines.append(_wrap("needs (to verify %s): %s" % (nd["unverifiable"], provide_txt)))
    # scope one-liner (the honest 'what we checked')
    sc = led.get("scope", {})
    if sc:
        fams = sc.get("families", {})
        checked = [k for k, v in fams.items() if str(v).startswith("checked")]
        if rv == V.CONFIRMED:
            # clean pass: lead with the plain reassurance, not the families jargon.
            lines.append("  verified by re-execution (isolation: %s, determinism: %s)"
                         % (sc.get("isolation_tier", "?"), _det(sc.get("determinism_mode"))))
        else:
            # not-clean: scope on its own wrapped block, rather than one 240-char line that wraps
            # into a wall on any normal terminal.
            lines.append(_wrap("scope: %s | isolation: %s | determinism: %s"
                               % (", ".join(checked) or "-", sc.get("isolation_tier", "?"),
                                  _det(sc.get("determinism_mode")))))
        # the honest 'what we did NOT check' scope limit. Collapses to a one-line summary on the
        # terminal (why=False) so the verdict isn't buried under a 14-item wall on every run; the
        # durable report.txt + --why + --json keep the full enumerated list (why=True). The
        # data-authenticity ceiling is surfaced in both - a CONFIRMED is reproduction, not a
        # provenance blessing.
        lines.extend(_not_verified_lines(list(sc.get("not_verified", []) or []), why=why))
        if sc.get("binding_note"):
            lines.append(_wrap("checked: " + sc["binding_note"]))
    return "\n".join(lines)


fix_line = _fix_line  # public alias (agent/JSON consumers)


# --- CAN'T-CONFIRM -> a STRUCTURED demand -----------------------------------------------------------
# A gap that just says "can't confirm" is a dead end. needs_demand() turns it into leverage: exactly
# WHAT could not be verified and WHAT to provide to resolve it - the deliverable in diligence ("we
# couldn't verify X; here's what we need"), which shifts the burden of proof onto the producer and is
# useful even against an adversary. It reuses the ledger's own structured data (a driving finding's
# `reverify` block) and falls back to a reason->needs table for the guard-path INCONCLUSIVEs that carry
# no finding. source -> (what-could-not-be-verified, [concrete inputs to provide]):
_SOURCE_NEEDS = {
    "split":        ("train/test leakage", ["the train/test split (split.train + split.test, or split.file + split.column) so row / entity / temporal overlap can be checked"]),
    "rows":         ("train/test leakage", ["the row id / time / target keys (keys.id, keys.time, keys.target) so overlap can be checked"]),
    "corpus":       ("eval/benchmark contamination", ["the known / pretraining corpus manifest (corpus.manifest) to check eval-in-corpus overlap"]),
    "windows":      ("regime / walk-forward robustness", ["out-of-sample / walk-forward windows (a windows block), or scope the claim to the regime the edge actually holds in"]),
    "frictions":    ("execution realism", ["the execution frictions (fee_bps, slippage_bps, turnover, ADV) for a net-of-cost claim"]),
    "trials":       ("overfitting / multiple-testing", ["the number of configurations searched (trials:N) or the grid-search / sweep log, so the deflated Sharpe / PBO can run"]),
    "returns":      ("statistical plausibility", ["the periodicity and annualization convention, and an out-of-sample (walk-forward) re-run"]),
    "baseline":     ("baseline comparison", ["a baseline series to compare the edge against"]),
    "universe":     ("survivorship / point-in-time", ["the point-in-time universe membership (universe.point_in_time), including delisted names"]),
    "availability": ("look-ahead", ["the per-row availability dates (an availability block) so availability <= effective can be checked"]),
    "study":        ("study-wide multiple-testing", ["the study size (study: trials, periods) for the multiple-testing / HLZ haircut"]),
}
# reason-needle -> (what-could-not-be-verified, [concrete inputs]). Mirrors the _FIXES needles so a
# guard-path INCONCLUSIVE (no finding) still emits a precise, structured demand.
_REASON_NEEDS = [
    ("exited non-zero", "reproduction", ["an entrypoint that runs to completion (exit 0) so the result re-executes"]),
    ("outputs differ across identical re-runs", "determinism", ["a deterministic run: a fixed seed (np.random.seed(42) / torch.manual_seed(42) / random.seed(42), or R set.seed(42)) plus deterministic output writes, so the result is stable across re-runs"]),
    ("determinism is uncontrolled", "determinism", ["a fixed seed (np.random.seed(42) / torch.manual_seed(42)) and deterministic output writes, or a calibration run, so the band is controlled"]),
    ("determinism is measured-band", "determinism", ["a fixed seed (np.random.seed(42) / torch.manual_seed(42)) or a calibration run, so the determinism band is controlled"]),
    ("no recomputed numeric", "the headline number", ["the result's raw numbers in a machine-readable file (e.g. predictions.csv with y_true,y_pred), or state the metric and number you computed"]),
    ("untrusted code", "isolation", ["a verified container / microVM tier (--isolation docker|e2b), or set trust: own-code if you wrote the code"]),
    ("killed or isolation was refused", "execution budget", ["a larger budget (--timeout SECONDS), or a live isolation tier (check `run_hermetic.py doctor`)"]),
    ("degenerate recompute", "data-cleaning policy", ["an na_policy for the NaN/Inf cells in the output file"]),
    ("claim target is unconfirmed", "the metric", ["the metric in the claim (e.g. \"accuracy 0.99\") or pass --metric <id>"]),
    ("not statistically distinguishable", "statistical resolution", ["a finer-grained claim or more data - the gap is within the claim's own noise"]),
    ("declare the scope", "validity scope", ["the scope the claim asserts (e.g. the held-out split / window) so the validity concern can be adjudicated as claimed"]),
]
_NEEDS_UNTIL = "stays CAN'T-CONFIRM (INCONCLUSIVE) until the above is provided"


def needs_demand(led):
    """Structured 'what to provide to resolve a CAN'T-CONFIRM', for --json consumers (agents). Returns
    None unless the outcome is INCONCLUSIVE - a WRONG number (REFUTED/INVALIDATED) needs a fix, not more
    inputs. Shape: {unverifiable, reason, provide:[...], reverify:{...}|None, until_then}. Sources, in
    order: a DRIVING finding's reverify.source (precise), then a reason->needs table (guard paths), then
    the fix line as a single-item fallback."""
    claims = led.get("claims") or []
    if not claims:
        return None
    head = next((c for c in claims if c.get("headline")), claims[0])
    if led.get("repo_verdict") != V.INCONCLUSIVE and head.get("verdict") != V.INCONCLUSIVE:
        return None
    reason = head.get("reason") or ""
    # 1) a DRIVING finding (named by driving_dimension) carries a structured reverify hint we can map to
    #    concrete inputs. Keyed on driving_dimension - never an arbitrary finding-with-reverify, which
    #    could be an unrelated soft smell sitting next to a guard-path INCONCLUSIVE.
    drv = head.get("driving_dimension")
    finding = next((f for f in led.get("findings", []) if f.get("dimension") == drv), None) if drv else None
    if finding is not None and finding.get("reverify"):
        rev = finding["reverify"]
        unver, provide = _SOURCE_NEEDS.get(rev.get("source"),
                                           (finding.get("dimension") or "the claim", []))
        if not provide and finding.get("unblock"):
            provide = [finding["unblock"]]
        return {"unverifiable": unver, "reason": finding.get("locator") or reason,
                "provide": provide, "reverify": rev or None, "until_then": _NEEDS_UNTIL}
    # 2) a precise recompute / binding error (column not found, non-finite cell) beats the generic
    #    reason mapping - mirrors _fix_line's precedence so the demand names the real blocker.
    rce = next((c.get("recompute_error") for c in claims if c.get("recompute_error")), None)
    if rce:
        return {"unverifiable": "the metric binding", "reason": rce,
                "provide": ["bind the column the metric needs: pass --metric <id> or pin the binding "
                            "in verify.yaml (recompute error: %s)" % rce],
                "reverify": None, "until_then": _NEEDS_UNTIL}
    # 3) no driving finding (a guard-path INCONCLUSIVE): map the reason to a concrete demand
    for needle, unver, provide in _REASON_NEEDS:
        if needle in reason:
            return {"unverifiable": unver, "reason": reason, "provide": list(provide),
                    "reverify": None, "until_then": _NEEDS_UNTIL}
    # 4) fallback: still a CAN'T-CONFIRM - surface the fix line as the single demand
    fx = _fix_line(led)
    return {"unverifiable": "the claim", "reason": reason, "provide": [fx] if fx else [],
            "reverify": None, "until_then": _NEEDS_UNTIL}


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def svg_card(led, width=820):
    """A self-contained dark SVG share card for a broken result - the local, no-SaaS version of an OG
    image. REFUTED -> claimed vs a different recomputed (red). INVALIDATED -> the number reproduces
    (recomputed shown in white == claimed) but the result is invalid (red verdict). Deterministic."""
    rv = led.get("repo_verdict")
    if rv not in ("REFUTED", "MIXED", V.INVALIDATED):
        return None
    claims = led.get("claims") or [{}]
    c = next((x for x in claims if x.get("verdict") in (V.REFUTED, V.INVALIDATED)), claims[0])
    mid = c.get("metric")
    invalid = c.get("verdict") == V.INVALIDATED
    claimed = fmt_value(c.get("claimed_value"), mid)
    recomputed = fmt_value(c.get("recomputed_value"), mid)
    blockers = [f for f in led.get("findings", [])
                if f.get("severity") in ("blocker", "major")
                and (f.get("claim_id") == c.get("id") or f.get("claim_id") is None)] \
        or [f for f in led.get("findings", []) if f.get("severity") in ("blocker", "major")]
    why = _DIMENSION_GLOSS.get(blockers[0].get("dimension"), blockers[0].get("dimension")) \
        if blockers else "the number doesn't recompute"
    # INVALIDATED: the recomputed number IS the claim (it reproduces) - render it white, not red, and
    # label the row so the story reads "the number is real, the result is what's invalid".
    recomp_label = "RECOMPUTED — the number reproduces" if invalid else "RECOMPUTED — by re-running the code"
    recomp_fill = "#FAFAFA" if invalid else "#F87171"
    word = "INVALIDATED" if invalid else "REFUTED"
    sc = led.get("scope", {})
    h = 456
    return """<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">
  <rect width="%d" height="%d" rx="16" fill="#0A0A0B"/>
  <rect x="1" y="1" width="%d" height="%d" rx="15" fill="none" stroke="#26262B" stroke-width="2"/>
  <text x="48" y="64" font-family="ui-monospace,Menlo,monospace" font-size="15" fill="#71717A" letter-spacing="3">CALMA TEARDOWN — %s</text>
  <text x="48" y="120" font-family="ui-monospace,Menlo,monospace" font-size="17" fill="#A1A1AA">CLAIMED</text>
  <text x="48" y="172" font-family="ui-monospace,Menlo,monospace" font-size="44" font-weight="700" fill="#FAFAFA">%s</text>
  <text x="48" y="218" font-family="ui-monospace,Menlo,monospace" font-size="17" fill="#A1A1AA">%s</text>
  <text x="48" y="272" font-family="ui-monospace,Menlo,monospace" font-size="44" font-weight="700" fill="%s">%s</text>
  <rect x="48" y="300" width="%d" height="1" fill="#26262B"/>
  <text x="48" y="336" font-family="ui-monospace,Menlo,monospace" font-size="15" fill="#FCA5A5">%s — %s</text>
  <text x="48" y="376" font-family="ui-monospace,Menlo,monospace" font-size="13" fill="#71717A">verified by RE-EXECUTION, not opinion</text>
  <text x="48" y="400" font-family="ui-monospace,Menlo,monospace" font-size="13" fill="#71717A">isolation: %s · determinism: %s</text>
  <text x="48" y="430" font-family="ui-monospace,Menlo,monospace" font-size="13" fill="#4ADE80">$ calma verify · github.com/rikhinkavuru/calma</text>
</svg>
""" % (width, h, width, h, width, h, width - 2, h - 2,
       _esc(_plain(led.get("target", "result"))), _esc(claimed), _esc(recomp_label), recomp_fill, _esc(recomputed),
       width - 96, word, _esc(_plain(why)),
       _esc(sc.get("isolation_tier", "?")), _esc(_det(sc.get("determinism_mode"))))


_DIMENSION_GLOSS = {
    "metric-mismatch": "the number doesn't recompute",
    "baseline": "loses to the trivial baseline",
    "reproducibility": "doesn't re-run",
    "contract-grounding": "not enough structure to verify",
    "leakage": "the held-out set is contaminated",
    "overfitting": "the edge doesn't survive multiple-testing correction",
    "execution-realism": "the edge doesn't survive realistic frictions",
    "contamination": "the eval set is contaminated by the training corpus",
    "omitted-costs": "the headline is gross, sold as a net-of-cost return",
    "window": "the claimed period isn't the period actually tested",
    "survivorship": "the universe is survivors-only, not point-in-time",
    "look-ahead": "the signal used information that wasn't knowable in time",
    "data-snooping": "the edge doesn't survive study-wide multiple-testing (the HLZ haircut)",
    "regime": "the edge holds in one regime/window, not across the sample (walk-forward)",
    "model-leakage": "a transform saw the test set, or configs were selected on it",
    "distribution-shift": "train and test come from different distributions (won't generalize)",
}


def teardown_card(led, diff=None):
    """A copy-pasteable shareable card for a broken result. Two shapes, both led by the evidence:
    REFUTED/MIXED -> 'claimed X -> really Y'; INVALIDATED -> 'the number reproduces, X == X, BUT the
    result is invalid'. Returns None for a clean (or INCONCLUSIVE) result."""
    rv = led.get("repo_verdict")
    if rv not in ("REFUTED", "MIXED", V.INVALIDATED):
        return None
    # lead with the broken claim (a non-headline break can drive MIXED, so pick the broken one)
    claims = led.get("claims") or [{}]
    c = next((x for x in claims if x.get("verdict") in (V.REFUTED, V.INVALIDATED)), claims[0])
    mid = c.get("metric")
    invalid = c.get("verdict") == V.INVALIDATED
    lines = ["CALMA TEARDOWN  -  %s" % _plain(led.get("target", "result")), ""]
    if c.get("claimed_value") is not None and c.get("recomputed_value") is not None:
        lines.append("  CLAIMED:     %s" % fmt_value(c["claimed_value"], mid))
        if invalid:
            # the number reproduces - that is the point: it is real, the RESULT is what's invalid.
            lines.append("  RECOMPUTED:  %s   <- the number reproduces from the raw outputs"
                         % fmt_value(c["recomputed_value"], mid))
            lines.append("  VERDICT:     INVALIDATED   <- ...but the result is invalid (see below)")
        else:
            lines.append("  RECOMPUTED:  %s   <- re-ran the code, recomputed from raw outputs"
                         % fmt_value(c["recomputed_value"], mid))
        lines.append("")
    cid = c.get("id")
    blockers = [f for f in led.get("findings", []) if f.get("severity") in ("blocker", "major")]
    # for a per-claim break, lead with that claim's own blockers (the driving evidence)
    own = [f for f in blockers if f.get("claim_id") == cid] or blockers
    if own:
        lines.append("  why it's invalid:" if invalid else "  why it breaks:")
        for f in own[:4]:
            # the locators are self-describing (they lead with the dimension in prose), so the gloss
            # prefix only restated them - drop it and let the locator carry the line.
            lines.append("   - %s" % _plain(f.get("locator")))
        lines.append("")
        fix = next((f.get("unblock") for f in own if f.get("unblock")), None)
        if fix:
            lines.append("  fix:  %s" % _plain(fix))
    rep = c.get("reproduction_or_reverify", {})
    if rep.get("command"):
        lines.append("  reproduce:  %s" % rep["command"])
    sc = led.get("scope", {})
    lines.append("  verified by RE-EXECUTION, not opinion  -  isolation: %s | determinism: %s"
                 % (sc.get("isolation_tier", "?"), _det(sc.get("determinism_mode"))))
    return "\n".join(lines)


# ===========================================================================================
# WS2: the deliverable - a branded, self-contained HTML report (prints to a clean PDF) plus a
# one-command offline replay bundle that re-derives the verdict byte-for-byte. The report states
# the claim, the verdict, the measured gap, an EXPLICIT scope-of-verification ("verified X; did
# NOT assess Y"), the limits, the isolation/determinism stamps, and the content hashes. Nothing in
# here computes a verdict - it renders what the deterministic pipeline already decided.
# ===========================================================================================

# Calma palette: warm-black ink, cream paper, amber accent. Inline so the file is self-contained
# (no external assets) and prints cleanly from any browser (Cmd/Ctrl-P -> Save as PDF).
_HTML_CSS = """
:root { --ink:#0A0A0B; --ink2:#26262B; --mut:#71717A; --mut2:#A1A1AA; --paper:#FAFAF7;
        --line:#E4E1D8; --amber:#B8821B; --green:#2F7D43; --red:#B23A33; }
* { box-sizing:border-box; }
html { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
body { margin:0; background:var(--paper); color:var(--ink);
       font:15px/1.55 ui-sans-serif,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }
.page { max-width:760px; margin:0 auto; padding:48px 40px 64px; }
.mono { font-family:ui-monospace,Menlo,"SF Mono",Consolas,monospace; }
.brandrow { display:flex; justify-content:space-between; align-items:baseline;
            border-bottom:2px solid var(--ink); padding-bottom:10px; margin-bottom:4px; }
.brand { font-family:ui-monospace,Menlo,monospace; font-weight:700; letter-spacing:3px; font-size:15px; }
.brand .dot { color:var(--amber); }
.tag { font-family:ui-monospace,Menlo,monospace; font-size:11px; letter-spacing:2px; color:var(--mut); }
h1 { font-size:13px; letter-spacing:2px; text-transform:uppercase; color:var(--mut);
     margin:34px 0 8px; font-weight:600; }
.verdict { display:flex; align-items:center; gap:14px; margin:18px 0 6px; }
.vbadge { font-family:ui-monospace,Menlo,monospace; font-weight:700; font-size:22px;
          padding:8px 16px; border-radius:8px; border:2px solid; }
.v-CONFIRMED, .v-CONFIRMED-WITH-CAVEATS { color:var(--green); border-color:var(--green); background:#EAF3EC; }
.v-REFUTED, .v-MIXED, .v-INVALIDATED { color:var(--red); border-color:var(--red); background:#F6E9E8; }
.v-CANT-CONFIRM { color:var(--amber); border-color:var(--amber); background:#F6EFDD; }
.conf { font-family:ui-monospace,Menlo,monospace; color:var(--mut); font-size:14px; }
.gloss { color:var(--ink2); margin:2px 0 0; }
.claimbox { background:#fff; border:1px solid var(--line); border-radius:10px; padding:18px 20px;
            margin:14px 0; }
.gap { display:flex; gap:40px; flex-wrap:wrap; margin-top:6px; }
.gap .lab { font-size:11px; letter-spacing:1.5px; color:var(--mut); text-transform:uppercase; }
.gap .num { font-family:ui-monospace,Menlo,monospace; font-size:26px; font-weight:700; margin-top:3px; }
.gap .claimed .num { color:var(--ink); }
.gap .recomp .num { color:var(--red); }
.gap.clean .recomp .num { color:var(--green); }
table.kv { width:100%; border-collapse:collapse; margin:6px 0 4px; }
table.kv td { padding:7px 0; border-bottom:1px solid var(--line); vertical-align:top; font-size:14px; }
table.kv td.k { color:var(--mut); width:40%; }
table.kv td.v { font-family:ui-monospace,Menlo,monospace; word-break:break-all; }
ul.scope { margin:6px 0; padding-left:20px; }
ul.scope li { margin:4px 0; }
.did-not { color:var(--ink2); }
.note { background:#F6EFDD; border-left:3px solid var(--amber); padding:10px 14px; border-radius:0 6px 6px 0;
        margin:10px 0; font-size:14px; }
.foot { margin-top:36px; padding-top:14px; border-top:1px solid var(--line); color:var(--mut);
        font-size:12px; font-family:ui-monospace,Menlo,monospace; line-height:1.7; }
.hashes td.v { font-size:12px; color:var(--ink2); }
@media print { body { background:#fff; } .page { padding:0; max-width:none; }
               @page { margin:18mm 16mm; } a { color:inherit; text-decoration:none; } }
"""

# D8-02: the data-authenticity ceiling (K4), rendered on every verdict's "not verified" line — never just
# the footer. Calma re-executes + recomputes the declared output; it cannot attest the INPUTS are authentic.
_DATA_AUTH_CEILING = ("input-data authenticity — Calma re-executes and recomputes the declared output, but "
                      "cannot attest the input data/artifacts are authentic or untampered upstream "
                      "(chain-of-custody is the producer's)")

_LIMITS = ("Calma verifies a result by RE-EXECUTING it in the stated isolation tier and RECOMPUTING "
           "the headline number from the raw machine-readable outputs on deterministic kernels - every "
           "statistic and the verdict come from unit-tested scripts, never a model. A CONFIRMED is a "
           "reproduction-and-recompute result for the claimed metric under the stated scope; it is NOT "
           "an audit of economic soundness, data provenance, or anything listed under \"did NOT assess\" "
           "below.")


def _html_verdict_class(rv):
    return {V.CONFIRMED: "CONFIRMED", V.CAVEATS: "CONFIRMED-WITH-CAVEATS", V.REFUTED: "REFUTED",
            "MIXED": "MIXED", V.INVALIDATED: "INVALIDATED",
            V.INCONCLUSIVE: "CANT-CONFIRM"}.get(rv, "CANT-CONFIRM")


def _sha256_file(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _report_hashes(run_dir, bundle=None):
    """Content hashes for the report footer. Computed from the run-dir files; when a signed bundle
    is present its authoritative values (subject digest, policy contract hash, signing keyid,
    timeVerified) are preferred so the report's hashes match what a counterparty verifies."""
    h = {"ledger_sha256": _sha256_file(os.path.join(run_dir, "ledger.json")),
         "manifest_sha256": _sha256_file(os.path.join(run_dir, "manifest.json")),
         "contract_sha256": _sha256_file(os.path.join(run_dir, "verify.yaml")),
         "keyid": None, "time_verified": None}
    if bundle:
        stmt = bundle.get("statement", {}) or {}
        pred = stmt.get("predicate", {}) or {}
        pol = pred.get("policy", {}) or {}
        if pol.get("contract_sha256"):
            h["contract_sha256"] = pol["contract_sha256"]
        subj = (stmt.get("subject") or [{}])[0].get("digest", {}) or {}
        if subj.get("sha256"):
            h["manifest_sha256"] = subj["sha256"]
        sigs = (bundle.get("envelope", {}) or {}).get("signatures") or [{}]
        h["keyid"] = sigs[0].get("keyid")
        h["time_verified"] = pred.get("timeVerified")
    return h


def render_html(led, diff=None, bundle=None, run_dir=None):
    """A self-contained, branded HTML report for a verification run. Deterministic (the only time
    value is the bundle's timeVerified, which is itself fixed at signing). Prints to a clean PDF."""
    rv = led.get("repo_verdict", V.INCONCLUSIVE)
    word = display(rv)
    vclass = _html_verdict_class(rv)
    claims = [c for c in led.get("claims", []) if c.get("metric")]
    c0 = claims[0] if claims else (led.get("claims") or [{}])[0]
    conf = c0.get("headline_confidence") or 0.0
    sc = led.get("scope", {}) or {}
    target = _esc(led.get("target", "result"))
    gloss = _TOPLINE.get(rv, _TOPLINE[V.INCONCLUSIVE])[1]

    P = []
    P.append("<!doctype html><html lang=en><head><meta charset=utf-8>")
    P.append("<meta name=viewport content='width=device-width,initial-scale=1'>")
    P.append("<title>Calma verification - %s</title><style>%s</style></head><body><div class=page>" %
             (target, _HTML_CSS))
    P.append("<div class=brandrow><div class=brand>CALMA<span class=dot>.</span></div>"
             "<div class=tag>INDEPENDENT VERIFICATION REPORT</div></div>")
    P.append("<div class=tag style='margin-top:6px'>target: %s</div>" % target)

    # verdict
    P.append("<h1>Verdict</h1><div class=verdict><span class='vbadge v-%s'>%s</span>" % (vclass, _esc(word)))
    if conf > 0:
        P.append("<span class=conf>confidence %d / 100</span>" % int(round(conf * 100)))
    P.append("</div><p class=gloss>%s</p>" % _esc(gloss))

    # claim under test + measured gap
    mid = c0.get("metric")
    cv, rvv = c0.get("claimed_value"), c0.get("recomputed_value")
    P.append("<h1>Claim under test</h1><div class=claimbox>")
    if mid:
        P.append("<div class=mono style='font-size:15px'>metric: <b>%s</b></div>" % _esc(mid))
    clean = rv in (V.CONFIRMED, V.CAVEATS)
    if cv is not None:
        P.append("<div class='gap%s'>" % (" clean" if clean else ""))
        P.append("<div class=claimed><div class=lab>claimed</div><div class=num>%s</div></div>" %
                 _esc(fmt_value(cv, mid)))
        if rvv is not None:
            P.append("<div class=recomp><div class=lab>recomputed by re-execution</div>"
                     "<div class=num>%s</div></div>" % _esc(fmt_value(rvv, mid)))
        P.append("</div>")
    elif rvv is not None:
        P.append("<div class=mono>no claim given (reproduction mode) - recomputed %s = <b>%s</b></div>" %
                 (_esc(mid), _esc(fmt_value(rvv, mid))))
    P.append("</div>")

    # multi-metric table
    if len(claims) > 1:
        P.append("<table class=kv>")
        for c in claims:
            m = c.get("metric")
            cc, rc = c.get("claimed_value"), c.get("recomputed_value")
            num = ("claimed %s &rarr; recomputed %s" % (_esc(fmt_value(cc, m)), _esc(fmt_value(rc, m)))
                   if cc is not None else "recomputed %s" % _esc(fmt_value(rc, m)))
            P.append("<tr><td class=k>%s</td><td class=v>%s &nbsp;[%s]</td></tr>" %
                     (_esc(m), num, _esc(display(c.get("verdict")))))
        P.append("</table>")

    # why it breaks / limiter
    blockers = [f for f in led.get("findings", []) if f.get("severity") in ("blocker", "major")]
    if blockers:
        P.append("<h1>Findings</h1><table class=kv>")
        for f in blockers[:6]:
            P.append("<tr><td class=k>%s</td><td class=v>%s</td></tr>" %
                     (_esc(f.get("dimension", "")), _esc(f.get("locator", ""))))
            if f.get("unblock"):
                P.append("<tr><td class=k>&nbsp;&nbsp;fix</td><td class=v>%s</td></tr>" % _esc(f["unblock"]))
        P.append("</table>")
    fixln = _fix_line(led, diff)
    if rv in (V.INCONCLUSIVE, V.CAVEATS) and fixln:
        P.append("<div class=note><b>fix:</b> %s</div>" % _esc(fixln))

    # scope of verification - the explicit "verified X; did NOT assess Y"
    P.append("<h1>Scope of verification</h1>")
    fams = sc.get("families", {}) or {}
    checked = [k for k, v in fams.items() if str(v).startswith("checked")]
    P.append("<ul class=scope>")
    P.append("<li><b>Verified</b> by re-execution: reproduced the run and recomputed <span class=mono>%s</span>"
             " from raw outputs%s.</li>" %
             (_esc(mid or "the headline metric"),
              (" (" + _esc(", ".join(checked)) + ")") if checked else ""))
    if sc.get("binding_note"):
        P.append("<li><b>Bound</b>: %s</li>" % _esc(sc["binding_note"]))
    nv = sc.get("not_verified") or []
    if nv:
        P.append("<li class=did-not><b>Did NOT assess</b>: %s.</li>" % _esc("; ".join(nv)))
    P.append("</ul>")

    # isolation + determinism stamps
    P.append("<h1>Execution scope</h1><table class=kv>")
    P.append("<tr><td class=k>isolation tier</td><td class=v>%s</td></tr>" % _esc(sc.get("isolation_tier", "?")))
    P.append("<tr><td class=k>determinism</td><td class=v>%s</td></tr>" % _esc(_det(sc.get("determinism_mode"))))
    if sc.get("run_network"):
        P.append("<tr><td class=k>network</td><td class=v>%s</td></tr>" % _esc(sc.get("run_network")))
    if sc.get("determinism_recheck"):
        P.append("<tr><td class=k>determinism recheck</td><td class=v>%s</td></tr>" %
                 _esc(sc.get("determinism_recheck")))
    P.append("</table>")

    # limits
    P.append("<h1>Limits</h1><p class=gloss>%s</p>" % _esc(_LIMITS))

    # hashes
    if run_dir:
        h = _report_hashes(run_dir, bundle)
        P.append("<h1>Integrity</h1><table class='kv hashes'>")
        for lab, key in (("ledger sha256", "ledger_sha256"), ("manifest sha256", "manifest_sha256"),
                         ("contract sha256", "contract_sha256"), ("signing keyid", "keyid"),
                         ("time verified", "time_verified")):
            if h.get(key):
                P.append("<tr><td class=k>%s</td><td class=v>%s</td></tr>" % (lab, _esc(h[key])))
        P.append("</table>")
        if bundle:
            P.append("<p class=gloss style='font-size:13px'>This report is backed by a DSSE/in-toto "
                     "signed attestation (Ed25519, OpenSSH-verifiable) and a self-contained replay "
                     "bundle that re-derives the verdict offline, byte-for-byte.</p>")

    P.append("<div class=foot>verified by RE-EXECUTION, not opinion &middot; the verdict is computed "
             "by deterministic scripts, never a model<br>github.com/rikhinkavuru/calma &middot; "
             "calma %s</div>" % _esc((bundle or {}).get("statement", {}).get("predicate", {})
                                     .get("verifier", {}).get("version", "")))
    P.append("</div></body></html>")
    return "".join(P)


# files copied verbatim into a replay bundle so `attest verify` re-derives the verdict offline with
# zero installs (all pure stdlib). This is the dependency closure of attest.verify_bundle() - it MUST
# include every sibling module the copied ones import (tiers.py is imported by verdict.py for the
# single-source verified-tier gate; omit it and the bundled verdict.py raises ModuleNotFoundError).
_REPLAY_SCRIPTS = ["attest.py", "ledger.py", "verdict.py", "tiers.py", "ed25519.py", "sshsig.py", "rfc3161.py"]
# run artifacts the bundle carries so a counterparty can also RE-EXECUTE (optional, env-dependent).
_REPLAY_ARTIFACTS = ["attestation.bundle.json", "attestation.payload.json", "attestation.sig.sshsig",
                     "attestation.allowed_signers", "ledger.json", "manifest.json", "verify.yaml",
                     "recompute.json", "diff.json", "run.json", "VERIFY-THIS.txt", "report.html"]

_REPLAY_DRIVER = '''#!/usr/bin/env python3
"""Offline replay: re-derive the verdict byte-for-byte from the signed bundle and check the
signatures. No network, no calma install - pure stdlib. Exit 0 iff the verdict re-derives and the
signature verifies."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "calma"))
import attest  # noqa: E402
bundle = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "attestation.bundle.json")))
ok, checks = attest.verify_bundle(bundle)
print(attest.render_verify(bundle, ok, checks))
sys.exit(0 if ok else 1)
'''

_REPLAY_SH = '''#!/bin/sh
# One command, fully offline: re-derive the verdict byte-for-byte and verify the signatures.
set -e
cd "$(dirname "$0")"
python3 replay_verify.py
'''

_REPLAY_README = '''CALMA REPLAY BUNDLE
===================
This bundle re-derives the verification verdict OFFLINE, byte-for-byte, on a fresh machine.
Nothing here needs the network or a calma install (everything is pure Python stdlib).

ONE COMMAND (re-derive the verdict + check signatures):
    sh replay.sh
  -> exit 0 means: the embedded ledger re-derives to the same verdict (verdict.verdict() is re-run
     over the stored inputs) AND the DSSE + SSHSIG signatures verify against the signing key.

ZERO-INSTALL SIGNATURE CHECK (stock OpenSSH, no Python):
    see VERIFY-THIS.txt for the exact `ssh-keygen -Y verify` command.

WHAT IS HERE:
    replay.sh / replay_verify.py  - the offline re-derivation driver
    calma/                        - the pure-stdlib scripts it imports (verdict, ledger, attest, ...)
    attestation.bundle.json (+ sidecars) - the signed DSSE/in-toto attestation
    ledger.json / manifest.json / verify.yaml / recompute.json / diff.json / run.json - run artifacts
    report.html                   - the human-readable report (open in a browser; print to PDF)

The verdict is computed by deterministic scripts, never a model. Verified by RE-EXECUTION, not opinion.
'''


def write_replay_bundle(run_dir, scripts_dir, out_dir=None):
    """Assemble a self-contained, offline replay bundle under <run_dir>/replay (or out_dir). Copies
    the run artifacts + the pure-stdlib dependency closure of attest.verify_bundle() + a one-command
    driver. Returns the bundle dir path. Idempotent (rebuilds clean)."""
    run_dir = os.path.realpath(run_dir)
    out_dir = os.path.realpath(out_dir or os.path.join(run_dir, "replay"))
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(os.path.join(out_dir, "calma"))
    for name in _REPLAY_SCRIPTS:
        src = os.path.join(scripts_dir, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out_dir, "calma", name))
    for name in _REPLAY_ARTIFACTS:
        src = os.path.join(run_dir, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out_dir, name))
    with open(os.path.join(out_dir, "replay_verify.py"), "w") as fh:
        fh.write(_REPLAY_DRIVER)
    with open(os.path.join(out_dir, "replay.sh"), "w") as fh:
        fh.write(_REPLAY_SH)
    with open(os.path.join(out_dir, "README.txt"), "w") as fh:
        fh.write(_REPLAY_README)
    for f in ("replay.sh", "replay_verify.py"):
        try:
            os.chmod(os.path.join(out_dir, f), 0o755)
        except OSError:
            pass
    return out_dir


def to_pdf(html_path, pdf_path=None):
    """Best-effort HTML->PDF via a headless browser if one is present. Returns the pdf path on
    success, else None (the HTML always prints to PDF from any browser - that is the fallback)."""
    pdf_path = pdf_path or os.path.splitext(html_path)[0] + ".pdf"
    candidates = [
        shutil.which("wkhtmltopdf"),
        shutil.which("chromium"), shutil.which("chromium-browser"), shutil.which("google-chrome"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for bin_ in candidates:
        if not bin_ or not os.path.exists(bin_):
            continue
        try:
            if bin_.endswith("wkhtmltopdf"):
                cmd = [bin_, "-q", html_path, pdf_path]
            else:
                cmd = [bin_, "--headless", "--disable-gpu", "--no-sandbox",
                       "--print-to-pdf=" + pdf_path, "--print-to-pdf-no-header",
                       "file://" + os.path.realpath(html_path)]
            r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            if r.returncode == 0 and os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                return pdf_path
        except (OSError, subprocess.SubprocessError):
            continue
    return None
