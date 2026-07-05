"""calma.spike.core.report — a plain-language verdict summary.

Per-claim verdicts (CONFIRMED/REFUTED/INVALIDATED/…) are precise but a wall of them buries the point. This
composes a short human explanation: what Calma did, what it caught (misreports, leakage, trivial baselines),
and the overall conclusion — the thing a person actually wants to read first. Deterministic (no model call, no
cost, always available); the UI leads with it and keeps the per-claim table below. Pure stdlib.

FCR surface: none — it only re-describes verdicts already decided; it never changes one.
"""
from __future__ import annotations

_PROBLEM = ("REFUTED", "INVALIDATED", "NON-DETERMINISTIC")


def _tally(records):
    c: dict[str, int] = {}
    for r in records or []:
        c[r.get("verdict")] = c.get(r.get("verdict"), 0) + 1
    return c


def summarize(records, run=None, leakage=None) -> dict:
    """Return {headline, conclusion, findings[], next_step} — a plain-language read of a verify result.

    `records`: per-claim verdict dicts. `run`: the run summary ({ran, entry, calls, ...}). `leakage`: the
    dataset-level contamination findings. All optional; the summary degrades gracefully."""
    c = _tally(records)
    n = len(records or [])
    confirmed = c.get("CONFIRMED", 0)
    refuted = c.get("REFUTED", 0)
    invalid = c.get("INVALIDATED", 0)
    nondet = c.get("NON-DETERMINISTIC", 0)
    inconclusive = c.get("INCONCLUSIVE", 0) + c.get("REPRODUCED-ONLY", 0)
    discovered = c.get("DISCOVERED", 0)
    problems = refuted + invalid + nondet

    findings: list[str] = []
    # what Calma did
    if run and run.get("ran"):
        det = (run.get("determinism") or {})
        detword = " (deterministic across re-runs)" if det.get("stable") or det.get("proven") else ""
        findings.append("Re-ran `%s` and independently recomputed %d of its computations%s."
                        % (run.get("entry", "the repo"), run.get("calls", 0), detword))
    elif run and run.get("entry"):
        fail = run.get("failure") or {}
        why = fail.get("hint") or run.get("error") or "it didn't execute"
        # an env-build / dependency failure is NOT an entrypoint problem — name the real cause so the user fixes
        # the right thing (relax pins / use conda / connect data), not the entrypoint.
        verb = ("Couldn't build the environment to run" if fail.get("kind") in ("env-build", "missing-dep")
                else "Could not re-run")
        findings.append("%s `%s` — %s." % (verb, run.get("entry"), why))

    # what it caught (most serious first)
    if refuted:
        findings.append("**%d number%s misreported** — the claim doesn't match Calma's independent recompute."
                        % (refuted, "" if refuted == 1 else "s"))
    for d in (leakage or []):
        for f in d.get("findings", []):
            if f.get("invalidating"):
                findings.append("**Data leakage** in `%s`: %s." % (d.get("dataset", "a split"), f.get("detail", "")))
    if invalid:
        findings.append("**%d number%s invalid** — reproducible, but the evaluation is contaminated or the score "
                        "is no better than a trivial baseline." % (invalid, "" if invalid == 1 else "s"))
    if nondet:
        findings.append("**%d number%s non-deterministic** — it changes from run to run, so it can't be trusted "
                        "as reported." % (nondet, "" if nondet == 1 else "s"))
    if confirmed:
        findings.append("%d number%s **confirmed** — independently recomputed and matched." % (
            confirmed, "" if confirmed == 1 else "s"))
    if inconclusive:
        findings.append("%d number%s couldn't be pinned to a specific computation (this repo reports many "
                        "numbers for the same metric) — scope one, or connect a predictions file, to verify it."
                        % (inconclusive, "" if inconclusive == 1 else "s"))
    if discovered and not (run and run.get("ran")):
        findings.append("%d number%s found but not re-run (no runnable entrypoint / data)." % (
            discovered, "" if discovered == 1 else "s"))

    # headline + conclusion
    if problems:
        headline = "⚠ Calma found %d problem%s in the reported numbers." % (problems, "" if problems == 1 else "s")
        conclusion = ("The reported results don't fully hold up: %s. Treat the flagged numbers as unreliable "
                      "until the underlying issue (a misreport, a contaminated split, or a trivial-baseline "
                      "score) is fixed." % _problem_phrase(refuted, invalid, nondet))
    elif confirmed:
        headline = "✓ %d number%s hold up." % (confirmed, "" if confirmed == 1 else "s")
        conclusion = ("Calma independently reproduced and recomputed the verified number%s and found no "
                      "misreport, leakage, or trivial-baseline problem." % ("" if confirmed == 1 else "s"))
    elif run and run.get("ran"):
        headline = "Calma reproduced the run but couldn't confirm specific numbers."
        conclusion = ("The code ran and reproduced deterministically, but its reported numbers couldn't each be "
                      "bound to one computation (or aren't recomputable as-is). No problem was detected — but "
                      "nothing was confirmed either. Connect a predictions file or scope a claim to get a verdict.")
    else:
        headline = "Calma found %d reported number%s but couldn't run the repo to verify them." % (
            n, "" if n == 1 else "s")
        conclusion = ("Give Calma a runnable entrypoint (and any data/deps), or commit a predictions file, so it "
                      "can recompute and check the numbers.")

    next_step = _next_step(problems, confirmed, inconclusive, run)
    return {"headline": headline, "conclusion": conclusion, "findings": findings, "next_step": next_step}


def _problem_phrase(refuted, invalid, nondet) -> str:
    bits = []
    if refuted:
        bits.append("%d misreported" % refuted)
    if invalid:
        bits.append("%d invalidated (leakage / trivial baseline)" % invalid)
    if nondet:
        bits.append("%d non-deterministic" % nondet)
    return ", ".join(bits)


def _next_step(problems, confirmed, inconclusive, run) -> str:
    if problems:
        return "Review the flagged numbers below — each explains exactly what's wrong."
    if inconclusive and not confirmed:
        return "Commit a predictions file (id, y_true, y_score) or scope a claim to a specific dataset/model to confirm it."
    if run and not run.get("ran"):
        return "Name the entrypoint (Advanced → Entrypoint) or commit predictions so Calma can verify."
    return ""
