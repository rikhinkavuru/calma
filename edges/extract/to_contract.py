"""P1.3 — ClaimGraph -> Calma multi-metric verify.yaml (the format adapter), then verify.

Compile a P1.2 ClaimGraph into a COMMITTED Calma verify.yaml (one metrics[] entry per resolvable
claim), drop it at the target, and run the engine as a subprocess. The engine verifies every claim
in one fanned-out pass and -- crucially -- regrade_committed re-derives each binding_status from the
ACTUAL re-emitted data, so a mis-extracted binding can never manufacture a CONFIRMED (or a false
REFUTED). This adapter is PURE and deterministic: measure -> metric_id is the engine's OWN table, not
a model call.

Architecture rule (AI proposes, determinism disposes):
- The LLM's claimed binding is only a PROPOSAL. We write binding_status='author-asserted'; the engine
  upgrades or caps it from data. We never write a grade stronger than author-asserted.
- claimed_value is always DC.parse_claim(value_text) -- the literal the author wrote, never a guess.
- We import draft_contract / recipes (the contract-schema + recipe-manifest modules) read-only. We
  NEVER import the verdict core (verdict / ledger / compare / recompute / numeric) -- enforced by
  edges/tests/test_firewall.py. The verdict comes only from engine.verify (a subprocess).
"""
from __future__ import annotations

import json
import os
import re
import sys

from edges.common import engine


# --- read-only access to the engine's own mapping tables / recipe manifests -------------------
def _scripts_on_path():
    scripts = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                            ".claude", "skills", "calma", "scripts"))
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return scripts


def _dc():
    """draft_contract -- the contract schema/heuristics module (CLAIM_METRIC_HINTS, METRIC_BY_TAGS,
    TAG_PATTERNS, parse_claim, claim_precision, infer_convention, _infer_tag, validate_contract,
    draft). NOT the verdict core; the firewall allowlist forbids verdict/ledger/compare/recompute."""
    _scripts_on_path()
    import draft_contract as DC
    return DC


def _recipes():
    """The recipe registry, read-only -- for each metric's declared required_tags. Optional: returns
    None if the registry can't be imported (caller falls back to METRIC_BY_TAGS)."""
    _scripts_on_path()
    try:
        import recipes as RCP
        return RCP
    except Exception:
        return None


# --- measure -> metric_id (the engine's table, never a guess) ----------------------------------
def resolve_metric_id(measure, value_text):
    """measure -> metric_id. (1) the measure already IS a recipe id (kept). (2) the engine's claim
    parser / CLAIM_METRIC_HINTS over the measure + literal. (3) None when unresolved -- the caller
    drops the claim, so it surfaces as an honest abstention, never a guessed verdict."""
    DC = _dc()
    m = (measure or "").strip().lower()
    RCP = _recipes()
    if RCP is not None and m and RCP.get(m) is not None:    # (1) already a recipe id
        return m
    _v, hint = DC.parse_claim((measure or "") + " " + (value_text or ""))   # (2) hint via the parser
    if hint:
        return hint
    for phrase, mid in DC.CLAIM_METRIC_HINTS:
        if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(phrase), m):
            return mid
    return None                                            # (3) unresolved


def tag_for_column(col):
    """Tag a column EXACTLY as the engine would (DC._infer_tag / TAG_PATTERNS)."""
    return _dc()._infer_tag(col or "")


# --- required tags per metric (recipe manifest first, METRIC_BY_TAGS as a fallback) ------------
_GROUND_TRUTH_TAGS = {"label", "target", "reference"}


def _required_tags(mid):
    RCP = _recipes()
    if RCP is not None:
        fn = RCP.get(mid)
        if fn is not None:
            req = (getattr(fn, "manifest", {}) or {}).get("required_tags")
            if req:
                return list(req)
    DC = _dc()
    for tagset, m in DC.METRIC_BY_TAGS:                     # reverse the auto-pick table
        if m == mid:
            return list(tagset)
    return []


def _tag_index(art_columns):
    """tag -> first column carrying it (artifact order is deterministic)."""
    by_tag = {}
    for col, spec in (art_columns or {}).items():
        t = (spec or {}).get("tag")
        if t and t not in by_tag:
            by_tag[t] = col
    return by_tag


def _build_binding(required, art_columns, author_column):
    """{tag: column} for the metric. When the author NAMED a column, it drives the metric's primary
    (non-ground-truth) input and the remaining required tags fill from the artifact -- so a wrong
    author column rides through to regrade_committed, which caps its grade from the data."""
    by_tag = _tag_index(art_columns)
    binding = {}
    if author_column:
        primary = next((t for t in required if t not in _GROUND_TRUTH_TAGS),
                       (required[0] if required else None))
        if primary:
            binding[primary] = author_column
        for t in required:
            if t != primary and t in by_tag:
                binding[t] = by_tag[t]
    else:
        for t in required:
            if t in by_tag:
                binding[t] = by_tag[t]
    return binding


def _resolve_artifact(file_hint, artifacts, required, default_path):
    """Pick the contract artifact this claim binds against. (1) basename match on the author's named
    file. (2) the artifact that satisfies the most required tags. (3) the default (first) artifact."""
    if file_hint:
        base = os.path.basename(str(file_hint))
        for a in artifacts:
            if os.path.basename(a.get("path", "")) == base:
                return a
    if required:
        best, best_score = None, 0
        for a in artifacts:
            tags = {(s or {}).get("tag") for s in (a.get("columns") or {}).values()}
            score = sum(1 for t in required if t in tags)
            if score > best_score:
                best, best_score = a, score
        if best is not None:
            return best
    if default_path:
        for a in artifacts:
            if a.get("path") == default_path:
                return a
    return artifacts[0] if artifacts else None


def claim_to_metric(claim, default_artifact, artifacts):
    """One ClaimGraph Claim -> one committed contract metric dict (or None when it can't be bound).
    claimed_value/precision/convention all come from the engine's own helpers over the literal; the
    binding is a PROPOSAL graded later by regrade_committed. Annotates _claim/_span for P1.4."""
    DC = _dc()
    mid = resolve_metric_id(claim.get("measure"), claim.get("value_text"))
    if mid is None:                                        # unresolved -> drop (honest abstention)
        return None
    prov = claim.get("claimed_provenance") or {}
    required = _required_tags(mid)
    artifact = _resolve_artifact(prov.get("file"), artifacts, required, default_artifact)
    if artifact is None:                                   # nothing to bind against
        return None
    binding = _build_binding(required, artifact.get("columns") or {}, prov.get("column"))
    value_text = claim.get("value_text") or ""
    claimed_value, _ = DC.parse_claim(value_text)
    span = claim.get("source_span") or {}
    return {
        "metric_id": mid,
        "artifact": artifact.get("path"),
        "binding": binding,
        "convention": DC.infer_convention(value_text + " " + (claim.get("subject") or ""), mid),
        "claimed_value": claimed_value,
        "claimed_precision": DC.claim_precision(value_text),
        "headline": False,
        "binding_status": "author-asserted",               # regrade_committed UPGRADES from data
        "_claim": (span.get("quote") or "")[:200],
        "_span": span,
    }


_OPTIONAL_FAMILY_KEYS = ("split", "keys", "features", "trials", "trials_artifact",
                         "var_sr", "frictions", "corpus")

_NOTE = ("AUTO-GENERATED by edges/extract (A1). Committed contract: regrade_committed re-derives "
         "each binding_status from the re-emitted data; the engine owns every verdict.")


def to_contract(graph, target):
    """Compile the whole graph -> write <target>/verify.yaml (committed form), return its path. The
    artifacts base + entrypoint come from DC.draft(target) (engine-correct tags); we replace metrics
    with one entry per resolvable claim, mark exactly one headline, and validate before shipping."""
    DC = _dc()
    base = DC.draft(target)
    artifacts = []
    for a in base.get("artifacts", []):
        art = dict(a)
        art["re_emit"] = True                              # mirror assets/btc: re-emit raw artifacts
        artifacts.append(art)
    default_artifact = artifacts[0]["path"] if artifacts else None

    metrics, confidences = [], []
    for claim in graph.get("claims", []):
        m = claim_to_metric(claim, default_artifact, artifacts)
        if m is not None:
            metrics.append(m)
            confidences.append(claim.get("confidence") or 0.0)
    if metrics:                                            # exactly one headline = highest confidence
        top = max(range(len(metrics)), key=lambda i: confidences[i])
        metrics[top]["headline"] = True

    contract = {
        "_note": _NOTE,
        "run": base.get("run"),
        "env": base.get("env"),
        "artifacts": artifacts,
        "metrics": metrics,
        "baselines": base.get("baselines", []),
    }
    # validity-family keys travel ONLY when DC.draft detected them (we never synthesize them in A1)
    for k in _OPTIONAL_FAMILY_KEYS:
        if k in base:
            contract[k] = base[k]

    errs = DC.validate_contract(contract)
    if errs:
        raise ValueError("refusing to ship a malformed contract: %s" % errs)
    path = os.path.join(target, "verify.yaml")
    with open(path, "w") as fh:
        json.dump(contract, fh, indent=2)                  # JSON is valid YAML; load_contract reads JSON
    return path


def verify_graph(graph, target):
    """to_contract then engine.verify (subprocess). Returns {engine, ledger, graph}. No claim/metric
    is passed to engine.verify -- the committed multi-metric contract drives the fan-out itself."""
    to_contract(graph, target)
    res = engine.verify(target)
    return {"engine": res, "ledger": engine.read_ledger(res["run_dir"]), "graph": graph}
