"""P1.5 -- Cost control: the distilled router (Haiku->Sonnet->Opus) + a recompute pre-check.

Make extraction cheap at scale. A HAIKU pass handles the easy ~80%; only low-confidence / complex /
unresolved-measure claims escalate to SONNET, and only the still-hard ones to OPUS. A FinGround-style
formula-reconstruction PRE-CHECK triages obviously-fine claims (cheap, local, NO engine run) so the
full deterministic engine run is reserved for the suspicious ones. (FinGround distilled an 8B detector
to 91.4% F1 at ~1/15th cost -- same shape.)

Architecture rule (AI proposes, determinism disposes):
- Escalation changes WHICH MODEL extracts -- never the schema, the engine, the binding grade, or the
  verdict. A more expensive model still only PROPOSES claims.
- The local pre-check is TRIAGE, NEVER a verdict. likely_ok only affects prioritization; nothing shown
  to a user is decided here -- only by engine.verify (P1.3's verify_graph). The test enforces that the
  likely_ok set is a STRICT SUBSET of what the engine later CONFIRMs.
- _eval_formula uses a whitelisted arithmetic AST -- never eval() of model/author text.
- This module imports extract / to_contract / llm / store only; never the verdict core (firewall).
"""
from __future__ import annotations

import ast
import operator
import os
import re
from dataclasses import asdict, dataclass

from edges.common import llm, store
from edges.extract import extract as EX, to_contract as TC

CONF_THRESHOLD = 0.65                       # below -> escalate one tier
TOL = 1e-6                                   # relative +/- tolerance for the local pre-check (triage)


# --- per-run cost / coverage stats -------------------------------------------------------------
@dataclass
class RouteStats:
    claims: int = 0                          # spans seen (the routing unit; one classify() per span)
    heuristic: int = 0                       # resolved with NO LLM (simple spans)
    haiku: int = 0                           # spans that took the HAIKU first pass
    escalated_sonnet: int = 0                # claims re-extracted by SONNET
    escalated_opus: int = 0                  # claims re-extracted by OPUS
    likely_ok: int = 0                       # pre-check agreed (triage), NOT a verdict

    def coverage_no_escalation(self) -> float:
        base = max(self.claims, 1)
        return (self.heuristic + self.haiku) / base

    def to_json(self) -> dict:
        return asdict(self)


ROUTESTATS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "RouteStats",
    "type": "object",
    "required": ["claims", "heuristic", "haiku", "escalated_sonnet", "escalated_opus", "likely_ok"],
    "additionalProperties": False,
    "properties": {
        "claims": {"type": "integer", "minimum": 0},
        "heuristic": {"type": "integer", "minimum": 0},
        "haiku": {"type": "integer", "minimum": 0},
        "escalated_sonnet": {"type": "integer", "minimum": 0},
        "escalated_opus": {"type": "integer", "minimum": 0},
        "likely_ok": {"type": "integer", "minimum": 0},
    },
}


# --- the escalation re-extraction picker -------------------------------------------------------
def _pick_best(candidates, current):
    """From a re-extraction of the SAME span (`candidates`, a list of claims) choose the claim that
    best replaces `current`: prefer the same number (nearest value), then a RESOLVED measure, then the
    higher self-rated confidence. Keep `current` if the re-extraction returned nothing usable. The
    escalation only ever upgrades the PROPOSAL -- the engine still owns the verdict."""
    if not candidates:
        return current
    cur_v = current.get("value")

    def near(c):
        v = c.get("value")
        if isinstance(v, (int, float)) and isinstance(cur_v, (int, float)) \
                and not isinstance(v, bool) and not isinstance(cur_v, bool):
            return abs(v - cur_v) <= max(1e-9, 1e-6 * abs(cur_v))
        return False

    pool = [c for c in candidates if near(c)] or candidates

    def score(c):
        resolved = 1 if TC.resolve_metric_id(c.get("measure"), c.get("value_text")) is not None else 0
        return (resolved, c.get("confidence") or 0.0)

    return max(pool, key=score)


# --- the FinGround formula-reconstruction pre-check (triage only) ------------------------------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv}
_ASSIGN = re.compile(r"([A-Za-z_]\w*)\s*[=:]\s*([-+]?\d[\d,]*\.?\d*)")


def _to_num(tok):
    try:
        return float((tok or "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _eval_formula(formula_hint, operands):
    """Tiny SAFE evaluator for the handful of FinGround formula shapes ('TP/(TP+FP)', '(end/start)-1',
    'a/b', 'sum/n'): parse to an AST and walk it with a whitelist of +-*/ , unary +/-, parens, numeric
    constants, and named operands. NEVER eval() of arbitrary code. Returns None on anything
    unparseable / unsafe / with a missing operand / a divide-by-zero."""
    try:
        tree = ast.parse(formula_hint or "", mode="eval")
    except (SyntaxError, ValueError, TypeError):
        return None

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            a, b = ev(node.left), ev(node.right)
            if a is None or b is None:
                return None
            if isinstance(node.op, ast.Div) and b == 0:
                return None
            return _OPS[type(node.op)](a, b)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            v = ev(node.operand)
            return None if v is None else -v
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
            return ev(node.operand)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            return operands.get(node.id)
        return None                                   # any other node -> reject (unsafe/unsupported)

    try:
        out = ev(tree)
    except Exception:                                 # pragma: no cover - defensive
        return None
    return out if isinstance(out, (int, float)) and out == out else None


def _match_span(bundle, source_span):
    """Find the bundle Span this claim was read from (by section), so retrieve() can pull operands."""
    sec = (source_span or {}).get("section")
    for s in getattr(bundle, "spans", []):
        if (getattr(s, "provenance", None) or {}).get("section") == sec:
            return s
    return None


def _operands_for(claim, bundle):
    """Operand name->value from the cited span's text (and any cell/table it references via
    retrieve()). 'TP = 90', 'FP: 10', 'end = 132.5' style assignments only -- no code execution."""
    sp = claim.get("source_span") or {}
    texts = [sp.get("quote") or ""]
    span_obj = _match_span(bundle, sp) if bundle is not None else None
    if span_obj is not None:
        texts.append(getattr(span_obj, "text", "") or "")
        try:
            texts.append(EX.retrieve(bundle, span_obj))
        except Exception:                             # pragma: no cover - defensive
            pass
    operands = {}
    for t in texts:
        for name, num in _ASSIGN.findall(t or ""):
            if name not in operands:
                v = _to_num(num)
                if v is not None:
                    operands[name] = v
    return operands


def precheck(claim, bundle=None):
    """FinGround formula reconstruction -- CHEAP, NO ENGINE RUN, TRIAGE ONLY. When the claim names a
    formula_hint AND its operands are present in the same cell/table, recompute the formula locally and
    compare to claim.value within relative tolerance TOL. Returns True (likely_ok) on agreement, False
    on disagreement (worth a full engine run), None when the formula/operands are unavailable. NEVER a
    verdict -- it only affects ordering/priority; everything a user sees is engine-decided."""
    formula = (claim.get("claimed_provenance") or {}).get("formula_hint")
    if not formula:
        return None
    result = _eval_formula(formula, _operands_for(claim, bundle))
    if result is None:
        return None
    value = claim.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return abs(result - value) <= TOL * max(abs(value), 1.0)


# --- the router --------------------------------------------------------------------------------
def extract_routed(bundle):
    """classify -> simple: heuristic_claim (NO LLM). moderate/complex: HAIKU first; if a returned claim
    has confidence < CONF_THRESHOLD OR the span is complex OR its measure is unresolved -> re-extract
    that span with SONNET; if STILL (low confidence AND unresolved) -> OPUS. Tally each path. The
    pre-check tags likely_ok claims (triage only). Returns (graph, RouteStats)."""
    st = RouteStats()
    example = None                                     # built lazily by the strong model (P1.2)
    claims = []
    for sp in getattr(bundle, "spans", []):
        c = EX.classify(sp)
        st.claims += 1
        if c == "simple":
            hc = EX.heuristic_claim(sp)
            if hc:
                claims.append(hc)
                st.heuristic += 1
            continue
        if example is None:
            example = EX.bootstrap_example(bundle, model=llm.SONNET) or ""
        related = EX.retrieve(bundle, sp) if c == "complex" else ""
        got = EX.extract_span_llm(sp, example=example, model=llm.HAIKU, related=related)
        st.haiku += 1
        for cl in got:
            unresolved = TC.resolve_metric_id(cl.get("measure"), cl.get("value_text")) is None
            if cl.get("confidence", 0.0) < CONF_THRESHOLD or c == "complex" or unresolved:
                re2 = EX.extract_span_llm(sp, example=example, model=llm.SONNET, related=related)
                st.escalated_sonnet += 1
                cl = _pick_best(re2, cl)
                still = (cl.get("confidence", 0.0) < CONF_THRESHOLD and
                         TC.resolve_metric_id(cl.get("measure"), cl.get("value_text")) is None)
                if still:
                    re3 = EX.extract_span_llm(sp, example=example, model=llm.OPUS, related=related)
                    st.escalated_opus += 1
                    cl = _pick_best(re3, cl)
            if precheck(cl, bundle) is True:
                st.likely_ok += 1
            claims.append(cl)
    return {"claims": claims}, st


# --- adaptive hook: per-run cost/coverage breadcrumb -------------------------------------------
STATS_PATH = os.path.join(os.path.dirname(__file__), "data", "route_stats.jsonl")


def record_run(stats, *, ts_from_args=None, path=STATS_PATH):
    """Append one RouteStats record per run (store.append). The KPI watched over time:
    coverage_no_escalation (target >0.70) and the escalation mix -- the cheap path should carry more
    as P1.6's few-shot improves. ts is supplied by the caller (never time.time() here -- determinism).
    Returns the written record."""
    rec = stats.to_json()
    if ts_from_args is not None:
        rec["ts"] = int(ts_from_args)
    store.append(path, rec)
    return rec
