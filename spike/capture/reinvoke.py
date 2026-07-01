"""capture.reinvoke — in-sandbox re-invocation emitter (features 2 / 7 / 10).

After a repo's entrypoint runs, this re-invokes the repo's OWN metric callable(s) on FRESH, canonical, seeded
inputs and writes each `(inputs, outputs)` to `CALMA_CAPTURE_OUT + '.fuzz'` as JSONL. Three host-side
consumers read that file:

  * feature 2  (core.formula_diff)  — differential-tests the repo's `base` output against the trusted catalog
    on many random inputs: "the number matches" becomes "the function IS the metric."
  * feature 7  (core.metamorphic)   — checks the repo's outputs honour exact analytic relations between an
    input and its transform (permute samples → accuracy unchanged; negate scores → AUC → 1−AUC).
  * feature 10 (core.perturb)        — flags a value that is INVARIANT under input corruptions the metric must
    move under (a hard-coded literal).

All three are DOWNGRADE-ONLY host-side. This module only RE-INVOKES the repo's own function — it never mutates
repo source and never touches the verdict, so it cannot change the repo's real numbers. Pure stdlib; fail-soft
by construction (any error skips a variant / a target; a missing .fuzz file just leaves the verdict where it
was). Gated on CALMA_FUZZ=1 (and armed at interpreter exit so __main__-defined targets are resolvable).
"""
from __future__ import annotations

import json
import random
import sys

# canonical metric → input family (the shape of inputs to synthesize + which transforms apply). The spec's
# `metric` is already canonical (the planner sets it), so an exact lookup suffices; unknown → no fuzz.
_FAMILY = {
    "accuracy": "labels", "balanced_accuracy": "labels", "f1": "labels", "precision": "labels",
    "recall": "labels", "mcc": "labels", "cohen_kappa": "labels",
    "roc_auc": "ranking",
    "mse": "regression", "rmse": "regression", "mae": "regression", "r2": "regression",
    "sharpe": "finance", "sortino": "finance", "calmar": "finance",
    "mean": "reduction1", "sum": "reduction1", "total_sum": "reduction1", "stdev": "reduction1",
    "variance": "reduction1",
    "correlation": "corr", "spearman": "corr", "pearson": "corr", "kendall": "corr",
}

# family → the transform tags to emit outputs for (a superset of what any one consumer needs).
_FAMILY_TAGS = {
    "labels": ["perm_samples", "perm_labels", "flip_pred", "drop_tail"],
    "ranking": ["perm_samples", "neg_score", "noise", "drop_tail"],
    "regression": ["perm_samples", "translate", "scale_pos", "drop_tail"],
    "finance": ["perm_samples", "scale_pos", "drop_tail", "noise"],
    "reduction1": ["perm_samples", "scale_pos", "drop_tail", "noise"],
    "corr": ["perm_samples", "neg_second", "scale_pos", "drop_tail"],
}


# ---- canonical input generators (keys match core.catalog's expected inputs) ------------------------
def _gen(family: str, rng: random.Random, n: int = 40) -> dict | None:
    if family == "labels":
        yt = [rng.randint(0, 1) for _ in range(n)]
        yt[0], yt[1] = 0, 1                                   # guarantee ≥2 classes
        yp = [yt[i] if rng.random() < 0.8 else 1 - yt[i] for i in range(n)]
        return {"y_true": yt, "y_pred": yp}
    if family == "ranking":
        yt = [rng.randint(0, 1) for _ in range(n)]
        yt[0], yt[1] = 0, 1
        ys = [rng.random() * 0.4 + (0.4 if yt[i] else 0.0) for i in range(n)]   # separable-ish, not perfect
        return {"y_true": yt, "y_score": ys}
    if family == "regression":
        yt_r = [rng.gauss(0, 1) for _ in range(n)]
        yp_r = [yt_r[i] + rng.gauss(0, 0.3) for i in range(n)]
        return {"y_true": yt_r, "y_pred": yp_r}
    if family == "finance":
        return {"returns": [rng.gauss(0.001, 0.02) for _ in range(n)]}
    if family == "reduction1":
        return {"values": [rng.gauss(0, 1) for _ in range(n)]}
    if family == "corr":
        a = [rng.gauss(0, 1) for _ in range(n)]
        b = [a[i] * 0.7 + rng.gauss(0, 0.5) for i in range(n)]
        return {"x": a, "y": b}
    return None


# ---- generic transforms (tag → inputs' | None). Never mutate the input dict. ------------------------
_ARRAYS = ("y_true", "y_pred", "y_score", "y_prob", "returns", "values", "x", "y", "a", "b")
_NUM = ("y_score", "y_prob", "returns", "values", "x", "y", "a", "b", "y_pred")


def _arrs(inp):
    return {k: list(v) for k, v in inp.items() if isinstance(v, (list, tuple))}


def _t_perm_samples(inp, rng):
    arrs = _arrs(inp)
    lens = {len(v) for v in arrs.values()}
    if len(lens) != 1 or next(iter(lens)) < 3:
        return None
    n = next(iter(lens))
    order = list(range(n))
    rng.shuffle(order)
    if order == list(range(n)):
        return None
    d = dict(inp)
    for k, v in arrs.items():
        d[k] = [v[i] for i in order]
    return d


def _t_perm_labels(inp, rng):
    yt, yp = inp.get("y_true"), inp.get("y_pred")
    if not isinstance(yt, (list, tuple)) or not isinstance(yp, (list, tuple)):
        return None
    classes = sorted({*yt, *yp}, key=str)
    if len(classes) < 2:
        return None
    perm = list(classes)
    for _ in range(6):
        rng.shuffle(perm)
        if perm != classes:
            break
    if perm == classes:
        return None
    m = dict(zip(classes, perm))
    d = dict(inp)
    d["y_true"] = [m[v] for v in yt]
    d["y_pred"] = [m[v] for v in yp]
    return d


def _t_neg_score(inp, rng):
    key = "y_score" if isinstance(inp.get("y_score"), (list, tuple)) else ("y_prob" if isinstance(inp.get("y_prob"), (list, tuple)) else None)
    if key is None:
        return None
    d = dict(inp)
    d[key] = [-float(x) for x in inp[key]]
    return d


def _t_neg_second(inp, rng):
    key = "y" if isinstance(inp.get("y"), (list, tuple)) else ("b" if isinstance(inp.get("b"), (list, tuple)) else None)
    if key is None:
        return None
    d = dict(inp)
    d[key] = [-float(x) for x in inp[key]]
    return d


def _t_scale_pos(inp, rng):
    d, changed = dict(inp), False
    for k in _NUM:
        v = inp.get(k)
        if isinstance(v, (list, tuple)) and v and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            d[k] = [float(x) * 1.5 for x in v]
            changed = True
    return d if changed else None


def _t_translate(inp, rng):
    yt, yp = inp.get("y_true"), inp.get("y_pred")
    if not (isinstance(yt, (list, tuple)) and isinstance(yp, (list, tuple))):
        return None
    c = 3.0
    d = dict(inp)
    d["y_true"] = [float(x) + c for x in yt]
    d["y_pred"] = [float(x) + c for x in yp]
    return d


def _t_drop_tail(inp, rng):
    arrs = _arrs(inp)
    lens = {len(v) for v in arrs.values()}
    if len(lens) != 1:
        return None
    n = next(iter(lens))
    cut = max(3, int(n * 0.8))
    if cut >= n:
        return None
    d = dict(inp)
    for k, v in arrs.items():
        d[k] = v[:cut]
    return d


def _t_flip_pred(inp, rng):
    yp = inp.get("y_pred")
    if not isinstance(yp, (list, tuple)) or len(yp) < 3:
        return None
    classes = list({*yp})
    if len(classes) < 2:
        return None
    w = list(yp)
    idxs = list(range(len(w)))
    rng.shuffle(idxs)
    for i in idxs[:max(1, int(len(w) * 0.4))]:
        alt = next((cl for cl in classes if cl != w[i]), None)
        if alt is not None:
            w[i] = alt
    if w == list(yp):
        return None
    d = dict(inp)
    d["y_pred"] = w
    return d


def _t_noise(inp, rng):
    d, changed = dict(inp), False
    for k in _NUM:
        v = inp.get(k)
        if isinstance(v, (list, tuple)) and v and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            rng2 = (max(v) - min(v)) or 1.0
            d[k] = [float(x) + rng.gauss(0, 0.15 * rng2) for x in v]
            changed = True
    return d if changed else None


_TRANSFORMS = {
    "perm_samples": _t_perm_samples, "perm_labels": _t_perm_labels, "neg_score": _t_neg_score,
    "neg_second": _t_neg_second, "scale_pos": _t_scale_pos, "translate": _t_translate,
    "drop_tail": _t_drop_tail, "flip_pred": _t_flip_pred, "noise": _t_noise,
}


# ---- call the repo's own callable, mapped from canonical inputs to its args -------------------------
def _resolve(target: str):
    """Resolve a target callable WITHOUT re-running any repo code. Order, chosen to avoid re-executing a
    script entrypoint (running `python eval.py` makes the module `__main__`, not `eval`, so importing `eval`
    would re-run the whole script): (1) an ALREADY-loaded module of the given name; (2) the running __main__;
    (3) only as a last resort, import a genuinely-unloaded library module. None on any failure — fuzz then
    simply skips this target (fail-closed)."""
    if not target:
        return None
    attr = target.rsplit(".", 1)[-1]
    mod_name = target.rsplit(".", 1)[0] if "." in target else None
    # (1) module already imported during the run — safe, no re-execution.
    if mod_name and mod_name in sys.modules:
        fn = getattr(sys.modules[mod_name], attr, None)
        if callable(fn):
            return fn
    # (2) defined in the running entrypoint's __main__ (the common hand-rolled-metric case).
    main = sys.modules.get("__main__")
    fn = getattr(main, attr, None) if main else None
    if callable(fn):
        return fn
    # (3) a library module that was never loaded during the run (rare — the metric was never called). Import
    # is a last resort; a script that would re-run is already handled by (1)/(2).
    if mod_name:
        try:
            import importlib
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, attr, None)
            return fn if callable(fn) else None
        except Exception:  # noqa: BLE001
            return None
    return None


def _scalar(x):
    if isinstance(x, bool):
        return 1.0 if x else 0.0
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _call(fn, mapping: dict, gen: dict):
    """Invoke `fn` with canonical `gen` values mapped to its args per `mapping` {canonical: 'argN'|kwname}."""
    pos, kw = {}, {}
    for key, ref in (mapping or {}).items():
        if key not in gen:
            continue
        if isinstance(ref, str) and ref.startswith("arg") and ref[3:].isdigit():
            pos[int(ref[3:])] = gen[key]
        else:
            kw[ref] = gen[key]
    if pos:
        n = max(pos) + 1
        args = [pos.get(i) for i in range(n)]
        return fn(*args, **kw)
    if kw:
        return fn(**kw)
    # no mapping → best effort: pass the canonical values positionally in a stable order
    return fn(*[gen[k] for k in sorted(gen)])


def _default_mapping(family: str) -> dict:
    return {
        "labels": {"y_true": "arg0", "y_pred": "arg1"},
        "ranking": {"y_true": "arg0", "y_score": "arg1"},
        "regression": {"y_true": "arg0", "y_pred": "arg1"},
        "finance": {"returns": "arg0"},
        "reduction1": {"values": "arg0"},
        "corr": {"x": "arg0", "y": "arg1"},
    }.get(family, {})


def fuzz_target(spec: dict, k: int = 16, seed: int = 1234) -> dict | None:
    """Re-invoke one target on k seeded random inputs + their transforms. Returns the emit record or None if
    the target can't be fuzzed (unknown family / unresolvable callable / base call fails)."""
    metric = (spec.get("metric") or "").strip().lower()
    family = _FAMILY.get(metric)
    if family is None:
        return None
    fn = _resolve(spec.get("target") or "")
    if not callable(fn):
        return None
    mapping = spec.get("inputs") or _default_mapping(family)
    if not mapping:
        mapping = _default_mapping(family)
    rng = random.Random(seed)
    cases = []
    for i in range(k):
        gen = _gen(family, rng, n=40)
        if gen is None:
            break
        try:
            base = _scalar(_call(fn, mapping, gen))
        except Exception:  # noqa: BLE001 — repo fn errored on synthetic input; skip this case
            continue
        if base is None:
            continue
        outputs = {"base": base}
        for tag in _FAMILY_TAGS.get(family, []):
            tf = _TRANSFORMS.get(tag)
            pin = tf(gen, rng) if tf else None
            if pin is None:
                continue
            try:
                outputs[tag] = _scalar(_call(fn, mapping, pin))
            except Exception:  # noqa: BLE001
                continue
        cases.append({"i": i, "inputs": gen, "outputs": outputs})
    if not cases:
        return None
    return {"target": spec.get("target"), "metric": metric, "family": family, "cases": cases}


def run_fuzz(specs, out_path: str, k: int = 16, seed: int = 1234) -> int:
    """Emit fuzz records for every fuzzable target spec to `out_path` (JSONL, one record per target). Returns
    the number of targets emitted. Fail-soft throughout."""
    n = 0
    try:
        with open(out_path, "a") as fh:
            for spec in specs or []:
                try:
                    rec = fuzz_target(spec, k=k, seed=seed)
                except Exception:  # noqa: BLE001
                    rec = None
                if rec:
                    fh.write(json.dumps(rec, default=str) + "\n")
                    n += 1
    except Exception:  # noqa: BLE001 — emission must never break the run
        return n
    return n


def install_atexit(specs, out_path: str):
    """Arm fuzz emission at interpreter exit (so __main__-defined targets are already defined). Idempotent."""
    import atexit
    done = [False]

    def _run():
        if done[0]:
            return
        done[0] = True
        run_fuzz(specs, out_path)

    atexit.register(_run)
