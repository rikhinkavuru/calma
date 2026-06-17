"""A3's synthesizer loop. THE GATE NEVER MOVES: the model drafts, compiler.admit() decides, and a draft
becomes a shipped recipe only when differential-vs-oracle + metamorphic + degeneracy + bit-stability all
pass. Importing compiler+dsl is the firewall-sanctioned exception (test_firewall allowlist); importing
verdict/ledger/compare/recompute is forbidden and would fail the firewall.

Recipe "Definition of done for a NEW recipe" (references/recipes.md), which the loop satisfies on
admission: (1) verification -- compiling via admit() IS the published-reference validation (its
differential vectors re-validate pure-stdlib); (2) suggester enrichment -- a recipe_descriptions.json
entry (>=2 aliases incl. a paraphrase); (3) claim routing -- claim_hints when the metric has a spoken
name; (4) green tests -- test_recipes_sota + test_suggest; (5) benchmark for a real pack.
"""
import json
import os
import re
import sys
from dataclasses import dataclass, field

# the deterministic gate -- the ONLY core modules A3 imports
_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..",
                        ".claude", "skills", "calma", "scripts")
sys.path.insert(0, os.path.abspath(_SCRIPTS))
import compiler  # noqa: E402
import dsl  # noqa: E402

from edges.common import llm, store  # noqa: E402
from edges.synth import constraints, feedback  # noqa: E402

_SCHEMA_PATH = os.path.join(_SCRIPTS, "..", "references", "recipe-draft.schema.json")
ASSETS = os.path.join(_SCRIPTS, "..", "assets")
DESC_PATH = os.path.join(ASSETS, "recipe_descriptions.json")
DRAFTS_LOG = os.path.join(os.path.dirname(__file__), "data", "drafts.jsonl")


@dataclass
class Result:
    metric_id: str
    admitted: bool
    iterations: int                       # number of draft attempts made
    program_sha256: str = None            # set on admission (the content address)
    vectors: list = field(default_factory=list)        # pinned differential vectors on admission
    last_stage: str = None                # the stage of the final failing counterexample (if not admitted)
    trace: list = field(default_factory=list)          # [{attempt, ok, stage|None, draft_sha}]
    enrichment_written: bool = False      # did we add the recipe_descriptions.json entry?
    tests_passed: bool = False            # test_suggest + test_recipes_sota green after admission?


def _load_schema():
    return json.load(open(_SCHEMA_PATH))


_ARGSIG_LABEL = {("list",): "one numeric column -> scalar",
                 ("list", "list"): "two numeric columns -> scalar",
                 ("rawlist",): "one raw (string) column -> scalar"}


def _render_kernels():
    """Render the gate's CURRENT dsl.KERNELS whitelist into the synthesizer prompt, grouped by arg
    signature. Generated from dsl.KERNELS so it always reflects the live table -- when P3.4 widens the
    kernels, the synthesizer is told about them automatically (no prompt drift)."""
    from collections import OrderedDict
    groups = OrderedDict()
    for name, spec in dsl.KERNELS.items():
        argtypes = tuple(spec[1])
        scalars = spec[2] if len(spec) > 2 else {}
        sig = ", ".join(list(argtypes) + ["%s%s" % (k, "!" if req else "?")
                                          for k, req in scalars.items()])
        groups.setdefault(argtypes, []).append("%s(%s)" % (name, sig))
    lines = []
    for argtypes, kernels in groups.items():
        lines.append("  %s:" % _ARGSIG_LABEL.get(argtypes, "/".join(argtypes) + " -> scalar"))
        lines.append("    " + ", ".join(kernels))
    return "\n".join(lines)


def _system():
    """The synthesizer system prompt with the live kernel whitelist spliced in."""
    return _SYSTEM.replace("__KERNELS__", _render_kernels())


def synthesize(metric_id, spec, *, venv_python, budget=8, model=llm.SONNET,
               compiled_path=None, desc_path=None, constraints_db=None, drafts_log=None,
               run_def_of_done=True, write_enrichment=True):
    """Run the CEGIS loop for ONE metric. Returns Result. Never raises on a synthesis miss -- a miss is a
    Result(admitted=False) with the last counterexample stage, which the fleet harness aggregates.

    The path params (compiled_path/desc_path/constraints_db/drafts_log) default to the production
    locations; a test passes tmp paths so freezing never mutates the committed assets. run_def_of_done /
    write_enrichment toggle the (slow, asset-writing) definition-of-done steps off under test.
    """
    assert metric_id == spec.metric_id, "metric_id mismatch"
    assert re.fullmatch(r"[a-z][a-z0-9_]*", metric_id), "metric_id pattern"
    compiled_path = compiled_path or compiler.COMPILED_PATH
    drafts_log = drafts_log or DRAFTS_LOG
    schema = _load_schema()
    acc = []                                              # accumulated counterexample feedback this run
    trace = []
    last_stage = None

    for attempt in range(1, budget + 1):
        prior = constraints.relevant(spec, db=constraints_db)   # ConVer: cross-recipe constraints
        prompt = _user_prompt(spec, accumulated=acc, prior_constraints=prior)
        draft = llm.structured(prompt, schema=schema, model=model, system=_system(), tool_name="emit")
        draft_sha = dsl.program_hash(draft.get("program", {})) if draft.get("program") else None
        store.append(drafts_log, {"metric_id": metric_id, "attempt": attempt, "draft": draft,
                                  "draft_program_sha": draft_sha})

        ok, result = compiler.admit(draft, venv_python=venv_python, compiled_path=compiled_path,
                                    write=False)              # DRY RUN -- never freeze here
        if ok:
            ok2, result2 = compiler.admit(draft, venv_python=venv_python, compiled_path=compiled_path,
                                          write=True)         # FREEZE + SSHSIG-sign
            assert ok2, "a draft that passed the dry run must pass on write"
            compiled = result2["compiled"]
            constraints.record_positive(spec, draft, db=constraints_db)   # a passing draft is a positive
            enriched = _write_enrichment(metric_id, spec, draft, desc_path) if write_enrichment else False
            passed = _run_def_of_done_tests() if run_def_of_done else False
            trace.append({"attempt": attempt, "ok": True, "draft_sha": compiled["program_sha256"]})
            return Result(metric_id=metric_id, admitted=True, iterations=attempt,
                          program_sha256=compiled["program_sha256"], vectors=compiled["vectors"],
                          trace=trace, enrichment_written=enriched, tests_passed=passed)

        ce = result["counterexamples"][0]                 # the FIRST counterexample -- most localized
        last_stage = ce["stage"]
        msg = feedback.format_counterexample(ce)          # operand-level diff hints
        constraints.record_negative(spec, draft, ce, db=constraints_db)   # a failing draft is a negative
        acc.append({"attempt": attempt, "stage": ce["stage"], "feedback": msg})
        trace.append({"attempt": attempt, "ok": False, "stage": ce["stage"], "draft_sha": draft_sha})

    return Result(metric_id=metric_id, admitted=False, iterations=budget, last_stage=last_stage,
                  trace=trace)


def _indent(s, pad):
    return "\n".join(pad + ln for ln in (s or "").splitlines())


def _user_prompt(spec, *, accumulated, prior_constraints):
    import json as _j
    head = (
        "Synthesize a calma/recipe-draft@1 for this metric.\n\n"
        "metric_id: %s\nfamily: %s\ndescription: %s\n\n"
        "REFERENCE ORACLE (your ground truth):\n  call: %s\n  args (input tags, in call order): %s\n"
        "  kwargs: %s\n\n"
        "Declare program.inputs for exactly those tags (%s), a generator per input in the oracle's valid\n"
        "domain, the metamorphic relations the metric obeys, and the edge_cases degradation contract.\n"
    ) % (spec.metric_id, spec.family, spec.description, spec.oracle_call,
         _j.dumps(spec.oracle_args), _j.dumps(spec.oracle_kwargs), ", ".join(spec.oracle_args))
    if spec.inputs_hint:
        head += "\nInput type hints (tag -> list|rawlist): %s\n" % _j.dumps(spec.inputs_hint)
    if prior_constraints:
        head += ("\n=== ACCUMULATED CONSTRAINTS (from other recipes in this family -- do not repeat these "
                 "mistakes) ===\n")
        for c in prior_constraints:
            head += "  - [%s/%s] %s\n" % (c["kind"], c.get("stage", "-"), c["lesson"])
    if accumulated:
        head += "\n=== COUNTEREXAMPLES FROM YOUR PRIOR ATTEMPTS (this metric) ===\n"
        for a in accumulated:
            head += "  attempt %d (%s stage):\n%s\n" % (a["attempt"], a["stage"],
                                                        _indent(a["feedback"], "    "))
    head += "\nEmit the corrected full recipe-draft@1 object via the tool."
    return head


_ALIASES_PROMPT = ("Give 5-8 short lowercase ways a user might search for the metric '%s' (%s) WITHOUT "
                   "knowing its exact name: include the full spelled-out name, the common abbreviation, "
                   "and 3-6 plain-language paraphrases of what it MEASURES. Return a JSON list of strings.")


def _propose_aliases(metric_id, spec, draft):
    """RANKING-ONLY text (never a verdict input). Prefer the spec's seeded aliases (no LLM call); fall
    back to the model only when none were provided."""
    if spec.aliases_seed and len(spec.aliases_seed) >= 2:
        return list(spec.aliases_seed)
    data = llm.structured(_ALIASES_PROMPT % (metric_id, spec.description),
                          schema={"type": "object", "required": ["aliases"], "properties":
                                  {"aliases": {"type": "array", "items": {"type": "string"}}}},
                          model=llm.HAIKU, tool_name="emit")
    return data.get("aliases", [])


def _write_enrichment(metric_id, spec, draft, desc_path=None):
    """Definition-of-done steps 2 & 3: add a recipe_descriptions.json entry (>=2 aliases incl. a
    paraphrase) so test_suggest's coverage guard stays green. RANKING-ONLY text -- an LLM-authored alias
    can never cause a false verification, worst case is a worse suggestion."""
    desc_path = desc_path or DESC_PATH
    aliases = _propose_aliases(metric_id, spec, draft)
    book = json.load(open(desc_path)) if os.path.exists(desc_path) else {"recipes": {}}
    book.setdefault("recipes", {})
    book["recipes"][metric_id] = {"description": spec.description[:160],
                                  "aliases": sorted(set(aliases))}
    json.dump(book, open(desc_path, "w"), indent=2, sort_keys=True)
    return len(book["recipes"][metric_id]["aliases"]) >= 2


def _run_def_of_done_tests():
    """Definition-of-done step 4: the suggester coverage guard + the SOTA reference-vector suite must be
    green AFTER admission (the new recipe is now registered via _load_compiled at import)."""
    import subprocess
    tdir = os.path.join(_SCRIPTS, "tests")
    a = subprocess.run([sys.executable, os.path.join(tdir, "test_suggest.py")],
                       capture_output=True, text=True)
    b = subprocess.run([sys.executable, os.path.join(tdir, "test_recipes_sota.py")],
                       capture_output=True, text=True)
    return a.returncode == 0 and b.returncode == 0


_SYSTEM = """You are the SYNTHESIZER in a Counterexample-Guided Inductive Synthesis (CEGIS) loop for
Calma, a computation-verification engine. You PROPOSE a metric recipe as a single JSON object conforming
to the `calma/recipe-draft@1` schema. A fully deterministic gate then decides -- you are NEVER consulted
after it runs. Your draft becomes a shipped recipe only if it passes ALL of:
  (1) DIFFERENTIAL: your DSL program must equal the NAMED reference oracle (executed in a trusted venv)
      to a relative tolerance of 1e-9 on deterministic datasets of sizes 3, 7, 31, 128, 256.
  (2) METAMORPHIC: your program must satisfy every relation you declare (permutation/scale/shift/
      duplicate/bounds).
  (3) DEGENERACY: on empty / single-row / constant / NaN-bearing inputs your program must DEGRADE to NaN
      (or a finite value you declare) -- never raise, never return +-inf.
  (4) BIT-STABILITY: identical inputs must produce byte-identical results.

You emit EXACTLY ONE object via the provided tool. No prose, no markdown, no code outside the JSON.

=== THE DSL (the language your `program.expr` is written in) ===
A program is a finite JSON expression TREE -- no loops, no names, no I/O. It is evaluated bottom-up and
MUST evaluate to a single scalar. Types: `list` (a numeric column), `rawlist` (a string column),
`scalar`. Node forms:
  {"col": "<tag>"}                          -> a column (its type is whatever program.inputs declares)
  {"lit": <number>}                         -> a scalar literal
  {"call": "<kernel>", "args": [<node>...], "scalars": {<name>: <number>}}  -> scalar  (kernels only)
  {"op": "<+|-|*|/|neg|abs|sqrt|log|exp|min|max>", "args": [<scalar node>(, <scalar node>)]} -> scalar
      (neg/abs/sqrt/log/exp are UNARY; the rest are BINARY. sqrt of a negative -> NaN; log of <=0 -> NaN;
       /0 -> NaN. NaN propagates.)
  {"zip": "<+|-|*|/>", "args": [<list-or-scalar>, <list-or-scalar>]} -> list  (elementwise; broadcasts a
      scalar across a list; length-mismatched lists degrade to empty -> NaN downstream)
  {"len": <list node>}                      -> scalar  (the column length)
Budget: depth <= 16, nodes <= 256. Use ONLY the whitelisted kernels listed below (a `!` marks a REQUIRED
scalar parameter, a `?` an optional one) -- anything else is rejected by the structural stage. A kernel
takes typed args and named scalar parameters EXACTLY as listed:

__KERNELS__

If you need a kernel that is NOT on this list, the metric is currently INEXPRESSIBLE -- say so by emitting
your best partial program and a description that names the missing kernel; do not invent a kernel name.

=== THE ORACLE (your ground truth) ===
`oracle.call` is a dotted path into ONE of: numpy, scipy, sklearn, statsmodels, math, statistics
(nothing else is allowed). `oracle.args` lists the program input tags in the order the callable receives
them; `oracle.kwargs` carries any keyword arguments (THIS IS WHERE ddof / bias / nan_policy LIVE -- get
them right; ddof mismatches are the #1 differential failure). The gate calls
`oracle.call(*[data[t] for t in oracle.args], **oracle.kwargs)` and coerces the result to float. Your
DSL program must reproduce that float to 1e-9 relative.

=== GENERATORS (how the gate samples test data for each input) ===
Declare exactly one generator per program input, with a `kind`:
  uniform{lo,hi}: U[lo,hi)   positive{scale}: scale*(U+1e-6) (strictly >0)   prob{}: U[0,1)
  binary{}: 0/1   int{lo,hi}: integers in [lo,hi]   returns{}: small signed ~U(-0.05,0.05)
  category{k}: k distinct string labels (ONLY for a `rawlist` input -- and a rawlist input REQUIRES kind
  `category`; a numeric input must NOT use category)
Choose generators in the oracle's valid DOMAIN: `prob` for a probability arg, `positive` for a ratio
denominator that must not be zero, `returns` for a return series, `binary` for a 0/1 label.

=== METAMORPHIC RELATIONS (declare the ones your metric actually obeys -- at least one) ===
  {"relation":"permutation","expect":"equal"}            order-invariant metrics
  {"relation":"scale","factor":F,"expect":"equal"|"linear"|"quadratic"}   scale-invariant (equal) vs
       scale-homogeneous (linear: value*F) vs degree-2 (quadratic: value*F^2)
  {"relation":"shift","delta":D,"expect":"equal"|"shift-by-delta"}   translation-invariant vs additive
  {"relation":"duplicate","expect":"equal"}              invariant to doubling the sample
  {"relation":"bounds","min":m,"max":M}                  the value must lie in [m, M]
`tags` (optional) limits which inputs a scale/shift transform touches (default: all numeric inputs).
Declare every relation you are CONFIDENT of -- each one is an extra correctness proof. Do NOT declare a
relation your metric violates; the gate will produce a metamorphic counterexample.

=== EDGE CASES (the degradation contract) ===
For each of empty / single / constant / nan, declare "nan" (must degrade to NaN) or a number (must equal
it). A sample-std-based metric is "nan" on empty and single (n-ddof<=0); a coefficient of variation is 0
on constant data; many ratios are "nan" on constant. Cases you don't list must still never raise and
never return +-inf.

=== HOW TO USE THE FEEDBACK ===
If you receive COUNTEREXAMPLES from a prior attempt, they are CONCRETE failing cases from the gate, plus
accumulated constraints from OTHER recipes in this family. Treat them as ground truth about where your
program is wrong. A differential counterexample tells you the oracle's value vs yours on a specific seed --
reason about which operation differs (a `ddof`, a denominator n vs n-1, a missing sqrt, a sign). Fix that
specific operation; do not rewrite blindly. Re-emit a corrected full draft.

Output ONLY the recipe-draft@1 object via the tool."""
