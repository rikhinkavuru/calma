"""calma.compiler - the deterministic admission gate for model-drafted recipes (CEGIS-style).

The model's ONLY role is the DRAFT, produced fully offline under a JSON schema
(references/recipe-draft.schema.json): a DSL program (dsl.py - total by construction), a NAMED
reference oracle ("scipy.stats.sem with ddof=1"), the metamorphic relations the metric must
satisfy, and the required edge-case behaviour. Admission is 100% deterministic - no ML anywhere
in the gate, which is the existing 385-vector harness generalized:

  0  structural   - dsl.validate: whitelisted kernels only, typed, depth/size budgets
  1  differential - the program vs the named oracle, executed in the REFERENCE VENV, over
                    LCG-generated datasets (deterministic seeds; sizes 3..256)
  2  metamorphic  - permutation / scaling / shift / duplication / bounds relations, evaluated
                    on the DSL side alone (deterministic generators, so reproducible anywhere)
  3  degeneracy   - empty / single-row / constant / NaN-bearing inputs must DEGRADE (NaN or a
                    declared value), never raise, never return +-inf
  4  bit-stability- every vector double-run; byte-identical reprs required

Any failure returns a structured COUNTEREXAMPLE (stage, seed, inputs, expected, got) - the
feedback the drafting model uses to repair the draft: classic counterexample-guided synthesis.

PASS => the program is frozen: content-hashed, its reference vectors pinned, registered in
assets/compiled_recipes.json with set_maturity "compiled-validated", and SSHSIG-signed with the
lab key when one exists (the admission evidence is itself attestable). recipes.py loads admitted
recipes at import time - re-validating the hash, so a tampered asset entry fails closed.
Verify-time NEVER consults a model: compiled, validated, frozen - never improvised.

CLI:  python3 compiler.py admit <draft.json> [--venv PYTHON] [--out compiled_recipes.json]
      python3 compiler.py check <draft.json>      (stages 0,2,3,4 only - no venv needed)
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsl  # noqa: E402

DRAFT_SCHEMA = "calma/recipe-draft@1"
COMPILED_SCHEMA = "calma/compiled-recipe@1"
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
COMPILED_PATH = os.path.join(ASSETS, "compiled_recipes.json")
# reference venv resolution: $CALMA_REF_VENV first, else a PRIVATE per-user path under ~/.calma.
# NOT /tmp: code under verification can write to a world-writable /tmp and swap the oracle
# interpreter for a trojan (run_oracle refuses any world-writable venv as defense-in-depth).
DEFAULT_VENV = os.environ.get("CALMA_REF_VENV") or os.path.join(
    os.path.expanduser("~/.calma"), "ref-venv", "bin", "python")
SIZES = (3, 7, 31, 128, 256)
REL_TOL = 1e-9
ALLOWED_ORACLE_MODULES = ("numpy", "scipy", "sklearn", "statsmodels", "math", "statistics")
GEN_KINDS = {"uniform", "positive", "prob", "binary", "int", "category", "returns"}
RELATIONS = {"permutation", "scale", "shift", "duplicate", "bounds"}
EXPECTS = {"equal", "linear", "quadratic", "shift-by-delta"}


# ---- deterministic data generation (LCG - same idea as gen_reference_vectors) ----

class LCG:
    def __init__(self, seed):
        self.s = seed & 0x7FFFFFFF

    def next(self):
        self.s = (1103515245 * self.s + 12345) & 0x7FFFFFFF
        return self.s / 0x7FFFFFFF  # [0, 1)


def gen_column(spec, n, rng):
    kind = spec.get("kind")
    if kind == "uniform":
        lo, hi = float(spec.get("lo", 0.0)), float(spec.get("hi", 1.0))
        return [lo + (hi - lo) * rng.next() for _ in range(n)]
    if kind == "positive":
        scale = float(spec.get("scale", 100.0))
        return [scale * (rng.next() + 1e-6) for _ in range(n)]
    if kind == "prob":
        return [rng.next() for _ in range(n)]
    if kind == "binary":
        return [1.0 if rng.next() >= 0.5 else 0.0 for _ in range(n)]
    if kind == "int":
        lo, hi = int(spec.get("lo", 0)), int(spec.get("hi", 100))
        return [float(lo + int(rng.next() * (hi - lo + 1))) for _ in range(n)]
    if kind == "returns":
        return [(rng.next() - 0.5) * 0.1 for _ in range(n)]
    if kind == "category":
        k = int(spec.get("k", 5))
        return ["cat%d" % int(rng.next() * k) for _ in range(n)]
    raise ValueError("unknown generator kind %r" % kind)


def gen_dataset(draft, n, seed):
    rng = LCG(seed)
    return {tag: gen_column(spec, n, rng) for tag, spec in sorted(draft["generators"].items())}


# ---- draft validation -----------------------------------------------------------

def validate_draft(draft):
    e = []
    if draft.get("schema") != DRAFT_SCHEMA:
        e.append("schema must be %r" % DRAFT_SCHEMA)
        return e
    mid = draft.get("metric_id")
    if not isinstance(mid, str) or not mid.isidentifier():
        e.append("metric_id must be an identifier")
    if not isinstance(draft.get("family"), str):
        e.append("family is required")
    prog = draft.get("program")
    e += ["program: " + x for x in dsl.validate(prog or {})]
    gens = draft.get("generators")
    inputs = (prog or {}).get("inputs") or {}
    if not isinstance(gens, dict) or set(gens) != set(inputs):
        e.append("generators must cover exactly the program inputs (%s)" % ", ".join(sorted(inputs)))
    else:
        for tag, spec in gens.items():
            if not isinstance(spec, dict) or spec.get("kind") not in GEN_KINDS:
                e.append("generator %r: kind must be one of %s" % (tag, sorted(GEN_KINDS)))
            elif (spec["kind"] == "category") != (inputs.get(tag) == "rawlist"):
                e.append("generator %r: category <=> rawlist input" % tag)
    orc = draft.get("oracle")
    if orc is not None:
        if not isinstance(orc, dict) or not isinstance(orc.get("call"), str):
            e.append("oracle.call must be a dotted callable, e.g. scipy.stats.sem")
        elif orc["call"].split(".")[0] not in ALLOWED_ORACLE_MODULES:
            e.append("oracle module %r not allowed (allowed: %s)"
                     % (orc["call"].split(".")[0], ", ".join(ALLOWED_ORACLE_MODULES)))
        args = orc.get("args", []) if isinstance(orc, dict) else []
        if not isinstance(args, list) or not all(isinstance(a, str) and a in inputs for a in args):
            e.append("oracle.args must name program input tags")
    rels = draft.get("metamorphic", [])
    if not isinstance(rels, list) or not rels:
        e.append("at least one metamorphic relation is required")
    for i, r in enumerate(rels if isinstance(rels, list) else []):
        if not isinstance(r, dict) or r.get("relation") not in RELATIONS:
            e.append("metamorphic[%d].relation must be one of %s" % (i, sorted(RELATIONS)))
            continue
        if r["relation"] in ("scale", "shift", "duplicate", "permutation"):
            if r.get("expect") not in EXPECTS:
                e.append("metamorphic[%d].expect must be one of %s" % (i, sorted(EXPECTS)))
        if r["relation"] == "bounds" and not ("min" in r or "max" in r):
            e.append("metamorphic[%d]: bounds needs min and/or max" % i)
        tags = r.get("tags")
        if tags is not None and (not isinstance(tags, list)
                                 or not all(t in inputs for t in tags)):
            e.append("metamorphic[%d].tags must name program inputs" % i)
    edge = draft.get("edge_cases", {})
    if not isinstance(edge, dict):
        e.append("edge_cases must be an object")
    return e


# ---- stage 1: differential vs the named oracle (reference venv) -------------------

_ORACLE_RUNNER = r"""
import importlib, json, sys
req = json.load(sys.stdin)
parts = req["call"].split(".")
mod = None
for i in range(len(parts) - 1, 0, -1):
    try:
        mod = importlib.import_module(".".join(parts[:i]))
        rest = parts[i:]
        break
    except ImportError:
        continue
obj = mod
for p in rest:
    obj = getattr(obj, p)
args = [req["data"][t] for t in req["args"]]
out = obj(*args, **req.get("kwargs", {}))
print(repr(float(out)))
"""


def _refuse_world_writable_venv(venv_python):
    """Refuse a reference-oracle interpreter whose path passes through a directory ANY user could
    tamper with: world-writable AND NOT sticky (anyone can replace/rename its contents, swapping the
    oracle for a trojan). A world-writable dir WITH the sticky bit (e.g. /tmp) only lets a file's
    OWNER delete it, so an owner-only subdir under it is safe - so this allows a private temp dir
    under /tmp but still refuses a genuinely-shared (non-sticky) directory. The default ref venv lives
    under ~/.calma (private); set CALMA_REF_VENV to a private path if you override it."""
    import stat
    d = os.path.dirname(os.path.realpath(venv_python))
    while True:
        try:
            mode = os.stat(d).st_mode
            if (mode & stat.S_IWOTH) and not (mode & stat.S_ISVTX):
                raise ValueError(
                    "refusing a world-writable reference venv: %r is world-writable and not sticky, "
                    "so any user could swap the oracle interpreter. Set CALMA_REF_VENV to a private "
                    "path." % d)
        except OSError:
            pass
        parent = os.path.dirname(d)
        if parent == d:
            return
        d = parent


def run_oracle(draft, data, venv_python):
    _refuse_world_writable_venv(venv_python)
    req = {"call": draft["oracle"]["call"], "args": draft["oracle"].get("args", []),
           "kwargs": draft["oracle"].get("kwargs", {}), "data": data}
    r = subprocess.run([venv_python, "-c", _ORACLE_RUNNER], input=json.dumps(req),
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise ValueError("oracle failed: %s" % r.stderr.strip()[-300:])
    return float(r.stdout.strip())


def _close(a, b):
    if a != a and b != b:
        return True
    if a != a or b != b:
        return False
    return abs(a - b) <= REL_TOL * max(1.0, abs(a), abs(b))


def stage_differential(draft, venv_python):
    """The program must agree with the named reference oracle on every LCG dataset."""
    failures, vectors = [], []
    for si, n in enumerate(SIZES):
        seed = 1000003 * (si + 1) + len(draft["metric_id"])
        data = gen_dataset(draft, n, seed)
        got = dsl.execute(draft["program"], data)
        try:
            want = run_oracle(draft, data, venv_python)
        except ValueError as e:
            failures.append({"stage": "differential", "seed": seed, "n": n,
                             "error": str(e)})
            continue
        if not _close(got, want):
            failures.append({"stage": "differential", "seed": seed, "n": n,
                             "oracle": draft["oracle"]["call"],
                             "expected": repr(want), "got": repr(got),
                             "inputs": {t: v[:8] for t, v in data.items()}})
        else:
            vectors.append({"seed": seed, "n": n, "value_repr": repr(got),
                            "oracle_repr": repr(want)})
    return failures, vectors


# ---- stage 2: metamorphic relations (DSL side only - venv-free, reproducible) -----

def _permute(values, rng):
    out = list(values)
    for i in range(len(out) - 1, 0, -1):
        j = int(rng.next() * (i + 1))
        out[i], out[j] = out[j], out[i]
    return out


def _apply_relation(rel, data, rng):
    """The transformed dataset for a relation. `tags` limits which inputs transform
    (default: all numeric inputs)."""
    kind = rel["relation"]
    tags = rel.get("tags") or [t for t, v in data.items()
                               if v and isinstance(v[0], float)]
    out = {t: list(v) for t, v in data.items()}
    if kind == "permutation":
        # rows permute JOINTLY (one shared shuffle) so paired columns stay aligned
        n = len(next(iter(data.values()), []))
        order = _permute(list(range(n)), rng)
        for t in data:
            out[t] = [data[t][i] for i in order]
    elif kind == "scale":
        f = float(rel.get("factor", 2.0))
        for t in tags:
            out[t] = [x * f for x in data[t]]
    elif kind == "shift":
        d = float(rel.get("delta", 1.0))
        for t in tags:
            out[t] = [x + d for x in data[t]]
    elif kind == "duplicate":
        for t in data:
            out[t] = list(data[t]) + list(data[t])
    return out


def _expected(rel, base):
    kind, exp = rel["relation"], rel.get("expect")
    if exp == "equal":
        return base
    if exp == "linear":
        return base * float(rel.get("factor", 2.0))
    if exp == "quadratic":
        return base * float(rel.get("factor", 2.0)) ** 2
    if exp == "shift-by-delta":
        return base + float(rel.get("delta", 1.0))
    return base


def stage_metamorphic(draft):
    failures = []
    for si, n in enumerate((7, 31, 128)):
        seed = 7000003 * (si + 1) + len(draft["metric_id"])
        data = gen_dataset(draft, n, seed)
        base = dsl.execute(draft["program"], data)
        if base != base:
            continue  # degenerate baseline carries no metamorphic information
        for ri, rel in enumerate(draft.get("metamorphic", [])):
            if rel["relation"] == "bounds":
                lo, hi = rel.get("min"), rel.get("max")
                if (lo is not None and base < float(lo) - 1e-12) or \
                        (hi is not None and base > float(hi) + 1e-12):
                    failures.append({"stage": "metamorphic", "relation": "bounds", "seed": seed,
                                     "n": n, "expected": "in [%s, %s]" % (lo, hi),
                                     "got": repr(base)})
                continue
            rng = LCG(seed ^ 0x5EED)
            got = dsl.execute(draft["program"], _apply_relation(rel, data, rng))
            want = _expected(rel, base)
            if not _close(got, want):
                failures.append({"stage": "metamorphic", "relation": rel["relation"],
                                 "index": ri, "seed": seed, "n": n,
                                 "expected": repr(want), "got": repr(got)})
    return failures


# ---- stage 3: degeneracy / NaN policy ---------------------------------------------

def stage_degenerate(draft):
    """Empty, single-row, constant, and NaN-bearing inputs must DEGRADE - NaN or a declared
    finite value - never raise, never +-inf. dsl.execute already converts kernel errors to NaN;
    this stage asserts the contract holds for THIS program and that declared edge values match."""
    failures = []
    inputs = draft["program"]["inputs"]
    declared = draft.get("edge_cases", {})

    def mk(case):
        rng = LCG(31337)
        if case == "empty":
            return {t: [] for t in inputs}
        if case == "single":
            return {t: gen_column(draft["generators"][t], 1, rng) for t in inputs}
        if case == "constant":
            out = {}
            for t in inputs:
                col = gen_column(draft["generators"][t], 16, rng)
                out[t] = [col[0]] * 16 if col else []
            return out
        if case == "nan":
            out = {}
            for t in inputs:
                col = gen_column(draft["generators"][t], 16, rng)
                if col and isinstance(col[0], float):
                    col[3] = float("nan")
                out[t] = col
            return out
        raise AssertionError(case)

    for case in ("empty", "single", "constant", "nan"):
        try:
            got = dsl.execute(draft["program"], mk(case))
        except Exception as e:  # noqa: BLE001 - the whole point: NOTHING may escape
            failures.append({"stage": "degenerate", "case": case,
                             "error": "%s: %s" % (type(e).__name__, e)})
            continue
        if got in (float("inf"), float("-inf")):
            failures.append({"stage": "degenerate", "case": case, "got": repr(got),
                             "expected": "NaN or finite (never infinite)"})
            continue
        want = declared.get(case)
        if want == "nan" and got == got:
            failures.append({"stage": "degenerate", "case": case, "expected": "NaN",
                             "got": repr(got)})
        elif isinstance(want, (int, float)) and not _close(got, float(want)):
            failures.append({"stage": "degenerate", "case": case, "expected": repr(float(want)),
                             "got": repr(got)})
    return failures


# ---- stage 4: bit stability --------------------------------------------------------

def stage_bitstable(draft):
    failures = []
    for si, n in enumerate(SIZES):
        seed = 1000003 * (si + 1) + len(draft["metric_id"])
        data = gen_dataset(draft, n, seed)
        r1 = repr(dsl.execute(draft["program"], data))
        r2 = repr(dsl.execute(draft["program"], gen_dataset(draft, n, seed)))
        if r1 != r2:
            failures.append({"stage": "bit-stability", "seed": seed, "n": n,
                             "run1": r1, "run2": r2})
    return failures


# ---- admission ----------------------------------------------------------------------

def admit(draft, venv_python=None, compiled_path=COMPILED_PATH, skip_differential=False,
          write=True):
    """Run the full gate. Returns (ok, result): on failure result["counterexamples"] is the
    CEGIS feedback; on success result["compiled"] is the frozen registry entry (written +
    signed when write=True and a lab key exists). skip_differential is for `check` runs on
    machines without the reference venv - such runs NEVER freeze a recipe."""
    errs = validate_draft(draft)
    if errs:
        return False, {"counterexamples": [{"stage": "structural", "errors": errs}]}
    failures, vectors = [], []
    if not skip_differential:
        if draft.get("oracle") is None:
            return False, {"counterexamples": [{"stage": "structural",
                                                "errors": ["a named oracle is required for admission"]}]}
        venv = venv_python or DEFAULT_VENV
        if not os.path.exists(venv):
            return False, {"counterexamples": [{"stage": "differential",
                                                "error": "reference venv missing at %s" % venv}]}
        # the oracle executes from this path: a world-writable /tmp venv is swappable by any
        # local user on a multi-user system - warn (stderr) and point at $CALMA_REF_VENV
        if not os.environ.get("CALMA_REF_VENV") and venv == "/tmp/calma-ref-venv/bin/python":
            print("warning: reference venv lives under world-writable /tmp - on a multi-user "
                  "machine another user could replace it; set $CALMA_REF_VENV to a private "
                  "path (e.g. ~/.calma/ref-venv/bin/python)", file=sys.stderr)
        f, vectors = stage_differential(draft, venv)
        failures += f
    failures += stage_metamorphic(draft)
    failures += stage_degenerate(draft)
    failures += stage_bitstable(draft)
    if failures:
        return False, {"counterexamples": failures}

    import datetime
    compiled = {
        "schema": COMPILED_SCHEMA,
        "metric_id": draft["metric_id"],
        "family": draft["family"],
        "description": draft.get("description"),
        "required_tags": sorted(draft["program"]["inputs"]),
        "string_tags": sorted(t for t, ty in draft["program"]["inputs"].items()
                              if ty == "rawlist"),
        "program": draft["program"],
        "program_sha256": dsl.program_hash(draft["program"]),
        "generators": draft["generators"],
        "oracle": draft.get("oracle"),
        "metamorphic": draft.get("metamorphic"),
        "edge_cases": draft.get("edge_cases", {}),
        "vectors": vectors,
        "claim_hints": draft.get("claim_hints", []),
        "set_maturity": "compiled-validated",
        "admitted": {"date": datetime.date.today().isoformat(),
                     "differential_vectors": len(vectors),
                     "skip_differential": bool(skip_differential)},
    }
    # the recipe itself is attested: SSHSIG over the canonical compiled entry, lab key
    try:
        import attest
        import sshsig
        seed = attest.load_signing_key()
        if seed is not None:
            canon = json.dumps(compiled, sort_keys=True, separators=(",", ":")).encode()
            compiled["ssh"] = {"namespace": sshsig.NAMESPACE,
                               "signature": sshsig.sign(seed, canon)}
    except Exception:  # noqa: BLE001 - signing is evidence, never load-bearing for admission
        pass

    if write and not skip_differential:
        book = {"schema": "calma/compiled-recipes@1", "recipes": []}
        if os.path.exists(compiled_path):
            book = json.load(open(compiled_path))
        book["recipes"] = [r for r in book.get("recipes", [])
                           if r.get("metric_id") != compiled["metric_id"]] + [compiled]
        book["recipes"].sort(key=lambda r: r["metric_id"])
        os.makedirs(os.path.dirname(compiled_path), exist_ok=True)
        with open(compiled_path, "w") as fh:
            json.dump(book, fh, indent=2)
    return True, {"compiled": compiled, "path": compiled_path}


def main():
    ap = argparse.ArgumentParser(description="deterministic admission gate for drafted recipes")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("admit", "check"):
        p = sub.add_parser(name)
        p.add_argument("draft", help="path to a calma/recipe-draft@1 JSON file")
        p.add_argument("--venv", default=None, help="reference venv python (admit only)")
        p.add_argument("--out", default=COMPILED_PATH, help="compiled registry path")
    a = ap.parse_args()
    draft = json.load(open(a.draft))
    ok, result = admit(draft, venv_python=a.venv, compiled_path=a.out,
                       skip_differential=(a.cmd == "check"), write=(a.cmd == "admit"))
    if not ok:
        print(json.dumps({"admitted": False,
                          "counterexamples": result["counterexamples"]}, indent=2))
        return 1
    if a.cmd == "check":
        print(json.dumps({"admitted": False, "note": "check passed (stages 0,2,3,4); "
                          "run `admit` with the reference venv to finish"}, indent=2))
        return 0
    c = result["compiled"]
    print(json.dumps({"admitted": True, "metric_id": c["metric_id"],
                      "program_sha256": c["program_sha256"],
                      "vectors": len(c["vectors"]), "registry": result["path"],
                      "set_maturity": c["set_maturity"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
