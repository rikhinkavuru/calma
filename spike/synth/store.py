"""calma.spike.synth.store — the verified-formula store (the catalog flywheel, rebuild guide §10 #2).

When Calma meets a metric its trusted catalog doesn't recognise, it can synthesise + validate a formula
(see formula.py) and BANK it here. The next repo that reports the same metric — even phrased differently
("MCC" vs "Matthews correlation coefficient" vs "phi coefficient") — gets a fast vector hit and reuses the
already-validated formula instead of re-discovering it. Coverage compounds with volume; "unrecognized"
shrinks.

Two backends behind one interface:
  LocalStore  a JSON file + a pure-stdlib hashing embedder + cosine — works today, zero infra.
  HelixStore  helix-py over a running HelixDB instance (Rust graph-vector DB) — the production backend:
              vector ANN at scale, `SearchV<Formula>(Embed(text))`. Activates when CALMA_HELIX is set and
              the instance is reachable; falls back to LocalStore otherwise.

A formula is only ever stored AFTER it passes validation (formula._validate_synth), so the store holds
trusted, reusable recompute code — never an unvalidated guess.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass, field

_EMBED_DIM = 256


# ---- pure-stdlib hashing embedder (the local vector path; Helix uses its own Embed) ----------------
def embed(text: str) -> list[float]:
    """A deterministic, dependency-free embedding of a metric's name + aliases + definition: hash word
    tokens and char 3-grams into a fixed-dim bag, L2-normalised. Good enough to cluster paraphrases of the
    same metric for the local backend; HelixDB swaps in a real embedding model in production."""
    v = [0.0] * _EMBED_DIM
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    toks = set(words)
    for w in words:
        for i in range(len(w) - 2):
            toks.add(w[i:i + 3])
    for t in toks:
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        v[h % _EMBED_DIM] += 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _match(records, metric: str, text: str | None = None, threshold: float = 0.86):
    """Shared lookup: exact metric/alias (certain) first, then vector cosine for paraphrases. Used by both
    the local store and the Helix store (a formula catalog is small, so reading all + matching host-side is
    fine, and keeps the backend-agnostic)."""
    m = (metric or "").strip().lower()
    for r in records:
        if r.metric == m or m in [a.lower() for a in r.aliases]:
            return r, 1.0
    if not records:
        return None
    q = embed(text or metric)
    best, score = None, 0.0
    for r in records:
        s = cosine(q, r.embedding or embed(r.text()))
        if s > score:
            best, score = r, s
    return (best, score) if (best and score >= threshold) else None


def _find_helix():
    import shutil  # noqa: PLC0415
    p = os.path.expanduser("~/.local/bin/helix")
    return shutil.which("helix") or (p if os.path.isfile(p) else None)


@dataclass
class FormulaRecord:
    metric: str                       # canonical id we file it under
    aliases: list[str]                # names/spellings that map here
    inputs: list[str]                 # canonical input keys it consumes (e.g. ["y_true","y_pred"])
    code: str                         # the synthesised recompute source: def recompute(I, K) -> float
    definition: str = ""              # the human definition that grounded the synthesis (from Exa)
    source: str = ""                  # provenance (exa url / "hand-synth")
    validation: dict = field(default_factory=dict)   # {method, trials, max_err} — how it was trusted
    embedding: list[float] = field(default_factory=list)
    created: float = 0.0

    def text(self) -> str:
        return " ".join([self.metric, *self.aliases, self.definition])


class LocalStore:
    """JSON-file store + the hashing embedder. lookup() tries exact metric/alias first (the fast, certain
    path), then vector cosine for paraphrases above a threshold."""

    def __init__(self, path=None):
        self.path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "formula_store.json")
        self.records: list[FormulaRecord] = []
        self._load()

    name = "local"

    def available(self):
        return True, "local json store"

    def _load(self):
        if os.path.isfile(self.path):
            try:
                raw = json.load(open(self.path))
                self.records = [FormulaRecord(**r) for r in raw]
            except Exception:  # noqa: BLE001
                self.records = []

    def _persist(self):
        try:
            with open(self.path, "w") as fh:
                json.dump([asdict(r) for r in self.records], fh, indent=2)
        except OSError:
            pass

    def lookup(self, metric: str, text: str | None = None, threshold: float = 0.86):
        return _match(self.records, metric, text, threshold)

    def add(self, rec: FormulaRecord):
        if not rec.embedding:
            rec.embedding = embed(rec.text())
        if not rec.created:
            rec.created = _now()
        # de-dup by canonical metric
        self.records = [r for r in self.records if r.metric != rec.metric]
        self.records.append(rec)
        self._persist()
        return rec

    def all(self):
        return list(self.records)


class HelixStore:
    """Live HelixDB (3.x) backend over a running local instance (`helix start dev`, port 6969). Each formula
    is a graph node (label `Formula`) carrying its `metric` key + a base64-encoded JSON of the full record
    (base64 sidesteps DSL string-escaping for code/aliases). Writes via the `helix query -e writeBatch addN`
    DSL; reads all `Formula` nodes via `valueMap()` and matches host-side (a formula catalog is small). The
    instance IS the graph store of record — formulas persist as nodes you can traverse/visualize."""

    name = "helix"

    def __init__(self, project_dir=None, helix_bin=None):
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
            self._q('readBatch().varAs("n", g().nWithLabel("Formula").count()).returning(["n"])')
            return True, "helix instance reachable"
        except Exception as e:  # noqa: BLE001
            return False, "helix unreachable: %s" % str(e)[:120]

    def add(self, rec: FormulaRecord):
        import base64  # noqa: PLC0415
        if not rec.embedding:
            rec.embedding = embed(rec.text())
        if not rec.created:
            rec.created = _now()
        b64 = base64.b64encode(json.dumps(asdict(rec)).encode()).decode()
        metric = "".join(c for c in rec.metric if c.isalnum() or c in "_-")
        try:
            self._q('writeBatch().varAs("f", g().addN("Formula", {metric:"%s", b64:"%s"})).returning(["f"])'
                    % (metric, b64))
        except Exception:  # noqa: BLE001
            pass
        return rec

    def all(self):
        import base64  # noqa: PLC0415
        try:
            res = self._q('readBatch().varAs("fs", g().nWithLabel("Formula").valueMap()).returning(["fs"])')
        except Exception:  # noqa: BLE001
            return []
        rows = (res.get("fs") or {}).get("properties", []) if isinstance(res.get("fs"), dict) else []
        out = []
        for row in rows:
            if not row.get("b64"):
                continue
            try:
                out.append(FormulaRecord(**json.loads(base64.b64decode(row["b64"]))))
            except Exception:  # noqa: BLE001
                pass
        return out

    def lookup(self, metric: str, text: str | None = None, threshold: float = 0.86):
        return _match(self.all(), metric, text, threshold)


def _now():
    # Date.now-free: read an env-injectable timestamp, else 0 (stamped by the caller if it matters)
    try:
        return float(os.environ.get("CALMA_NOW", "0")) or 0.0
    except ValueError:
        return 0.0


def get_store():
    """The default store: the live HelixDB graph instance when CALMA_HELIX is set + reachable, else the
    local JSON store (fast, zero-infra). Falls back automatically if the Helix instance isn't running."""
    if os.environ.get("CALMA_HELIX"):
        hs = HelixStore()
        ok, _ = hs.available()
        if ok:
            return hs
    return LocalStore()
