"""calma.spike.discovery.claim_classifier — feature 4 (P1): best-effort LLM salience refinement.

Asks a small model to rate each already-discovered candidate by how likely it is the HEADLINE number a reader
would quote, and to label its kind (metric / hyperparam / dataset-stat / noise). It NEVER invents, alters, or
drops a claim, and it NEVER touches `metric`/`value`/`id` — it only re-weights the deterministic P0 salience
(discovery.salience) and annotates `claim_kind`. Gated + best-effort exactly like the planner: no
ANTHROPIC_API_KEY, no `anthropic` package, or any error → no-op, and the pure P0 ranking stands. Because it
touches no verdict input, its FCR surface is zero.
"""
from __future__ import annotations

import json
import os

# a cheap model is right here — this is a ranking/labeling pass, not the plan synthesis. Override with
# CALMA_CLAIM_MODEL (claude-sonnet-5 / claude-opus-4-8 for a stronger read).
_MODEL = os.environ.get("CALMA_CLAIM_MODEL", "claude-haiku-4-5").strip() or "claude-haiku-4-5"

_SYSTEM = (
    "You are the legibility step of a verification system. You are given numeric claims already extracted "
    "from a code repository. Rank each by how likely it is the HEADLINE result a reader would quote from the "
    "repo, and label its kind. You do NOT judge whether any number is correct, and you MUST NOT invent, "
    "remove, or change any claim or its value — score ONLY the ids you are given. Return every id exactly once."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "is_headline": {"type": "boolean"},
                    "salience": {"type": "number", "minimum": 0, "maximum": 1},
                    "kind": {"type": "string", "enum": ["metric", "hyperparam", "dataset-stat", "noise"]},
                },
                "required": ["id", "salience", "kind"],
            },
        }
    },
    "required": ["claims"],
}


def _call_model(context: str, model: str) -> str | None:
    """The gated, best-effort model call (isolated so tests can stub it). None on any failure."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except Exception:  # noqa: BLE001
        return None
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(  # type: ignore[call-overload]  # structured-output param (SDK stubs lag)
            model=model, max_tokens=4096, system=_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{"role": "user", "content": context}],
        )
        if resp.stop_reason == "max_tokens":
            return None
        return next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
    except Exception:  # noqa: BLE001 — auth/rate/network/parse → best-effort no-op
        return None


def _context(claims: list[dict], repo_dir: str | None) -> str:
    lines = ["Candidate claims (id | metric | value | source | location):"]
    for c in claims[:120]:
        lines.append("%s | %s | %s | %s | %s" % (c.get("id"), c.get("metric"), c.get("value"),
                                                 c.get("source"), (c.get("location") or "")[:70]))
    ctx = "\n".join(lines)
    if repo_dir:
        for fn in ("README.md", "readme.md", "README.rst", "README.txt"):
            p = os.path.join(repo_dir, fn)
            if os.path.isfile(p):
                try:
                    with open(p, errors="replace") as fh:
                        ctx += "\n\nREADME (head):\n" + fh.read(4000)
                except OSError:
                    pass
                break
    return ctx


def merge(claims: list[dict], repo_dir: str | None = None, model: str | None = None) -> list[dict]:
    """Refine `salience` in place with the model's headline-rating (mean of P0 and model score, so the model
    can nudge but not dominate), and set `claim_kind` + `is_metric_claim`. Best-effort: any failure leaves the
    claims exactly as P0 scored them. NEVER mutates metric/value/id."""
    if not claims:
        return claims
    raw = _call_model(_context(claims, repo_dir), model or _MODEL)
    if not raw:
        return claims
    try:
        data = json.loads(raw)
        rated = {r["id"]: r for r in data.get("claims", []) if isinstance(r, dict) and r.get("id")}
    except (ValueError, TypeError):
        return claims
    for c in claims:
        r = rated.get(c.get("id"))
        if not r:
            continue
        ms = r.get("salience")
        if isinstance(ms, (int, float)):
            ms = 0.0 if ms < 0 else 1.0 if ms > 1 else float(ms)
            c["salience"] = round(0.5 * c.get("salience", ms) + 0.5 * ms, 4)   # blend, never overwrite
        kind = r.get("kind")
        if kind:
            c["claim_kind"] = kind
            c["is_metric_claim"] = (kind == "metric")
    return claims
