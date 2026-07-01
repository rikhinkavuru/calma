"""calma.spike.core.refstore — a persistent reference store of INDEPENDENTLY-VERIFIED values (feature 11).

Keyed by (normalized dataset, metric) → [verified values]. It is updated ONLY from CONFIRMED /
CONFIRMED-STOCHASTIC / REPRODUCED-ONLY runs (never from unverified claims) so the baseline can't be poisoned.
The anomaly overlay (pipeline) reads it to flag a cross-run outlier as an advisory. JSON-backed, fail-soft.
"""
from __future__ import annotations

import json
import os
import re


def norm_dataset(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _key(dataset, metric) -> str:
    return "%s␟%s" % (norm_dataset(dataset), str(metric or "").strip().lower())


class RefStore:
    def __init__(self, path: str | None = None):
        self.path = path
        self.data: dict[str, list] = {}
        if path and os.path.isfile(path):
            try:
                self.data = json.load(open(path))
            except (OSError, ValueError):
                self.data = {}

    def values(self, dataset, metric) -> list:
        return list(self.data.get(_key(dataset, metric), []))

    def append(self, dataset, metric, value, cap: int = 5000):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if v != v:
            return
        k = _key(dataset, metric)
        lst = self.data.setdefault(k, [])
        lst.append(v)
        if len(lst) > cap:                 # bound growth; keep the most recent
            del lst[:-cap]
        self._save()

    def _save(self):
        if not self.path:
            return
        try:
            with open(self.path, "w") as fh:
                json.dump(self.data, fh)
        except OSError:
            pass
