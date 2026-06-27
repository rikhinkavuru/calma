"""calma_capture — instrumented input capture (rebuild guide §4.2b: "intercept and dump the actual arrays
passed to the metric — the raw inputs, not just the printed number").

This is the key new capability of the rebuild. It is auto-loaded inside the sandbox at interpreter startup
(via sitecustomize on PYTHONPATH) and monkeypatches known metric *sinks* so that when the repo computes its
headline number we record, to CALMA_CAPTURE_OUT as JSONL:

    {"seq", "sink", "metric", "inputs": {...arrays...}, "kwargs": {...}, "result": <repo value>, "captured_full"}

Three capture layers (each measured separately by the spike):
  1. auto sklearn.metrics.*    — high-yield, no per-repo work; covers the ML-eval beachhead.
  2. targeted wrap (bind hint) — wrap a named custom function `pkg.mod.fn` and map its args to canonical
     inputs, so a hand-rolled / cheating formula's inputs are still captured -> demonstrates INVALIDATED.
  3. explicit                  — `calma_capture.record(metric, value, **inputs)` for repos we instrument.

Host-side, core.diff recomputes each captured metric independently and three-way-diffs. PURE STDLIB +
duck-typing for numpy/pandas (never imports them); fail-soft (a capture error must never break the run).
"""
from __future__ import annotations

import json
import os
import threading

_LOCK = threading.Lock()
_DEPTH = threading.local()
_SEQ = [0]


def _enter():
    """Reentrancy guard: returns True only for the OUTERMOST wrapped metric call. A repo's
    `model.score()` internally calls our patched `accuracy_score`; without this we'd record the same
    computation twice (-> ambiguous binding). Record only the outermost; suppress nested captures."""
    n = getattr(_DEPTH, "n", 0)
    _DEPTH.n = n + 1
    return n == 0


def _leave():
    _DEPTH.n = getattr(_DEPTH, "n", 1) - 1
_OUT_PATH = [None]
_MAX_ELEMS = [5_000_000]
_INSTALLED = [False]


# ---- serialization (numpy/pandas via duck-typing; bounded) ----------------------------------------
def _to_list(x, budget):
    """(list|scalar|None, ok). ok=False -> too large / not 1-D-serializable (host treats as uncaptured)."""
    if x is None:
        return None, True
    if isinstance(x, bool):
        return (1 if x else 0), True
    if isinstance(x, (int, float, str)):
        return x, True
    # numpy / pandas / array-likes expose .tolist() and .size/.shape
    shape = getattr(x, "shape", None)
    if shape is not None and hasattr(x, "tolist"):
        if len(shape) != 1:
            return None, False  # 2-D (e.g. multiclass scores) — out of spike scope
        if shape[0] > budget:
            return None, False
        try:
            return [_scalar(v) for v in x.tolist()], True
        except Exception:  # noqa: BLE001
            return None, False
    if isinstance(x, (list, tuple)):
        if len(x) > budget:
            return None, False
        out = []
        for v in x:
            sv, ok = _to_list(v, budget)
            if not ok or isinstance(sv, list):
                return None, False  # nested / unserializable element
            out.append(sv)
        return out, True
    # pandas Series without .shape? try tolist
    if hasattr(x, "tolist"):
        try:
            lst = x.tolist()
            if len(lst) > budget:
                return None, False
            return [_scalar(v) for v in lst], True
        except Exception:  # noqa: BLE001
            return None, False
    return None, False


def _scalar(v):
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float, str)):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return str(v)


def _result_scalar(r):
    if isinstance(r, bool):
        return 1.0 if r else 0.0
    try:
        return float(r)
    except (TypeError, ValueError):
        return None


# ---- the JSONL sink -------------------------------------------------------------------------------
def record(metric, value, *, sink="explicit", label=None, kwargs=None, **inputs):
    """Public explicit-capture API (and the internal recorder). Records one captured computation."""
    if _OUT_PATH[0] is None:
        _OUT_PATH[0] = os.environ.get("CALMA_CAPTURE_OUT")
        if _OUT_PATH[0] is None:
            return  # capture disabled
    budget = _MAX_ELEMS[0]
    ser_inputs, full = {}, True
    for k, v in inputs.items():
        sv, ok = _to_list(v, budget)
        if not ok:
            full = False
        else:
            ser_inputs[k] = sv
    entry = {"sink": sink, "metric": metric, "kwargs": _safe_kwargs(kwargs),
             "result": _result_scalar(value), "captured_full": full}
    if full:
        entry["inputs"] = ser_inputs
    if label is not None:
        entry["label"] = label
    _emit(entry)


def _safe_kwargs(kwargs):
    if not kwargs:
        return {}
    out = {}
    for k, v in kwargs.items():
        if isinstance(v, (bool, int, float, str)) or v is None:
            out[k] = v
    return out


def _emit(entry):
    try:
        with _LOCK:
            entry["seq"] = _SEQ[0]
            _SEQ[0] += 1
            with open(_OUT_PATH[0], "a") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
    except Exception:  # noqa: BLE001 — capture must never break the run under test
        pass


# ---- sklearn.metrics adapters ---------------------------------------------------------------------
def _get(args, kwargs, idx, name):
    if len(args) > idx:
        return args[idx]
    return kwargs.get(name)


def _ad_classify(metric):
    def extract(args, kwargs):
        return metric, {"y_true": _get(args, kwargs, 0, "y_true"),
                        "y_pred": _get(args, kwargs, 1, "y_pred")}, \
            {k: kwargs[k] for k in ("normalize", "pos_label", "average") if k in kwargs}
    return extract


def _ad_auc(args, kwargs):
    return "roc_auc", {"y_true": _get(args, kwargs, 0, "y_true"),
                       "y_score": _get(args, kwargs, 1, "y_score")}, {}


def _ad_mse(args, kwargs):
    squared = kwargs.get("squared", True)
    metric = "mse" if squared else "rmse"
    return metric, {"y_true": _get(args, kwargs, 0, "y_true"),
                    "y_pred": _get(args, kwargs, 1, "y_pred")}, {}


def _ad_reg(metric):
    def extract(args, kwargs):
        return metric, {"y_true": _get(args, kwargs, 0, "y_true"),
                        "y_pred": _get(args, kwargs, 1, "y_pred")}, {}
    return extract


_SKLEARN_ADAPTERS = {
    "accuracy_score": _ad_classify("accuracy"),
    "balanced_accuracy_score": _ad_classify("balanced_accuracy"),
    "precision_score": _ad_classify("precision"),
    "recall_score": _ad_classify("recall"),
    "f1_score": _ad_classify("f1"),
    "roc_auc_score": _ad_auc,
    "mean_squared_error": _ad_mse,
    "root_mean_squared_error": _ad_reg("rmse"),
    "mean_absolute_error": _ad_reg("mae"),
    "r2_score": _ad_reg("r2"),
    # metrics not in the curated catalog — captured here, recomputed via the recipes / synth flywheel:
    "matthews_corrcoef": _ad_classify("mcc"),
    "cohen_kappa_score": _ad_classify("cohen_kappa"),
    "log_loss": lambda a, k: ("log_loss", {"y_true": _get(a, k, 0, "y_true"),
                                           "y_score": _get(a, k, 1, "y_pred")}, {}),
    "brier_score_loss": lambda a, k: ("brier", {"y_true": _get(a, k, 0, "y_true"),
                                                "y_score": _get(a, k, 1, "y_prob")}, {}),
}


def _wrap(orig, sink_name, extract):
    def wrapper(*args, **kwargs):
        outer = _enter()
        try:
            result = orig(*args, **kwargs)
        finally:
            _leave()
        if outer:
            try:
                metric, inputs, kw = extract(args, kwargs)
                record(metric, result, sink=sink_name, kwargs=kw, **inputs)
            except Exception:  # noqa: BLE001
                pass
        return result
    wrapper.__name__ = getattr(orig, "__name__", "wrapped")
    wrapper.__wrapped__ = orig
    wrapper.__calma_wrapped__ = True
    return wrapper


def install_sklearn(names=None):
    try:
        import sklearn.metrics as M
    except Exception:  # noqa: BLE001 — repo doesn't use sklearn; nothing to hook
        return []
    hooked = []
    for fn_name, extract in _SKLEARN_ADAPTERS.items():
        if names and fn_name not in names:
            continue
        orig = getattr(M, fn_name, None)
        if orig is None or getattr(orig, "__calma_wrapped__", False):
            continue
        setattr(M, fn_name, _wrap(orig, "sklearn.metrics." + fn_name, extract))
        hooked.append(fn_name)
    return hooked + install_sklearn_scores()


def install_sklearn_scores():
    """Hook the estimator `.score()` mixins. Hugely common in real repos (`model.score(X, y)`) and it
    bypasses the public sklearn.metrics functions — ClassifierMixin.score computes accuracy internally,
    RegressorMixin.score computes R². We capture (y_true=y, y_pred=estimator.predict(X)) + the score, so the
    three-way diff works on score()-style evals too. (Found by the Phase-0 spike on a real iris repo.)"""
    hooked = []
    try:
        from sklearn.base import ClassifierMixin, RegressorMixin
    except Exception:  # noqa: BLE001
        return hooked
    for cls, metric in ((ClassifierMixin, "accuracy"), (RegressorMixin, "r2")):
        orig = cls.__dict__.get("score")
        if orig is None or getattr(orig, "__calma_wrapped__", False):
            continue

        def make(orig, metric, cls_name):
            def score(self, X, y, sample_weight=None):
                outer = _enter()
                try:
                    result = orig(self, X, y, sample_weight=sample_weight)
                finally:
                    _leave()
                if outer:
                    try:
                        y_pred = self.predict(X)
                        record(metric, result, sink="sklearn.%s.score" % cls_name, y_true=y, y_pred=y_pred)
                    except Exception:  # noqa: BLE001
                        pass
                return result
            score.__calma_wrapped__ = True
            return score
        try:
            cls.score = make(orig, metric, cls.__name__)
            hooked.append("%s.score" % cls.__name__)
        except (TypeError, AttributeError):
            pass
    return hooked


# ---- targeted wrap of a named custom function (bind hint) ------------------------------------------
def install_targets(specs):
    """specs: [{"target":"pkg.mod.fn", "metric":"sharpe", "inputs":{"returns":"arg0"}, "result":"return"}].
    Wraps the named function so its args (mapped to canonical inputs) + return are captured -> lets the
    three-way diff catch a hand-rolled / cheating formula (INVALIDATED). 'argN' indexes positionals."""
    import importlib
    import sys
    cwd = os.getcwd()  # the entrypoint's dir; a repo's own metric module lives here under the sandbox
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    hooked = []
    for spec in specs or []:
        target = spec.get("target")
        if not target or "." not in target:
            continue
        mod_name, _, attr = target.rpartition(".")
        try:
            mod = importlib.import_module(mod_name)
            orig = getattr(mod, attr)
        except Exception:  # noqa: BLE001
            continue
        if getattr(orig, "__calma_wrapped__", False):
            continue
        metric = spec.get("metric") or attr
        mapping = spec.get("inputs") or {}

        def make(orig, metric, mapping, sink):
            def wrapper(*args, **kwargs):
                result = orig(*args, **kwargs)
                try:
                    inputs = {}
                    for key, ref in mapping.items():
                        if isinstance(ref, str) and ref.startswith("arg"):
                            i = int(ref[3:])
                            inputs[key] = args[i] if len(args) > i else None
                        else:
                            inputs[key] = kwargs.get(ref)
                    record(metric, result, sink=sink, **inputs)
                except Exception:  # noqa: BLE001
                    pass
                return result
            wrapper.__calma_wrapped__ = True
            return wrapper
        setattr(mod, attr, make(orig, metric, mapping, "target:" + target))
        hooked.append(target)
    return hooked


# ---- bootstrap from env ---------------------------------------------------------------------------
def install_from_env():
    if _INSTALLED[0]:
        return
    _INSTALLED[0] = True
    _OUT_PATH[0] = os.environ.get("CALMA_CAPTURE_OUT")
    if not _OUT_PATH[0]:
        return
    try:
        _MAX_ELEMS[0] = int(os.environ.get("CALMA_CAPTURE_MAX_ELEMS", "5000000"))
    except ValueError:
        pass
    hooks = (os.environ.get("CALMA_CAPTURE_HOOKS") or "sklearn").split(",")
    meta = {"sklearn": [], "targets": []}
    if "sklearn" in hooks:
        meta["sklearn"] = install_sklearn()
    targets_json = os.environ.get("CALMA_CAPTURE_TARGETS")
    if targets_json:
        try:
            meta["targets"] = install_targets(json.loads(targets_json))
        except Exception:  # noqa: BLE001
            pass
    # a breadcrumb the runner can read to confirm hooks armed (never fatal)
    try:
        with open(_OUT_PATH[0] + ".hooks", "w") as fh:
            json.dump(meta, fh)
    except Exception:  # noqa: BLE001
        pass
