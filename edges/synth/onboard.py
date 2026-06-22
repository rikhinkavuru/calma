"""M4 -- onboard a firm's BESPOKE metric from a methodology description + firm-supplied reference
vectors. Same CEGIS discipline as synth.cegis, but the ground truth is the FIRM'S OWN numbers, not a
published oracle:

  methodology text (+ reference vectors)  ->  LLM PROPOSES a calma/recipe-draft@1 (a pure-stdlib DSL
  program)  ->  compiler.admit() DISPOSES against the firm's reference vectors + the declared metamorphic
  relations + degeneracy + bit-stability  ->  a draft becomes a frozen, verdict-emitting recipe ONLY when
  it clears the FULL gate. On any failure the concrete counterexample (which reference vector, expected
  vs got, on the firm's exact inputs) is fed back and the model re-proposes, up to a bound.

Why this is a moat and not the 'attested-but-wrong' trap: the LLM never sees the gate after it runs, and
it never supplies its own ground truth -- the firm's reference_vectors are INJECTED by this harness, so
the model can only propose the program, never grade it. The metamorphic relations are a second,
independent gate that catches a program which merely overfits the handful of reference points.

A bespoke metric typically has NO published callable, so admission here needs NO reference venv -- the
firm's numbers are the oracle. The proposer is the only LLM call; everything that ADMITS is deterministic.

Firewall: like the rest of synth, this imports exactly `compiler` and `dsl` from the core (the gate) and
nothing from verdict/ledger/compare/recompute (test_firewall allowlist).
"""
import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field

_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..",
                        ".claude", "skills", "calma", "scripts")
sys.path.insert(0, os.path.abspath(_SCRIPTS))
import compiler  # noqa: E402  the deterministic gate (firewall-sanctioned)
import dsl  # noqa: E402

from edges.common import llm, store  # noqa: E402
from edges.synth import cegis, constraints, feedback  # noqa: E402
from edges.synth.spec import Spec  # noqa: E402

_SCHEMA_PATH = os.path.join(_SCRIPTS, "..", "references", "recipe-draft.schema.json")
DRAFTS_LOG = os.path.join(os.path.dirname(__file__), "data", "onboard_drafts.jsonl")


@dataclass
class OnboardResult:
    metric_id: str
    admitted: bool
    iterations: int
    program_sha256: str = None
    vectors: list = field(default_factory=list)        # the firm reference vectors pinned on admission
    last_stage: str = None                             # stage of the final failing counterexample
    trace: list = field(default_factory=list)          # [{attempt, ok, stage|None, draft_sha}]
    last_feedback: str = None                          # the final counterexample text (if not admitted)


def _onboard_schema():
    """The proposer's structured-output schema = the recipe-draft schema with `oracle` removed: a
    bespoke metric has no published oracle, and the firm's reference_vectors are injected by the harness
    (never modeled), so the LLM proposes ONLY the program/generators/metamorphic/edge_cases."""
    base = json.load(open(_SCHEMA_PATH))
    s = json.loads(json.dumps(base))                   # deep copy; never mutate the committed schema
    s.get("properties", {}).pop("oracle", None)
    s["required"] = [r for r in s.get("required", []) if r != "oracle"]
    return s


def onboard(metric_id, family, methodology, reference_vectors, *, metamorphic_hints=None,
            description=None, budget=8, model=llm.HAIKU, compiled_path=None, drafts_log=None,
            constraints_db=None):
    """Run the onboarding CEGIS loop for ONE bespoke metric. Returns OnboardResult. Never raises on a
    synthesis miss -- a miss is OnboardResult(admitted=False) with the last counterexample stage.

    metric_id / family : the recipe identity (family is one of the draft-schema family enum values).
    methodology        : the firm's plain-language definition of the metric (what the model reads).
    reference_vectors  : the firm's ground truth, [{"inputs": {tag: [..]}, "expected": <number>}, ...];
                         INJECTED into every draft, so the model proposes only the program.
    metamorphic_hints  : optional list of plain-language invariants the operator knows hold (e.g.
                         'scale-invariant', 'bounded in [0,1]') -- surfaced to the proposer.
    The path params default to production locations; tests/demos pass tmp paths so onboarding a toy
    metric never mutates the committed registry / constraint DB.
    """
    assert re.fullmatch(r"[a-z][a-z0-9_]*", metric_id), "metric_id must match ^[a-z][a-z0-9_]*$"
    assert isinstance(reference_vectors, list) and reference_vectors, "reference_vectors required"
    compiled_path = compiled_path or compiler.COMPILED_PATH
    drafts_log = drafts_log or DRAFTS_LOG
    schema = _onboard_schema()
    # a minimal Spec so the cross-recipe constraint DB (ConVer) still accumulates lessons by family;
    # onboarding has no named oracle, so oracle_call is just a label in the recorded lesson.
    spec = Spec(metric_id=metric_id, family=family,
                description=(description or methodology)[:300],
                oracle_call="(firm reference vectors)", oracle_args=[], oracle_kwargs={})
    acc, trace, last_stage, last_feedback = [], [], None, None

    for attempt in range(1, budget + 1):
        prior = constraints.relevant(spec, db=constraints_db)
        prompt = _user_prompt(metric_id, family, methodology, reference_vectors,
                              metamorphic_hints, acc, prior)
        model_draft = llm.structured(prompt, schema=schema, model=model, system=_system(),
                                     tool_name="emit")
        draft = dict(model_draft)
        draft["schema"] = "calma/recipe-draft@1"
        draft["metric_id"] = metric_id                  # the identity is the operator's, not the model's
        draft["family"] = family
        draft.pop("oracle", None)                        # a bespoke metric has no published oracle
        draft["reference_vectors"] = reference_vectors   # the firm's ground truth -- injected, not modeled
        draft_sha = dsl.program_hash(draft.get("program", {})) if draft.get("program") else None
        store.append(drafts_log, {"metric_id": metric_id, "attempt": attempt, "draft": draft,
                                  "draft_program_sha": draft_sha})

        ok, result = compiler.admit(draft, venv_python=None, compiled_path=compiled_path, write=False)
        if ok:
            ok2, result2 = compiler.admit(draft, venv_python=None, compiled_path=compiled_path,
                                          write=True)         # FREEZE (+ SSHSIG-sign when a key exists)
            assert ok2, "a draft that passed the dry run must pass on write"
            compiled = result2["compiled"]
            constraints.record_positive(spec, draft, db=constraints_db)
            trace.append({"attempt": attempt, "ok": True, "draft_sha": compiled["program_sha256"]})
            return OnboardResult(metric_id=metric_id, admitted=True, iterations=attempt,
                                 program_sha256=compiled["program_sha256"], vectors=compiled["vectors"],
                                 trace=trace)

        ce = result["counterexamples"][0]                # the FIRST counterexample -- most localized
        last_stage = ce["stage"]
        last_feedback = feedback.format_counterexample(ce)
        constraints.record_negative(spec, draft, ce, db=constraints_db)
        acc.append({"attempt": attempt, "stage": ce["stage"], "feedback": last_feedback})
        trace.append({"attempt": attempt, "ok": False, "stage": ce["stage"], "draft_sha": draft_sha})

    return OnboardResult(metric_id=metric_id, admitted=False, iterations=budget, last_stage=last_stage,
                         trace=trace, last_feedback=last_feedback)


def _system():
    """The proposer system prompt with the gate's live kernel whitelist spliced in (reused from cegis so
    the two paths never drift)."""
    return _SYSTEM.replace("__KERNELS__", cegis._render_kernels())


def _indent(s, pad):
    return "\n".join(pad + ln for ln in (s or "").splitlines())


def _fmt_reference_vectors(reference_vectors):
    lines = []
    for i, vec in enumerate(reference_vectors):
        ins = ", ".join("%s=%s" % (t, json.dumps(v)) for t, v in (vec.get("inputs") or {}).items())
        lines.append("  [%d] inputs: %s  -> expected: %s" % (i, ins, vec.get("expected")))
    return "\n".join(lines)


def _user_prompt(metric_id, family, methodology, reference_vectors, metamorphic_hints, accumulated,
                 prior_constraints):
    inputs = sorted({t for vec in reference_vectors for t in (vec.get("inputs") or {})})
    head = (
        "Onboard a firm's BESPOKE metric. Synthesize a calma/recipe-draft@1 (WITHOUT an oracle field).\n\n"
        "metric_id: %s\nfamily: %s\n\n"
        "METHODOLOGY (the firm's own definition -- this is what the metric MEANS):\n%s\n\n"
        "REFERENCE VECTORS (the firm's ground truth; your program MUST reproduce every `expected` to a\n"
        "relative tolerance of 1e-9 on exactly these inputs):\n%s\n\n"
        "Declare program.inputs for exactly these tags: %s. Declare one generator per input (used by the\n"
        "metamorphic + degeneracy stages to sample fresh data), the metamorphic relations the metric\n"
        "obeys, and the edge_cases degradation contract. Do NOT emit an oracle.\n"
    ) % (metric_id, family, methodology.strip(), _fmt_reference_vectors(reference_vectors),
         ", ".join(inputs))
    if metamorphic_hints:
        head += ("\nThe operator believes these invariants hold (declare the matching metamorphic\n"
                 "relations only if the methodology supports them): %s\n" % "; ".join(metamorphic_hints))
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
    head += "\nEmit the corrected full recipe-draft@1 object (no oracle) via the tool."
    return head


_SYSTEM = """You are the SYNTHESIZER in a Counterexample-Guided Inductive Synthesis (CEGIS) loop that
ONBOARDS a firm's bespoke metric for Calma, a computation-verification engine. You are given the firm's
METHODOLOGY (plain-language definition) and its REFERENCE VECTORS (concrete inputs paired with the
expected value). There is NO published oracle. You PROPOSE the metric as a single JSON object conforming
to the `calma/recipe-draft@1` schema MINUS the oracle field. A fully deterministic gate then decides --
you are NEVER consulted after it runs. Your draft becomes a shipped recipe only if it passes ALL of:
  (1) REFERENCE: your DSL program must equal every firm reference vector's `expected` to a relative
      tolerance of 1e-9 on exactly the firm's inputs.
  (2) METAMORPHIC: your program must satisfy every relation you declare (permutation/scale/shift/
      duplicate/bounds). These are an INDEPENDENT correctness gate -- a program that merely fits the few
      reference points but has the wrong shape fails here. Declare every relation the methodology implies.
  (3) DEGENERACY: on empty / single-row / constant / NaN-bearing inputs your program must DEGRADE to NaN
      (or a finite value you declare) -- never raise, never return an infinity.
  (4) BIT-STABILITY: identical inputs must produce byte-identical results.

You emit EXACTLY ONE object via the provided tool. No prose, no markdown, no code outside the JSON. Do
NOT emit an `oracle` field -- the firm's reference vectors are the ground truth and are supplied for you.

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
Budget: depth <= 16, nodes <= 256. Use ONLY the whitelisted kernels below (a `!` marks a REQUIRED scalar
parameter, a `?` an optional one); anything else is rejected by the structural stage:

__KERNELS__

If you need a kernel that is NOT on this list, the metric is currently INEXPRESSIBLE -- emit your best
partial program and name the missing kernel in the description; do not invent a kernel name.

=== GENERATORS (one per program input; used by the metamorphic + degeneracy stages) ===
  uniform{lo,hi}: U[lo,hi)   positive{scale}: scale*(U+1e-6) (strictly >0)   prob{}: U[0,1)
  binary{}: 0/1   int{lo,hi}: integers in [lo,hi]   returns{}: small signed ~U(-0.05,0.05)
  category{k}: k distinct string labels (ONLY for a `rawlist` input -- and a rawlist input REQUIRES kind
  `category`; a numeric input must NOT use category)
Choose a generator in the metric's valid DOMAIN (e.g. `positive` if the methodology says inputs are
always positive, `prob` for a probability, `returns` for a return series).

=== METAMORPHIC RELATIONS (declare every one the methodology implies -- at least one) ===
  {"relation":"permutation","expect":"equal"}            order-invariant metrics
  {"relation":"scale","factor":F,"expect":"equal"|"linear"|"quadratic"}   scale-invariant (equal) vs
       scale-homogeneous (linear: value*F) vs degree-2 (quadratic: value*F^2)
  {"relation":"shift","delta":D,"expect":"equal"|"shift-by-delta"}   translation-invariant vs additive
  {"relation":"duplicate","expect":"equal"}              invariant to doubling the sample
  {"relation":"bounds","min":m,"max":M}                  the value must lie in [m, M]
The methodology often states these directly ('invariant to the units', 'does not depend on order',
'lies between 0 and 1'). Declare the matching relations -- each is an extra correctness proof. Do NOT
declare a relation the metric violates; the gate will produce a metamorphic counterexample.

=== EDGE CASES (the degradation contract) ===
For each of empty / single / constant / nan, declare "nan" (must degrade to NaN) or a number (must equal
it). Cases you don't list must still never raise and never return an infinity.

=== HOW TO USE THE FEEDBACK ===
A counterexample is a CONCRETE failing case from the gate. A REFERENCE counterexample gives the firm's
exact inputs, their expected value, and what your program produced -- reason about which operation differs
(a denominator, a sign, a missing sqrt, a ddof) and fix THAT operation; do not rewrite blindly. A
METAMORPHIC counterexample means your program has the wrong shape (e.g. an additive term breaks scale-
invariance). Re-emit a corrected full draft.

Output ONLY the recipe-draft@1 object (no oracle) via the tool."""


def _read_methodology(s):
    """`@path` reads a file; anything else is the methodology text verbatim."""
    if s.startswith("@"):
        return open(s[1:]).read()
    return s


def _load_vectors(s):
    """A path to a JSON file, or inline JSON: [{"inputs": {tag: [..]}, "expected": <number>}, ...]."""
    if os.path.exists(s):
        return json.load(open(s))
    return json.loads(s)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m edges.synth.onboard",
        description="Onboard a firm's bespoke metric from a methodology + reference vectors. The LLM "
                    "proposes the DSL program; the deterministic gate admits it only when it reproduces "
                    "every firm reference vector + holds the declared metamorphic relations + degrades on "
                    "edge cases + is bit-stable. AI proposes, determinism disposes.")
    ap.add_argument("--metric-id", required=True, help="^[a-z][a-z0-9_]*$")
    ap.add_argument("--family", required=True,
                    help="quant|classification|regression|analytics|engineering|retrieval|llm-eval|"
                         "stats|finance|forecasting")
    ap.add_argument("--methodology", required=True, help="the metric's definition (text, or @path-to-file)")
    ap.add_argument("--vectors", required=True,
                    help="reference vectors: a path to a JSON file, or inline JSON "
                         "[{\"inputs\": {tag: [..]}, \"expected\": <number>}, ...]")
    ap.add_argument("--metamorphic-hint", action="append", default=[], dest="hints",
                    help="a plain-language invariant the metric obeys (repeatable)")
    ap.add_argument("--model", default=llm.HAIKU, help="proposer model (use a cheap one)")
    ap.add_argument("--budget", type=int, default=6, help="max CEGIS attempts")
    ap.add_argument("--compiled-path", default=None,
                    help="freeze target registry (default: the production compiled_recipes.json)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="machine-readable result")
    a = ap.parse_args(argv)

    res = onboard(a.metric_id, a.family, _read_methodology(a.methodology), _load_vectors(a.vectors),
                  metamorphic_hints=a.hints, budget=a.budget, model=a.model,
                  compiled_path=a.compiled_path)

    if a.as_json:
        print(json.dumps({"admitted": res.admitted, "metric_id": res.metric_id,
                          "iterations": res.iterations, "program_sha256": res.program_sha256,
                          "last_stage": res.last_stage, "trace": res.trace}))
        return 0 if res.admitted else 1
    print("onboarding %r (%s) -- AI proposes, the deterministic gate disposes:" % (a.metric_id, a.family))
    for t in res.trace:
        if t["ok"]:
            print("  attempt %d: ADMITTED (program sha256 %s)" % (t["attempt"], (t["draft_sha"] or "")[:16]))
        else:
            print("  attempt %d: rejected at the %-11s stage -> counterexample fed back"
                  % (t["attempt"], t["stage"]))
    if res.admitted:
        print("\nADMITTED in %d attempt(s). program_sha256=%s" % (res.iterations, res.program_sha256))
        print("%d reference vectors pinned; the recipe is frozen and will re-validate on load."
              % len(res.vectors))
    else:
        print("\nNOT admitted within budget (last failing stage: %s)." % res.last_stage)
        if res.last_feedback:
            print(res.last_feedback)
    return 0 if res.admitted else 1


if __name__ == "__main__":
    sys.exit(main())
