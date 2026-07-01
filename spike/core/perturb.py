"""calma.spike.core.perturb — feature 10 perturbation-fabrication primitives.

A genuine metric is a FUNCTION of its inputs: corrupt the inputs and the number moves. A fabricated /
hard-coded value (a `return 0.95`, a literal copied into results.json) does NOT move — it is invariant under
input perturbation. This module builds the deterministic, seed-controlled corruptions and the two host-side
signals:

  * `sensitivity(cid, inputs, kwargs, recompute)` — how much the trusted ORACLE moves under perturbation
    (P0, advisory). Establishes that the perturbations actually have power on this metric.
  * `verdict_signal(oracle_deltas, repo_deltas)` — the fabrication charge (P1): the oracle moves materially
    on ≥2 perturbations but the REPO's own re-invoked value is bit-invariant across all of them → the
    reported number does not depend on its inputs. Consumed only as a `validity.invalidating` note, so it is
    strictly downgrade-only (CONFIRMED/REPRODUCED-ONLY → INVALIDATED); it never supplies a value or a confirm.

Pure stdlib; never mutates the caller's input dict.
"""
from __future__ import annotations

import random

from . import catalog as C

# a move is "material" (real, not float noise) when it exceeds this relative magnitude — comfortably above the
# recompute tolerance (rtol 1e-6) so benign drift is never mistaken for input-sensitivity.
_MATERIAL_REL = 5e-3

# captured input keys that carry NUMERIC data a metric depends on (labels y_true stay categorical).
_NUMERIC_KEYS = ("y_score", "y_prob", "y_pred", "returns", "values", "a", "b")
_ARRAY_KEYS = ("y_true", "y_pred", "y_score", "y_prob", "returns", "values", "a", "b")


def _is_num_seq(x) -> bool:
    return isinstance(x, (list, tuple)) and len(x) > 0 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in x)


def _seq(x):
    return list(x) if isinstance(x, (list, tuple)) else None


def _default_kinds(cid: str, inputs: dict) -> list[str]:
    has = lambda k: inputs.get(k) is not None  # noqa: E731
    kinds: list[str] = []
    if has("y_score") or has("y_prob"):
        # negate_score deterministically flips a ranking metric (AUC → 1−AUC): a guaranteed material mover
        # even on a perfectly-separated classifier where small noise has no power.
        kinds += ["negate_score", "noise_score", "drop_tail"]
    if has("y_true") and has("y_pred"):
        kinds += ["flip_pred", "shuffle_pred", "drop_tail"]
    if has("returns") or has("values"):
        kinds += ["scale", "noise", "drop_tail"]
    if not kinds:
        kinds = ["drop_tail", "noise"]
    # dedupe preserving order
    seen, out = set(), []
    for k in kinds:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _apply(kind: str, inputs: dict, r: random.Random):
    """Return a perturbed COPY of `inputs`, or None if the kind can't apply to these inputs."""
    d = dict(inputs)
    if kind == "drop_tail":
        # truncate every equal-length array to the first ~80% (keeps arrays aligned; changes the sample).
        lens = {len(v) for k in _ARRAY_KEYS if (v := _seq(inputs.get(k))) is not None}
        if not lens or max(lens) < 5:
            return None
        n = max(lens)
        cut = max(3, int(n * 0.8))
        if cut >= n:
            return None
        changed = False
        for k in _ARRAY_KEYS:
            v = _seq(inputs.get(k))
            if v is not None and len(v) == n:
                d[k] = v[:cut]
                changed = True
        return d if changed else None
    if kind == "flip_pred":
        # flip ~40% of predictions to a DIFFERENT observed class — a guaranteed move for accuracy/F1.
        v = _seq(inputs.get("y_pred"))
        if v is None or len(v) < 3:
            return None
        classes = list({x for x in v})
        if len(classes) < 2:
            return None
        w = list(v)
        idxs = list(range(len(w)))
        r.shuffle(idxs)
        flipped = False
        for i in idxs[:max(1, int(len(w) * 0.4))]:
            alt = next((cl for cl in classes if cl != w[i]), None)
            if alt is not None:
                w[i] = alt
                flipped = True
        if not flipped or w == v:
            return None
        d["y_pred"] = w
        return d
    if kind == "negate_score":
        key = "y_score" if _is_num_seq(inputs.get("y_score")) else ("y_prob" if _is_num_seq(inputs.get("y_prob")) else None)
        if key is None:
            return None
        d[key] = [-float(x) for x in inputs[key]]
        return d
    if kind == "shuffle_pred":
        v = _seq(inputs.get("y_pred"))
        if v is None or len(v) < 3 or len(set(map(str, v))) <= 1:
            return None
        w = list(v)
        for _ in range(8):                       # a few shuffles; bail if it can't change (all-equal handled above)
            r.shuffle(w)
            if w != v:
                break
        if w == v:
            return None
        d["y_pred"] = w
        return d
    if kind in ("noise_score", "noise", "scale"):
        key = "y_score" if kind == "noise_score" else next((k for k in ("returns", "values", "y_pred") if _is_num_seq(inputs.get(k))), None)
        if kind == "noise_score" and not _is_num_seq(inputs.get("y_score")):
            key = "y_prob" if _is_num_seq(inputs.get("y_prob")) else None
        if key is None or not _is_num_seq(inputs.get(key)):
            return None
        v = [float(x) for x in inputs[key]]
        rng = (max(v) - min(v)) or (abs(sum(v) / len(v)) or 1.0)
        if kind == "scale":
            d[key] = [x * 1.7 + 0.3 for x in v]
        else:
            d[key] = [x + r.gauss(0, 0.2 * rng) for x in v]
        return d
    return None


def perturb_inputs(metric: str, inputs: dict, kinds=None, seed: int = 0):
    """[(kind, perturbed_inputs)] — deterministic seed-controlled corruptions designed to MOVE a genuine
    metric. Never mutates `inputs`."""
    if not isinstance(inputs, dict):
        return []
    cid = C.canonical(metric) or (metric or "").strip().lower()
    r = random.Random(seed)
    out = []
    for kind in (kinds or _default_kinds(cid, inputs)):
        p = _apply(kind, inputs, r)
        if p is not None:
            out.append((kind, p))
    return out


def _rel(a: float, b: float) -> float:
    denom = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / denom


def sensitivity(cid: str, inputs: dict, kwargs: dict, recompute, seed: int = 0) -> dict:
    """How much the trusted ORACLE moves under perturbation. `recompute(metric, inputs, kwargs)->Result`.
    Returns {base, per_kind:{kind: rel_delta}, moved_kinds:[...], moved: bool}. Advisory (P0): it does not by
    itself flag fabrication — it proves the perturbations have power, which `verdict_signal` (P1) needs."""
    base = recompute(cid, inputs, kwargs or {})
    if not base or base.get("degenerate"):
        return {"base": None, "per_kind": {}, "moved_kinds": [], "moved": False}
    bv = base["value"]
    per_kind: dict[str, float] = {}
    for kind, pin in perturb_inputs(cid, inputs, seed=seed):
        rr = recompute(cid, pin, kwargs or {})
        if not rr or rr.get("degenerate"):
            continue
        per_kind[kind] = _rel(bv, rr["value"])
    moved_kinds = [k for k, dv in per_kind.items() if dv > _MATERIAL_REL]
    return {"base": bv, "per_kind": per_kind, "moved_kinds": moved_kinds, "moved": len(moved_kinds) >= 1}


def fabrication_from_fuzz(cases, min_cases: int = 4) -> str | None:
    """The fabrication charge from capture.reinvoke fuzz `cases` (feature 10, P1). The repo callable's output
    is INVARIANT across every random input AND every input transform — it does not depend on its inputs at
    all (a hard-coded literal). Returns an invalidating note or None. Downgrade-only.

    A genuine continuous metric produces many distinct values across random inputs; a single distinct value
    across ≥`min_cases` random inputs and their corruptions is the unambiguous fabrication signature. A real
    metric's coincidental constancy across that many independent random draws is negligible."""
    vals = []
    n_base = 0
    for case in cases or []:
        outs = case.get("outputs") or {}
        b = outs.get("base")
        if isinstance(b, (int, float)) and b == b:
            n_base += 1
        for o in outs.values():
            if isinstance(o, (int, float)) and o == o and o not in (float("inf"), float("-inf")):
                vals.append(round(float(o), 12))
    distinct = set(vals)
    if n_base >= min_cases and len(distinct) == 1:
        return ("value does not depend on its inputs — constant %.6g across %d random inputs and their "
                "transforms: fabrication / hard-coded literal" % (next(iter(distinct)), n_base))
    return None


def verdict_signal(oracle_deltas: dict, repo_deltas: dict) -> str | None:
    """The fabrication charge (P1). `oracle_deltas`/`repo_deltas` map kind -> relative move. Fires only when
    the ORACLE moved materially on ≥2 perturbations AND the repo's own re-invoked value was invariant
    (< material) on EVERY perturbation the oracle moved on. Returns an invalidating note, or None.

    Requiring ≥2 oracle-moving perturbations + repo-invariance-on-all-of-them is what keeps a genuine but
    coincidentally-robust metric from being falsely flagged (a real trust cost, not an FCR breach) — a real
    function of the data will move on at least one of several independent corruptions."""
    oracle_moved = [k for k, dv in (oracle_deltas or {}).items() if dv > _MATERIAL_REL]
    if len(oracle_moved) < 2:
        return None
    repo_moved_any = any((repo_deltas or {}).get(k, 0.0) > _MATERIAL_REL for k in oracle_moved)
    if repo_moved_any:
        return None
    return ("value does not depend on its inputs — invariant under %d input perturbation(s) (%s) that move the "
            "metric materially: fabrication / hard-coded literal" % (len(oracle_moved), ", ".join(oracle_moved)))
