"""pr.bundle - the FindingsBundle schema (the unprivileged half's machine-readable output) + the
span -> (file, line) GitHub-anchor resolution + a stable fingerprint for idempotency. Pure stdlib;
NO engine import (every verdict/number/citation is COPIED from the engine's --json, never computed).

FindingsBundle = {
  "schema": "calma/pr-findings@1",
  "pr_number": int, "head_sha": str, "base_sha": str,
  "targets": [ {
    "target": str, "kind": "artifact"|"contract",
    "repo_verdict": str,        # CONFIRMED|CONFIRMED-WITH-CAVEATS|REFUTED|INVALIDATED|INCONCLUSIVE|MIXED
    "summary": str,             # the engine/A1 summary line, verbatim
    "isolation_tier": str, "determinism_mode": str,
    "findings": [ {             # one per A1 ClaimReport / engine metric
      "metric_id": str, "verdict": str, "claimed": float|None, "recomputed": float|None,
      "citation": str,          # CLARIESG, verbatim
      "reason": str|None,
      "file": str|None, "line": int|None,   # the GitHub anchor, resolved from span + the changed file
      "fingerprint": str        # sha256(target|metric_id|file|line|verdict) for idempotency
    } ],
    "fix": str|None
  } ]
}
"""
import hashlib
import json
import os
import re

SCHEMA = "calma/pr-findings@1"
# the engine verdicts that are CATCHES (a failing check-run); copied verbatim, never recomputed here.
CATCH_VERDICTS = ("REFUTED", "INVALIDATED", "MIXED")
CANT_CONFIRM = ("INCONCLUSIVE", "CAN'T-CONFIRM")


def fingerprint(target, metric_id, file, line, verdict):
    """Stable across re-runs on the same head (the engine is deterministic) -> idempotent comments."""
    key = "%s|%s|%s|%s|%s" % (target, metric_id, file, line, verdict)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _notebook_cell_line(repo, nb_relpath, section):
    """Best-effort: section like 'cell 14' -> the 1-based line in the .ipynb file where that code
    cell's source begins (parse nbformat, locate the cell's first non-empty source line in the raw
    file text). None when unresolvable - B2 then renders it file-level, never guesses a line."""
    m = re.search(r"cell\s*(\d+)", str(section or ""), re.I)
    if not m:
        return None
    idx = int(m.group(1))
    path = os.path.join(repo, nb_relpath)
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
        nb = json.loads(raw)
    except (OSError, ValueError):
        return None
    code = [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]
    cells = code if 0 <= idx < len(code) else nb.get("cells", [])
    if not (0 <= idx < len(cells)):
        return None
    src = cells[idx].get("source") or []
    if isinstance(src, str):
        src = [src]
    first = next((s for s in src if s.strip()), None)
    if not first:
        return None
    pos = raw.find(first.strip()[:60])  # the source text appears (mostly verbatim) in the JSON
    return raw[:pos].count("\n") + 1 if pos >= 0 else None


def _contract_metric_line(repo, target, metric_id):
    """For a contract target, anchor to the line in verify.yaml that mentions the metric (best-effort).
    Returns (file_relpath, line|None) or (None, None) when there is no verify.yaml."""
    rel = os.path.join(target, "verify.yaml")
    path = os.path.join(repo, rel)
    if not os.path.isfile(path):
        return None, None
    try:
        for i, ln in enumerate(open(path, encoding="utf-8", errors="replace"), start=1):
            if metric_id and metric_id in ln:
                return rel, i
    except OSError:
        return rel, None
    return rel, None


def resolve_anchor(claim, target, kind, changed_files, repo="."):
    """Map a ClaimReport.span back to a (file, line) anchor in a CHANGED file. Prefers the notebook
    cell offset for an artifact target; the verify.yaml metric line for a contract target. (file, line);
    either may be None (B2 renders an unresolved line as a file-level / summary finding)."""
    span = claim.get("span") or {}
    section = span.get("section") or span.get("element") or ""
    # an artifact (notebook/pdf) target: anchor to the changed .ipynb cell
    if kind == "artifact":
        nb = next((c for c in changed_files if c.lower().endswith(".ipynb")), None)
        if nb:
            return nb, _notebook_cell_line(repo, nb, section)
        other = next((c for c in changed_files if c.lower().endswith((".pdf", ".csv"))), None)
        return (other, None) if other else (None, None)
    # a contract target: anchor to verify.yaml's metric line, else the changed data file
    f, line = _contract_metric_line(repo, target, claim.get("metric_id"))
    if f:
        return f, line
    data = next((c for c in changed_files if c.lower().endswith((".csv", ".tsv", ".parquet"))), None)
    return (data, None) if data else (None, None)


def finding_from_claim(claim, target, kind, changed_files, repo="."):
    """One bundle finding from one engine/A1 claim. Every verdict/number/citation copied verbatim."""
    verdict = claim.get("verdict")
    metric_id = claim.get("metric_id")
    file, line = resolve_anchor(claim, target, kind, changed_files, repo)
    return {"metric_id": metric_id, "verdict": verdict,
            "claimed": claim.get("claimed"), "recomputed": claim.get("recomputed"),
            "citation": claim.get("citation") or "", "reason": claim.get("reason"),
            "file": file, "line": line,
            "fingerprint": fingerprint(target, metric_id, file, line, verdict)}


def target_entry(target, kind, engine_json, changed_files, repo="."):
    """Build one bundle target from a parsed engine --json (A1 Report shape, or a calma.py verify shape
    normalised by run_pr). engine_json carries: repo_verdict, summary, isolation_tier, determinism_mode,
    claims[], fix."""
    claims = engine_json.get("claims") or []
    return {"target": target, "kind": kind,
            "repo_verdict": engine_json.get("repo_verdict") or engine_json.get("verdict"),
            "summary": engine_json.get("summary") or "",
            "isolation_tier": engine_json.get("isolation_tier"),
            "determinism_mode": engine_json.get("determinism_mode"),
            "findings": [finding_from_claim(c, target, kind, changed_files, repo) for c in claims],
            "fix": engine_json.get("fix")}


def make_bundle(pr_number, head_sha, base_sha, targets):
    return {"schema": SCHEMA, "pr_number": pr_number, "head_sha": head_sha, "base_sha": base_sha,
            "targets": targets}


def validate(bundle):
    """Structural check (B2 treats the bundle as UNTRUSTED DATA). Returns [] or a list of errors."""
    e = []
    if not isinstance(bundle, dict) or bundle.get("schema") != SCHEMA:
        return ["bad or missing schema (expected %r)" % SCHEMA]
    for k in ("pr_number", "head_sha", "base_sha", "targets"):
        if k not in bundle:
            e.append("missing key: %s" % k)
    if not isinstance(bundle.get("targets"), list):
        e.append("targets is not a list")
        return e
    for i, t in enumerate(bundle["targets"]):
        for k in ("target", "kind", "repo_verdict", "findings"):
            if k not in t:
                e.append("target[%d] missing %s" % (i, k))
        for j, f in enumerate(t.get("findings") or []):
            for k in ("metric_id", "verdict", "fingerprint"):
                if k not in f:
                    e.append("target[%d].finding[%d] missing %s" % (i, j, k))
    return e


def has_catch(bundle):
    """True iff any target's repo_verdict is a catch (REFUTED/INVALIDATED/MIXED) - a pure function of
    the engine verdicts the bundle copied; B2's check-run conclusion derives from this."""
    return any((t.get("repo_verdict") in CATCH_VERDICTS) for t in bundle.get("targets", []))


def to_json(bundle):
    return json.dumps(bundle, indent=2)


def from_json(text):
    return json.loads(text)
