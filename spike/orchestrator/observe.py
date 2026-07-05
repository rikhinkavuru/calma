"""orchestrator.observe — the Prosecutor–Judge observe step (build plan §4.5, slice S2).

Between a failed run and the loop's next move, OBSERVE collects structured evidence (the Prosecutor — via the
S1 remediation registry) and LABELS the failure, distinguishing:

  • SETUP-INDUCED — Calma's own fault, keep adapting (relink the committed data, add the missing dep), and
  • REPO-BUG / ENVIRONMENTAL — the input genuinely isn't in the repo, or the code needs a GPU the tier lacks;
    a different entrypoint can't conjure either, so surface it honestly.

This is the SetupX lesson made structural — separate *setup-induced failure* from *repo bug*, beyond exit
codes (agents that declare "done" when only the install ran). It is the loop-control Judge, DISTINCT from the
FCR Judge that issues the verdict: like everything under ``orchestrator/`` this module never imports
``core.verdict`` / ``core.diff`` and never sees a claim value — it only picks the loop's next move.

The observation drives that move — ``remediate`` (a licensed HOW-only fix), ``stop`` (environmental / repo-bug),
or ``revise`` (a dep/argv/entrypoint problem the loop can iterate on) — and its label + evidence go into the
ReAct trace (self-healing lit: the trace is an audit feature) so a reviewer sees WHY the loop acted.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import remediation as _rem
from .types import RunResult

# faults where a DIFFERENT entrypoint cannot help: the run reached the repo's code and hit a wall re-running
# can't climb — a missing input file, or a GPU the CPU tier lacks. Every other fault is revisable in-approach.
_ENVIRONMENTAL = ("missing-data", "needs-gpu")


@dataclass(frozen=True)
class Observation:
    """The structured read of a failed run + the loop's next move. ``plan`` is a ``remediation.RemediationPlan``
    only when ``next_move == 'remediate'``. Never carries a verdict/claim — purely loop control + audit."""
    fault: str
    label: str            # "setup-induced" | "repo-bug" | "environmental"
    next_move: str        # "remediate" | "stop" | "revise"
    detail: str = ""
    plan: object = None


def _stderr(result: RunResult) -> str:
    return " ".join((m.get("stderr_tail") if isinstance(m, dict) else "") or "" for m in (result.meta or []))


def observe(result: RunResult, repo_dir: str | None = None, *, can_remediate: bool = False,
            already_resolved: bool = False) -> Observation:
    """Classify a failed run and pick the loop's next move. ``repo_dir`` (when given) unlocks the evidence-gated
    remediation registry; without it (the hermetic loop tests) observe degrades to signature-only classification
    — the SAME control flow as the pre-S2 loop, so no behavior change on the injected-fake path."""
    tax = _rem.classify(_stderr(result), repo_dir)
    fault, plan = tax["kind"], tax["plan"]

    # (1) a fixable environmental fault with resolution still available → apply the licensed HOW-only fix once.
    #     (Trigger matches the pre-S2 loop: missing-data + a resolver + not-yet-tried on this approach.)
    if fault == "missing-data" and can_remediate and not already_resolved:
        detail = plan.detail if plan else "attempting data resolution (relink / fetch)"
        return Observation(fault, "setup-induced", "remediate", detail, plan)

    # (2) environmental + nothing left to try → surface honestly, with the Prosecutor–Judge label: a genuine
    #     missing input (repo-bug) vs an infra wall (needs a GPU).
    if fault in _ENVIRONMENTAL:
        if fault == "missing-data":
            detail = "the input file is not committed in-repo and no fetch source resolved it — a genuine " \
                     "missing input, not a setup mistake"
            return Observation(fault, "repo-bug", "stop", detail)
        return Observation(fault, "environmental", "stop", tax.get("hint") or "requires a GPU (CPU tier)")

    # (3) a dependency / argv / entrypoint failure the loop can iterate on.
    return Observation(fault, "setup-induced", "revise", tax.get("hint") or "")
