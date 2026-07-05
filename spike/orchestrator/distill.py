"""orchestrator.distill — offline experience distillation into the XPU store (build plan §4.3/§7, slice S7).

Aggregate the run-journal (every revise OUTCOME across runs) into conflict-free XPU units carrying REAL
telemetry (Trace2Skill: distill trajectory lessons into a transferable, consolidated skill library, rather
than a low-abstraction per-run memory that causes negative transfer). For each error SIGNATURE:

  1. tally each candidate action's successes/failures across ALL runs (the journal logs failures too — the
     online record-on-win path can't),
  2. pick the WINNING action — the conflict-free choice: highest NET successes (successes − failures), ties
     broken by total successes (prefer the better-EVIDENCED fix, not a lucky 1/1),
  3. DROP (delayed audit) a signature whose best action is net-negative or below the demote floor — a fix that
     doesn't work across runs must never be proposed,
  4. otherwise upsert a dual-modality XPU unit (symptom + action + scope + aggregated telemetry).

Deterministic + HOW-only: a distilled unit only ever proposes an *action* (add-dep / set-env), and the
unchanged recompute still disposes every verdict — so a mis-distilled unit can only cost coverage, never a
false CONFIRM. Imports no ``core.verdict`` / ``core.diff`` (CI firewall). An LLM analyzer fleet that extracts
HIGHER-abstraction lessons ("any libGL error → opencv-python-headless") layers on top of this deterministic
telemetry core — a post-MVP enhancement.
"""
from __future__ import annotations

import json
from collections import defaultdict

from .xpu import _DEMOTE_FLOOR, XPUnit


def _action_key(action: dict) -> str:
    """A stable hashable key for a HOW-only action dict ({"add_dep": ...} / {"set_env": {...}})."""
    return json.dumps(action, sort_keys=True)


def distill(records, xpu) -> dict:
    """Aggregate journal ``records`` ({sig, symptom, action, success, scope?}) → conflict-free XPU units in
    ``xpu``. Returns a summary ``{"absorbed", "pruned", "signatures"}``. Idempotent: re-running over the same
    journal produces the same telemetry (``absorb`` overwrites, never doubles)."""
    by_sig: dict = defaultdict(lambda: defaultdict(
        lambda: {"s": 0, "f": 0, "action": None, "symptom": "", "scope": {}}))
    for r in records or []:
        if not isinstance(r, dict):
            continue
        sig, action = r.get("sig"), r.get("action")
        if not sig or not isinstance(action, dict) or not action:
            continue
        cell = by_sig[sig][_action_key(action)]
        cell["action"] = action
        cell["symptom"] = r.get("symptom") or cell["symptom"] or sig
        if isinstance(r.get("scope"), dict) and r["scope"]:
            cell["scope"] = {**cell["scope"], **r["scope"]}
        if r.get("success"):
            cell["s"] += 1
        else:
            cell["f"] += 1

    absorbed = pruned = 0
    for sig, actions in by_sig.items():
        best = max(actions.values(), key=lambda c: (c["s"] - c["f"], c["s"]))   # net successes, tie → most wins
        total = best["s"] + best["f"]
        rate = (best["s"] / total) if total else 0.0
        if (best["s"] - best["f"]) <= 0 or rate < _DEMOTE_FLOOR:                 # doesn't work across runs → drop
            pruned += 1
            continue
        xpu.absorb(XPUnit(signature=sig, symptom=best["symptom"], action=best["action"],
                          scope=best["scope"], successes=best["s"], failures=best["f"]))
        absorbed += 1
    return {"absorbed": absorbed, "pruned": pruned, "signatures": len(by_sig)}
