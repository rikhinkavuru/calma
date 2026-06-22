"""Recipe compiler: the DSL's totality/typing/DoS budgets, the deterministic admission gate
(differential, metamorphic, degeneracy, bit-stability) with CEGIS counterexamples, the frozen
compiled registry (vectors re-validate pure-stdlib; tampered programs fail closed at load), and
the end-to-end path: a compiled recipe verifying a real claim through the CLI. Pure stdlib -
the reference venv is only used by `admit`, never by these checks.
Run: python3 test_compiler.py
"""
import copy
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import compiler as CMP  # noqa: E402
import dsl  # noqa: E402
import recipes as R  # noqa: E402

CALMA = os.path.join(SCR, "calma.py")
COMPILED = os.path.realpath(os.path.join(SCR, "..", "assets", "compiled_recipes.json"))
_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


SEM_PROG = {
    "schema": "calma/recipe-dsl@1",
    "inputs": {"value": "list"},
    "expr": {"op": "/", "args": [
        {"call": "fstd", "args": [{"col": "value"}], "scalars": {"ddof": 1}},
        {"op": "sqrt", "args": [{"len": {"col": "value"}}]}]},
}

# --- DSL: typing, totality, budgets ---
truth(dsl.validate(SEM_PROG) == [], "a well-formed program validates")
truth(dsl.validate({"schema": "x"}) != [], "wrong schema rejected")

bad = copy.deepcopy(SEM_PROG)
bad["expr"]["args"][0]["call"] = "os_system"
truth(any("not whitelisted" in e for e in dsl.validate(bad)),
      "non-whitelisted kernel rejected (no escape from the kernel set)")

bad = copy.deepcopy(SEM_PROG)
bad["expr"]["args"][0]["args"] = [{"col": "ghost"}]
truth(any("not a declared input" in e for e in dsl.validate(bad)), "undeclared input rejected")

bad = copy.deepcopy(SEM_PROG)
bad["expr"] = {"col": "value"}
truth(any("must evaluate to a scalar" in e for e in dsl.validate(bad)),
      "a program returning a list (not a scalar) is rejected")

# DoS budgets: depth and node count
deep = {"op": "neg", "args": [{"lit": 1.0}]}
for _ in range(40):
    deep = {"op": "neg", "args": [deep]}
bad = {"schema": dsl.SCHEMA, "inputs": {"value": "list"}, "expr": deep}
truth(any("depth" in e for e in dsl.validate(bad)), "depth budget rejects a 40-deep tree")
wide = {"op": "+", "args": [{"lit": 1.0}, {"lit": 1.0}]}
for _ in range(300):
    wide = {"op": "+", "args": [wide, {"lit": 1.0}]}
bad = {"schema": dsl.SCHEMA, "inputs": {"value": "list"}, "expr": wide}
truth(any("nodes" in e or "depth" in e for e in dsl.validate(bad)),
      "node-count budget rejects a 300-node tree")

# type errors: zip on a rawlist; scalar op on a list
bad = {"schema": dsl.SCHEMA, "inputs": {"g": "rawlist"},
       "expr": {"call": "fmean", "args": [{"zip": "+", "args": [{"col": "g"}, {"lit": 1}]}]}}
truth(any("numeric" in e for e in dsl.validate(bad)), "zip over a string column is a type error")

# execution: deterministic, NaN-degrading, never raising
vals = [1.0, 2.0, 3.0, 4.0, 5.0]
got = dsl.execute(SEM_PROG, {"value": vals})
truth(abs(got - 0.7071067811865476) < 1e-12, "sem program computes std/sqrt(n) correctly")
truth(repr(dsl.execute(SEM_PROG, {"value": vals})) == repr(got), "execution is bit-stable")
truth(dsl.execute(SEM_PROG, {"value": []}) != dsl.execute(SEM_PROG, {"value": []}),
      "empty input degrades to NaN (never a crash)")
div0 = {"schema": dsl.SCHEMA, "inputs": {"value": "list"},
        "expr": {"op": "/", "args": [{"lit": 1.0}, {"lit": 0.0}]}}
truth(dsl.execute(div0, {"value": vals}) != dsl.execute(div0, {"value": vals}),
      "division by zero degrades to NaN")
truth(dsl.program_hash(SEM_PROG) == dsl.program_hash(json.loads(json.dumps(SEM_PROG))),
      "program hash is canonical (key order irrelevant)")

# --- the gate (venv-free stages) with CEGIS counterexamples ---
DRAFT = {
    "schema": "calma/recipe-draft@1", "metric_id": "t_sem", "family": "stats",
    "description": "test", "program": SEM_PROG,
    "generators": {"value": {"kind": "uniform", "lo": -5, "hi": 10}},
    "oracle": {"call": "scipy.stats.sem", "args": ["value"], "kwargs": {"ddof": 1}},
    "metamorphic": [{"relation": "permutation", "expect": "equal"},
                    {"relation": "scale", "factor": 3.0, "expect": "linear"},
                    {"relation": "shift", "delta": 5.0, "expect": "equal"},
                    {"relation": "bounds", "min": 0}],
    "edge_cases": {"empty": "nan", "single": "nan", "constant": 0, "nan": "nan"},
}
ok, res = CMP.admit(DRAFT, skip_differential=True, write=False)
truth(ok, "a correct draft passes the venv-free stages: %s"
      % json.dumps(res.get("counterexamples", []))[:200])

# a FALSE metamorphic claim -> counterexample names the relation, seed, expected, got
bad_draft = copy.deepcopy(DRAFT)
bad_draft["metamorphic"].append({"relation": "shift", "delta": 5.0, "expect": "shift-by-delta"})
ok, res = CMP.admit(bad_draft, skip_differential=True, write=False)
cx = res.get("counterexamples", [])
truth(not ok and any(c.get("relation") == "shift" and "expected" in c and "seed" in c
                     for c in cx),
      "a false metamorphic relation fails with a structured counterexample (CEGIS feedback)")

# a WRONG program (mean instead of sem) -> the scale relation kills it even without the oracle
wrong = copy.deepcopy(DRAFT)
wrong["program"] = {"schema": dsl.SCHEMA, "inputs": {"value": "list"},
                    "expr": {"call": "fmean", "args": [{"col": "value"}]}}
wrong["metamorphic"] = [{"relation": "shift", "delta": 5.0, "expect": "equal"},
                        {"relation": "bounds", "min": 0}]
ok, res = CMP.admit(wrong, skip_differential=True, write=False)
truth(not ok, "a wrong program is rejected by the property suite alone")

# a draft whose edge behaviour is mis-declared -> degeneracy stage catches it
bad_edge = copy.deepcopy(DRAFT)
bad_edge["edge_cases"] = {"empty": 0}
ok, res = CMP.admit(bad_edge, skip_differential=True, write=False)
truth(not ok and any(c.get("stage") == "degenerate" for c in res["counterexamples"]),
      "mis-declared edge behaviour fails the degeneracy stage")

# structural rejects: oracle module outside the allowlist; generator/input mismatch
bad_orc = copy.deepcopy(DRAFT)
bad_orc["oracle"] = {"call": "subprocess.run", "args": ["value"]}
truth(any("not allowed" in e for e in CMP.validate_draft(bad_orc)),
      "an oracle outside numpy/scipy/sklearn/statsmodels is rejected")
bad_gen = copy.deepcopy(DRAFT)
bad_gen["generators"] = {}
truth(any("generators" in e for e in CMP.validate_draft(bad_gen)),
      "generators must cover exactly the program inputs")

# --- P3.4 widening: the new DSL kernels (col_mean/col_std/col_median/harmonic_mean) are registered,
#     execute correctly, NaN-degrade, and a recipe using each passes the venv-free gate stages ---
for _kern in ("col_mean", "col_std", "col_median", "harmonic_mean"):
    truth(_kern in dsl.KERNELS, "P3.4 kernel %s is registered in dsl.KERNELS" % _kern)

_med_prog = {"schema": dsl.SCHEMA, "inputs": {"value": "list"},
             "expr": {"call": "col_median", "args": [{"col": "value"}]}}
truth(dsl.validate(_med_prog) == [], "col_median program validates")
truth(dsl.execute(_med_prog, {"value": [3.0, 1.0, 2.0, 4.0]}) == 2.5, "col_median executes (median 2.5)")
truth(dsl.execute(_med_prog, {"value": []}) != dsl.execute(_med_prog, {"value": []}),
      "col_median NaN-degrades on empty")

_med_draft = {"schema": "calma/recipe-draft@1", "metric_id": "t_median", "family": "analytics",
              "description": "median of a column.", "program": _med_prog,
              "generators": {"value": {"kind": "uniform", "lo": -10.0, "hi": 10.0}},
              "oracle": {"call": "numpy.median", "args": ["value"], "kwargs": {}},
              "metamorphic": [{"relation": "permutation", "expect": "equal"},
                              {"relation": "scale", "factor": 3.0, "expect": "linear"}],
              "edge_cases": {"empty": "nan", "single": None, "constant": None, "nan": "nan"}}
ok, res = CMP.admit(_med_draft, skip_differential=True, write=False)
truth(ok, "a col_median recipe passes the venv-free gate stages: %s"
      % json.dumps(res.get("counterexamples", []))[:200])

_hm_prog = {"schema": dsl.SCHEMA, "inputs": {"value": "list"},
            "expr": {"call": "harmonic_mean", "args": [{"col": "value"}]}}
truth(dsl.validate(_hm_prog) == [], "harmonic_mean program validates")
_hm_draft = {"schema": "calma/recipe-draft@1", "metric_id": "t_hmean", "family": "analytics",
             "description": "harmonic mean.", "program": _hm_prog,
             "generators": {"value": {"kind": "positive", "scale": 10.0}},
             "oracle": {"call": "statistics.harmonic_mean", "args": ["value"], "kwargs": {}},
             "metamorphic": [{"relation": "permutation", "expect": "equal"},
                             {"relation": "scale", "factor": 4.0, "expect": "linear"},
                             {"relation": "bounds", "min": 0}],
             "edge_cases": {"empty": "nan", "single": None, "constant": None, "nan": "nan"}}
ok, res = CMP.admit(_hm_draft, skip_differential=True, write=False)
truth(ok, "a harmonic_mean recipe passes the venv-free gate stages: %s"
      % json.dumps(res.get("counterexamples", []))[:200])

# --- the committed compiled registry: real recipes, frozen, revalidating ---
book = json.load(open(COMPILED))
truth({r["metric_id"] for r in book["recipes"]} >= {"sem", "coefficient_of_variation"},
      "sem and coefficient_of_variation are admitted in the committed registry")
for rec in book["recipes"]:
    mid = rec["metric_id"]
    truth(dsl.program_hash(rec["program"]) == rec["program_sha256"],
          "%s: frozen program hash re-derives" % mid)
    truth(dsl.validate(rec["program"]) == [], "%s: frozen program re-validates" % mid)
    truth(rec["set_maturity"] == "compiled-validated", "%s: maturity is compiled-validated" % mid)
    truth(len(rec.get("vectors", [])) >= 5, "%s: differential vectors are pinned" % mid)
    # the pinned vectors re-validate PURE-STDLIB: regenerate the LCG dataset, run the DSL,
    # byte-compare against the value pinned at admission (which equalled the oracle)
    draft_like = {"metric_id": mid, "generators": rec["generators"]}
    for v in rec["vectors"]:
        data = CMP.gen_dataset(draft_like, v["n"], v["seed"])
        truth(repr(dsl.execute(rec["program"], data)) == v["value_repr"],
              "%s: vector n=%d re-derives byte-for-byte" % (mid, v["n"]))
    # and the pinned value matched the oracle at admission to <= 1e-9
    truth(all(CMP._close(float(v["value_repr"]), float(v["oracle_repr"]))
              for v in rec["vectors"]),
          "%s: pinned values agree with the pinned oracle values" % mid)

# registration: compiled recipes are live in the registry with the right manifest
truth(R.get("sem") is not None and R.get("sem").manifest["set_maturity"] == "compiled-validated",
      "sem is registered as compiled-validated")

# tamper: edit the frozen program -> the loader skips it (fails closed)
tampered = copy.deepcopy(book)
for rec in tampered["recipes"]:
    if rec["metric_id"] == "sem":
        rec["program"]["expr"]["args"][0]["scalars"]["ddof"] = 0  # silently change semantics
tmp_asset = tempfile.mkdtemp()
shutil.copytree(os.path.join(SCR, "..", "assets"), os.path.join(tmp_asset, "assets"),
                dirs_exist_ok=True)
json.dump(tampered, open(os.path.join(tmp_asset, "assets", "compiled_recipes.json"), "w"))
# stage the scripts next to the tampered assets so the loader resolves them
shutil.copytree(SCR, os.path.join(tmp_asset, "scripts"),
                ignore=shutil.ignore_patterns("__pycache__", "tests"), dirs_exist_ok=True)
probe = subprocess.run([sys.executable, "-c", (
    "import sys\n"
    "sys.path.insert(0, %r)\n"
    "import recipes\n"
    "print('sem' in recipes.ids())\n") % os.path.join(tmp_asset, "scripts")],
    capture_output=True, text=True, env=dict(os.environ))
truth(probe.stdout.strip() == "False" and "hash/validation mismatch" in probe.stderr,
      "a tampered frozen program is SKIPPED at load with a warning (fails closed): %s"
      % probe.stderr.strip()[:120])
shutil.rmtree(tmp_asset, ignore_errors=True)

# --- end to end: a compiled recipe verifies a real claim through the CLI ---
proj = tempfile.mkdtemp()
os.makedirs(os.path.join(proj, "runs"))
vals = [4.1, 5.2, 3.9, 4.8, 5.0, 4.4, 4.6, 5.1, 4.0, 4.9]
with open(os.path.join(proj, "runs", "samples.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["measurement"])
    for v in vals:
        w.writerow([v])
with open(os.path.join(proj, "analyze.py"), "w") as fh:
    fh.write("pass\n")
true_sem = dsl.execute(SEM_PROG, {"value": vals})
env = dict(os.environ)
env.pop("CALMA_KEY_DIR", None)
r = subprocess.run([sys.executable, CALMA, "verify", proj,
                    "standard error of the mean %.6f" % true_sem, "--json"],
                   capture_output=True, text=True, env=env)
out = json.loads(r.stdout or "{}")
truth(out.get("verdict") in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS"),
      "TRUE sem claim CONFIRMS through the compiled recipe (got %s)" % out.get("verdict"))
truth(out.get("metric") == "sem",
      "the claim text bound to the compiled sem recipe (not column_mean)")
r2 = subprocess.run([sys.executable, CALMA, "verify", proj,
                     "standard error of the mean %.6f" % (true_sem * 4), "--json", "--force"],
                    capture_output=True, text=True, env=env)
out2 = json.loads(r2.stdout or "{}")
truth(out2.get("verdict") in ("REFUTED", "MIXED", "INCONCLUSIVE"),
      "an inflated sem claim does NOT confirm (got %s)" % out2.get("verdict"))
shutil.rmtree(proj, ignore_errors=True)

# --- M4: admission via FIRM-SUPPLIED reference vectors (a bespoke metric, no named oracle, no venv) ---
# the firm's metric: a 'load factor' = average exposure / peak exposure (avg/max). The firm's own
# (inputs -> expected) numbers ARE the oracle, so this whole path is venv-free + pure-stdlib.
def _lf_draft(denom="col_max", mm=None, rv=True):
    d = {"schema": "calma/recipe-draft@1", "metric_id": "t_load_factor", "family": "analytics",
         "description": "average exposure divided by peak exposure",
         "program": {"schema": "calma/recipe-dsl@1", "inputs": {"value": "list"},
                     "expr": {"op": "/", "args": [{"call": "fmean", "args": [{"col": "value"}]},
                                                 {"call": denom, "args": [{"col": "value"}]}]}},
         "generators": {"value": {"kind": "positive", "scale": 100.0}},
         "metamorphic": mm or [{"relation": "permutation", "expect": "equal"},
                               {"relation": "scale", "factor": 3.0, "expect": "equal"},
                               {"relation": "bounds", "min": 0.0, "max": 1.0}],
         "edge_cases": {"empty": "nan", "single": 1.0, "constant": 1.0, "nan": "nan"}}
    if rv:
        d["reference_vectors"] = [
            {"inputs": {"value": [10, 20, 30, 40]}, "expected": 0.625},
            {"inputs": {"value": [1, 3, 5, 7, 9]}, "expected": 5 / 9},
            {"inputs": {"value": [100, 50, 25, 25]}, "expected": 0.5},
            {"inputs": {"value": [7, 7, 7]}, "expected": 1.0},
            {"inputs": {"value": [3, 1, 4, 1, 5, 9, 2, 6]}, "expected": (31 / 8) / 9}]
    return d

_lf_tmp = tempfile.mkdtemp()
_lf_cp = os.path.join(_lf_tmp, "compiled.json")
ok, res = CMP.admit(_lf_draft(), venv_python=None, compiled_path=_lf_cp, write=True)
truth(ok, "a bespoke reference-vector recipe admits venv-free: %s"
      % json.dumps(res.get("counterexamples", []))[:200])
if ok:
    c = res["compiled"]
    truth(c["admitted"]["ground_truth"] == "reference-vectors",
          "admission records ground_truth=reference-vectors")
    truth(len(c["vectors"]) == 5, "all 5 firm reference vectors are pinned")
    truth(c.get("oracle") is None and c.get("reference_vectors"),
          "the frozen entry carries the firm vectors and no named oracle")
    book = json.load(open(_lf_cp))
    fr = next((r for r in book["recipes"] if r["metric_id"] == "t_load_factor"), None)
    truth(fr is not None and dsl.program_hash(fr["program"]) == fr["program_sha256"]
          and dsl.validate(fr["program"]) == [],
          "the frozen bespoke recipe re-validates (hash + dsl.validate) exactly as the loader would")
    # the program reproduces each firm vector byte-for-byte (what was pinned at admission)
    truth(all(repr(dsl.execute(fr["program"], v["inputs"])) == p["value_repr"]
              for v, p in zip(fr["reference_vectors"], fr["vectors"])),
          "the frozen program re-derives every firm reference vector byte-for-byte")
# a wrong program (mean/MIN, not mean/max) is caught by the reference stage on the firm's exact inputs
ok, res = CMP.admit(_lf_draft(denom="col_min"), venv_python=None,
                    compiled_path=os.path.join(_lf_tmp, "c2.json"), write=False)
truth(not ok and res["counterexamples"][0]["stage"] == "reference",
      "a wrong program fails the reference stage (not metamorphic) -- the firm's numbers catch it")
# the metamorphic stage is an INDEPENDENT overfit guard: a program that fits the 5 points but declares a
# relation it violates (shift-invariance, which avg/peak does NOT have) is still rejected
ok, res = CMP.admit(_lf_draft(mm=[{"relation": "permutation", "expect": "equal"},
                                  {"relation": "shift", "delta": 5.0, "expect": "equal"}]),
                    venv_python=None, compiled_path=os.path.join(_lf_tmp, "c3.json"), write=False)
truth(not ok and any(c.get("stage") == "metamorphic" for c in res["counterexamples"]),
      "a false metamorphic claim is rejected even when the reference vectors pass (overfit guard)")
# a draft with NEITHER a named oracle NOR reference vectors cannot be admitted
ok, res = CMP.admit(_lf_draft(rv=False), venv_python=None, skip_differential=True, write=False)
truth(not ok and any("ground-truth source" in e
                     for cx in res["counterexamples"] for e in cx.get("errors", [])),
      "a draft with no ground-truth source (no oracle, no reference vectors) is rejected")
shutil.rmtree(_lf_tmp, ignore_errors=True)

print("compiler: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
