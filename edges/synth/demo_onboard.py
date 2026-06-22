"""M4 demo -- onboard a firm's BESPOKE metric from a methodology paragraph + a handful of reference
numbers, in ONE run. 'AI proposes, determinism disposes': a cheap LLM proposes the DSL program; the
deterministic gate admits it ONLY when it reproduces the firm's reference vectors (to 1e-9) AND satisfies
the metamorphic relations AND degrades on edge cases AND is bit-stable. No reference venv needed -- the
firm's own numbers are the oracle.

The metric here is a real bespoke convention with NO published callable: a 'load factor' = average
exposure / peak (maximum) exposure (the utilization ratio used in energy/ops, applied to a strategy's
exposure series). The five reference vectors are computed INDEPENDENTLY (plain mean/max), so a successful
onboarding proves Calma reproduces an independent computation -- not its own kernel.

Freezes to a TMP registry (never the committed assets). Run (cheap model, key in the environment):
  PYTHONPATH=. ~/.cache/calma-edges-venv/bin/python edges/synth/demo_onboard.py --model claude-haiku-4-5
"""
import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                                 ".claude", "skills", "calma", "scripts")))
import dsl  # noqa: E402

from edges.common import llm  # noqa: E402
from edges.synth import onboard  # noqa: E402

METHODOLOGY = (
    "Acme Capital reports a proprietary 'load factor' for each strategy's exposure series: the average "
    "exposure over the period divided by the peak (maximum) exposure over the period. Exposures are "
    "always strictly positive. The load factor lies between 0 and 1 -- a value near 1 means exposure was "
    "held steadily near its peak, a low value means exposure spiked only rarely. The metric is invariant "
    "to the units exposure is measured in (scaling every exposure by the same positive constant leaves it "
    "unchanged) and does not depend on the order of the observations.")

# the firm's ground truth -- computed INDEPENDENTLY (plain mean/max), NOT via any Calma kernel
_RAW = [[10, 20, 30, 40], [1, 3, 5, 7, 9], [100, 50, 25, 25], [7, 7, 7], [3, 1, 4, 1, 5, 9, 2, 6]]
REF_VECTORS = [{"inputs": {"value": xs}, "expected": (sum(xs) / len(xs)) / max(xs)} for xs in _RAW]
METAMORPHIC_HINTS = ["invariant to scaling all inputs by a positive constant",
                     "independent of observation order", "bounded between 0 and 1"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=llm.HAIKU, help="proposer model (use a CHEAP one)")
    ap.add_argument("--budget", type=int, default=6, help="max CEGIS attempts")
    a = ap.parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY") and a.model.startswith("claude"):
        sys.exit("set ANTHROPIC_API_KEY to run the live proposer (the gate itself needs no key)")

    tmp = tempfile.mkdtemp(prefix="calma-onboard-demo-")
    paths = dict(compiled_path=os.path.join(tmp, "compiled_recipes.json"),
                 drafts_log=os.path.join(tmp, "onboard_drafts.jsonl"),
                 constraints_db=os.path.join(tmp, "constraints.jsonl"))

    print("=" * 84)
    print("M4 demo: onboard a BESPOKE metric ('Acme load factor' = avg/peak exposure)")
    print("  proposer model : %s   |   budget : %d attempts" % (a.model, a.budget))
    print("  ground truth   : %d firm reference vectors (computed independently, no published oracle)"
          % len(REF_VECTORS))
    print("  gate           : reference vectors + metamorphic + degeneracy + bit-stability (no venv)")
    print("=" * 84)

    res = onboard.onboard("acme_load_factor", "analytics", METHODOLOGY, REF_VECTORS,
                          metamorphic_hints=METAMORPHIC_HINTS, budget=a.budget, model=a.model, **paths)

    print("\nCEGIS trace (AI proposes -> deterministic gate disposes):")
    for t in res.trace:
        if t["ok"]:
            print("  attempt %d: ADMITTED  (program sha256 %s)" % (t["attempt"], t["draft_sha"][:16]))
        else:
            print("  attempt %d: rejected at the %-11s stage -> counterexample fed back"
                  % (t["attempt"], t["stage"]))
    print()
    if not res.admitted:
        print("NOT admitted within budget (last stage: %s)." % res.last_stage)
        if res.last_feedback:
            print("last counterexample:\n" + res.last_feedback)
        sys.exit(1)

    import json
    entry = next(r for r in json.load(open(paths["compiled_path"]))["recipes"]
                 if r["metric_id"] == "acme_load_factor")
    print("ADMITTED in %d attempt(s). The frozen, deterministic recipe the model discovered:"
          % res.iterations)
    print("  expr          : %s" % json.dumps(entry["program"]["expr"]))
    print("  program_sha256: %s" % entry["program_sha256"])
    print("  ground_truth  : %s   |   vectors pinned: %d   |   maturity: %s"
          % (entry["admitted"]["ground_truth"], len(entry["vectors"]), entry["set_maturity"]))
    print("\nIndependent re-check (the frozen program vs the firm's independent numbers):")
    for vec in REF_VECTORS:
        got = dsl.execute(entry["program"], vec["inputs"])
        print("  %-26s expected %.10f  got %.10f  %s"
              % (vec["inputs"]["value"], vec["expected"], got,
                 "OK" if abs(got - vec["expected"]) <= 1e-9 * max(1.0, abs(vec["expected"])) else "MISMATCH"))
    print("\nThe LLM never touched the gate; only a program that reproduces the firm's numbers AND holds")
    print("the declared invariances was admitted. (frozen to a throwaway registry: %s)" % tmp)


if __name__ == "__main__":
    main()
