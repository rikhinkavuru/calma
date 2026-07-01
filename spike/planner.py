"""calma.spike.planner — AI repo understanding → a structured RUN PLAN handed to the rest of the pipeline.

"AI proposes, determinism disposes." A fast model reads the repo and proposes HOW to run it — the entrypoint
that reproduces the headline numbers, the deps to install, the Python version, the data it needs. That plan
ONLY changes how we execute the repo's OWN code; it NEVER computes a metric or decides a verdict — that stays
deterministic in core/. The blast radius of a wrong or prompt-injected plan is therefore a failed run
(→ DISCOVERED), never a false verdict.

Best-effort by construction: no ANTHROPIC_API_KEY, no `anthropic` package, or any error → returns None and the
pipeline falls back to its heuristics (build.detect_entrypoint / infer_requirements). It is a pre-stage that
sharpens the run, not a dependency of it. Meant to run concurrently with the sandbox boot so its latency is
hidden; even sequential it pays for itself by avoiding failed installs / wrong-entrypoint reruns.
"""
from __future__ import annotations

import json
import os
import re

# The planner earns its keep on HARD repos (ambiguous entrypoints, monorepos, unusual repro steps, deps not
# declared) — easy repos already resolve from heuristics — so the read quality matters, and since the output
# is validated (entrypoint must exist) + best-effort, model choice never risks a verdict, only run success.
# Sonnet 5 is the sweet spot: best speed+intelligence, "Fast" latency for the hot path, ~Haiku-cheap at intro
# pricing. CALMA_PLAN_MODEL overrides (claude-haiku-4-5 to cut cost at scale; claude-opus-4-8/claude-fable-5
# for a maximal read).
_MODEL = os.environ.get("CALMA_PLAN_MODEL", "claude-sonnet-5").strip() or "claude-sonnet-5"

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", ".venvs", "results"}

_SYSTEM = (
    "You are the environment-synthesis step of a verification system. Your ONLY job is to plan how to RUN a "
    "repository so it reproduces the numbers it reports — you do NOT compute, judge, or predict any metric "
    "value, and you never decide whether a number is correct. Read the repo and return how to execute its "
    "OWN code: the entrypoint that produces the headline metrics, the pip packages to install, the Python "
    "version it targets, and any external data it needs. Prefer the repo's real reproduce/eval/benchmark "
    "script over a training script. If you are unsure of the entrypoint, return an empty list rather than "
    "guessing — a wrong guess is worse than none."
)

# Structured output: the model is constrained to emit exactly this shape (no Pydantic needed).
_SCHEMA = {
    "type": "object",
    "properties": {
        "entrypoint": {"type": "array", "items": {"type": "string"},
                       "description": "argv (relative to the repo root) that reproduces the headline numbers, "
                                      "e.g. ['run_benchmark.py','--all'] or ['-m','pkg.eval']. Empty list if unsure."},
        "pip_install": {"type": "array", "items": {"type": "string"},
                        "description": "pip package specs the run needs (respect requirements.txt if present)."},
        "python_version": {"type": "string", "description": "the Python the repo targets, e.g. '3.11'; '' if unknown."},
        "data_needed": {"type": "string", "description": "external data the repo needs + where from; '' if none/bundled."},
        "notes": {"type": "string", "description": "one sentence: what the repo does and how its headline metric is computed."},
        "confidence": {"type": "number", "description": "0..1 confidence that the entrypoint reproduces the headline numbers."},
    },
    "required": ["entrypoint", "pip_install", "python_version", "data_needed", "notes", "confidence"],
    "additionalProperties": False,
}

_MAX_README = 8000
_MAX_SCRIPT = 2500
_MAX_SCRIPTS = 8
_MAX_TREE = 240


def _read(path: str, cap: int) -> str:
    try:
        with open(path, errors="replace") as fh:
            return fh.read(cap)
    except OSError:
        return ""


def _gather_context(repo_dir: str) -> str:
    """Assemble a bounded snapshot of the repo for the model: file tree + README + declared deps + the head of
    the root-level scripts (where entrypoints and their imports live)."""
    tree, scripts = [], []
    n = 0
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        rel = os.path.relpath(root, repo_dir)
        for fn in sorted(files):
            n += 1
            if n > _MAX_TREE:
                break
            tree.append(os.path.normpath(os.path.join(rel, fn)) if rel != "." else fn)
        if n > _MAX_TREE:
            break

    parts = ["## File tree (truncated)\n" + "\n".join(tree)]
    for name in ("README.md", "README.rst", "README.txt", "readme.md", "REPRODUCE.md"):
        p = os.path.join(repo_dir, name)
        if os.path.isfile(p):
            parts.append("## %s\n%s" % (name, _read(p, _MAX_README)))
            break
    for name in ("requirements.txt", "pyproject.toml", "setup.py", "environment.yml", ".python-version", "runtime.txt"):
        p = os.path.join(repo_dir, name)
        if os.path.isfile(p):
            parts.append("## %s\n%s" % (name, _read(p, 2000)))

    # the head of each root-level Python script — entrypoints + their imports live here
    roots = sorted(f for f in (os.listdir(repo_dir) if os.path.isdir(repo_dir) else [])
                   if f.endswith(".py")) [:_MAX_SCRIPTS]
    for f in roots:
        parts.append("## %s (head)\n%s" % (f, _read(os.path.join(repo_dir, f), _MAX_SCRIPT)))
    return "\n\n".join(parts)


def _call_model(context: str, model: str) -> str | None:
    """Return the model's raw JSON string, or None on any failure. Isolated so tests can stub it without the
    SDK or a network call. Lazy-imports `anthropic` so the module loads even when the SDK isn't installed."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except Exception:  # noqa: BLE001 — SDK not installed → planner disabled, heuristics take over
        return None
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model, max_tokens=1024, system=_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{"role": "user", "content": context}],
        )
        return next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
    except Exception:  # noqa: BLE001 — auth/rate/network/parse → best-effort, fall back to heuristics
        return None


def _valid_entry(entry, repo_dir: str):
    """Trust the proposed entrypoint ONLY if it points at code that actually exists — a `-m module` form, or a
    script present in the repo. This is the anti-hallucination / anti-injection gate: a made-up entrypoint is
    dropped and the deterministic detector takes over."""
    if not isinstance(entry, list) or not entry or not all(isinstance(x, str) for x in entry):
        return None
    if entry[0] == "-m":
        return entry if len(entry) > 1 and re.match(r"^[\w.]+$", entry[1]) else None
    base = os.path.basename(entry[0])
    return [base] + [str(a) for a in entry[1:]] if os.path.isfile(os.path.join(repo_dir, base)) else None


def plan_repo(repo_dir: str, model: str | None = None) -> dict | None:
    """Understand a repo and return a validated run plan, or None if planning is unavailable/failed.

    Returns {entry, pip_install, python_version, data_needed, notes, confidence}. `entry`/`pip_install` are
    None when the model didn't supply a usable value (the caller then keeps its heuristics)."""
    if not os.path.isdir(repo_dir):
        return None
    raw = _call_model(_gather_context(repo_dir), (model or _MODEL))
    if not raw:
        return None
    try:
        p = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(p, dict):
        return None

    entry = _valid_entry(p.get("entrypoint"), repo_dir)
    deps = [d for d in (p.get("pip_install") or []) if isinstance(d, str) and d.strip()] or None
    pyver = p.get("python_version") if re.match(r"^\d+\.\d+", str(p.get("python_version") or "")) else None
    try:
        conf = max(0.0, min(1.0, float(p.get("confidence", 0))))
    except (TypeError, ValueError):
        conf = 0.0
    return {"entry": entry, "pip_install": deps, "python_version": pyver,
            "data_needed": str(p.get("data_needed") or ""), "notes": str(p.get("notes") or ""),
            "confidence": conf}
