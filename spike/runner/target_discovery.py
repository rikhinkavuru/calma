"""runner.target_discovery — Cycle-2 binding fix (the digits-softmax gap): a deterministic, non-LLM fallback
that proposes a repo's OWN metric-computing function as a capture target by NAME MATCH alone, for the case
where nothing known-library was captured (e.g. a from-scratch numpy accuracy/softmax with no sklearn call to
hook). Sits alongside the AI planner's LLM-proposed targets (planner.py) as the deterministic-core sibling —
"AI proposes when available; a static heuristic covers when it isn't" — never a required dependency.

Safety: this is a NAME match only, never a value match (module docstring of core/diff.py's rule, unbroken
here). A wrong guess still flows through the ordinary capture → independent-recompute → three-way-diff path,
so it can catch a real misreport (REFUTED) or a wrong formula (INVALIDATED) same as any other target. But
because the function was chosen by syntax, not by a human/AI's semantic judgment, callers MUST mark the
resulting captured call so core/diff.py can cap it below CONFIRMED (see the "static:" sink prefix wiring in
capture/calma_capture.py + capture/ast_capture.py, and core/diff.py's `heuristic_bind`) — the same
downgrade-only discipline as the Cycle-1 binding fix.
"""
from __future__ import annotations

import ast
import os

from discovery.extract import map_metric

# metrics already coverable by the sklearn capture hooks (capture/calma_capture.py _SKLEARN_ADAPTERS) — a real
# library call is always the higher-trust source, so this fallback never competes with it.
_SKLEARN_COVERED = frozenset({
    "accuracy", "balanced_accuracy", "precision", "recall", "f1", "roc_auc",
    "mse", "rmse", "mae", "r2", "mcc", "cohen_kappa", "log_loss", "brier",
})

_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "env", "node_modules",
              "site-packages", "dist-packages", "test", "tests", "build", "dist", "egg-info"}
_MAX_FILES = 40
_MAX_BYTES = 300_000
_MAX_TARGETS = 5
_MIN_CONFIDENCE = 0.55   # discovery.extract's keyword-match tier is 0.6; the alias tier is 0.9 — excludes noise


def _iter_py_files(repo_dir: str):
    n = 0
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            try:
                if os.path.getsize(path) > _MAX_BYTES:
                    continue
            except OSError:
                continue
            yield path
            n += 1
            if n >= _MAX_FILES:
                return


def propose(repo_dir: str, known_metrics=None) -> list[dict]:
    """[{target, metric, inputs, confidence, static}] — candidate hand-rolled metric functions, ranked by name-
    match confidence, capped to `_MAX_TARGETS`. `target` is a bare function name (all 3 capture tiers accept
    that — see ast_capture.target_atoms / calma_capture's sys.monitoring qualname match); `inputs` assumes the
    conventional (y_true, y_pred) positional shape (order-independent for accuracy; a swapped order on an
    order-sensitive metric just fails the independent recompute, same fail-closed outcome as a wrong guess
    anywhere else in the capture ladder). Best-effort: any parse/IO error on a file is silently skipped.

    `known_metrics`: metrics to SKIP because a higher-trust source already covers them. Default (None) auto-
    detects: `_SKLEARN_COVERED` if any scanned file actually imports/mentions sklearn (so this fallback
    doesn't propose a redundant/conflicting candidate for a metric sklearn's own hooks will capture), else
    empty (nothing pre-excluded — e.g. a repo with zero sklearn usage, the digits-softmax shape this exists
    for). Pass an explicit set/frozenset to override."""
    out: list[dict] = []
    seen: set[str] = set()
    sklearn_seen = False
    sources: list[tuple[str, ast.AST]] = []
    for path in _iter_py_files(repo_dir):
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                src = fh.read()
            tree = ast.parse(src, path)
        except (SyntaxError, OSError, UnicodeDecodeError, ValueError):
            continue
        if "sklearn" in src:
            sklearn_seen = True
        sources.append((path, tree))
    if known_metrics is None:
        known_metrics = _SKLEARN_COVERED if sklearn_seen else frozenset()
    for _path, mod_tree in sources:
        for node in ast.walk(mod_tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = node.name
            if name.startswith("_") or name in seen:
                continue
            args = node.args.args
            if len(args) < 2:                       # needs at least (y_true, y_pred) — extra optional params
                continue                            # (threshold, form, k, ...) are common and fine to allow
            if not any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(node)):
                continue                            # must actually return something (not a void helper)
            cid, _split, confidence = map_metric(name)
            if not cid or cid in known_metrics or confidence < _MIN_CONFIDENCE:
                continue
            seen.add(name)
            out.append({"target": name, "metric": cid,
                        "inputs": {"y_true": "arg0", "y_pred": "arg1"},
                        "confidence": confidence, "static": True})
    out.sort(key=lambda t: -t["confidence"])
    return out[:_MAX_TARGETS]
