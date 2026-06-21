"""pr.render - a FindingsBundle finding -> GitHub comment Markdown. Every verdict WORD and every NUMBER
is COPIED from the engine (through the bundle); render adds only structure + a hidden idempotency
marker. No engine import (transport only). INVALIDATED reads distinctly from a plain REFUTED so the
validity layer is legible.
"""
CATCH = ("REFUTED", "INVALIDATED", "MIXED")
CANT_CONFIRM = ("INCONCLUSIVE", "CAN'T-CONFIRM")
FP_MARK = "<!-- calma:fp=%s -->"          # per-finding idempotency marker (B2 keys off this)
SUMMARY_MARK = "<!-- calma:summary -->"   # the single updatable summary comment


def _sanitize(s):
    """Neutralize control sequences in ENGINE/CONTRACT-derived display strings (reason / citation / a
    non-numeric claimed-recomputed / target / fix / metric_id) before they're interpolated into a
    GitHub-markdown comment. A contract-controlled binding column name can otherwise smuggle the
    idempotency marker `calma:fp=<hex>` - which `_fps_in` scans comment bodies for - to spoof the
    'already-posted' set and SUPPRESS a genuine inline finding, or inject `<!-- ... -->` / markdown into
    the bot's authoritative comment. (The merge GATE is a pure function of the verdict enums in
    check_conclusion, so this can never flip pass/fail; it protects review-UX + the idempotency machinery.)"""
    s = str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # defang HTML comments/markup
    # break the literal marker tokens so the fp / summary scanners can't read an injected one (&#61; / &#58;
    # render as = / : but no longer match calma:fp= / calma:summary in the raw comment body)
    return s.replace("calma:fp=", "calma:fp&#61;").replace("calma:summary", "calma&#58;summary")


def _num(x):
    if x is None:
        return "?"
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return _sanitize(str(x))
    return ("%g" % x)


def _claimed_recomputed(f):
    c, r = f.get("claimed"), f.get("recomputed")
    if c is None and r is None:
        return ""
    return " (claimed %s → recomputed %s)" % (_num(c), _num(r))


def is_catch(finding):
    return finding.get("verdict") in ("REFUTED", "INVALIDATED")


def inline_body(finding, isolation_tier=None):
    """One inline review comment. Verdict label + the CLARIESG citation (verbatim) + claimed→recomputed
    + the engine reason + the isolation stamp + a hidden fingerprint marker for idempotency."""
    v = finding.get("verdict")
    cite = _sanitize(finding.get("citation") or "")
    cr = _claimed_recomputed(finding)
    if v == "INVALIDATED":
        head = "**INVALIDATED** — reproduces, but not a valid result. %s%s" % (cite, cr)
    else:
        head = "**%s** — %s%s" % (v, cite, cr)
    bits = [head]
    if finding.get("reason"):
        bits.append("Reason: %s." % _sanitize(str(finding["reason"]).rstrip(".")))
    if isolation_tier:
        bits.append("Verified by re-execution under %s isolation." % isolation_tier)
    return "%s %s" % (" ".join(bits), FP_MARK % (finding.get("fingerprint") or ""))


def review_comments(bundle, only_fingerprints=None):
    """[{path, line, side, body, fingerprint}] for every CATCH finding with a resolvable line anchor.
    `only_fingerprints` (a set) restricts to NEW findings (incremental). Findings without a line are
    surfaced in the summary, not as a dangling inline comment."""
    out = []
    for t in bundle.get("targets", []):
        for f in t.get("findings", []):
            if not is_catch(f) or not f.get("file") or not f.get("line"):
                continue
            if only_fingerprints is not None and f.get("fingerprint") not in only_fingerprints:
                continue
            out.append({"path": f["file"], "line": int(f["line"]), "side": "RIGHT",
                        "body": inline_body(f, t.get("isolation_tier")), "fingerprint": f.get("fingerprint")})
    return out


def all_catch_fingerprints(bundle):
    return {f.get("fingerprint") for t in bundle.get("targets", []) for f in t.get("findings", [])
            if is_catch(f)}


def summary_body(bundle):
    """The single updatable summary comment: the per-target table, the most-actionable fix, the
    isolation/determinism stamps, and the hidden marker B2 finds+updates instead of re-posting."""
    lines = ["### Calma verification", "", "| target | verdict | catches |", "|---|---|---|"]
    fix = None
    for t in bundle.get("targets", []):
        nc = sum(1 for f in t.get("findings", []) if is_catch(f))
        lines.append("| `%s` | %s | %d |" % (_sanitize(t.get("target")), t.get("repo_verdict"), nc))
        if not fix and t.get("fix"):
            fix = t["fix"]
    if fix:
        lines += ["", "**Fix:** %s" % _sanitize(fix)]
    t0 = (bundle.get("targets") or [{}])[0]
    lines += ["", "_isolation: %s · determinism: %s · every number recomputed from raw outputs by the "
              "deterministic engine_" % (t0.get("isolation_tier"), t0.get("determinism_mode"))]
    return "\n".join(lines) + "\n\n" + SUMMARY_MARK


def check_conclusion(bundle):
    """A pure function of the engine verdicts: failure on any REFUTED/INVALIDATED/MIXED, neutral on any
    CAN'T-CONFIRM, else success."""
    vs = [t.get("repo_verdict") for t in bundle.get("targets", [])]
    if any(v in CATCH for v in vs):
        return "failure"
    if any(v in CANT_CONFIRM for v in vs):
        return "neutral"
    return "success"


def check_output(bundle):
    """The check-run output: title, summary (markdown), and <=50 annotations (PATCH to append more)."""
    n_catch = sum(1 for t in bundle.get("targets", []) for f in t.get("findings", []) if is_catch(f))
    title = ("Calma: %d catch%s" % (n_catch, "" if n_catch == 1 else "es")) if n_catch else "Calma: clean"
    annotations = []
    for t in bundle.get("targets", []):
        for f in t.get("findings", []):
            if not is_catch(f) or not f.get("file") or not f.get("line"):
                continue
            annotations.append({
                "path": f["file"], "start_line": int(f["line"]), "end_line": int(f["line"]),
                "annotation_level": "failure",
                "title": "%s %s" % (f.get("verdict"), _sanitize(f.get("metric_id") or "")),
                "message": _sanitize(f.get("citation") or "")
                + (" — " + _sanitize(f["reason"]) if f.get("reason") else "")})
    return {"title": title, "summary": summary_body(bundle), "annotations": annotations[:50]}
