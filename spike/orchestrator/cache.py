"""calma.spike.orchestrator.cache — the reproduction flywheel + error→fix experience store (Phase 4).

Two FCR-safe, HOW-only stores that make the orchestrator cheaper as coverage compounds (PRICING.md):

* ``ApproachCache`` — fingerprint → the winning ``RunApproach``. A repeat or sibling repo (same tree-hash +
  commit) skips the LLM ranking entirely and tries the known-good approach first. Cost-per-scan trends to $0.

* ``HintStore`` — error-signature → a successful revise action (the SOTA "experience unit" idea, e.g. SetupX's
  XPU / ExecutionAgent's lessons). A NOVEL repo that hits `ModuleNotFoundError: cv2` benefits from a past run
  that learned "add opencv-python-headless". Closes a gap the base plan left (its cache was fingerprint-only).

Both are strictly HOW-only: they cache/replay an *approach* or a *fix*, never a claim value, binding, or
verdict. A cached approach still flows through the full k-runs → identity-binding → recompute → fail-closed
verdict, so a stale/wrong cache entry can only cost coverage (a failed run → DISCOVERED), never a false
CONFIRM. A changed repo yields a different fingerprint → automatic miss. Both persist best-effort to JSON,
are thread-safe, and are size-bounded (a cache is not a memory leak, CWE-770).
"""
from __future__ import annotations

import json
import os
import re
import threading

from runner import build

from .types import RunApproach

_DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".calma", "orchestrator")
_MAX_ENTRIES = 5000


def _load(path: str) -> dict:
    try:
        with open(path) as fh:
            d = json.load(fh)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path: str, data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except OSError:
        pass


class ApproachCache:
    """fingerprint → RunApproach (the flywheel). Best-effort persistence; thread-safe; bounded."""

    def __init__(self, path: str | None = None):
        self._path = path or os.path.join(_DEFAULT_DIR, "approaches.json")
        self._lock = threading.Lock()
        self._data = _load(self._path)

    def get(self, fingerprint: str) -> RunApproach | None:
        if not fingerprint:
            return None
        with self._lock:
            raw = self._data.get(fingerprint)
        if not raw:
            return None
        try:
            return RunApproach.from_dict(raw)
        except Exception:  # noqa: BLE001 — a malformed cached entry is ignored (treated as a miss)
            return None

    def put(self, fingerprint: str, approach: RunApproach) -> None:
        if not fingerprint or approach is None:
            return
        with self._lock:
            if fingerprint not in self._data and len(self._data) >= _MAX_ENTRIES:
                self._data.pop(next(iter(self._data)), None)     # bound: drop oldest-inserted
            self._data[fingerprint] = approach.to_dict()
            _save(self._path, self._data)

    def __len__(self):
        return len(self._data)


# ── error signatures (the HintStore key) ──────────────────────────────────────────────────────────────────────
_MODERR = re.compile(r"No module named ['\"]([\w.]+)['\"]")


def error_signature(stderr: str) -> str | None:
    """A stable, low-cardinality signature for a run failure — the key the HintStore learns fixes against.
    Combines the classified failure kind with the salient token (missing module / data file), so a specific,
    fixable error maps to one bucket and a generic one is skipped (returns None → not worth caching a fix)."""
    s = stderr or ""
    m = _MODERR.search(s)
    if m:
        return "missing-dep:" + m.group(1).split(".")[0]
    kind = build.classify_failure(s).get("kind")
    if kind in ("missing-data", "needs-network", "needs-gpu", "too-heavy", "too-slow"):
        return kind
    return None


class HintStore:
    """error-signature → a successful revise action (the experience flywheel). Only ADDITIVE, HOW-only fixes
    (add a dep, set an env var); it can never influence a verdict. Bounded + persisted best-effort."""

    def __init__(self, path: str | None = None):
        self._path = path or os.path.join(_DEFAULT_DIR, "hints.json")
        self._lock = threading.Lock()
        self._data = _load(self._path)

    def get(self, sig: str):
        if not sig:
            return None
        with self._lock:
            return self._data.get(sig)

    def record(self, sig: str, action: dict) -> None:
        """Remember that ``action`` fixed ``sig``. ``action`` is a small dict, e.g. {"add_dep": "opencv-..."}
        or {"set_env": {"KEY": "val"}} — the HOW-only vocabulary. No-op on a bad signature/action."""
        if not sig or not isinstance(action, dict) or not action:
            return
        with self._lock:
            if sig not in self._data and len(self._data) >= _MAX_ENTRIES:
                self._data.pop(next(iter(self._data)), None)
            self._data[sig] = action
            _save(self._path, self._data)

    def __len__(self):
        return len(self._data)


# process-wide singletons (the single in-memory instance's stores; a durable control plane is the later layer)
_APPROACHES: ApproachCache | None = None
_HINTS: HintStore | None = None


def approach_cache() -> ApproachCache:
    global _APPROACHES
    if _APPROACHES is None:
        _APPROACHES = ApproachCache()
    return _APPROACHES


def hint_store() -> HintStore:
    global _HINTS
    if _HINTS is None:
        _HINTS = HintStore()
    return _HINTS
