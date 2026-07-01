"""calma.spike.attest.tlog — append-only transparency log (feature 12, Rekor-style).

The leaf is the digest of the feature-3 DSSE verdict envelope. Logging happens strictly AFTER the verdict is
decided and is off the critical path: the verdict is fully valid whether or not it is logged yet — the log adds
non-repudiation over time, it is not a gate. FAIL-OPEN on submit (a log outage never fails a job). FAIL-CLOSED
on verification (a presented 'logged verdict' whose chain doesn't replay is not shown as CONFIRMED).

Two tiers: a local self-checkpointing ledger (each entry chains to the previous by prev_hash, so any retro
edit breaks the chain — always available, no network) and an optional public Rekor v2 anchor (injected client;
any error → local-only). We log the DIGEST of the envelope, not the envelope, so entries stay tiny (well under
Rekor's 100 KB cap).
"""
from __future__ import annotations

import hashlib
import json
import os

_ZERO = "sha256:" + "0" * 64


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def leaf_hash(envelope) -> str:
    return "sha256:" + hashlib.sha256(_canonical(envelope)).hexdigest()


def _entry_hash(entry: dict) -> str:
    core = {k: entry[k] for k in ("index", "verdict_id", "leaf", "prev_hash")}
    return "sha256:" + hashlib.sha256(_canonical(core)).hexdigest()


class LocalLedger:
    """A local append-only, hash-chained ledger. `entry_hash = H(index, verdict_id, leaf, prev_hash)`;
    `prev_hash` links to the previous entry, so tampering with any past entry breaks every subsequent link."""

    def __init__(self, path: str | None = None):
        self.path = path
        self.entries: list[dict] = []
        if path and os.path.isfile(path):
            try:
                self.entries = json.load(open(path))
            except (OSError, ValueError):
                self.entries = []

    def append(self, verdict_id: str, envelope: dict) -> dict:
        prev = self.entries[-1]["entry_hash"] if self.entries else _ZERO
        entry = {"index": len(self.entries), "verdict_id": verdict_id,
                 "leaf": leaf_hash(envelope), "prev_hash": prev}
        entry["entry_hash"] = _entry_hash(entry)
        self.entries.append(entry)
        self._save()
        return entry

    def verify_chain(self) -> tuple[bool, str]:
        prev = _ZERO
        for i, e in enumerate(self.entries):
            if e.get("prev_hash") != prev:
                return False, "broken chain at index %d" % i
            if e.get("entry_hash") != _entry_hash(e):
                return False, "tampered entry at index %d" % i
            prev = e["entry_hash"]
        return True, "chain intact (%d entries)" % len(self.entries)

    def _save(self):
        if not self.path:
            return
        try:
            with open(self.path, "w") as fh:
                json.dump(self.entries, fh)
        except OSError:
            pass


def submit(envelope: dict, verdict_id: str, *, ledger: LocalLedger | None = None, rekor_submit=None) -> dict:
    """Best-effort transparency submission. ALWAYS appends to the local ledger (if given); ALSO anchors to a
    public Rekor v2 log if `rekor_submit(leaf)->proof` is provided. Any error is swallowed → the job still
    completes normally (fail-open)."""
    out: dict = {"leaf": leaf_hash(envelope), "local": None, "rekor": None}
    if ledger is not None:
        try:
            out["local"] = ledger.append(verdict_id, envelope)
        except Exception:  # noqa: BLE001
            out["local"] = None
    if rekor_submit is not None:
        try:
            out["rekor"] = rekor_submit(out["leaf"])
        except Exception:  # noqa: BLE001 — a Rekor outage never fails the job
            out["rekor"] = None
    return out
