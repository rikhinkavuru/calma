"""calma.spike.synth.xcheck — differential recompute (feature 17).

Belt-and-suspenders against a latent bug in the recompute itself: require TWO independent recompute paths to
AGREE before trusting a recompute. Its real, bounded value is cross-checking the SYNTH / RECIPE paths
(generated or lifted code, not curated to 1e-9) against the native catalog.

FCR posture — strictly DOWNGRADE-ONLY and ASYMMETRIC (the Knight–Leveson lesson: agreeing versions do not fail
independently, so agreement is NOT independent evidence):
  * DISAGREE → the recompute is no longer trustworthy → force it DEGENERATE, so the verdict falls to
    REPRODUCED-ONLY/INCONCLUSIVE instead of confirming on a possibly-buggy oracle (a strict tightening of FCR).
  * AGREE → do NOT raise confidence beyond what a single trusted catalog already grants — CONFIRMED is reached
    exactly as before.
Net: F17 can only ever REMOVE a CONFIRMED, never add one.
"""
from __future__ import annotations


def crosscheck(metric, inputs, kwargs, paths, close) -> dict:
    """`paths`: {name: recompute_fn(metric, inputs, kwargs) -> Result|None}. Computes every non-degenerate
    path and compares with `close`. Returns {agree, n_paths, values, provenances}. With <2 resolvable paths
    there is nothing to cross-check → agree=True (no downgrade)."""
    values, provs = [], []
    for name, fn in (paths or {}).items():
        try:
            r = fn(metric, inputs, kwargs)
        except Exception:  # noqa: BLE001
            r = None
        if r and not r.get("degenerate") and r.get("value") == r.get("value"):   # finite, non-degenerate
            values.append(r["value"])
            provs.append(name)
    if len(values) < 2:
        return {"agree": True, "n_paths": len(values), "values": values, "provenances": provs}
    agree = all(close(values[0], x) for x in values[1:])
    return {"agree": agree, "n_paths": len(values), "values": values, "provenances": provs}


def reconcile(recomputed: dict, shadow_value, close) -> dict:
    """Fold a single independent SHADOW recompute into the primary `recomputed` result. On disagreement, return
    a DEGENERATE result (fail-closed). On agreement (or no shadow), return `recomputed` unchanged — never
    upgraded. `shadow_value` is None when no independent path resolved."""
    if not recomputed or recomputed.get("degenerate") or shadow_value is None:
        return recomputed
    if shadow_value != shadow_value:                         # NaN shadow — ignore (no independent evidence)
        return recomputed
    if close(recomputed.get("value"), shadow_value):
        return recomputed                                    # agreement adds no confidence, changes nothing
    return {**recomputed, "degenerate": True,
            "note": "recompute paths disagree (primary=%.8g vs independent=%.8g) — cannot trust the oracle"
                    % (recomputed.get("value", float("nan")), shadow_value)}
