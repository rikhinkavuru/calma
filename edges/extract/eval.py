"""P1.6 -- the EXTRACTION eval harness (precision/recall of EXTRACTION, not the verdict).

This measures whether the right claim+provenance gets EXTRACTED -- a different axis from whether a
number is CORRECT (that is the engine's job, frozen). evaluate() ingests each labeled artifact,
extracts (optionally conditioned on a candidate few-shot block), and greedily matches predictions to
gold by (measure, value-within-precision, source_span.section). The few-shot is the ONLY thing that
moves; the matcher and the gold are fixed, so a recall delta is attributable to the proposer alone.

Architecture rule (AI proposes, determinism disposes): this harness never touches the engine, the
verdict, calibration, or binding grades. It only scores the PROPOSER. It imports extract / ingest /
llm only -- never the verdict core (firewall).
"""
from __future__ import annotations

import json
import os

from edges.common import llm
from edges.extract import extract as EX, ingest

ARTIFACTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures",
                                         "artifacts"))


# --- the labeled (held-out) eval set -----------------------------------------------------------
def load_labeled(path):
    """Each line: {artifact: <name under edges/tests/fixtures/artifacts (or an abs path)>,
    gold_claims: [Claim...]}. Resolves the artifact to an absolute fixture path on `_path`."""
    rows = []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        art = rec["artifact"]
        rec["_path"] = art if os.path.isabs(art) else os.path.join(ARTIFACTS, art)
        rows.append(rec)
    return rows


# --- turn a candidate few-shot (list of worked examples) into the in-context block --------------
def fewshot_to_example(fewshot):
    """Serialize build_fewshot()'s list[{fragment, claims}] into the deterministic text block that
    P1.2's extract_span_llm consumes as its `example`. Pure string assembly -- no model call."""
    if not fewshot:
        return ""
    parts = ["WORKED EXAMPLES FROM PRIOR CORRECTIONS (same task; learn the pattern, do not copy "
             "numbers):"]
    for i, ex in enumerate(fewshot, 1):
        frag = (ex.get("fragment") or "").strip()
        claims = ex.get("claims") or []
        parts.append("Example %d -- fragment:\n```\n%s\n```\ncorrect extraction:\n```json\n%s\n```"
                     % (i, frag, json.dumps({"claims": claims}, sort_keys=True)))
    return "\n\n".join(parts)


# --- the EXTRACTION matcher (provenance-aware, value-tolerant; NOT a verdict) -------------------
def _parsed(value_text):
    v, _ = EX._dc().parse_claim(value_text or "")
    return v


def _measure(claim):
    return (claim.get("measure") or "").strip().lower()


def _section(claim):
    return (claim.get("source_span") or {}).get("section")


def match(gold, pred):
    """An EXTRACTION match: same measure (both 'unknown' counts as same) AND the same
    source_span.section AND value within claim_precision(gold.value_text). Provenance-aware and
    value-tolerant -- it asks 'did we extract the right number, with the right meaning, from the
    right place?', never 'is the number correct?'."""
    if _measure(gold) != _measure(pred):
        return False
    if _section(gold) != _section(pred):
        return False
    gv, pv = _parsed(gold.get("value_text")), _parsed(pred.get("value_text"))
    if gv is None or pv is None:
        return False
    prec = EX._dc().claim_precision(gold.get("value_text") or "") or 0.0
    return abs(gv - pv) <= max(prec, 1e-9)


# --- conditioned extraction (mirrors EX.extract, but seeds a candidate few-shot as the example) --
def _extract_conditioned(bundle, example):
    """EX.extract's loop, but the LLM-routed spans are conditioned on `example` when one is given
    (the candidate few-shot); otherwise the lazily-built bootstrap example is used (the baseline).
    Reuses EX.classify/heuristic_claim/retrieve/extract_span_llm -- no change to extract.py."""
    from jsonschema import validate
    claims, boot = [], None
    for sp in getattr(bundle, "spans", []):
        c = EX.classify(sp)
        if c == "simple":
            hc = EX.heuristic_claim(sp)
            if hc:
                claims.append(hc)
            continue
        if example:
            ex = example
        else:
            if boot is None:
                boot = EX.bootstrap_example(bundle, model=llm.SONNET) or ""
            ex = boot
        related = EX.retrieve(bundle, sp) if c == "complex" else ""
        claims += EX.extract_span_llm(sp, example=ex, model=llm.HAIKU, related=related)
    claims = [c for c in claims if EX._normalized_value(c.get("value_text", "")) is not None]
    graph = {"claims": claims}
    validate(instance=graph, schema=EX.GRAPH_SCHEMA)
    return graph


def _fn_kind(gold, preds):
    """Classify an unmatched gold (a false negative) for the by_type breakdown: a same-section number
    with a different measure -> wrong-measure; a same-measure number in a different section ->
    wrong-cell; otherwise the number was not proposed at all -> missed."""
    gv, gm, gsec = _parsed(gold.get("value_text")), _measure(gold), _section(gold)
    for p in preds:
        pv = _parsed(p.get("value_text"))
        if gv is None or pv is None or abs(gv - pv) > max(1e-6 * max(abs(gv), 1.0), 1e-9):
            continue
        if _section(p) == gsec and _measure(p) != gm:
            return "wrong-measure"
        if _measure(p) == gm and _section(p) != gsec:
            return "wrong-cell"
    return "missed"


def evaluate(labeled, *, fewshot):
    """Ingest -> extract (conditioned on `fewshot` if given) -> greedily match pred vs gold. Returns
    EXTRACTION precision/recall plus a by_type breakdown of the misses. fewshot=None uses the baseline
    (bootstrap) extraction; a list conditions on that candidate block."""
    example = fewshot_to_example(fewshot) if fewshot else None
    tp = fp = fn = 0
    by_type = {"missed": 0, "wrong-measure": 0, "wrong-cell": 0, "spurious": 0}
    for rec in labeled:
        bundle = ingest.ingest(rec.get("_path") or rec["artifact"])
        preds = list(_extract_conditioned(bundle, example)["claims"])
        used = set()
        for g in rec.get("gold_claims", []):
            hit = next((i for i, p in enumerate(preds) if i not in used and match(g, p)), None)
            if hit is not None:
                used.add(hit)
                tp += 1
            else:
                fn += 1
                by_type[_fn_kind(g, preds)] += 1
        for i, _p in enumerate(preds):
            if i not in used:
                fp += 1
                by_type["spurious"] += 1
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    return {"precision": precision, "recall": recall, "tp": tp, "fp": fp, "fn": fn,
            "by_type": by_type}
