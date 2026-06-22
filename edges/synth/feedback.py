"""Format a single stage-tagged counterexample from compiler.admit() into sharp, localized feedback for
the synthesizer. Feedback is ADVISORY to the proposer; it NEVER relaxes the gate. The differential
formatter does the heavy lifting: it parses expected/got and the sampled inputs and emits a hypothesis
about which DSL operation is wrong (ddof, denominator, sign, a missing sqrt/abs, a degree mismatch)."""
import ast
import math


def format_counterexample(ce: dict) -> str:
    stage = ce.get("stage")
    if stage == "structural":
        return _fmt_structural(ce)
    if stage == "differential":
        return _fmt_differential(ce)
    if stage == "reference":
        return _fmt_reference(ce)
    if stage == "metamorphic":
        return _fmt_metamorphic(ce)
    if stage == "degenerate":
        return _fmt_degenerate(ce)
    if stage == "bit-stability":
        return _fmt_bitstable(ce)
    return "Unknown counterexample stage %r: %r" % (stage, ce)


def _f(x):
    """repr -> float, tolerating 'nan'/'inf'."""
    try:
        return float(ast.literal_eval(x)) if isinstance(x, str) else float(x)
    except Exception:
        return float("nan")


def _fmt_structural(ce):
    return ("STRUCTURAL reject (your draft is not a well-formed/typed program within budget). Fix every "
            "error before anything else runs:\n  - " + "\n  - ".join(ce.get("errors", [])))


def _fmt_differential(ce):
    if "error" in ce:           # the oracle call itself failed -> the ORACLE spec is wrong, not the program
        return ("DIFFERENTIAL: the reference oracle %r raised on seed %s (n=%s): %s\n"
                "  -> Your oracle.call/args/kwargs are wrong (bad kwarg, wrong arg order, or the callable "
                "doesn't take these inputs). Fix the oracle spec, not the program."
                % (ce.get("oracle"), ce.get("seed"), ce.get("n"), ce["error"]))
    exp, got = _f(ce.get("expected")), _f(ce.get("got"))
    lines = ["DIFFERENTIAL mismatch vs %s on seed %s (n=%s):"
             % (ce.get("oracle"), ce.get("seed"), ce.get("n")),
             "  oracle expected = %s" % ce.get("expected"),
             "  your program got = %s" % ce.get("got"),
             "  sampled inputs (first 8 per tag): %s" % ce.get("inputs")]
    lines.append("  HYPOTHESIS: " + _diff_hint(exp, got))
    return "\n".join(lines)


def _diff_hint(exp, got):
    """Localize the wrong operation from the numeric relationship between expected and got. These are the
    recurring DSL synthesis bugs; emit the single most likely cause (the synthesizer fixes that op)."""
    if got != got and exp == exp:
        return ("your program degraded to NaN where the oracle is finite -- a kernel hit an empty list or a "
                "zero denominator on valid data; check a /0, a sqrt of a negative, or a list that came out "
                "empty (length-mismatched zip).")
    if exp != exp and got == got:
        return ("the oracle is NaN/undefined here but your program returned a number -- your degradation is "
                "too permissive; this case should degrade.")
    if exp == 0 or got == 0:
        return "one side is exactly 0 -- check a sign flip, an abs(), or a term that should cancel."
    r = got / exp if exp != 0 else float("nan")
    # ddof: sample vs population std differ by sqrt(n/(n-1)); var by n/(n-1)
    if abs(abs(r) - 1.0) < 0.5 and abs(r) != 1.0:
        return ("you are off by a constant factor ~%.6f. If this is a std/var metric, that is almost "
                "certainly a ddof mismatch (sample ddof=1 divides by n-1; population ddof=0 divides by n; "
                "std ratio = sqrt(n/(n-1)), var ratio = n/(n-1)). Set the kernel's `ddof` scalar to match "
                "the oracle's kwargs. If it is a mean-of-products, check n vs n-1 in YOUR denominator." % r)
    if r < 0 and abs(abs(r) - 1.0) < 1e-6:
        return "you have a SIGN error (got == -expected): a neg/subtraction is reversed (e.g. a-b vs b-a)."
    if abs(r - 2.0) < 1e-6 or abs(r - 0.5) < 1e-6:
        return "off by a factor of 2 -- a duplicated term, a missing/extra 1/2, or a both-tails vs one-tail."
    if exp > 0 and got > 0 and abs(got - exp * exp) / max(1.0, abs(exp * exp)) < 1e-6:
        return "got == expected^2 -- you are missing a sqrt() (or applied one too many)."
    if exp > 0 and got > 0 and abs(got - math.sqrt(exp)) / max(1.0, abs(math.sqrt(exp))) < 1e-6:
        return "got == sqrt(expected) -- you applied an EXTRA sqrt()."
    return ("the discrepancy is not a simple factor/sign/degree -- re-derive the oracle's exact formula "
            "(check its kwargs and definition) and compare operation-by-operation to your expr.")


def _fmt_reference(ce):
    """A firm reference vector the program failed to reproduce. The firm's EXACT inputs are the failing
    case, so the diff hint here is on real data, not an LCG sample."""
    exp, got = _f(ce.get("expected")), _f(ce.get("got"))
    lines = ["REFERENCE-VECTOR mismatch on %s (n=%s):" % (ce.get("oracle"), ce.get("n")),
             "  firm expected    = %s" % ce.get("expected"),
             "  your program got = %s" % ce.get("got"),
             "  the firm's exact inputs (first 8 per tag): %s" % ce.get("inputs"),
             "  HYPOTHESIS: " + _diff_hint(exp, got)]
    return "\n".join(lines)


def _fmt_metamorphic(ce):
    if ce.get("relation") == "bounds":
        return ("METAMORPHIC bounds violated on seed %s (n=%s): value %s is not %s. Either your metric does "
                "NOT obey that bound (drop the relation) or your program is wrong (e.g. a fraction should be "
                "clamped/derived to lie in [0,1])." % (ce.get("seed"), ce.get("n"), ce.get("got"),
                                                       ce.get("expected")))
    return ("METAMORPHIC '%s' (relation #%s) violated on seed %s (n=%s): expected %s, got %s. Your metric "
            "does not transform as you declared. Either the relation is wrong for this metric (a scale-"
            "INVARIANT metric must declare expect 'equal', a scale-HOMOGENEOUS one 'linear'), or your expr "
            "introduces a dependence it shouldn't (e.g. an additive constant breaks scale-invariance)."
            % (ce.get("relation"), ce.get("index"), ce.get("seed"), ce.get("n"),
               ce.get("expected"), ce.get("got")))


def _fmt_degenerate(ce):
    case = ce.get("case")
    if "error" in ce:
        return ("DEGENERACY: on the %r input your program RAISED (%s). Every degenerate input must degrade "
                "to NaN (or a declared finite value), never raise. The DSL degrades /0 and kernel errors to "
                "NaN automatically -- a raise means an op outside that contract; restructure so the bad path "
                "is a kernel/op that NaN-degrades." % (case, ce["error"]))
    return ("DEGENERACY: on the %r input you returned %s but the contract requires %s. If you declared "
            "edge_cases.%s, your program must actually produce it; if you returned +-inf, find the "
            "unbounded op (a /0 you turned into inf, an exp() overflow) and let it degrade to NaN instead."
            % (case, ce.get("got"), ce.get("expected"), case))


def _fmt_bitstable(ce):
    return ("BIT-STABILITY: identical inputs produced two different reprs on seed %s (n=%s): %s vs %s. "
            "Your program is non-deterministic at the bit level -- almost always set iteration/order "
            "(don't rely on dict/set ordering of intermediate values; the kernels are stable, so the "
            "instability is in how you combined them)." % (ce.get("seed"), ce.get("n"),
                                                           ce.get("run1"), ce.get("run2")))


# ---- optional "sharper feedback": derive-then-diff (loop-invariant-synthesis style) ----
def sharper_feedback(ce: dict, spec, *, model) -> str:
    """For a STUBBORN differential case (>=2 failed differential attempts on the same metric). Ask the
    model to write its step-by-step derivation of the formula, then diff that derivation against the
    oracle's published definition to localize the exact wrong step BEFORE it re-drafts. Returns extra
    feedback to append. Still advisory -- the gate is unchanged."""
    from edges.common import llm
    base = format_counterexample(ce)
    prompt = (
        "You keep failing the differential check below. Do NOT emit a new draft yet.\n\n%s\n\n"
        "1) Write the EXACT mathematical definition of %s as computed by the reference oracle `%s` with "
        "kwargs %s (look up its precise formula, including any ddof/bias/normalization).\n"
        "2) Write, step by step, what YOUR current DSL program computes.\n"
        "3) Diff (1) against (2) and state the SINGLE operation that differs and the one-line fix.\n"
        "Answer in 3 short numbered parts." % (base, spec.metric_id, spec.oracle_call, spec.oracle_kwargs)
    )
    return llm.complete(prompt, model=model, system="You localize a synthesis bug by formal derivation.")
