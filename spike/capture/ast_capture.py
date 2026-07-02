"""ast_capture — Tier 2 of the capture ladder (guide §B.1 ②): AST decorator-append + execute in a __main__
namespace. The PORTABLE fallback for Python < 3.12 (no sys.monitoring / Tier 1) or when monitoring can't
resolve a target's code object.

It parses the entrypoint, locates the target FunctionDef(s) by name, and APPENDS an observing decorator to
each (never touches the body — the smallest possible transform), then compiles and executes the tree in a
namespace whose __name__ is '__main__' so the repo's `if __name__ == "__main__":` block actually runs (the
reason run_path(run_name="__main__") is essential — running the file as an imported module skips that block
and reproduces nothing). The decorator wraps the function to record its args+return; the function's
semantics are untouched.

FCR guard (guide §B.1 ②, belt-and-suspenders): because this path ALTERS source, `capture_guarded` also runs
the UNTRANSFORMED source and asserts the transformed run's observable output matches it. If the transform
perturbed the number (or the run isn't reproducible), the outputs diverge → the capture is DISCARDED and the
verdict falls back to REPRODUCED-ONLY / INCONCLUSIVE. Capture can never silently change a verdict.

On >=3.12 the runner uses Tier 1 (sys.monitoring), which needs no source rewrite; this module is the
belt-and-suspenders portable path, unit-tested for transform-correctness + the round-trip guard.
"""
from __future__ import annotations

import ast
import contextlib
import io


def target_atoms(specs) -> dict:
    """{final-dotted-atom: spec} for each target (the atom is the function name to wrap)."""
    return {s["target"].rsplit(".", 1)[-1]: s for s in (specs or []) if s.get("target")}


def transform(src: str, filename: str, atoms: set):
    """Return (tree, wrapped_names): the parsed module with an observing decorator appended to every target
    FunctionDef. `ast.fix_missing_locations` keeps line numbers valid for compile."""
    tree = ast.parse(src, filename)
    wrapped = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in atoms:
            dec = ast.Call(func=ast.Name(id="__calma_ast_wrap__", ctx=ast.Load()),
                           args=[ast.Constant(value=node.name)], keywords=[])
            node.decorator_list.append(dec)          # innermost → observes the raw function's args/return
            wrapped.append(node.name)
    ast.fix_missing_locations(tree)
    return tree, wrapped


def _map_inputs(spec, args, kwargs) -> dict:
    mapping = spec.get("inputs") or {}
    if not mapping:
        return {}
    out = {}
    for key, ref in mapping.items():
        if isinstance(ref, str) and ref.startswith("arg") and ref[3:].isdigit():
            i = int(ref[3:])
            out[key] = args[i] if len(args) > i else None
        else:
            out[key] = kwargs.get(ref)
    return out


def _wrap_factory(atoms: dict, record_fn):
    def factory(qual):
        spec = atoms.get(qual) or {}

        def deco(fn):
            def wrapper(*a, **k):
                r = fn(*a, **k)
                try:
                    sink = ("static:" if spec.get("static") else "") + "ast:" + spec.get("target", qual)
                    record_fn(spec.get("metric") or qual, r, sink=sink, **_map_inputs(spec, a, k))
                except Exception:  # noqa: BLE001 — a capture error must never break the run
                    pass
                return r
            wrapper.__name__ = getattr(fn, "__name__", "wrapped")
            wrapper.__wrapped__ = fn
            wrapper.__calma_wrapped__ = True
            return wrapper
        return deco
    return factory


def run_transformed(entry_path: str, specs, record_fn, run_name: str = "__main__") -> list:
    """Execute entry_path with its target functions AST-wrapped, in a namespace whose __name__ is run_name
    ('__main__' by default so the entrypoint's main block runs). Returns the wrapped function names."""
    with open(entry_path) as fh:
        src = fh.read()
    atoms = target_atoms(specs)
    tree, wrapped = transform(src, entry_path, set(atoms))
    code = compile(tree, entry_path, "exec")
    ns = {"__name__": run_name, "__file__": entry_path, "__builtins__": __builtins__,
          "__calma_ast_wrap__": _wrap_factory(atoms, record_fn)}
    exec(code, ns)  # noqa: S102 — the repo's own code, run in the sandbox; the transform only appends a decorator
    return wrapped


def _run_plain(entry_path: str, run_name: str = "__main__"):
    with open(entry_path) as fh:
        src = fh.read()
    code = compile(src, entry_path, "exec")
    ns = {"__name__": run_name, "__file__": entry_path, "__builtins__": __builtins__}
    exec(code, ns)  # noqa: S102


def capture_guarded(entry_path: str, specs):
    """Run the transformed source (capturing) and the untransformed source, comparing observable stdout.
    Returns (captures, ok). ok=False (outputs diverge → the transform perturbed the run, or it isn't
    reproducible) means the captures are DISCARDED — the FCR guard. Deterministic, reproducible runs pass."""
    captures = []

    def rec(metric, value, sink="ast", **inputs):
        captures.append({"metric": metric, "result": value, "inputs": inputs, "sink": sink})

    buf_t = io.StringIO()
    with contextlib.redirect_stdout(buf_t):
        run_transformed(entry_path, specs, rec)
    buf_u = io.StringIO()
    with contextlib.redirect_stdout(buf_u):
        _run_plain(entry_path)
    ok = buf_t.getvalue() == buf_u.getvalue()
    return (captures if ok else []), ok
