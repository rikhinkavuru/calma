"""orchestrator.xpu — dual-modality experience units with vector retrieval (build plan §4.3, slice S3).

Upgrades the action-only ``HintStore`` to an **XPU** (eXperience Unit) store. Each unit pairs a RETRIEVABLE
SYMPTOM (the error signature + a one-line reflection) with an EXECUTABLE ACTION (the exact HOW-only delta), a
SCOPE (lang / pkg-manager / metric), and TELEMETRY (hits / successes / failures). The symptom half is
non-optional: action-only memories cause **negative transfer** (Memory Transfer Learning) — the text is what
makes a fix retrievable by a NOVEL repo whose error signature differs but whose *symptom* is the same
(Reflexion's verbal reinforcement; SetupX's XPU).

**Two-tier retrieval:** an exact-signature hit (certain) first, then vector cosine over the symptom text (the
paraphrase path) above a threshold. **Telemetry-gated (delayed audit):** a unit whose success-rate has fallen
below the floor is DEMOTED — never returned — so a fix that later correlated with a bad run stops being
proposed. A cached hit lets the loop skip the LLM entirely (self-healing lit: MTTR 13h→3s).

**Two backends behind one interface, mirroring ``synth/store.py``:** ``LocalXPU`` (JSON + the stdlib hashing
embedder — zero infra, the offline/test path) and ``HelixXPU`` (an ``XPU`` node on a running HelixDB — the
durable, cross-instance production store; activates when ``CALMA_HELIX`` is set + reachable).

FCR: same HOW-only guarantee as every flywheel — a unit only ever proposes an *action*; the unchanged
pure-stdlib recompute disposes the verdict, so a stale/wrong unit costs coverage (a failed run → DISCOVERED),
never a false CONFIRM. No ``core.verdict`` / ``core.diff`` import (CI firewall).
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field

from synth.store import cosine, embed   # the stdlib hashing embedder + cosine — the local vector path (DRY)

_DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".calma", "orchestrator")
_MAX_UNITS = 5000
_DEMOTE_FLOOR = 0.34       # a unit that fails ≳ ⅔ of its trials is demoted (delayed audit) — never proposed
_VEC_THRESHOLD = 0.86      # cosine floor for a symptom-paraphrase match (mirrors synth/store's threshold)


def _now() -> float:
    # Date.now-free (resume-safe): an env-injectable timestamp, else 0 — stamped by the caller if it matters.
    try:
        return float(os.environ.get("CALMA_NOW", "0")) or 0.0
    except ValueError:
        return 0.0


@dataclass
class XPUnit:
    """One experience unit. ``signature`` is the exact ``cache.error_signature`` key (the certain index);
    ``symptom`` is the retrievable text (signature + a one-line reflection); ``action`` is the HOW-only delta in
    the HintStore vocabulary (``{"add_dep": ...}`` / ``{"set_env": {...}}``)."""
    signature: str
    symptom: str
    action: dict
    scope: dict = field(default_factory=dict)
    hits: int = 0
    successes: int = 0
    failures: int = 0
    embedding: list[float] = field(default_factory=list)
    created: float = 0.0

    def text(self) -> str:
        return " ".join([self.symptom, self.signature, *(str(v) for v in self.scope.values())])

    def success_rate(self) -> float:
        # an unproven unit gets the benefit of the doubt (1.0) until it actually fails — new fixes aren't
        # pre-demoted; only ones that HAVE correlated with bad runs are.
        n = self.successes + self.failures
        return (self.successes / n) if n else 1.0


def _retrieve(units: list[XPUnit], signature: str | None, symptom: str | None,
              threshold: float = _VEC_THRESHOLD):
    """Two-tier, telemetry-gated retrieval shared by both backends (the unit set is small → match host-side).
    Returns ``(unit, score)`` or None. Exact signature = certain (1.0); else the best symptom-cosine ≥ threshold.
    Demoted units (success-rate below the floor) are filtered out first."""
    live = [u for u in units if u.success_rate() >= _DEMOTE_FLOOR]
    for u in live:                                              # (1) exact signature — the certain path
        if signature and u.signature == signature:
            return u, 1.0
    if not live:
        return None
    q = embed(symptom or signature or "")                      # (2) vector cosine over the symptom text
    best, score = None, 0.0
    for u in live:
        s = cosine(q, u.embedding or embed(u.text()))
        if s > score:
            best, score = u, s
    return (best, score) if (best and score >= threshold) else None


class LocalXPU:
    """JSON-file XPU store + the hashing embedder. Zero infra; the offline + test path. Thread-safe, bounded."""

    name = "local"

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(_DEFAULT_DIR, "xpu.json")
        self._lock = threading.Lock()
        self.units: list[XPUnit] = []
        self._load()

    def available(self):
        return True, "local json xpu store"

    def _load(self):
        if os.path.isfile(self.path):
            try:
                self.units = [XPUnit(**u) for u in json.load(open(self.path))]
            except Exception:  # noqa: BLE001 — a malformed store is treated as empty (never a crash)
                self.units = []

    def _persist(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump([asdict(u) for u in self.units], fh)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def _by_sig(self, signature: str) -> XPUnit | None:
        return next((u for u in self.units if u.signature == signature), None)

    def retrieve(self, signature: str | None, symptom: str | None = None):
        """The loop's pre-LLM lookup: a telemetry-gated exact-or-vector match. Bumps the unit's hit counter."""
        hit = _retrieve(self.units, signature, symptom)
        if hit:
            with self._lock:
                hit[0].hits += 1
                self._persist()
        return hit

    def record(self, signature: str, action: dict, symptom: str | None = None, scope: dict | None = None):
        """Bank a fix that VERIFIABLY worked. De-dups by signature (updates the action + merges telemetry)."""
        if not signature or not isinstance(action, dict) or not action:
            return None
        with self._lock:
            existing = self._by_sig(signature)
            if existing is not None:
                existing.action = action
                if symptom:
                    existing.symptom = symptom
                if scope:
                    existing.scope = {**existing.scope, **scope}
                existing.embedding = embed(existing.text())
                unit = existing
            else:
                if len(self.units) >= _MAX_UNITS:
                    self.units.pop(0)                          # bound: drop oldest (CWE-770)
                unit = XPUnit(signature=signature, symptom=symptom or signature, action=dict(action),
                              scope=dict(scope or {}), created=_now())
                unit.embedding = embed(unit.text())
                self.units.append(unit)
            self._persist()
            return unit

    def reward(self, signature: str, success: bool):
        """Delayed audit: record whether a proposed unit's downstream run/verdict held. A run of failures pushes
        its success-rate below the floor → the unit is demoted (filtered by ``_retrieve``), never auto-applied."""
        with self._lock:
            u = self._by_sig(signature)
            if u is None:
                return
            if success:
                u.successes += 1
            else:
                u.failures += 1
            self._persist()

    def absorb(self, unit: XPUnit):
        """Upsert a DISTILLED unit (S7): replace-or-add by signature, taking the unit's telemetry as
        authoritative — the run-journal is the source of truth for the aggregated success/failure counts, so an
        offline distillation pass overwrites (not increments) the stored telemetry. Re-embeds; bounded."""
        if unit is None or not unit.signature:
            return None
        with self._lock:
            existing = self._by_sig(unit.signature)
            if existing is not None:
                existing.action = unit.action
                existing.symptom = unit.symptom or existing.symptom
                existing.scope = {**existing.scope, **(unit.scope or {})}
                existing.successes, existing.failures = unit.successes, unit.failures
                existing.embedding = embed(existing.text())
                out = existing
            else:
                if len(self.units) >= _MAX_UNITS:
                    self.units.pop(0)
                unit.embedding = embed(unit.text())
                self.units.append(unit)
                out = unit
            self._persist()
            return out

    def all(self):
        return list(self.units)

    def __len__(self):
        return len(self.units)


class HelixXPU:
    """Live HelixDB backend: each XPU is a graph node (label ``XPU``) carrying its ``signature`` key + a
    base64-encoded JSON of the full unit (base64 sidesteps DSL string-escaping). Mirrors ``synth.store``'s
    HelixStore — the unit set is small, so we read all + match/telemetry host-side. Activates when a HelixDB
    instance is reachable; otherwise the caller falls back to LocalXPU."""

    name = "helix"

    def __init__(self, project_dir=None, helix_bin=None):
        from synth.store import _find_helix   # reuse the same CLI discovery as the formula store
        self.project_dir = project_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "helix")
        self.helix = helix_bin or _find_helix()

    def _q(self, expr):
        import subprocess  # noqa: PLC0415
        r = subprocess.run([self.helix, "query", "dev", "-e", expr], cwd=self.project_dir,
                           capture_output=True, text=True, timeout=90)
        i = r.stdout.find("{")
        if i < 0:
            raise RuntimeError("helix query failed: %s" % (r.stderr or r.stdout)[-200:])
        return json.loads(r.stdout[i:])

    def available(self):
        if not self.helix:
            return False, "helix CLI not found"
        try:
            self._q('readBatch().varAs("n", g().nWithLabel("XPU").count()).returning(["n"])')
            return True, "helix instance reachable"
        except Exception as e:  # noqa: BLE001
            return False, "helix unreachable: %s" % str(e)[:120]

    def all(self):
        import base64  # noqa: PLC0415
        try:
            res = self._q('readBatch().varAs("us", g().nWithLabel("XPU").valueMap()).returning(["us"])')
        except Exception:  # noqa: BLE001
            return []
        rows = (res.get("us") or {}).get("properties", []) if isinstance(res.get("us"), dict) else []
        out = []
        for row in rows:
            if not row.get("b64"):
                continue
            try:
                out.append(XPUnit(**json.loads(base64.b64decode(row["b64"]))))
            except Exception:  # noqa: BLE001
                pass
        return out

    def _write(self, unit: XPUnit):
        import base64  # noqa: PLC0415
        b64 = base64.b64encode(json.dumps(asdict(unit)).encode()).decode()
        sig = "".join(c for c in unit.signature if c.isalnum() or c in "_-:")
        try:
            self._q('writeBatch().varAs("u", g().addN("XPU", {signature:"%s", b64:"%s"})).returning(["u"])'
                    % (sig, b64))
        except Exception:  # noqa: BLE001
            pass

    def retrieve(self, signature: str | None, symptom: str | None = None):
        return _retrieve(self.all(), signature, symptom)

    def record(self, signature: str, action: dict, symptom: str | None = None, scope: dict | None = None):
        if not signature or not isinstance(action, dict) or not action:
            return None
        unit = XPUnit(signature=signature, symptom=symptom or signature, action=dict(action),
                      scope=dict(scope or {}), created=_now())
        unit.embedding = embed(unit.text())
        self._write(unit)
        return unit

    def reward(self, signature: str, success: bool):
        # telemetry lives in the node's JSON; a durable increment is a read-modify-write we keep best-effort.
        return None

    def absorb(self, unit: XPUnit):
        if unit is None or not unit.signature:
            return None
        unit.embedding = embed(unit.text())
        self._write(unit)                                      # a new node; the distilled telemetry rides in its b64
        return unit


_XPU = None


def xpu_store():
    """The default XPU store: the live HelixDB instance when ``CALMA_HELIX`` is set + reachable (OD-B: Helix
    now), else the local JSON store. Mirrors ``synth.store.get_store``."""
    global _XPU
    if _XPU is not None:
        return _XPU
    if os.environ.get("CALMA_HELIX"):
        hx = HelixXPU()
        if hx.available()[0]:
            _XPU = hx
            return _XPU
    _XPU = LocalXPU()
    return _XPU
