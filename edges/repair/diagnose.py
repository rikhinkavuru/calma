"""The LLM seam for A4: diagnose the defect and emit a MINIMAL unified diff to the producing code.

AI proposes the patch; the deterministic core (reached only via engine.verify, a subprocess) disposes
the verdict. This module calls edges.common.llm.structured -- it imports no verdict-core module.
"""
from __future__ import annotations

import json
import os

from edges.common import llm
from edges.repair.types import Diagnosis

DIAGNOSE_SYSTEM = '''You are the Debugger in an execution-grounded repair loop. A deterministic verifier
(Calma) RE-EXECUTED a piece of code in a sandbox, RECOMPUTED its headline number from the raw output files,
and REFUTED a claim because the recomputed value differs from the claimed value beyond a calibrated budget.
You are given the exact broken claim, the finding that localizes the defect, the producing code, and the
recompute diff. Your job: explain the root cause in one or two sentences, then emit the SMALLEST possible
unified diff to the PRODUCING CODE that makes the recompute close the gap.

THE RULES -- these are hard constraints; a patch that violates any is rejected by a separate gate you cannot
see or influence, so violating them only wastes a hypothesis:
1. Change ONLY the producing code (the entrypoint and the modules it calls). The fix must make the code
   compute/emit the HONEST number.
2. You MUST NOT edit verify.yaml, the claimed value, the metric binding, or any output/data file the
   verifier recomputes from. Moving the goalposts is detected and rejected.
3. You MUST NOT hard-code the expected number, special-case the verifier, disable a random seed or thread
   pin, swap which artifact is written, or downgrade the isolation tier. The recompute must close the gap
   because the CODE now produces the right values, not because you fed the check a constant.
4. The patch must be MINIMAL -- touch the fewest lines that fix the actual defect named in the finding's
   locator and dimension. Do not refactor, rename, reformat, or "improve" unrelated code.
5. If no honest code-only change can close the gap (e.g. the claim itself is the unfixable part -- an
   in-sample best-of-N number can never be an out-of-sample result), say so in `cause` and emit an EMPTY
   diff. An honest "no code-only fix exists" is correct and preferred over a fabricated one.

Output a single tool call matching the schema: cause, the finding locator you address, the dimension, the
unified_diff (standard `--- a/path` / `+++ b/path` / `@@` hunks, paths relative to the project root), the
exact target_files the diff touches, and a one-line rationale for why this closes the gap without moving a
goalpost. Think about WHY the recomputed number differs from the claim: the verifier read the real outputs,
so if they disagree with the claim, the code wrote the wrong outputs or reported the wrong quantity.'''

DIAGNOSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["cause", "locator", "dimension", "unified_diff", "target_files", "rationale"],
    "properties": {
        "cause":        {"type": "string", "minLength": 1},
        "locator":      {"type": "string"},
        "dimension":    {"type": "string"},
        "unified_diff": {"type": "string"},
        "target_files": {"type": "array", "items": {"type": "string"}},
        "rationale":    {"type": "string", "minLength": 1},
    },
}


# --- gather the deterministic context the prompt needs (all path-independent) -------------------
def _metric_row(diff, metric_id):
    for m in (diff.get("metrics") or []):
        if m.get("metric_id") == metric_id:
            return m
    return {}


def _entrypoint(scratch):
    """The entrypoint relpath from the scratch's committed verify.yaml (default gen_fixture.py)."""
    try:
        contract = json.load(open(os.path.join(scratch, "verify.yaml")))
        ep = (contract.get("run") or {}).get("entrypoint")
        if ep:
            return ep
    except (OSError, ValueError):
        pass
    return "gen_fixture.py"


def _read(scratch, relpath, cap=12000):
    try:
        return open(os.path.join(scratch, relpath)).read()[:cap]
    except OSError:
        return ""


def _extra_sources(scratch, entrypoint, cap=4):
    """Other small .py modules in the scratch (the entrypoint may call them). Deterministic order."""
    out = []
    for dp, dirs, names in os.walk(scratch):
        dirs.sort()
        if any(part in (".git", ".calma", "__pycache__", ".pytest_cache") for part in dp.split(os.sep)):
            continue
        for n in sorted(names):
            if not n.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dp, n), scratch)
            if rel == entrypoint:
                continue
            out.append(rel)
            if len(out) >= cap:
                return out
    return out


def _prior_block(prior):
    if not prior:
        return ""
    return ("\nA PRIOR FIX OF THIS BUG CLASS (dimension match, similar locator) had this shape -- adapt, "
            "don't copy blindly:\n  files: %s\n%s" % (prior.get("files"), prior.get("skeleton", "")))


def _history_block(history):
    if not history:
        return ""
    lines = ["\nALREADY TRIED AND REJECTED (do not repeat):"]
    for diag, why in history:
        summ = (diag.cause or "")[:80]
        lines.append(" - %s: %s" % (summ, why))
    return "\n".join(lines)


def _build_user(scratch, claim, finding, diff, goalposts, *, teardown_card, prior, history):
    metric_id = goalposts.metric_id
    row = _metric_row(diff, metric_id)
    entrypoint = _entrypoint(scratch)
    extra = _extra_sources(scratch, entrypoint)
    extra_sources = "".join(
        "\nA CALLED MODULE (%s)\n```\n%s\n```\n" % (rel, _read(scratch, rel)) for rel in extra)
    rev = (finding or {}).get("reverify") or {}
    return DIAGNOSE_USER.format(
        metric_id=metric_id,
        claimed_value=goalposts.claim_value,
        recomputed_value=row.get("recomputed"),
        verdict=claim.get("verdict"),
        gap=row.get("gap"),
        effective_budget=(row.get("verdict_inputs") or {}).get("effective_budget", row.get("budget")),
        dimension=(finding or {}).get("dimension"),
        severity=(finding or {}).get("severity"),
        locator=(finding or {}).get("locator"),
        reverify_expected=rev.get("expected"),
        teardown_card=teardown_card or "(no teardown card)",
        entrypoint=entrypoint,
        entrypoint_source=_read(scratch, entrypoint),
        extra_sources=extra_sources,
        reason=row.get("reason"),
        prior_episode_block=_prior_block(prior),
        history_block=_history_block(history),
    )


DIAGNOSE_USER = '''BROKEN CLAIM
  metric: {metric_id}
  claimed_value: {claimed_value}
  recomputed_value (by re-execution): {recomputed_value}
  verdict: {verdict}   gap: {gap}   budget (must end <= this): {effective_budget}

THE FINDING THAT LOCALIZES THE DEFECT
  dimension: {dimension}   severity: {severity}
  locator: {locator}
  reverify.expected: {reverify_expected}

WHY IT BREAKS (verifier teardown)
{teardown_card}

THE PRODUCING CODE (entrypoint: {entrypoint})
```
{entrypoint_source}
```
{extra_sources}

THE RECOMPUTE DIFF (what the verifier rebuilt from the raw outputs)
  metric {metric_id}: claimed {claimed_value} -> recomputed {recomputed_value} (gap {gap} > budget {effective_budget})
  reason: {reason}
{prior_episode_block}
{history_block}

Emit the minimal unified diff to the producing code that makes the recompute close the gap, under all the
rules. If no honest code-only fix exists, set cause accordingly and emit an empty unified_diff.'''


def _to_diagnosis(data):
    return Diagnosis(
        cause=data.get("cause", ""),
        locator=data.get("locator", ""),
        dimension=data.get("dimension", ""),
        unified_diff=data.get("unified_diff", "") or "",
        target_files=tuple(data.get("target_files") or ()),
        rationale=data.get("rationale", ""),
    )


def diagnose(scratch, claim, finding, diff, goalposts, *, teardown_card="", prior=None, model=None):
    """First hypothesis: diagnose the defect and emit a minimal unified diff (OPUS by default)."""
    user = _build_user(scratch, claim, finding, diff, goalposts,
                       teardown_card=teardown_card, prior=prior, history=None)
    data = llm.structured(user, schema=DIAGNOSIS_SCHEMA, model=model or llm.OPUS,
                          system=DIAGNOSE_SYSTEM, tool_name="diagnose")
    return _to_diagnosis(data)


def next_hypothesis(scratch, claim, finding, diff, goalposts, *, teardown_card="",
                    history=None, prior=None, model=None):
    """A later hypothesis, conditioned on the rejected diffs so far (do not repeat them)."""
    user = _build_user(scratch, claim, finding, diff, goalposts,
                       teardown_card=teardown_card, prior=prior, history=history or [])
    data = llm.structured(user, schema=DIAGNOSIS_SCHEMA, model=model or llm.OPUS,
                          system=DIAGNOSE_SYSTEM, tool_name="diagnose")
    return _to_diagnosis(data)
