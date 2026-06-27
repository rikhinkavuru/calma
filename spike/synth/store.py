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
import time
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

    def lookup(self, metric: str, text: str = None, threshold: float = 0.86):
        m = (metric or "").strip().lower()
        for r in self.records:                                   # exact / alias — certain match
            if r.metric == m or m in [a.lower() for a in r.aliases]:
                return r, 1.0
        if not self.records:
            return None
        q = embed(text or metric)                                # semantic match for paraphrases
        best, score = None, 0.0
        for r in self.records:
            e = r.embedding or embed(r.text())
            s = cosine(q, e)
            if s > score:
                best, score = r, s
        return (best, score) if (best and score >= threshold) else None

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
    """helix-py adapter over a running HelixDB instance (the production backend). Mirrors LocalStore's
    interface. Requires the instance to expose the queries (queries.hx) named below; on any connection or
    schema error it reports unavailable so the factory falls back to LocalStore. Vectors use HelixDB's
    SearchV/AddV (server-side Embed if configured). Import + connection are lazy."""

    name = "helix"
    #: the HelixQL queries this adapter expects (a builder fills queries.hx/schema.hx from this contract):
    QUERIES = {
        "AddFormula": "AddV<Formula>(Embed(text), {metric, aliases, inputs, code, definition, source, validation})",
        "SearchFormula": "SearchV<Formula>(Embed(text), limit) -> the nearest formula records",
    }

    def __init__(self, port=6969, api_endpoint=None):
        self._client = None
        self._err = ""
        try:
            import helix  # noqa: PLC0415 - optional, lazy
            self._client = (helix.Client(api_endpoint=api_endpoint) if api_endpoint
                            else helix.Client(local=True, port=port))
        except Exception as e:  # noqa: BLE001
            self._err = "helix-py/instance unavailable: %s" % e

    def available(self):
        if self._client is None:
            return False, self._err
        try:
            self._client.query("SearchFormula", {"text": "ping", "limit": 1})
            return True, "helixdb reachable"
        except Exception as e:  # noqa: BLE001
            return False, "helixdb query failed: %s" % e

    def lookup(self, metric: str, text: str = None, threshold: float = 0.86):
        try:
            res = self._client.query("SearchFormula", {"text": text or metric, "limit": 1})
            rows = res if isinstance(res, list) else res.get("formulas", [])
            if not rows:
                return None
            row = rows[0]
            rec = FormulaRecord(metric=row["metric"], aliases=row.get("aliases", []),
                                inputs=row.get("inputs", []), code=row["code"],
                                definition=row.get("definition", ""), source=row.get("source", ""),
                                validation=row.get("validation", {}))
            return rec, float(row.get("score", 1.0))
        except Exception:  # noqa: BLE001
            return None

    def add(self, rec: FormulaRecord):
        try:
            self._client.query("AddFormula", {"text": rec.text(), "metric": rec.metric,
                                              "aliases": rec.aliases, "inputs": rec.inputs, "code": rec.code,
                                              "definition": rec.definition, "source": rec.source,
                                              "validation": rec.validation})
        except Exception:  # noqa: BLE001
            pass
        return rec

    def all(self):
        return []


def _now():
    # Date.now-free: read an env-injectable timestamp, else 0 (stamped by the caller if it matters)
    try:
        return float(os.environ.get("CALMA_NOW", "0")) or 0.0
    except ValueError:
        return 0.0


def get_store():
    """The default store: HelixDB when CALMA_HELIX is set + reachable, else the local JSON store."""
    if os.environ.get("CALMA_HELIX"):
        hs = HelixStore(api_endpoint=os.environ.get("CALMA_HELIX_ENDPOINT"))
        ok, _ = hs.available()
        if ok:
            return hs
    return LocalStore()
