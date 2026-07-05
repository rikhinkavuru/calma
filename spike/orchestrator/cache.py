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


class RunPlanCache:
    """repo-fingerprint → the run-plan {'entry': [...], 'pip': [...], 'python': 'X.Y'|None} that VERIFIABLY
    captured — the reproduction flywheel for the DEFAULT (heuristic, non-orchestrated) path. A repeat or
    sibling scan of the same tree reuses the known-good plan, skipping re-derivation and the AI planner call
    (cost-per-scan → $0 on a hit). Same HOW-only guarantee as ApproachCache: a cached plan still flows through
    the full k-runs → binding → recompute → fail-closed verdict, so a stale entry can only cost coverage,
    never a verdict; a changed repo yields a different fingerprint → automatic miss. Bounded + persisted
    best-effort (CWE-770). Local JSON today; a HelixDB ``RunPlan`` node is the durable cross-instance backend."""

    def __init__(self, path: str | None = None):
        self._path = path or os.path.join(_DEFAULT_DIR, "runplans.json")
        self._lock = threading.Lock()
        self._data = _load(self._path)

    def get(self, fingerprint: str) -> dict | None:
        if not fingerprint:
            return None
        with self._lock:
            v = self._data.get(fingerprint)
        return dict(v) if isinstance(v, dict) and v.get("entry") else None

    def put(self, fingerprint: str, plan: dict) -> None:
        if not fingerprint or not isinstance(plan, dict) or not plan.get("entry"):
            return
        rec = {"entry": list(plan["entry"]), "pip": list(plan.get("pip") or []), "python": plan.get("python")}
        with self._lock:
            if fingerprint not in self._data and len(self._data) >= _MAX_ENTRIES:
                self._data.pop(next(iter(self._data)), None)     # bound: drop oldest-inserted
            self._data[fingerprint] = rec
            _save(self._path, self._data)

    def __len__(self):
        return len(self._data)


_RUNPLANS: RunPlanCache | None = None


def runplan_cache() -> RunPlanCache:
    global _RUNPLANS
    if _RUNPLANS is None:
        _RUNPLANS = RunPlanCache()
    return _RUNPLANS


class SnapshotCache:
    """fingerprint → a paused-sandbox snapshot id (the warm-env flywheel, build plan §4.4, S5). A repeat or
    sibling scan RESUMES the snapshot (~1s) instead of re-booting + re-installing the environment (minutes) —
    the RunPlan contract as a live image. HOW-only: a resumed env still flows through the full k-runs →
    recompute → fail-closed verdict, so a stale snapshot can only cost coverage (a failed run → DISCOVERED),
    never a verdict; a changed repo yields a different fingerprint → automatic miss.

    UNLIKE the pure-JSON caches, each entry is a LIVE paused sandbox = cost — E2B retains paused sandboxes
    INDEFINITELY (no TTL). So this cache is SMALL-bounded and, on replacement or eviction, KILLS the old sandbox
    via the injected ``kill_fn`` (a wrong/absent reaper would leak sandboxes). Persisted best-effort."""

    def __init__(self, path: str | None = None, kill_fn=None, max_entries: int = 64):
        self._path = path or os.path.join(_DEFAULT_DIR, "snapshots.json")
        self._lock = threading.Lock()
        self._data = _load(self._path)
        self._kill = kill_fn if callable(kill_fn) else (lambda _sid: None)
        self._max = max(1, int(max_entries))

    def get(self, fingerprint: str) -> str | None:
        if not fingerprint:
            return None
        with self._lock:
            v = self._data.get(fingerprint)
        return v if (isinstance(v, str) and v) else None

    def _reap(self, snapshot_id) -> None:
        try:
            if snapshot_id:
                self._kill(snapshot_id)                        # release the live sandbox (cost) — best-effort
        except Exception:  # noqa: BLE001 — a failed kill must never break put()/discard()
            pass

    def put(self, fingerprint: str, snapshot_id: str) -> None:
        if not fingerprint or not snapshot_id:
            return
        with self._lock:
            old = self._data.get(fingerprint)
            if old and old != snapshot_id:
                self._reap(old)                                # a replaced snapshot is now orphaned → kill it
            if fingerprint not in self._data and len(self._data) >= self._max:
                fk = next(iter(self._data))
                self._reap(self._data.pop(fk))                 # evict + kill the oldest-inserted (bound = cost cap)
            self._data[fingerprint] = snapshot_id
            _save(self._path, self._data)

    def discard(self, fingerprint: str) -> None:
        """Drop + kill the snapshot for a fingerprint — e.g. when a resume failed (the snapshot is gone/expired),
        so the next scan boots fresh instead of retrying a dead id."""
        with self._lock:
            sid = self._data.pop(fingerprint, None)
            if sid:
                self._reap(sid)
                _save(self._path, self._data)

    def __len__(self):
        return len(self._data)


class RunJournal:
    """Append-only JSONL of every revise OUTCOME across runs — ``{sig, symptom, action, success, scope}`` — the
    raw material for offline distillation (S7). Unlike the online XPU record-on-win, it logs FAILURES too, so
    ``distill()`` can compute a fix's REAL success rate across runs (the delayed-audit telemetry the online path
    lacks). HOW-only (an action is an add-dep/set-env delta, never a value/verdict). Bounded (a ring, CWE-770):
    on overflow the oldest lines are dropped. Best-effort persistence."""

    def __init__(self, path: str | None = None, max_records: int = 20000):
        self._path = path or os.path.join(_DEFAULT_DIR, "journal.jsonl")
        self._lock = threading.Lock()
        self._max = max(100, int(max_records))

    def append(self, record: dict) -> None:
        if not isinstance(record, dict) or not record.get("sig") or not record.get("action"):
            return
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self._path), exist_ok=True)
                with open(self._path, "a") as fh:
                    fh.write(json.dumps(record) + "\n")
            except OSError:
                return
            self._trim_locked()

    def _trim_locked(self) -> None:
        try:
            with open(self._path) as fh:
                lines = fh.readlines()
        except OSError:
            return
        if len(lines) <= self._max:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w") as fh:
                fh.writelines(lines[-self._max:])              # keep the newest max_records
            os.replace(tmp, self._path)
        except OSError:
            pass

    def records(self) -> list[dict]:
        try:
            with open(self._path) as fh:
                out = []
                for ln in fh:
                    ln = ln.strip()
                    if ln:
                        try:
                            out.append(json.loads(ln))
                        except ValueError:
                            continue
                return out
        except OSError:
            return []

    def __len__(self):
        return len(self.records())


_JOURNAL: RunJournal | None = None


def run_journal() -> RunJournal:
    global _JOURNAL
    if _JOURNAL is None:
        _JOURNAL = RunJournal()
    return _JOURNAL


_SNAPSHOTS: SnapshotCache | None = None


def snapshot_cache(kill_fn=None) -> SnapshotCache:
    """The process-wide snapshot cache. ``kill_fn`` (the E2B reaper) is bound on first construction — the E2B
    integration passes ``lambda sid: runner.snapshot.kill_snapshot(sid, cfg)``; tests pass a fake."""
    global _SNAPSHOTS
    if _SNAPSHOTS is None:
        _SNAPSHOTS = SnapshotCache(kill_fn=kill_fn)
    return _SNAPSHOTS
