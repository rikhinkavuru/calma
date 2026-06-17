"""P2.2 -- turn the engine's data-derived grade into a CONCRETE, column-specific counterexample for the
drafter. The data check (regrade_committed) already decided every grade; this module re-reads the bound
column's actual values, quantifies the SAME violation _grade used, finds the column that WOULD pass, and
renders the verbatim feedback sentence the model receives. It computes no grade and no verdict -- it reads
the ledger's data-derived grade and the real CSV values, both as data.

A2 imports draft_contract for its pure value samplers + _grade (read-only library; allowed). It never
imports verdict/ledger/compare/recompute/numeric."""
import csv
import math
import os
import sys

_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                        ".claude", "skills", "calma", "scripts"))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
import draft_contract as DC  # noqa: E402

GRADE_ORDER = ["author-asserted", "plausibly-bound", "independently-bound"]   # mirror DC._GRADE_ORDER

# the engine reasons (CONFIRMED-ish) that are NOT a thing to repair -- a true REFUTED is a SUCCESS
_RESOLVED_VERDICTS = ("CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "INVALIDATED")


def disagreements(contract, ledger, json_result):
    """Compare the LLM's IMPLIED binding intent against the engine's data-derived grade. A metric is a
    disagreement when its binding graded WEAKER than independently-bound AND it was either intended trusted
    (headline/claimed) OR its --json verdict is inconclusive for a binding reason. A true REFUTED on a
    clean binding is NOT a disagreement (it is a correct catch)."""
    out = []
    by_metric = {c.get("metric"): c for c in ledger.get("claims", [])}
    jmetrics = {m["metric"]: m for m in json_result.get("metrics", [])}
    for m in contract.get("metrics", []):
        mid = m["metric_id"]
        claim = by_metric.get(mid)
        if not claim:
            continue
        grade = claim.get("input_binding_status", "author-asserted")
        intended_trusted = bool(m.get("headline")) or (m.get("claimed_value") is not None)
        jm = jmetrics.get(mid)
        jverdict = (jm or {}).get("verdict", "")
        reason = (jm or {}).get("reason") or claim.get("reason")
        weak = grade != "independently-bound"
        binding_blocked = jverdict not in _RESOLVED_VERDICTS
        if weak and (intended_trusted or binding_blocked):
            for tag, col in (m.get("binding") or {}).items():
                out.append({"metric_id": mid, "artifact": m["artifact"], "tag": tag, "column": col,
                            "data_grade": grade, "intended_trusted": intended_trusted,
                            "json_verdict": jverdict, "reason": reason})
                break        # one representative weak binding per metric drives the re-draft
    return out


def _col_index(path, column):
    with open(path, newline="", encoding="utf-8", errors="ignore") as fh:
        header = next(csv.reader(fh), [])
    return (header.index(column) if column in header else None), header


def column_evidence(target, artifact, column, tag, *, limit=500):
    """Re-sample the bound column's real values and quantify the SPECIFIC violation against the SAME rule
    regrade_committed used. Returns {min,max,mean,frac_violating,n,distinct,examples,nonfinite,
    suggested_columns}. suggested_columns = OTHER columns in the same artifact whose values DO pass the
    tag's _grade check (the 'pick this instead' hint)."""
    path = os.path.join(target, artifact)
    idx, header = _col_index(path, column)
    vals = DC._sample_numeric(path, idx, limit) if idx is not None else []
    finite = [v for v in vals if isinstance(v, (int, float)) and v == v and v not in (math.inf, -math.inf)]
    n = len(vals)
    nonfinite = n - len(finite)
    mn = min(finite) if finite else float("nan")
    mx = max(finite) if finite else float("nan")
    mean = (math.fsum(finite) / len(finite)) if finite else float("nan")
    distinct = len({round(v, 9) for v in finite})

    frac = 0.0
    if tag in ("score", "prob"):
        frac = sum(1 for v in finite if v < -0.001 or v > 1.001) / max(1, len(finite))
    elif tag in ("return", "benchmark"):
        frac = sum(1 for v in finite if abs(v) >= 1) / max(1, len(finite))
    elif tag in ("label", "prediction"):
        frac = 1.0 if distinct > 20 else 0.0
    elif tag in ("duration", "before", "after", "rank", "hits"):
        frac = sum(1 for v in finite if v < 0) / max(1, len(finite))

    suggested = []
    for col in header:
        if col == column:
            continue
        cidx, _ = _col_index(path, col)
        cvals = DC._sample_numeric(path, cidx, limit) if cidx is not None else []
        if cvals and DC._grade(tag, cvals) == "independently-bound":
            suggested.append(col)

    return {"min": mn, "max": mx, "mean": mean, "frac_violating": frac, "n": n, "distinct": distinct,
            "nonfinite": nonfinite, "examples": [round(v, 4) for v in finite[:8]],
            "suggested_columns": suggested}


def build_counterexample(dis, evidence):
    """A Disagreement + its column_evidence -> a Counterexample dict, including the verbatim feedback
    sentence handed back to the model."""
    tag, col, mid = dis["tag"], dis["column"], dis["metric_id"]
    sg = evidence["suggested_columns"]
    sg_str = ", ".join(sg) if sg else None
    mn, mx, mean, frac = evidence["min"], evidence["max"], evidence["mean"], evidence["frac_violating"]
    ex = evidence["examples"]

    if evidence["nonfinite"] > 0 and tag not in ("query", "problem", "group", "outcome",
                                                 "left_key", "joined_key"):
        violation = "nonfinite"
        fb = ("column=%s bound to tag=%s contains NaN/Inf (%d of %d rows). The data check can't trust a "
              "non-finite column; fix na_policy or bind a clean column: %s."
              % (col, tag, evidence["nonfinite"], evidence["n"], sg_str or "(none found)"))
    elif tag in ("score", "prob"):
        violation = "out_of_unit_range"
        fb = ("you bound metric=%s tag=%s -> column=%s, but %.0f%% of %s values are outside [0,1] "
              "(min=%g, max=%g; e.g. %s) -- that is a logit/raw score, not a probability. Bind the column "
              "whose values lie in [0,1]: %s."
              % (mid, tag, col, 100 * frac, col, mn, mx, ex,
                 sg_str or "(none found; the values may need a sigmoid before this metric applies)"))
    elif tag in ("return", "benchmark"):
        violation = "return_too_large"
        fb = ("you bound metric=%s tag=%s -> column=%s, but %.0f%% of values have |value|>=1 (mean=%g; "
              "e.g. %s) -- these look like prices or percents, not per-period returns. Use a per-period "
              "return column (mostly |r|<1, roughly centered): %s."
              % (mid, tag, col, 100 * frac, mean, ex, sg_str or "(none found)"))
    elif tag in ("label", "prediction"):
        violation = "too_many_distinct"
        fb = ("you bound metric=%s tag=%s -> column=%s, but it has %d distinct values (a label/prediction "
              "should have <=20 or be 0/1). Either this is a continuous score (use a regression/probability "
              "metric) or bind the discrete label column: %s."
              % (mid, tag, col, evidence["distinct"], sg_str or "(none found)"))
    elif tag in ("duration", "before", "after", "rank", "hits"):
        violation = "negative_duration"
        fb = ("you bound metric=%s tag=%s -> column=%s, but its minimum is %g (durations/timings/counts "
              "are non-negative). Bind the non-negative column: %s."
              % (mid, tag, col, mn, sg_str or "(none found)"))
    elif not sg:
        violation = "unbindable"
        fb = ("no column in %s passes the %s check for metric=%s. If the metric truly applies, the repo "
              "may not emit the right artifact; otherwise drop this metric."
              % (dis["artifact"], tag, mid))
    else:
        violation = "ambiguous_tag"
        fb = ("the column=%s bound to tag=%s for metric=%s did not pass the role check (graded %s). "
              "Consider binding: %s." % (col, tag, mid, dis["data_grade"], sg_str))

    return {"metric_id": mid, "tag": tag, "bad_column": col, "artifact": dis["artifact"],
            "violation": violation,
            "stats": {"min": mn, "max": mx, "mean": mean, "frac_violating": frac,
                      "n": evidence["n"], "examples": ex},
            "suggested_columns": sg, "data_grade": dis["data_grade"], "feedback": fb}


def feedback_block(counterexamples):
    """Render all counterexamples into the single user message appended on the re-draft."""
    lines = []
    for i, ce in enumerate(counterexamples, 1):
        lines.append("%d. %s" % (i, ce["feedback"]))
    return "\n".join(lines)
