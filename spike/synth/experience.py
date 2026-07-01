"""calma.spike.synth.experience — the general experience bank (feature 5, the learning flywheel).

Generalizes the verified-formula store (store.py) into a bank of REUSABLE experience: banked run PLANS
(entry/deps), capture TARGETS, and CONVENTIONS that worked for a repo family — plus, in a STRICTLY SEPARATE
namespace, observed KNOWN VALUES. The bank makes Calma better + cheaper with volume (fewer Exa calls / planner
tokens, warmer-start binding) WITHOUT ever loosening the verdict.

FCR FIREWALL (the load-bearing invariant, mirrored by test_known_value_firewall):
  A `KnownValueHint` is a PRIOR/HINT only. It is consumed ONLY by the planner and binding-candidate RANKING;
  it is NEVER passed to core.diff.diff_claim or core.verdict.decide. The verdict's inputs stay: the producer's
  claim, THIS run's produced value, and THIS run's independent recompute. A hint can make Calma capture the
  right computation or try the right convention — it can never stand in for `produced` or `recomputed`.
  Formula reuse is safe because it RE-EXECUTES VALIDATED CODE on this repo's fresh inputs, never a cached
  scalar. Known values live under a distinct `kind` and are exposed only via `hints()`, never `lookup()`.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field

# experience kinds the bank stores. `known_value` is the firewalled namespace — hints only.
PLAN = "plan"
TARGETS = "targets"
CONVENTIONS = "conventions"
KNOWN_VALUE = "known_value"
_REUSABLE = (PLAN, TARGETS, CONVENTIONS)          # the kinds `lookup()` will return (never known_value)


@dataclass
class ExperienceRecord:
    key: str                                       # repo-family / metric / domain signature
    kind: str                                      # plan | targets | conventions (reusable, pre-verdict)
    payload: dict = field(default_factory=dict)
    telemetry: dict = field(default_factory=lambda: {"hits": 0, "successes": 0, "failures": 0})
    validation: dict = field(default_factory=dict)
    created: float = 0.0


@dataclass
class KnownValueHint:
    """A banked observed value — a PRIOR for planning/binding ONLY. Deliberately a DISTINCT type that is never
    a verdict input; it carries no path into diff/verdict."""
    key: str
    metric: str
    value: float
    dataset: str = ""
    source: str = ""
    n_seen: int = 1


def key_signature(repo_dir: str) -> str:
    """A cheap repo-family signature: sorted top-level dep names + entry-ish filenames. Paraphrase-robust
    enough to warm-start a similar repo; never used in a verdict."""
    parts = []
    try:
        req = os.path.join(repo_dir, "requirements.txt")
        if os.path.isfile(req):
            for ln in open(req, errors="replace").read(20000).splitlines():
                m = re.match(r"\s*([A-Za-z0-9_.\-]+)", ln)
                if m:
                    parts.append(m.group(1).lower())
        for fn in sorted(os.listdir(repo_dir)) if os.path.isdir(repo_dir) else []:
            if fn.endswith(".py"):
                parts.append(fn.lower())
    except OSError:
        pass
    return "|".join(sorted(set(parts))[:40]) or os.path.basename(repo_dir.rstrip("/"))


class ExperienceBank:
    """JSON-backed experience bank. `lookup` returns only REUSABLE experience (plan/targets/conventions);
    known values are firewalled behind `hints`. Telemetry (hits/successes/failures) tiers competing records."""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "experience_bank.json")
        self.records: list[ExperienceRecord] = []
        self.hints_ns: list[KnownValueHint] = []
        self._load()

    def _load(self):
        if self.path and os.path.isfile(self.path):
            try:
                raw = json.load(open(self.path))
                self.records = [ExperienceRecord(**r) for r in raw.get("records", [])]
                self.hints_ns = [KnownValueHint(**h) for h in raw.get("hints", [])]
            except Exception:  # noqa: BLE001
                self.records, self.hints_ns = [], []

    def _persist(self):
        if not self.path:
            return
        try:
            with open(self.path, "w") as fh:
                json.dump({"records": [asdict(r) for r in self.records],
                           "hints": [asdict(h) for h in self.hints_ns]}, fh)
        except OSError:
            pass

    def bank(self, key: str, kind: str, payload: dict, validation: dict | None = None, ts: float = 0.0):
        """Bank a reusable experience record (plan/targets/conventions). Refuses known_value — those go through
        bank_known_value into the firewalled namespace."""
        if kind not in _REUSABLE:
            raise ValueError("bank() only stores reusable kinds; known_value uses bank_known_value()")
        rec = ExperienceRecord(key=key, kind=kind, payload=payload, validation=validation or {}, created=ts)
        self.records.append(rec)
        self._persist()
        return rec

    def bank_known_value(self, key: str, metric: str, value, dataset: str = "", source: str = "", ts: float = 0.0):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        h = KnownValueHint(key=key, metric=metric, value=v, dataset=dataset, source=source)
        self.hints_ns.append(h)
        self._persist()
        return h

    def lookup(self, key: str, kind: str):
        """Best reusable record for (key, kind), tiered by telemetry (successes - failures). Returns None if
        none. NEVER returns a known_value (that kind is not stored here)."""
        if kind not in _REUSABLE:
            return None
        cands = [r for r in self.records if r.key == key and r.kind == kind]
        if not cands:
            return None
        return max(cands, key=lambda r: r.telemetry.get("successes", 0) - r.telemetry.get("failures", 0))

    def hints(self, key: str, metric: str | None = None) -> list[KnownValueHint]:
        """The firewalled known-value priors for (key[, metric]). Consumed ONLY by planner + binding ranking."""
        return [h for h in self.hints_ns if h.key == key and (metric is None or h.metric == metric)]

    def record_outcome(self, key: str, kind: str, success: bool):
        for r in self.records:
            if r.key == key and r.kind == kind:
                r.telemetry["hits"] = r.telemetry.get("hits", 0) + 1
                r.telemetry["successes" if success else "failures"] += 1
        self._persist()


def bank_experience(result: dict, repo_dir: str, bank: ExperienceBank, plan: dict | None = None) -> None:
    """Write-back hook (best-effort): bank the reusable pre-verdict artifacts (plan / conventions) and,
    separately, observed values from VERIFIED claims into the firewalled hints namespace. Called at the end of
    a verify (opt-in). Never touches the verdict."""
    key = key_signature(repo_dir)
    if plan:
        bank.bank(key, PLAN, {"entry": plan.get("entry"), "pip_install": plan.get("pip_install")})
    conventions = {}
    for rec in result.get("claims") or []:
        if rec.get("convention"):
            conventions[rec.get("metric")] = rec["convention"]
        # observed values from verified records -> the firewalled hints namespace (priors only)
        if rec.get("verdict") in ("CONFIRMED", "CONFIRMED-STOCHASTIC", "REPRODUCED-ONLY"):
            val = (rec.get("diff") or {}).get("recomputed") or (rec.get("diff") or {}).get("produced")
            if val is not None:
                bank.bank_known_value(key, rec.get("metric"), val, source="verified-run")
    if conventions:
        bank.bank(key, CONVENTIONS, conventions)


_DEFAULT_BANK = None


def get_bank(path: str | None = None) -> ExperienceBank:
    global _DEFAULT_BANK
    if path is not None:
        return ExperienceBank(path)
    if _DEFAULT_BANK is None:
        _DEFAULT_BANK = ExperienceBank()
    return _DEFAULT_BANK
