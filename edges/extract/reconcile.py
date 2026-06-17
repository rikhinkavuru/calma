"""P1.4 -- Reconcile + render: join every engine verdict back to its source span, then render the
catch with its provenance (the CLARIESG-style "cell 14 says 0.94 -> recomputes to 0.71" citation),
in flag-only or hand-to-A4 modes.

The FinGround/CLARIESG payoff: "verify every number, automatically, with each catch tied to its
source." Each ClaimReport pairs an engine verdict to the exact cell / quote / page / bbox the number
was read from, so a human sees not just "REFUTED" but where the bad number lives.

AI proposes, determinism disposes:
- This module RENDERS the engine's verdicts; it never decides one. Every verdict word and every
  recomputed number is copied VERBATIM from engine.verify's --json output (via verify_graph). The
  only model-free step is a STRUCTURAL join (metric_id + nearest claimed value) so a span travels
  back to its verdict.
- mode='fix' only PACKAGES a typed RepairHandoff (run_dir + the ORIGINAL claimed value + the span).
  It never patches code and never re-verifies -- that is A4, which re-verifies from scratch and owns
  the resulting verdict.
- report.fmt_value is reused read-only (a PURE display formatter, NOT a decision module) so a catch
  reads exactly as the engine prints it; if report is unavailable we fall back to a tiny local
  formatter. The core decision modules are NEVER reached (the firewall forbids those); a label
  arrives only through engine.verify (a subprocess), reached via verify_graph in P1.3.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field

from edges.extract import to_contract as TC


# --- verdict labels as plain strings (we do NOT import the core to obtain them) ----------------
CONFIRMED = "CONFIRMED"
CAVEATS = "CONFIRMED-WITH-CAVEATS"
REFUTED = "REFUTED"
INVALIDATED = "INVALIDATED"
INCONCLUSIVE = "INCONCLUSIVE"
MIXED = "MIXED"                                  # repo-level rollup only, never a per-claim label
# the authoritative "the catch worked" per-claim outcomes (MIXED lives at the repo level)
CATCH_VERDICTS = (REFUTED, INVALIDATED)

# render order: catches first, then caveats, then can't-confirm, then clean
_RANK = {REFUTED: 0, INVALIDATED: 0, CAVEATS: 1, INCONCLUSIVE: 2, CONFIRMED: 3}


def _rank(verdict):
    return _RANK.get(verdict, 2)                 # unknown/CAN'T-CONFIRM -> the can't-confirm bucket


# --- the engine's OWN display formatter, read-only (pure formatter; not a decision module) ------
try:
    TC._scripts_on_path()
    from report import fmt_value as _report_fmt_value
except Exception:                                # pragma: no cover - report should always import
    _report_fmt_value = None


def _fmt(value, metric_id=None):
    """report.fmt_value when available (so a catch renders byte-identically to the engine's own
    output -- '147.0x (+14,698%)', '-31.6%'); a tiny local fallback otherwise. Display only."""
    if _report_fmt_value is not None:
        try:
            return _report_fmt_value(value, metric_id)
        except Exception:                        # pragma: no cover - defensive
            pass
    if value is None:
        return "?"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    v = float(value)
    if v != v:
        return "NaN"
    if v.is_integer():
        return "{:,.0f}".format(v)
    return "%.4g" % v


# --- typed outputs -----------------------------------------------------------------------------
@dataclass
class ClaimReport:
    metric_id: str
    verdict: str                          # CONFIRMED | CONFIRMED-WITH-CAVEATS | REFUTED |
                                          #  INVALIDATED | INCONCLUSIVE  (the engine's own label)
    claimed: float | None
    recomputed: float | None
    citation: str                         # CLARIESG-style cell/page citation
    span: dict                            # the source_span joined back from the ClaimGraph
    reason: str | None = None

    def to_json(self):
        return asdict(self)


@dataclass
class Report:
    target: str
    repo_verdict: str                     # the engine's top-level verdict (MIXED for a mixed bag)
    summary: str                          # "5 numbers checked, 3 confirmed, 1 refuted, 1 can't-confirm"
    claims: list = field(default_factory=list)   # list[ClaimReport], catches first
    fix: str | None = None                # the single most actionable fix (from --json 'fix')

    def to_json(self):
        return {"target": self.target, "repo_verdict": self.repo_verdict,
                "summary": self.summary, "fix": self.fix,
                "claims": [c.to_json() for c in self.claims]}


@dataclass
class RepairHandoff:                       # typed handoff to A4 (which may not exist yet)
    run_dir: str                           # the engine run dir holding the REFUTED ledger
    metric_id: str
    claimed_value: float | None            # the ORIGINAL claimed value (anti-test-hacking, A4 P4.3)
    span: dict                             # where the bad number was reported (for the diagnosis UI)

    def to_json(self):
        return asdict(self)


# --- the join: each engine verdict back to its ClaimGraph claim --------------------------------
def _join(graph, engine_metrics):
    """Pair each engine metric (--json metrics[] entry) back to its ClaimGraph claim by
    (metric_id == the claim's resolved measure) AND nearest claimed value, so the claim's source_span
    travels through to the report. resolve_metric_id / parse_claim are the ENGINE's own tables (read
    through to_contract), never a re-implementation. Returns [(engine_metric, claim_or_None)]."""
    DC = TC._dc()
    resolved = []                                 # (resolved_metric_id, claimed_value, claim)
    for c in (graph or {}).get("claims", []):
        mid = TC.resolve_metric_id(c.get("measure"), c.get("value_text"))
        cv, _ = DC.parse_claim(c.get("value_text") or "")
        resolved.append((mid, cv, c))
    used, pairs = set(), []
    for em in engine_metrics:
        emid = em.get("metric")
        eclaimed = em.get("claimed")
        best_i, best_d = None, None
        for i, (mid, cv, _c) in enumerate(resolved):
            if i in used or mid != emid:
                continue
            d = 0.0 if (eclaimed is None or cv is None) else abs(cv - eclaimed)
            if best_d is None or d < best_d:
                best_i, best_d = i, d
        if best_i is not None:
            used.add(best_i)
            pairs.append((em, resolved[best_i][2]))
        else:
            pairs.append((em, None))              # an engine metric with no matching claim (rare)
    return pairs


def _citation(metric_id, claimed, recomputed, span):
    """CLARIESG cell/row/page citation. The template is chosen from span.element_type + whether a page
    is set; the numbers come from the engine's own fmt_value so they read exactly as the engine does.
     - notebook code/output: 'cell 14 says 0.94 -> recomputes to 0.71 [notebook cell 14]'
     - PDF table/paragraph:  '[Doc p.3, Table 2, Row 5] claims 1.85 sharpe -> recomputes to 0.90'
     - fallback (data summary): 'row_count: claimed 1,000 -> recomputed 900'"""
    span = span or {}
    c, r = _fmt(claimed, metric_id), _fmt(recomputed, metric_id)
    et = span.get("element_type")
    sec = span.get("section")
    page = span.get("page")
    if et in ("code", "output") and sec:
        return "%s says %s -> recomputes to %s [notebook %s]" % (sec, c, r, sec)
    if page is not None:
        loc = ("p.%s, %s" % (page, sec)) if sec else ("p.%s" % page)
        return "[Doc %s] claims %s %s -> recomputes to %s" % (loc, c, metric_id, r)
    return "%s: claimed %s -> recomputed %s" % (metric_id, c, r)


def _summary(reports):
    n = len(reports)
    confirmed = sum(1 for x in reports if x.verdict in (CONFIRMED, CAVEATS))
    refuted = sum(1 for x in reports if x.verdict == REFUTED)
    invalidated = sum(1 for x in reports if x.verdict == INVALIDATED)
    cant = sum(1 for x in reports if x.verdict not in (CONFIRMED, CAVEATS, REFUTED, INVALIDATED))
    parts = ["%d confirmed" % confirmed, "%d refuted" % refuted]
    if invalidated:
        parts.append("%d invalidated" % invalidated)
    parts.append("%d can't-confirm" % cant)
    noun = "number" if n == 1 else "numbers"
    return "%d %s checked, %s" % (n, noun, ", ".join(parts))


def _target_from_run_dir(run_dir):
    """The engine run dir is '<target>/.calma/run'; recover <target> for the Report header."""
    if not run_dir:
        return ""
    marker = os.sep + ".calma" + os.sep
    if marker in run_dir:
        return run_dir.split(marker)[0]
    return os.path.dirname(os.path.dirname(run_dir))


def render(graph, engine_result, *, mode="flag"):
    """Build the Report. engine_result is verify_graph()'s dict (the engine --json + the run's
    ledger.json). Per joined claim -> a ClaimReport with a provenance citation, sorted catches-first.
    summary counts each bucket; fix is copied verbatim from the engine output.

    mode='flag' -> return Report (stop and surface the catches).
    mode='fix'  -> return (Report, [RepairHandoff ...]) for each REFUTED/INVALIDATED claim. The handoff
                   carries the run_dir + the ORIGINAL claimed value + the span. We do NOT call A4 here;
                   an A4 entrypoint (edges.repair.orchestrate, not built yet) will consume the handoffs
                   and re-verify everything anew -- it, not render, owns the repaired label."""
    eng = (engine_result or {}).get("engine") or {}
    engine_metrics = eng.get("metrics") or []
    repo_verdict = eng.get("verdict")
    run_dir = eng.get("run_dir")

    reports = []
    for em, claim in _join(graph, engine_metrics):
        span = (claim or {}).get("source_span") or {}
        reports.append(ClaimReport(
            metric_id=em.get("metric"),
            verdict=em.get("verdict"),
            claimed=em.get("claimed"),
            recomputed=em.get("recomputed"),
            citation=_citation(em.get("metric"), em.get("claimed"), em.get("recomputed"), span),
            span=span,
            reason=em.get("reason"),
        ))
    reports.sort(key=lambda cr: _rank(cr.verdict))   # stable -> ties keep engine/contract order

    report = Report(target=_target_from_run_dir(run_dir), repo_verdict=repo_verdict,
                    summary=_summary(reports), claims=reports, fix=eng.get("fix"))

    if mode == "fix":
        handoffs = [RepairHandoff(run_dir=run_dir, metric_id=cr.metric_id,
                                  claimed_value=cr.claimed, span=cr.span)
                    for cr in reports if cr.verdict in CATCH_VERDICTS]
        # forward hook only: A4 does not exist yet. render PACKAGES the handoff; it never re-verifies.
        try:                                          # pragma: no cover - A4 is not built in P1.4
            from edges.repair import orchestrate as _a4_hook   # noqa: F401
        except Exception:
            _a4_hook = None
        return report, handoffs
    return report


# --- the Report JSON Schema (what render(...).to_json() emits) ----------------------------------
REPORT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Report",
    "type": "object",
    "required": ["target", "repo_verdict", "summary", "claims"],
    "additionalProperties": False,
    "properties": {
        "target": {"type": "string"},
        "repo_verdict": {"enum": ["CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "INVALIDATED",
                                  "INCONCLUSIVE", "MIXED"]},
        "summary": {"type": "string"},
        "fix": {"type": ["string", "null"]},
        "claims": {"type": "array", "items": {
            "type": "object",
            "required": ["metric_id", "verdict", "claimed", "recomputed", "citation", "span"],
            "additionalProperties": False,
            "properties": {
                "metric_id": {"type": "string"},
                "verdict": {"enum": ["CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "INVALIDATED",
                                     "INCONCLUSIVE"]},
                "claimed": {"type": ["number", "null"]},
                "recomputed": {"type": ["number", "null"]},
                "citation": {"type": "string"},
                "reason": {"type": ["string", "null"]},
                "span": {"type": "object"},
            },
        }},
    },
}
