"""P1.6 -- the adaptive loop: corrections -> active learning + a GUARDED few-shot promotion.

Make extraction RECALL climb with use while the VERDICT stays frozen. Every human correction is a
training signal appended to a JSONL corpus; build_fewshot() mines it into an in-context block;
grow_templates() generalizes seen formula_hints into reusable templates for route.precheck; and
refresh() adopts a new few-shot ONLY IF recall does not fall AND precision does not regress on the
held-out eval set (the engine's calibration discipline, applied to the proposer).

Architecture rule (AI proposes, determinism disposes): this loop changes ONLY the PROPOSER (the
few-shot / formula templates -> extraction recall). It never touches the engine, the verdict,
calibration, or binding grades. All timestamps are caller-supplied (ts_from_args) -- no wall-clock,
no randomness -- so the harness replays deterministically. It imports store / eval only; never the
verdict core (firewall).
"""
from __future__ import annotations

import json
import os

from edges.common import store
from edges.extract import eval as EV

_DATA = os.path.join(os.path.dirname(__file__), "data")
CORR = os.path.join(_DATA, "corrections.jsonl")            # created on first correction
FEWSHOT = os.path.join(_DATA, "fewshot.json")              # the adopted few-shot block (guarded)
TEMPLATES = os.path.join(_DATA, "formula_templates.json")  # the growing template library

# recall-first weighting: a missed claim is the only real extraction error (the engine catches the
# rest as a CAN'T-CONFIRM), so 'missed' outranks the provenance/measure fixes; 'spurious' last.
_TYPE_WEIGHT = {"missed": 3, "wrong-measure": 2, "wrong-cell": 1, "spurious": 0}
_VALID_TYPES = ("missed", "wrong-cell", "wrong-measure", "spurious")

CORRECTION_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Correction",
    "type": "object",
    "required": ["artifact_hash", "correction_type", "claim_before", "claim_after", "ts_from_args"],
    "additionalProperties": False,
    "properties": {
        "artifact_hash": {"type": "string"},
        "correction_type": {"enum": ["missed", "wrong-cell", "wrong-measure", "spurious"]},
        "claim_before": {"oneOf": [{"type": "null"}, {"type": "object"}]},
        "claim_after": {"oneOf": [{"type": "null"}, {"type": "object"}]},
        "ts_from_args": {"type": "integer"},
    },
}


# --- record a human correction -----------------------------------------------------------------
def record_correction(*, artifact_hash, claim_before, correction_type, claim_after, ts_from_args,
                      path=CORR):
    """Append one correction to the corpus. correction_type in {missed, wrong-cell, wrong-measure,
    spurious}: missed -> claim_before=None, claim_after=the claim that should have been produced;
    spurious -> claim_after=None; wrong-cell/wrong-measure -> both present (the fix). ts_from_args is
    caller-supplied -- NEVER time.time() here (determinism / replayability)."""
    if correction_type not in _VALID_TYPES:
        raise ValueError("unknown correction_type %r" % correction_type)
    store.append(path, {
        "artifact_hash": artifact_hash,
        "correction_type": correction_type,
        "claim_before": claim_before,
        "claim_after": claim_after,
        "ts_from_args": int(ts_from_args),
    })


# --- mine the corpus into an in-context few-shot block ------------------------------------------
def _correction_count_by_artifact(records):
    counts = {}
    for r in records:
        counts[r.get("artifact_hash")] = counts.get(r.get("artifact_hash"), 0) + 1
    return counts


def build_fewshot(*, k=6, path=CORR):
    """Mine the corpus for the most INFORMATIVE worked examples, ranked by (a) most-corrected
    artifact_hash, (b) correction_type weight (missed > wrong-measure > wrong-cell > spurious --
    recall-first), (c) recency (ts_from_args). Each example = {fragment, claims} where claims is the
    CORRECTED extraction (claim_after). 'spurious' corrections carry no positive claim, so they teach
    an empty extraction. Pure function of the corpus -- no model call."""
    records = list(store.iter_records(path))
    counts = _correction_count_by_artifact(records)
    usable = [r for r in records if r.get("claim_after") is not None
              or r.get("correction_type") == "spurious"]

    def rank(r):
        return (counts.get(r.get("artifact_hash"), 0),
                _TYPE_WEIGHT.get(r.get("correction_type"), 0),
                r.get("ts_from_args", 0))

    usable.sort(key=rank, reverse=True)
    examples = []
    for r in usable[:k]:
        after = r.get("claim_after")
        if after is not None:
            frag = (after.get("source_span") or {}).get("quote") or ""
            examples.append({"fragment": frag, "claims": [after]})
        else:                                              # spurious: the fragment yields no claim
            before = r.get("claim_before") or {}
            frag = (before.get("source_span") or {}).get("quote") or ""
            examples.append({"fragment": frag, "claims": []})
    return examples


# --- generalize formula_hints into reusable templates ------------------------------------------
def _normalize_formula(formula):
    """Collapse whitespace so 'TP/(TP+FP)' and 'TP / (TP + FP)' dedupe to one template."""
    return "".join((formula or "").split())


def _load_templates(path):
    if not os.path.exists(path):
        return []
    try:
        return json.load(open(path))
    except (ValueError, OSError):
        return []


def grow_templates(*, corr_path=CORR, templates_path=TEMPLATES):
    """Generalize distinct (measure -> formula_hint) pairs seen in corrections (claim_after) into the
    template library route.precheck/_eval_formula draws on (FinGround's reusable-template idea).
    Normalizes/dedupes, appends only NEW ones, returns the current template list. No model call."""
    existing = _load_templates(templates_path)
    seen = {(t.get("measure"), _normalize_formula(t.get("formula"))) for t in existing}
    for r in store.iter_records(corr_path):
        after = r.get("claim_after")
        if not after:
            continue
        formula = (after.get("claimed_provenance") or {}).get("formula_hint")
        if not formula:
            continue
        key = ((after.get("measure") or "").strip().lower(), _normalize_formula(formula))
        if key in seen:
            continue
        seen.add(key)
        existing.append({"measure": key[0], "formula": _normalize_formula(formula)})
    os.makedirs(os.path.dirname(templates_path), exist_ok=True)
    json.dump(existing, open(templates_path, "w"), indent=2)
    return existing


# --- the GUARDED promotion ---------------------------------------------------------------------
def _load_fewshot(path):
    if not os.path.exists(path):
        return []
    try:
        return json.load(open(path))
    except (ValueError, OSError):
        return []


def refresh(*, eval_path, ts_from_args, corr_path=CORR, fewshot_path=FEWSHOT,
            templates_path=TEMPLATES):
    """GUARDED promotion. Score the held-out eval set with the CURRENT adopted few-shot and with the
    candidate mined from the corpus; ADOPT the candidate (write fewshot_path) ONLY IF
    recall_candidate >= recall_current AND precision_candidate >= precision_current - EPS (EPS=0.0;
    precision must not regress). Always grow_templates(). Returns {adopted, before, after}. ts is
    caller-supplied for determinism (it is not consumed by the metrics, only stamped by callers)."""
    labeled = EV.load_labeled(eval_path)
    current = _load_fewshot(fewshot_path)
    before = EV.evaluate(labeled, fewshot=current or None)
    candidate = build_fewshot(path=corr_path)
    after = EV.evaluate(labeled, fewshot=candidate or None)
    EPS = 0.0
    adopt = (after["recall"] >= before["recall"]
             and after["precision"] >= before["precision"] - EPS)
    if adopt:
        os.makedirs(os.path.dirname(fewshot_path), exist_ok=True)
        json.dump(candidate, open(fewshot_path, "w"), indent=2)
    grow_templates(corr_path=corr_path, templates_path=templates_path)
    return {"adopted": adopt, "before": before, "after": after}
