"""ConVer constraint DB for A3. Every synthesis attempt -- pass OR fail -- deposits a constraint. The DB
is APPEND-ONLY JSONL (edges/synth/data/constraints.jsonl). Each synthesize() prompt is conditioned on the
relevant accumulated set, so a mistake made once on one metric is not re-made on the next. Constraints
shape the PROPOSER only; the gate is never consulted here and never changes.

(Every read/write takes an optional `db=` path so a test can isolate to a tmp DB; production uses the
module default.)"""
import os

from edges.common import store

DB = os.path.join(os.path.dirname(__file__), "data", "constraints.jsonl")

# A constraint record:
#   {"kind": "positive"|"negative"|"implication",
#    "family": "<family>", "kernels": ["<kernel>", ...], "stage": "<failure stage>"|None,
#    "metric_id": "<id>", "lesson": "<one-line, model-facing>", "ts": "<from args>"}
# positive    : a draft that PASSED the whole gate (an existence proof: "this expr admits for this oracle")
# negative    : a draft that FAILED a stage (the lesson is the localized feedback -- do not repeat)
# implication : a derived rule ("kernel fstd's `ddof` scalar must match the oracle's ddof kwarg")


def _kernels_of(program):
    """Collect every kernel name referenced in a program expr (walk the tree). Mirrors dsl's node walk."""
    out = set()

    def walk(node):
        if not isinstance(node, dict):
            return
        if "call" in node and isinstance(node["call"], str):
            out.add(node["call"])
        for a in node.get("args", []):
            walk(a)
        if "len" in node:
            walk(node["len"])
    walk((program or {}).get("expr", {}))
    return sorted(out)


def record_positive(spec, draft, *, ts=None, db=None):
    kernels = _kernels_of(draft.get("program", {}))
    store.append(db or DB, {"kind": "positive", "family": spec.family,
                            "kernels": kernels, "stage": None,
                            "metric_id": spec.metric_id,
                            "lesson": "ADMITTED: %s = a program using kernels %s against oracle %s; this "
                                      "shape is known-good for this family."
                                      % (spec.metric_id, kernels, spec.oracle_call),
                            "ts": ts})


def record_negative(spec, draft, ce, *, ts=None, db=None):
    from edges.synth import feedback
    store.append(db or DB, {"kind": "negative", "family": spec.family,
                            "kernels": _kernels_of(draft.get("program", {})), "stage": ce.get("stage"),
                            "metric_id": spec.metric_id,
                            "lesson": _one_line(feedback.format_counterexample(ce)), "ts": ts})


def record_implication(family, kernels, lesson, *, ts=None, db=None):
    store.append(db or DB, {"kind": "implication", "family": family, "kernels": sorted(kernels),
                            "stage": None, "metric_id": None, "lesson": lesson, "ts": ts})


def _one_line(s):
    s = " ".join(s.split())
    return s[:280]


def relevant(spec, *, limit=12, db=None):
    """Retrieve the constraints most likely to help THIS spec: same family first. Dedup by lesson; cap to
    `limit` (implication > positive > negative; within a kind, file order)."""
    rows = list(store.iter_records(db or DB))
    fam = [r for r in rows if r.get("family") == spec.family]
    order = {"implication": 0, "positive": 1, "negative": 2}
    fam.sort(key=lambda r: (order.get(r["kind"], 3),))
    seen, out = set(), []
    for r in fam:
        key = r["lesson"]
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= limit:
            break
    return out


def taxonomy(spec_family=None, *, db=None):
    """Mine a periodic failure taxonomy: the top recurring (stage, lesson-cluster) per family. Folded into
    the synthesizer SYSTEM prompt on a refresh. Returns {family: [(stage, count, exemplar_lesson), ...]}."""
    from collections import Counter, defaultdict
    by_fam = defaultdict(Counter)
    exemplar = {}
    for r in store.iter_records(db or DB):
        if r.get("kind") != "negative":
            continue
        if spec_family and r.get("family") != spec_family:
            continue
        key = (r.get("family"), r.get("stage"))
        by_fam[r.get("family")][r.get("stage")] += 1
        exemplar.setdefault(key, r.get("lesson"))
    out = {}
    for fam, ctr in by_fam.items():
        out[fam] = [(stage, n, exemplar.get((fam, stage), "")) for stage, n in ctr.most_common(5)]
    return out


def taxonomy_prompt_block(spec_family, *, db=None):
    """A short text block for the system prompt: 'in family X, the most common failure is a ddof mismatch
    on the differential stage'. Regenerated on refresh, not per-call."""
    tax = taxonomy(spec_family, db=db).get(spec_family, [])
    if not tax:
        return ""
    lines = ["Common failure modes already seen in the '%s' family (avoid these):" % spec_family]
    for stage, n, ex in tax:
        lines.append("  - %s (x%d): %s" % (stage, n, ex))
    return "\n".join(lines)
