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
import sys
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


# ---- call-site provenance (the binding signal) ----------------------------------------------------
_PREFIXES = tuple(p for p in {sys.prefix, sys.base_prefix} if p)


def _call_site():
    """Walk past this shim's own frames to the real caller. Returns (site, user_site): site = file:line of
    the call; user_site = True when the call originates in the REPO's own code, False when it comes from
    inside a library (sklearn's GridSearchCV / CV scorers live in site-packages). This is what lets the
    binder collapse a metric's 31 library-internal computations down to the one the repo's code computed —
    the headline number — without ever looking at the value."""
    try:
        f = sys._getframe(1)
    except Exception:  # noqa: BLE001
        return None, True
    while f is not None:
        fn = f.f_code.co_filename
        if fn.endswith("calma_capture.py"):
            f = f.f_back
            continue
        is_lib = ("site-packages" in fn or "dist-packages" in fn
                  or any(fn.startswith(p) for p in _PREFIXES) or fn.startswith("<"))
        base = fn.rsplit("/", 1)[-1]
        return "%s:%d" % (base, f.f_lineno), (not is_lib)
    return None, True


def _nsamples(inputs):
    """Size of the evaluation (n samples) — for the held-out/train split heuristic. Cheap len of the first
    array-like input (prefer y_true)."""
    for key in ("y_true", "y_score", "y_pred"):
        v = inputs.get(key)
        if v is not None:
            try:
                return int(len(v))
            except (TypeError, ValueError):
                pass
    for v in inputs.values():
        try:
            return int(len(v))
        except (TypeError, ValueError):
            continue
    return None


# ---- the JSONL sink -------------------------------------------------------------------------------
def record(metric, value, *, sink="explicit", label=None, kwargs=None, site=None, user_site=None, n=None,
           **inputs):
    """Public explicit-capture API. Records one captured computation; `**inputs` are the metric's arrays.

    The INTERNAL capture tiers must NOT use this **inputs form when they key inputs by the repo's own
    arbitrary parameter names — a repo metric with a param named `n`/`site`/`sink`/`metric`/... would collide
    with these keyword parameters (silently dropping the input, or raising a swallowed TypeError that loses the
    whole capture). They call `_record` with an inputs DICT instead, which cannot collide."""
    _record(metric, value, inputs, sink=sink, label=label, kwargs=kwargs, site=site, user_site=user_site, n=n)


def _record(metric, value, inputs, *, sink="explicit", label=None, kwargs=None, site=None, user_site=None,
            n=None):
    """Collision-safe recorder: `inputs` is an explicit dict (arbitrary repo param names), never **kwargs.

    site/user_site/n may be passed explicitly by a capture tier that already knows the provenance (the
    sys.monitoring Tier-1 path reads them off the target's own code object); otherwise they're derived from
    the live frame stack (the import-monkeypatch tiers)."""
    if _OUT_PATH[0] is None:
        _OUT_PATH[0] = os.environ.get("CALMA_CAPTURE_OUT")
        if _OUT_PATH[0] is None:
            return  # capture disabled
    budget = _MAX_ELEMS[0]
    ser_inputs, full = {}, True
    for k, v in (inputs or {}).items():
        sv, ok = _to_list(v, budget)
        if not ok:
            full = False
        else:
            ser_inputs[k] = sv
    if site is None and user_site is None:
        site, user_site = _call_site()
    entry = {"sink": sink, "metric": metric, "kwargs": _safe_kwargs(kwargs),
             "result": _result_scalar(value), "captured_full": full,
             "site": site, "user_site": bool(user_site), "n": n if n is not None else _nsamples(inputs or {})}
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
                _record(metric, result, inputs, sink=sink_name, kwargs=kw)
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
                        _record(metric, result, {"y_true": y, "y_pred": y_pred}, sink="sklearn.%s.score" % cls_name)
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
                    _record(metric, result, inputs, sink=sink)
                except Exception:  # noqa: BLE001
                    pass
                return result
            wrapper.__calma_wrapped__ = True
            return wrapper
        setattr(mod, attr, make(orig, metric, mapping, "target:" + target))
        hooked.append(target)
    return hooked


# ---- Tier 1: sys.monitoring (PEP 669) target capture (Python >= 3.12) -----------------------------
# The __main__ capture gap (guide §B.1): install_targets patches an IMPORTED module object, so it MISSES a
# metric defined+called in the entrypoint's own `__main__` (running `python train.py`, the executing script
# IS sys.modules['__main__']; import_module('train') returns a DIFFERENT object we can't reach the function
# through). sys.monitoring hooks the CODE OBJECT's execution, so it observes a target call regardless of where
# the function is defined — __main__, imported, OR in a worker thread (per-interpreter, not per-thread) — reads
# the NAMED args off the frame, and returns DISABLE for every non-target location so overhead is ~0 everywhere
# except the targets. It never mutates repo source, so it cannot change the numbers.
_MON_TARGETS: list = []            # [(attr_name, spec)]
_MON_PENDING = threading.local()   # id(frame) -> [(spec, inputs)] captured at PY_START, emitted at PY_RETURN
_MON_TOOL_ID = [None]


def _mon_pending():
    d = getattr(_MON_PENDING, "d", None)
    if d is None:
        d = {}
        _MON_PENDING.d = d
    return d


def _mon_match(code):
    """Return the spec for a target this code object implements, else None. Matches the target's final dotted
    atom against the code's qualname (top-level fn or method); the module/file is a soft signal only (a
    __main__-defined target's module won't match its filename). A wrong match can only mis-capture inputs that
    then fail the independent recompute (INVALIDATED/INCONCLUSIVE) — never a false CONFIRM."""
    try:
        qual = code.co_qualname
    except AttributeError:
        qual = code.co_name
    last = qual.rsplit(".", 1)[-1]
    for attr, spec in _MON_TARGETS:
        if last == attr or qual == attr or qual.endswith("." + attr):
            return spec
    return None


def _mon_frame_for(code):
    """The innermost active frame whose code is `code` (walk up from the callback). None if not found."""
    try:
        f = sys._getframe(1)
    except Exception:  # noqa: BLE001
        return None
    while f is not None:
        if f.f_code is code:
            return f
        f = f.f_back
    return None


def _mon_read_inputs(spec, f_locals, argnames):
    """Map the spec's inputs ({canonical: 'arg0'|kwname}) to values from the target frame's locals. With no
    mapping, capture every positional parameter under its own name (the value-recompute fallback still gets
    the raw arrays a hand-rolled metric received)."""
    mapping = spec.get("inputs") or {}
    if not mapping:
        return {name: f_locals.get(name) for name in argnames}
    out = {}
    for key, ref in mapping.items():
        if isinstance(ref, str) and ref.startswith("arg") and ref[3:].isdigit():
            i = int(ref[3:])
            out[key] = f_locals.get(argnames[i]) if i < len(argnames) else None
        else:
            out[key] = f_locals.get(ref)
    return out


def _mon_site(code):
    fn = getattr(code, "co_filename", "") or ""
    is_lib = ("site-packages" in fn or "dist-packages" in fn
              or any(fn.startswith(p) for p in _PREFIXES) or fn.startswith("<"))
    base = fn.rsplit("/", 1)[-1]
    return "%s:%d" % (base, getattr(code, "co_firstlineno", 0)), (not is_lib)


def install_targets_monitoring(specs):
    """Arm sys.monitoring PY_START/PY_RETURN filtered to the planner's target functions. Returns the list of
    hooked target paths (empty if unavailable / nothing to hook). Fail-soft; on any error the caller falls
    back to the import-patch tier."""
    mon = getattr(sys, "monitoring", None)
    if mon is None:
        return []
    global _MON_TARGETS
    _MON_TARGETS = []
    hooked = []
    for spec in specs or []:
        target = spec.get("target")
        if not target or not isinstance(target, str):
            continue
        attr = target.rsplit(".", 1)[-1]
        _MON_TARGETS.append((attr, spec))
        hooked.append(target)
    if not _MON_TARGETS:
        return []
    tool_id = None
    for tid in (5, 4, 3, 2):                      # avoid 0/1 (debugger/coverage) + 6/7 (settrace/setprofile)
        try:
            if mon.get_tool(tid) is None:
                tool_id = tid
                break
        except Exception:  # noqa: BLE001
            continue
    if tool_id is None:
        return []
    E = mon.events

    def on_start(code, _offset):
        try:
            spec = _mon_match(code)
            if spec is None:
                return mon.DISABLE                # never re-instrument a non-target location (~0 overhead)
            frame = _mon_frame_for(code)
            if frame is None:
                return None
            argnames = code.co_varnames[:code.co_argcount]
            inputs = _mon_read_inputs(spec, frame.f_locals, argnames)
            _mon_pending().setdefault(id(frame), []).append((spec, inputs))
        except Exception:  # noqa: BLE001 — a capture error must never break the run
            return None
        return None

    def on_return(code, _offset, retval):
        try:
            spec = _mon_match(code)
            if spec is None:
                return mon.DISABLE
            frame = _mon_frame_for(code)
            key = id(frame) if frame is not None else None
            pend = _mon_pending().get(key) if key is not None else None
            if pend:
                spec2, inputs = pend.pop()
                if not pend:
                    _mon_pending().pop(key, None)
                site, user_site = _mon_site(code)
                _record(spec2.get("metric") or _MON_TARGETS[0][0], retval, inputs,
                        sink="target:" + spec2.get("target", "?"), site=site, user_site=user_site)
        except Exception:  # noqa: BLE001
            return None
        return None

    try:
        mon.use_tool_id(tool_id, "calma_capture")
        _MON_TOOL_ID[0] = tool_id
        mon.register_callback(tool_id, E.PY_START, on_start)
        mon.register_callback(tool_id, E.PY_RETURN, on_return)
        mon.set_events(tool_id, E.PY_START | E.PY_RETURN)
    except Exception:  # noqa: BLE001 — monitoring unavailable/occupied → caller falls back to import patch
        try:
            if _MON_TOOL_ID[0] is not None:
                mon.free_tool_id(_MON_TOOL_ID[0])
        except Exception:  # noqa: BLE001
            pass
        return []
    return hooked


# ---- propagate capture across subprocess boundaries -----------------------------------------------
def _install_subprocess_propagation():
    """A repo that spawns per-cell workers with an explicit env= (very common — setting PYTHONHASHSEED /
    OMP_NUM_THREADS for each cell) DROPS our PYTHONPATH + CALMA_CAPTURE_OUT, so the child interpreter never
    arms and its metric computations are captured NOWHERE (the gb_kmer `subprocess-per-cell` hole). Patch
    subprocess.Popen so any child the run spawns inherits the capture env even when the repo supplies its own.
    Only touches calls that pass an explicit env (the failure case); env=None already inherits ours. Fail-soft
    and idempotent — instrumentation must never change what the repo does."""
    try:
        import subprocess
    except Exception:  # noqa: BLE001
        return
    if getattr(subprocess.Popen, "__calma_env_patched__", False):
        return
    orig_init = subprocess.Popen.__init__
    cap_dir = os.path.dirname(os.path.abspath(__file__))

    def __init__(self, *args, **kwargs):
        env = kwargs.get("env")
        if env is not None and _OUT_PATH[0]:                 # repo passed its own env → merge ours back in
            try:
                env = dict(env)
                env.setdefault("CALMA_CAPTURE_OUT", _OUT_PATH[0])
                for var in ("CALMA_CAPTURE_HOOKS", "CALMA_CAPTURE_MAX_ELEMS", "CALMA_CAPTURE_TARGETS",
                            "CALMA_FUZZ", "CALMA_INJECT_SEED"):
                    if os.environ.get(var) is not None:
                        env.setdefault(var, os.environ[var])
                pp = env.get("PYTHONPATH", "")
                if cap_dir not in pp.split(os.pathsep):       # ensure sitecustomize is importable in the child
                    env["PYTHONPATH"] = cap_dir + (os.pathsep + pp if pp else "")
                kwargs["env"] = env
            except Exception:  # noqa: BLE001
                pass
        return orig_init(self, *args, **kwargs)

    try:
        subprocess.Popen.__init__ = __init__
        subprocess.Popen.__calma_env_patched__ = True
    except (TypeError, AttributeError):  # noqa: BLE001 — can't patch (frozen) → children just won't capture
        pass


# ---- bootstrap from env ---------------------------------------------------------------------------
def install_from_env():
    if _INSTALLED[0]:
        return
    _INSTALLED[0] = True
    # feature 15 — force-seed all RNGs for a CHARACTERIZATION run (gated on CALMA_INJECT_SEED). Runs first, so
    # a seed set before any repo import takes effect. Never used to produce a claim (verdict caps it).
    try:
        import seedinject
        seedinject.install_seed_from_env()
    except Exception:  # noqa: BLE001
        pass
    _OUT_PATH[0] = os.environ.get("CALMA_CAPTURE_OUT")
    if not _OUT_PATH[0]:
        return
    _install_subprocess_propagation()   # so subprocess-per-cell repos capture in their children too
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
            specs = json.loads(targets_json)
            # Tier 1 (sys.monitoring) on >=3.12 catches __main__-defined AND imported AND threaded targets;
            # fall back to the Tier-1b import patch if monitoring is unavailable/occupied or <3.12.
            # CALMA_CAPTURE_NOMON=1 forces the legacy path (used to A/B the two tiers).
            use_mon = sys.version_info >= (3, 12) and os.environ.get("CALMA_CAPTURE_NOMON") != "1"
            hooked = install_targets_monitoring(specs) if use_mon else []
            meta["targets"] = hooked or install_targets(specs)
            meta["target_tier"] = "monitoring" if hooked else "import-patch"
            # feature 2/7/10 — arm the in-sandbox re-invocation emitter at interpreter exit (so a
            # __main__-defined target is already defined). Gated on CALMA_FUZZ=1; fail-soft.
            if os.environ.get("CALMA_FUZZ") == "1":
                try:
                    import reinvoke
                    reinvoke.install_atexit(specs, _OUT_PATH[0] + ".fuzz")
                    meta["fuzz_armed"] = True
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
    # a breadcrumb the runner can read to confirm hooks armed (never fatal)
    try:
        with open(_OUT_PATH[0] + ".hooks", "w") as fh:
            json.dump(meta, fh)
    except Exception:  # noqa: BLE001
        pass
