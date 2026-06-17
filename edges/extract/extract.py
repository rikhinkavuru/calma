"""P1.2 — The claim-graph extractor (structured, bootstrap few-shot, complexity routing).

From an ArtifactBundle (P1.1) extract a typed ClaimGraph: every numeric claim + what it claims to
be + where it came from. The design bias is high RECALL -- the deterministic engine downstream is the
precision filter, so over-extraction costs at worst a CAN'T-CONFIRM, never a false verdict.

Architecture rule (AI proposes, determinism disposes):
- The LLM only PROPOSES claims and provenance. It never decides whether a number is correct.
- This module imports `draft_contract` for its pure metric-vocabulary/claim-parsing helpers
  (parse_claim, claim_precision) -- the same module P1.3 reuses. It NEVER imports the verdict core
  (verdict / ledger / compare / recompute), enforced by edges/tests/test_firewall.py.
- Provenance on each claim's source_span (page/bbox/element_type/section) is KNOWN deterministically
  from the span, so we overwrite whatever the model echoed back with the span's real values.
- `value` is re-derived from `value_text` via parse_claim whenever that yields a finite number, so the
  invariant `parse_claim(value_text)[0] == value` holds for every claim regardless of model drift.
  (Downstream P1.3 reads claimed_value from value_text, not from this field.)

Routing (FinGround complexity routing) keeps it cheap:
- simple   -> heuristic_claim, NO model call (pure parse_claim).
- moderate -> one HAIKU structured() call, conditioned on a bootstrap few-shot example.
- complex  -> same call plus retrieved related context (the cited cell/table text).
The bootstrap example is produced ONCE by the strong model and is computed lazily -- a bundle made
only of simple spans makes ZERO LLM requests.
"""
from __future__ import annotations

import os
import re
import sys

from edges.common import llm
from edges.extract import ingest


# --- read-only reuse of the engine's pure claim helpers (NOT the verdict core) -----------------
def _dc():
    """Import draft_contract from the calma scripts dir for read-only use of its pure helpers
    (parse_claim, claim_precision, CLAIM_METRIC_HINTS). This is the contract schema/heuristics
    module -- the firewall allowlist forbids verdict/ledger/compare/recompute, not draft_contract."""
    scripts = os.path.join(os.path.dirname(__file__), "..", "..",
                           ".claude", "skills", "calma", "scripts")
    scripts = os.path.abspath(scripts)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import draft_contract as DC
    return DC


# --- the per-claim JSON Schema (CLAIM_SCHEMA) and the ClaimGraph wrapper (GRAPH_SCHEMA) ---------
CLAIM_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Claim",
    "type": "object",
    "required": ["value", "value_text", "measure", "subject", "claimed_provenance",
                 "source_span", "confidence"],
    "additionalProperties": False,
    "properties": {
        "value": {"type": "number",
                  "description": "the numeric value as a float, sign- and scale-normalized (% as a "
                                 "fraction is left to P1.3 via claim_precision; here keep it as "
                                 "written numerically, e.g. 14698 for '+14,698%')"},
        "value_text": {"type": "string",
                       "description": "the literal as written, with sign/separators/unit: '0.94', "
                                      "'+14,698%', '$4.2M', '1.85'"},
        "measure": {"type": "string",
                    "description": "a metric phrase from the recognized vocabulary when possible: "
                                   "accuracy|auc|pr_auc|f1|macro_f1|recall@k|sharpe|total_return|"
                                   "rmse|mae|r2|row_count|column_sum|null_fraction|latency_p95|... ; "
                                   "'unknown' if no metric word is present"},
        "subject": {"type": "string",
                    "description": "what the number is about: 'held-out test set', 'BTC strategy', "
                                   "'cleaned dataset'; '' if unstated"},
        "outcome_unit": {"type": ["string", "null"],
                         "enum": ["%", "ratio", "ms", "s", "rows", "$", "count", "bps", None]},
        "claimed_provenance": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "file": {"type": ["string", "null"],
                         "description": "the data file the author says it was computed from, "
                                        "e.g. 'preds.csv'"},
                "column": {"type": ["string", "null"], "description": "the column, if named"},
                "cell": {"type": ["string", "null"],
                         "description": "the notebook cell, e.g. 'cell 14'"},
                "computation": {"type": ["string", "null"],
                                "description": "a code/function reference, e.g. "
                                               "'sklearn.metrics.roc_auc_score'"},
                "formula_hint": {"type": ["string", "null"],
                                 "description": "the formula the author implies, e.g. 'TP/(TP+FP)', "
                                                "'(end/start)-1'"},
            },
        },
        "source_span": {
            "type": "object",
            "required": ["quote", "element_type"],
            "additionalProperties": False,
            "properties": {
                "quote": {"type": "string",
                          "description": "the exact span text the number was read from"},
                "page": {"type": ["integer", "null"]},
                "bbox": {"oneOf": [{"type": "null"},
                                   {"type": "array", "items": {"type": "number"},
                                    "minItems": 4, "maxItems": 4}]},
                "element_type": {"enum": ["code", "output", "markdown", "paragraph", "table",
                                          "caption", "figure"]},
                "section": {"type": ["string", "null"],
                            "description": "'cell 14', 'Table 2', a heading"},
            },
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1,
                       "description": "the model's self-rated EXTRACTION confidence (not correctness "
                                      "of the number) -- drives the P1.5 router"},
    },
}

GRAPH_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "ClaimGraph",
    "type": "object",
    "required": ["claims"],
    "additionalProperties": False,
    "properties": {"claims": {"type": "array", "items": CLAIM_SCHEMA}},
}


# --- complexity routing (FinGround) ------------------------------------------------------------
_NUMS = re.compile(r"[-+]?\d[\d,]*\.?\d*%?")
_REFERS = re.compile(r"\b(see|table|figure|cell|above|below)\b", re.I)


def classify(span) -> str:
    """simple | moderate | complex. simple: one number on one line, no cross-reference
    ('rows=10000', 'accuracy = 0.94'). complex: refers to another cell/table ('see Table 2', 'as
    computed above') or has >3 numbers tangled in prose. Everything else moderate. Pure regex."""
    t = span.text or ""
    nums = _NUMS.findall(t)
    if _REFERS.search(t) or len(nums) > 3:
        return "complex"
    if len(nums) == 1 and t.count("\n") <= 1:
        return "simple"
    return "moderate"


# --- the no-LLM heuristic path (simple spans) --------------------------------------------------
def _normalized_value(value_text: str):
    """parse_claim(value_text)[0], or None when it has no parseable number. Keeps `value` and
    `value_text` mutually consistent (the engine re-parses value_text downstream, so this is the
    authoritative reading) -- 'determinism disposes' applied to the numeric field."""
    DC = _dc()
    try:
        val, _ = DC.parse_claim(value_text)
    except Exception:
        return None
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _literal(text: str) -> str | None:
    """The first number literal exactly as written in `text` (sign/separators/unit kept)."""
    m = re.search(r"[-+]?\$?\d[\d,]*\.?\d*%?", text or "")
    return m.group(0) if m else None


def _cell_of(span) -> str | None:
    sec = (span.provenance or {}).get("section")
    return sec if (sec and str(sec).lower().startswith("cell")) else None


def _file_of(span) -> str | None:
    """The data file a 'data' summary span describes (its name leads the summary text)."""
    if span.source_kind != "data":
        return None
    head = (span.text or "").split(":", 1)[0].strip()
    return head or None


def _source_span(span, quote: str | None = None) -> dict:
    """The deterministic source_span -- provenance copied verbatim from the span, never invented."""
    prov = span.provenance or {}
    return {"quote": (quote if quote is not None else (span.text or ""))[:2000],
            "page": prov.get("page"),
            "bbox": list(span.bbox) if span.bbox else None,
            "element_type": prov.get("element_type") or "paragraph",
            "section": prov.get("section")}


def heuristic_claim(span) -> dict | None:
    """The no-LLM path for `simple` spans. parse_claim(span.text) -> (value, hint); the literal and
    claim_precision from the text. measure = hint or 'unknown', confidence=0.55. None when there is
    no parseable number."""
    DC = _dc()
    value, hint = DC.parse_claim(span.text or "")
    if value is None:
        return None
    literal = _literal(span.text) or str(value)
    claim = {
        "value": float(value),
        "value_text": literal,
        "measure": hint or "unknown",
        "subject": "",
        "claimed_provenance": {"file": _file_of(span), "column": None, "cell": _cell_of(span),
                               "computation": None, "formula_hint": None},
        "source_span": _source_span(span),
        "confidence": 0.55,
    }
    norm = _normalized_value(claim["value_text"])
    if norm is not None:
        claim["value"] = norm
    return claim


# --- retrieval for complex (retrieve-then-reason) ----------------------------------------------
_CITE_CELL = re.compile(r"\bcell\s+(\d+)\b", re.I)
_CITE_TABLE = re.compile(r"\btable\s+(\w+)\b", re.I)
_CITE_FIG = re.compile(r"\bfigure\s+(\w+)\b", re.I)
_CITE_REL = re.compile(r"\b(above|below)\b", re.I)


def retrieve(bundle, span) -> str:
    """For a `complex` span that cites 'Table 2' / 'cell 14' / 'above', return the referenced span
    text(s) from the bundle so the LLM reasons over the operands too. Deterministic lookup."""
    spans = list(getattr(bundle, "spans", []))
    try:
        here = spans.index(span)
    except ValueError:
        here = next((i for i, s in enumerate(spans) if s is span), -1)
    t = span.text or ""
    out, seen = [], set()

    def add(s):
        if s is span:
            return
        key = id(s)
        if key in seen:
            return
        seen.add(key)
        out.append(s.text or "")

    for m in _CITE_CELL.finditer(t):
        want = "cell %s" % m.group(1)
        for s in spans:
            if (s.provenance or {}).get("section") == want:
                add(s)
    if _CITE_TABLE.search(t):
        for s in spans:
            if (s.provenance or {}).get("element_type") == "table":
                add(s)
    if _CITE_FIG.search(t):
        for s in spans:
            if (s.provenance or {}).get("element_type") in ("figure", "caption"):
                add(s)
    for m in _CITE_REL.finditer(t):
        if here >= 0:
            j = here - 1 if m.group(1).lower() == "above" else here + 1
            if 0 <= j < len(spans):
                add(spans[j])
    return "\n---\n".join(p for p in out if p.strip())


# --- the bootstrap few-shot (VLDB-TaDA) --------------------------------------------------------
_BOOTSTRAP_SYSTEM = (
    "You write ONE worked example for a numeric-claim extraction task. Given a sample fragment, show "
    "the fragment, then the exact JSON a correct extractor would emit for it ({claims:[...]} matching "
    "the Claim schema). Keep it short and faithful. Output the example as plain text -- fragment, then "
    "a fenced JSON block. Do not add commentary."
)


def _is_example_span(span) -> bool:
    et = (span.provenance or {}).get("element_type")
    return span.source_kind == "data" or et in ("table", "output")


def bootstrap_example(bundle, model=llm.SONNET) -> str:
    """VLDB-TaDA bootstrap few-shot: take the FIRST data/table/output span, ask the STRONG model to
    produce ONE fully-worked extraction as an in-context example, return it as a text block. The
    cheap model is then conditioned on this example over the remaining spans. Cached via record/
    replay. Returns '' when there is no eligible span (no model call)."""
    sample = next((s for s in getattr(bundle, "spans", []) if _is_example_span(s)), None)
    if sample is None:
        return ""
    prov = sample.provenance or {}
    user = ("Sample fragment (%s, %s):\n```\n%s\n```\nWrite the worked example." %
            (prov.get("element_type"), prov.get("section"), sample.text or ""))
    return llm.complete(user, model=model, system=_BOOTSTRAP_SYSTEM)


# --- the per-span extractor --------------------------------------------------------------------
_EXTRACT_SYSTEM = (
    "You extract NUMERIC CLAIMS from a fragment of a data-science artifact (a notebook cell, an "
    "output, a PDF block, or a dataset summary). A numeric claim is any reported number that asserts "
    "a result: a metric (accuracy, AUC, F1, Sharpe, total return, RMSE, p95 latency, ...), a count "
    "(\"10,000 rows\"), a total (\"$4.2M\"), a rate (\"3.1% null\"), or a comparison (\"2.3x "
    "faster\").\n\n"
    "Your ONLY job is to PROPOSE claims and their provenance. You do NOT decide whether a number is "
    "correct -- a separate deterministic engine will recompute every claim from the raw data and "
    "judge it. Therefore: favor RECALL. When unsure whether a number is a claim, EXTRACT it. "
    "Over-extraction is cheap (it becomes an inconclusive, never a wrong verdict); a missed claim is "
    "the only real error.\n\n"
    "For each claim emit:\n"
    "- value: the number as a float, value_text: the literal exactly as written (keep sign, "
    "separators, and unit: '0.94', '+14,698%', '$4.2M', '1.85').\n"
    "- measure: the best metric phrase from this vocabulary when one fits, else 'unknown':\n"
    "  accuracy, auc, pr_auc, average precision, f1, macro_f1, micro_f1, weighted_f1, precision, "
    "recall, recall@k, ndcg, mrr, exact_match, pass@k, top-k, log_loss, mcc, ece, brier, rmse, mae, "
    "r2, mape, sharpe, sortino, calmar, max_drawdown, total_return, volatility, var, cvar, row_count, "
    "column_sum, column_mean, column_median, distinct_count, duplicate_count, null_fraction, "
    "growth_rate, latency_p50, latency_p95, latency_p99, throughput, peak_memory, speedup_ratio, "
    "test_coverage, error_rate, p_value, correlation, npv, irr, cagr, churn_rate, margin_pct.\n"
    "- subject: what it is about ('held-out test set', 'BTC strategy'); '' if unstated.\n"
    "- outcome_unit: one of %, ratio, ms, s, rows, $, count, bps, or null.\n"
    "- claimed_provenance: how the AUTHOR says it was computed -- {file, column, cell, computation, "
    "formula_hint}. Fill only what the text actually supports; use null otherwise. NEVER guess a file "
    "or column that isn't named or strongly implied.\n"
    "- source_span: {quote = the exact text you read the number from, page, bbox, element_type, "
    "section}. Copy page/bbox/element_type/section from the PROVENANCE BLOCK given to you; do not "
    "invent them.\n"
    "- confidence: 0..1, your self-rated confidence that THIS extraction (value+measure+provenance) "
    "is a faithful reading of the text. Low when the measure is unclear or the number is ambiguous.\n\n"
    "Return EVERY numeric claim in the fragment. If there is no number, return an empty claims list. "
    "Emit ONLY by calling the `emit` tool with a ClaimGraph ({claims:[...]})."
)


def _provenance_block(span) -> str:
    prov = span.provenance or {}
    return ("PROVENANCE BLOCK (copy page/bbox/element_type/section verbatim into each claim's "
            "source_span):\n"
            "document: %s\n"
            "section: %s\n"
            "page: %s\n"
            "element_type: %s\n"
            "bbox: %s\n" % (
                # basename only -- the recorded request must not embed a checkout-specific abs path
                os.path.basename(str(prov.get("document") or "")),
                prov.get("section"), prov.get("page"),
                prov.get("element_type"), span.bbox))


def _user_template(span, *, example: str, related: str = "") -> str:
    msg = (
        "%s\n"
        "WORKED EXAMPLE (same task, for format only -- do not copy its numbers):\n"
        "%s\n\n"
        "FRAGMENT TEXT:\n"
        "```\n%s\n```\n"
        "Extract every numeric claim. Call `emit`." % (
            _provenance_block(span), example or "(none)", span.text or ""))
    if related:
        msg += ("\n\nRELATED CONTEXT (the cell/table/figure this fragment references -- use it to "
                "recover operands and the formula, but the CLAIM's source_span must still cite the "
                "FRAGMENT above, not this context):\n```\n%s\n```" % related)
    return msg


def _finalize(claim: dict, span) -> dict:
    """Dispose the model's proposal: force source_span provenance from the span, re-derive value."""
    quote = (claim.get("source_span") or {}).get("quote") or (span.text or "")
    claim["source_span"] = _source_span(span, quote=quote)
    norm = _normalized_value(claim.get("value_text", ""))
    if norm is not None:
        claim["value"] = norm
    return claim


def extract_span_llm(span, *, example: str, model=llm.HAIKU, related: str = "") -> list:
    """One structured() call over a single span, conditioned on `example`. Returns the span's claims
    (possibly several), each with deterministic provenance reattached."""
    user = _user_template(span, example=example, related=related)
    data = llm.structured(user, schema=GRAPH_SCHEMA, model=model,
                          system=_EXTRACT_SYSTEM, tool_name="emit")
    return [_finalize(c, span) for c in data.get("claims", [])]


# --- top-level ---------------------------------------------------------------------------------
def extract(bundle, *, model=llm.HAIKU) -> dict:
    """Top-level. For each span: simple -> heuristic_claim (no LLM); moderate -> one HAIKU call;
    complex -> the same call with retrieved related context. The bootstrap example is built lazily
    by the STRONG model the first time a span needs the LLM, so a pure-simple bundle makes zero LLM
    requests. Concatenate, validate against GRAPH_SCHEMA, return."""
    from jsonschema import validate

    example = None  # lazily filled on first LLM-routed span
    claims = []
    for sp in getattr(bundle, "spans", []):
        c = classify(sp)
        if c == "simple":
            hc = heuristic_claim(sp)
            if hc:
                claims.append(hc)
            continue
        if example is None:
            example = bootstrap_example(bundle, model=llm.SONNET) or ""
        related = retrieve(bundle, sp) if c == "complex" else ""
        claims += extract_span_llm(sp, example=example, model=model, related=related)

    # A numeric claim must carry a parseable number; drop anything whose value_text does not (an
    # empty/hallucinated fragment). Survivors satisfy parse_claim(value_text)[0] == value.
    claims = [c for c in claims if _normalized_value(c.get("value_text", "")) is not None]
    graph = {"claims": claims}
    validate(instance=graph, schema=GRAPH_SCHEMA)
    return graph
