"""calma.dsl - the constrained recipe-composition language the compiler admits programs in.

A program is a JSON expression TREE over the existing deterministic kernels (numeric.py) -
column refs, literals, kernel calls, scalar arithmetic, elementwise zips. No loops, no
recursion, no names, no I/O: every program is TOTAL AND TERMINATING BY CONSTRUCTION (a finite
tree evaluates in one bottom-up pass), and the validator enforces depth/size budgets so a
hostile draft cannot DoS the gate. This is the eBPF-verifier idea applied to metrics:
verification is tractable because the language cannot express anything that doesn't halt.

Types are inferred bottom-up: `list` (numeric column), `rawlist` (string column), `scalar`.
A program that doesn't type-check never executes. Execution is bit-stable: kernels are the
same fsum/range-reduction kernels every shipped recipe uses, scalar ops are IEEE primitives,
and division by zero degrades to NaN (the verdict layer treats NaN as degenerate - INCONCLUSIVE,
never a crash, never a guess).

Node forms:
  {"col": "<tag>"}                                  -> list | rawlist (per program inputs)
  {"lit": 3.0}                                      -> scalar
  {"call": "<kernel>", "args": [...], "scalars": {...}}  -> scalar  (whitelisted kernels only)
  {"op": "+|-|*|/|neg|abs|sqrt|log|exp|min|max", "args": [...]} -> scalar
  {"zip": "+|-|*|/", "args": [<list|scalar>, <list|scalar>]}    -> list  (elementwise, broadcasts)
  {"len": <list node>}                              -> scalar

Library: validate(program), execute(program, tag_values), program_hash(program), KERNELS.
"""
import hashlib
import json
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numeric as N  # noqa: E402

_KERNEL_ERRORS = (ValueError, ZeroDivisionError, OverflowError, IndexError, KeyError,
                  TypeError, statistics.StatisticsError)

SCHEMA = "calma/recipe-dsl@1"
MAX_DEPTH = 16
MAX_NODES = 256

# The kernel whitelist: name -> (callable, [arg types], {scalar kwarg: required?}).
# Only column->scalar kernels from numeric.py; everything here is already reference-validated
# by the 385-vector harness for the shipped recipes that use it.
KERNELS = {
    # one numeric column -> scalar
    "fmean": (N.fmean, ["list"], {}),
    "fvar": (N.fvar, ["list"], {"ddof": False}),
    "fstd": (N.fstd, ["list"], {"ddof": False}),
    "col_sum": (N.col_sum, ["list"], {}),
    "col_min": (N.col_min, ["list"], {}),
    "col_max": (N.col_max, ["list"], {}),
    "quantile": (N.quantile, ["list"], {"q": True}),
    "iqr": (N.iqr, ["list"], {}),
    "skewness": (N.skewness, ["list"], {}),
    "kurtosis_excess": (N.kurtosis_excess, ["list"], {}),
    "autocorrelation": (N.autocorrelation, ["list"], {"lag": False}),
    "gini_coefficient": (N.gini_coefficient, ["list"], {}),
    "hhi": (N.hhi, ["list"], {}),
    "total_return": (N.total_return, ["list"], {}),
    "max_drawdown": (N.max_drawdown, ["list"], {}),
    "volatility": (N.volatility, ["list"], {"periods": True}),
    "downside_deviation": (N.downside_deviation, ["list"], {"periods": True}),
    "value_at_risk": (N.value_at_risk, ["list"], {"level": True}),
    "cvar": (N.cvar, ["list"], {"level": True}),
    "win_rate": (N.win_rate, ["list"], {}),
    "profit_factor": (N.profit_factor, ["list"], {}),
    "omega_ratio": (N.omega_ratio, ["list"], {"threshold": False}),
    "throughput": (N.throughput, ["list"], {}),
    "peak": (N.peak, ["list"], {}),
    "coverage_fraction": (N.coverage_fraction, ["list"], {}),
    # two numeric columns -> scalar
    "rmse": (N.rmse, ["list", "list"], {}),
    "mae": (N.mae, ["list", "list"], {}),
    "r2": (N.r2, ["list", "list"], {}),
    "medae": (N.medae, ["list", "list"], {}),
    "max_error": (N.max_error, ["list", "list"], {}),
    "wape": (N.wape, ["list", "list"], {}),
    "pearson_r": (N.pearson_r, ["list", "list"], {}),
    "spearman_r": (N.spearman_r, ["list", "list"], {}),
    "beta": (N.beta, ["list", "list"], {}),
    "accuracy": (N.accuracy, ["list", "list"], {}),
    "precision": (N.precision, ["list", "list"], {}),
    "recall": (N.recall, ["list", "list"], {}),
    "f1": (N.f1, ["list", "list"], {}),
    "auc": (N.auc, ["list", "list"], {}),
    "brier": (N.brier, ["list", "list"], {}),
    # one raw (string) column -> scalar
    "null_fraction": (N.null_fraction, ["rawlist"], {}),
    "distinct_count": (N.distinct_count, ["rawlist"], {"include_null": False}),
    "duplicate_count": (N.duplicate_count, ["rawlist"], {}),
    "mode_share": (N.mode_share, ["rawlist"], {}),
    "cat_entropy": (N.cat_entropy, ["rawlist"], {"base": False}),
}

_SCALAR_OPS = {"+", "-", "*", "/", "neg", "abs", "sqrt", "log", "exp", "min", "max"}
_ZIP_OPS = {"+", "-", "*", "/"}
_UNARY = {"neg", "abs", "sqrt", "log", "exp"}


def program_hash(program):
    """Content address of a program: sha256 over canonical JSON. The frozen identity."""
    return hashlib.sha256(
        json.dumps(program, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ---- validation (the admission gate's stage 0; also re-run at load time) ----

def validate(program):
    """A list of error strings; empty means the program is well-formed, well-typed, within
    budget, and references only declared inputs and whitelisted kernels."""
    errs = []
    if not isinstance(program, dict) or program.get("schema") != SCHEMA:
        return ["program.schema must be %r" % SCHEMA]
    inputs = program.get("inputs")
    if (not isinstance(inputs, dict) or not inputs
            or not all(isinstance(k, str) and v in ("list", "rawlist") for k, v in inputs.items())):
        return ["program.inputs must map tag -> 'list'|'rawlist' (at least one input)"]
    expr = program.get("expr")
    if not isinstance(expr, dict):
        return ["program.expr must be an expression node"]
    count = [0]

    def walk(node, depth):
        count[0] += 1
        if count[0] > MAX_NODES:
            errs.append("program exceeds %d nodes" % MAX_NODES)
            return "scalar"
        if depth > MAX_DEPTH:
            errs.append("program exceeds depth %d" % MAX_DEPTH)
            return "scalar"
        if not isinstance(node, dict) or len(node) == 0:
            errs.append("node must be a non-empty object")
            return "scalar"
        if "col" in node:
            tag = node["col"]
            if tag not in inputs:
                errs.append("col %r is not a declared input" % tag)
                return "list"
            return inputs[tag]
        if "lit" in node:
            if not isinstance(node["lit"], (int, float)) or isinstance(node["lit"], bool):
                errs.append("lit must be a number")
            return "scalar"
        if "call" in node:
            name = node["call"]
            spec = KERNELS.get(name)
            if spec is None:
                errs.append("kernel %r is not whitelisted" % name)
                return "scalar"
            fn, argtypes, scalars = spec
            args = node.get("args", [])
            if len(args) != len(argtypes):
                errs.append("kernel %r takes %d args, got %d" % (name, len(argtypes), len(args)))
            for arg, want in zip(args, argtypes):
                got = walk(arg, depth + 1)
                if got != want:
                    errs.append("kernel %r arg expects %s, got %s" % (name, want, got))
            given = node.get("scalars", {})
            if not isinstance(given, dict):
                errs.append("kernel %r scalars must be an object" % name)
                given = {}
            for k, v in given.items():
                if k not in scalars:
                    errs.append("kernel %r has no scalar parameter %r" % (name, k))
                elif not isinstance(v, (int, float)) or isinstance(v, bool):
                    errs.append("kernel %r scalar %r must be a number" % (name, k))
            for k, required in scalars.items():
                if required and k not in given:
                    errs.append("kernel %r requires scalar %r" % (name, k))
            return "scalar"
        if "op" in node:
            op = node["op"]
            if op not in _SCALAR_OPS:
                errs.append("op %r is not allowed" % op)
                return "scalar"
            args = node.get("args", [])
            want_n = 1 if op in _UNARY else 2
            if len(args) != want_n:
                errs.append("op %r takes %d args, got %d" % (op, want_n, len(args)))
            for arg in args:
                got = walk(arg, depth + 1)
                if got != "scalar":
                    errs.append("op %r needs scalar args, got %s" % (op, got))
            return "scalar"
        if "zip" in node:
            op = node["zip"]
            if op not in _ZIP_OPS:
                errs.append("zip %r is not allowed" % op)
            args = node.get("args", [])
            if len(args) != 2:
                errs.append("zip takes exactly 2 args")
                return "list"
            types = [walk(a, depth + 1) for a in args]
            if "rawlist" in types:
                errs.append("zip works on numeric lists/scalars only")
            if "list" not in types:
                errs.append("zip needs at least one list arg (use op for scalar math)")
            return "list"
        if "len" in node:
            got = walk(node["len"], depth + 1)
            if got not in ("list", "rawlist"):
                errs.append("len needs a list arg, got %s" % got)
            return "scalar"
        errs.append("unknown node form: %s" % sorted(node.keys()))
        return "scalar"

    top = walk(expr, 1)
    if not errs and top != "scalar":
        errs.append("program must evaluate to a scalar, got %s" % top)
    return errs


# ---- execution ----------------------------------------------------------------

def _nan():
    return float("nan")


def _scalar_op(op, vals):
    a = vals[0]
    try:
        if op == "neg":
            return -a
        if op == "abs":
            return abs(a)
        if op == "sqrt":
            return math.sqrt(a) if a >= 0 else _nan()
        if op == "log":
            return N.dlog(a) if a > 0 else _nan()
        if op == "exp":
            return N.dexp(a)
        b = vals[1]
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            return a / b if b != 0 else _nan()
        if op == "min":
            return min(a, b)
        if op == "max":
            return max(a, b)
    except (ValueError, OverflowError):
        return _nan()
    return _nan()


def execute(program, tag_values):
    """Evaluate a VALIDATED program against {tag: column values}. Returns a float (NaN on any
    degenerate path - empty inputs, division by zero, kernel NaN). Never raises on numeric
    content; bit-stable for identical inputs."""

    def ev(node):
        if "col" in node:
            return list(tag_values.get(node["col"], []))
        if "lit" in node:
            return float(node["lit"])
        if "call" in node:
            fn, argtypes, scalars = KERNELS[node["call"]]
            args = [ev(a) for a in node.get("args", [])]
            kwargs = {k: float(v) if isinstance(v, float) else v
                      for k, v in node.get("scalars", {}).items()}
            try:
                out = fn(*args, **kwargs)
            except _KERNEL_ERRORS:
                return _nan()
            return float(out) if isinstance(out, (int, float)) else _nan()
        if "op" in node:
            vals = [ev(a) for a in node.get("args", [])]
            if any(isinstance(v, float) and v != v for v in vals):
                return _nan()  # NaN propagates silently through ops
            return _scalar_op(node["op"], vals)
        if "zip" in node:
            a, b = ev(node["args"][0]), ev(node["args"][1])
            la = a if isinstance(a, list) else None
            lb = b if isinstance(b, list) else None
            n = len(la) if la is not None else len(lb)
            if la is not None and lb is not None and len(la) != len(lb):
                return []  # length mismatch degrades: downstream kernel sees empty -> NaN
            out = []
            op = node["zip"]
            for i in range(n):
                x = la[i] if la is not None else a
                y = lb[i] if lb is not None else b
                out.append(_scalar_op(op, [x, y]))
            return out
        if "len" in node:
            v = ev(node["len"])
            return float(len(v)) if isinstance(v, list) else _nan()
        return _nan()

    out = ev(program["expr"])
    return out if isinstance(out, float) else _nan()
