"""calma.spike.orchestrator.orchestrate — assess → rank → bounded execute/observe/revise (Phase 2).

This is the make-runnable BRAIN. After the static assessment (``assess.py``) it ranks a small set of typed
``RunApproach`` candidates (static-first; one reused LLM turn only when the profile is ambiguous), then runs
a bounded loop that tries them in order, observing each run and revising (add a dep, switch builder/entry,
set an env var) until the repo runs and its computations are captured — or it honestly gives up.

FCR (build plan §0): the loop's ONLY product is a ``RunResult`` (runs/meta/cost/source_modified). It has no
verdict tool; a wrong choice yields wrong/empty capture → DISCOVERED/REFUTED downstream, never a false
CONFIRM. The effectors (build+run) are INJECTED, so this module is pure orchestration — fully testable
without a sandbox or an API key, exactly like ``runner/repair.py``.

Three SOTA hardenings the base plan under-specified, closed here:
  * **No-progress / oscillation detection** — a revised approach that hashes to one already tried ends the
    revise chain (stop thrashing; SOTA: hash the action tuple, repeats = stuck).
  * **Budget checked BEFORE the effector runs** — never pay for the call that busts the ceiling.
  * **Untrusted-content envelope** — hostile repo text is spotlighted + injection-scanned (``envelope.py``);
    findings surface in the trace/report. Defense-in-depth atop the structural firewall.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from core import limits as LIM

from . import envelope as ENV
from . import registry as REG  # noqa: F401 — ensures the package's tools are importable alongside the loop
from . import tools_static as S
from .assess import assess
from .types import RunApproach, RunResult

# how many ranked candidates the loop will try (A4). Tier-scaled by the caller; a sane default here.
MAX_APPROACHES = 4
STEP_CAP = 6


# ── budget (checked BEFORE each effector call) ────────────────────────────────────────────────────────────────
@dataclass
class Budget:
    """Loop ceilings. ``time_left`` is an optional callable returning seconds remaining (injected so tests need
    no clock). Every ceiling is checked BEFORE an effector runs, so we never pay for the step that busts it."""
    step_cap: int = STEP_CAP
    max_approaches: int = MAX_APPROACHES
    tokens_cap: int | None = None
    time_left: Callable[[], float] | None = None
    _steps: int = 0
    _tokens: int = 0

    def stop_reason(self) -> str | None:
        if self._steps >= self.step_cap:
            return "step-cap (%d)" % self.step_cap
        if self.tokens_cap is not None and self._tokens >= self.tokens_cap:
            return "token-budget (%d)" % self.tokens_cap
        if self.time_left is not None:
            try:
                if self.time_left() <= 0:
                    return "wall-deadline"
            except Exception:  # noqa: BLE001
                pass
        return None

    def charge_step(self):
        self._steps += 1

    def charge_tokens(self, n: int):
        self._tokens += max(0, int(n or 0))


# ── approach identity (oscillation detection) ─────────────────────────────────────────────────────────────────
def approach_key(a: RunApproach) -> tuple:
    """A stable identity for an approach, used to detect no-progress loops. Two approaches that would run the
    SAME way (same entry/builder/runner/deps/env) share a key even if notes/confidence differ."""
    return (tuple(a.entry), a.builder, a.runner,
            tuple(sorted(a.deps)), tuple(sorted(a.env.items())))


# ── ranking: static-first, one reused LLM turn only when ambiguous ────────────────────────────────────────────
def _builder_for(profile) -> str:
    if profile.pkg_manager == "conda":
        return "conda-micromamba"
    if profile.pkg_manager in ("pyproject", "poetry", "pipenv", "setup") and profile.declared_deps:
        return "declared"
    return "venv-pip"


def build_static_approaches(profile, repo_dir: str) -> list[RunApproach]:
    """Deterministic candidate approaches from the profile — ZERO LLM. One per ranked entry candidate, with a
    builder chosen from the package manager and deps from the declared manifest / entry-seeded scan."""
    builder = _builder_for(profile)
    targets = S.propose_capture_targets(repo_dir,
                                        entry=(profile.entry_candidates[0].argv
                                               if profile.entry_candidates else None))
    approaches: list[RunApproach] = []
    for cand in profile.entry_candidates[:MAX_APPROACHES]:
        deps = list(profile.declared_deps)
        if not deps:                                     # B5: seed deps from the entrypoint's transitive imports
            deps = S.entry_seeded_imports(repo_dir, cand.argv)
        approaches.append(RunApproach(
            runner="local", builder=builder if deps else "none",
            entry=list(cand.argv), deps=LIM.sanitize_pip(deps),
            capture_targets=list(targets), env={},
            notes="static: %s (%s)" % (" ".join(cand.argv), ", ".join(cand.signals) or "heuristic"),
            confidence=cand.confidence))

    # A3: a Makefile target as an approach. First when the repo is make-driven (no script entry), else a
    # lower-ranked fallback — some repos only reproduce via `make`.
    if profile.make_targets:
        pref = next((t for t in ("reproduce", "all", "run", "eval", "evaluate", "benchmark", "experiment",
                                 "main") if t in profile.make_targets), profile.make_targets[0])
        mk = RunApproach(runner="local", builder=(builder if profile.declared_deps else "none"),
                         entry=["make:" + pref], deps=LIM.sanitize_pip(profile.declared_deps),
                         capture_targets=list(targets), env={},
                         notes="static: make %s" % pref,
                         confidence=0.55 if profile.layout == "make-driven" else 0.35)
        approaches.insert(0, mk) if profile.layout == "make-driven" else approaches.append(mk)
    return approaches[:MAX_APPROACHES + 1]


def _is_ambiguous(profile) -> bool:
    """The profile is unambiguous when there's a single clearly-best entrypoint. Only then do we skip the LLM
    (SOTA Profile-Then-Reason: a predictable task doesn't need the ReAct/LLM turn)."""
    cands = profile.entry_candidates
    if not cands:
        return True                                       # nothing found → ask the model
    if len(cands) == 1:
        return cands[0].confidence < 0.8
    # two near-tied top candidates → ambiguous
    return (cands[0].confidence - cands[1].confidence) < 0.15


def rank_approaches(profile, repo_dir: str, *, use_llm: bool = True, model: str | None = None,
                    plan: dict | None = None, log=None) -> list[RunApproach]:
    """Return ranked RunApproach[]. Static approaches always; when the profile is ambiguous AND the LLM is
    available, one reused planner turn proposes a top candidate placed first. The planner is the tested,
    FCR-safe LLM plumbing (validated entrypoint + sanitized deps); reusing it avoids a second raw model call.

    ``plan``: a pre-computed planner result (the pipeline runs the planner in a BACKGROUND THREAD to overlap
    the E2B boot; passing it here reuses that turn instead of making a second call)."""
    static = build_static_approaches(profile, repo_dir)

    # defense-in-depth: scan the README for injection and record it (the structural firewall is the real guard)
    inj = _scan_repo_injection(repo_dir)
    if inj and log:
        log("orchestrator: untrusted-content injection patterns flagged in repo docs: %s" % ", ".join(inj))

    if not use_llm or not _is_ambiguous(profile):
        return static
    if plan is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return static
        try:
            import planner as PLAN
        except Exception:  # noqa: BLE001
            return static
        plan = PLAN.plan_repo(repo_dir, model=model)
    if not plan or not plan.get("entry"):
        return static
    llm = RunApproach(
        runner="local",
        builder=("declared" if profile.declared_deps and not plan.get("pip_install") else _builder_for(profile)),
        entry=list(plan["entry"]),
        deps=LIM.sanitize_pip(plan.get("pip_install") or profile.declared_deps),
        capture_targets=list(plan.get("targets") or S.propose_capture_targets(repo_dir, entry=plan["entry"])),
        env={},
        notes="llm-ranked: %s" % (plan.get("notes") or "planner proposal"),
        confidence=max(0.85, float(plan.get("confidence") or 0.85)))
    ranked = [llm] + [a for a in static if approach_key(a) != approach_key(llm)]
    if log:
        log("orchestrator: LLM ranked entrypoint %s first (%d candidates)" % (" ".join(llm.entry), len(ranked)))
    return ranked[:MAX_APPROACHES + 1]


def _scan_repo_injection(repo_dir: str) -> list[str]:
    hits: list[str] = []
    for fn in ("README.md", "README.rst", "README.txt", "readme.md", "REPRODUCE.md"):
        p = os.path.join(repo_dir, fn)
        if os.path.isfile(p):
            try:
                hits += ENV.scan_injection(open(p, errors="replace").read(50_000))
            except OSError:
                pass
    # de-dup preserve order
    seen, out = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


# ── revise steps (heuristic key-free; LLM best-effort → heuristic) ────────────────────────────────────────────
def _missing_module(result: RunResult) -> str | None:
    """The top-level module name from a ModuleNotFoundError in the run's stderr, if any. Also detects pandas'
    'Unable to find a usable engine' (a missing parquet backend) → pyarrow, so the revise loop heals it."""
    import re
    for m in (result.meta or []):
        tail = (m.get("stderr_tail") if isinstance(m, dict) else "") or ""
        if "Unable to find a usable engine" in tail or "pyarrow is required" in tail:
            return "pyarrow"
        mm = re.search(r"ModuleNotFoundError: No module named ['\"]([\w.]+)['\"]", tail)
        if mm:
            return mm.group(1).split(".")[0]
    return None


def _with_dep(approach: RunApproach, dist: str, note: str) -> RunApproach | None:
    new_deps = LIM.sanitize_pip(approach.deps + [dist])
    if set(new_deps) == set(approach.deps):
        return None
    return RunApproach(runner=approach.runner,
                       builder=(approach.builder if approach.builder != "none" else "venv-pip"),
                       entry=list(approach.entry), deps=new_deps,
                       capture_targets=list(approach.capture_targets), env=dict(approach.env),
                       notes=note, confidence=approach.confidence)


def _with_env(approach: RunApproach, env: dict, note: str) -> RunApproach | None:
    merged = {**approach.env, **{str(k): str(v) for k, v in env.items()}}
    if merged == approach.env:
        return None
    return RunApproach(runner=approach.runner, builder=approach.builder, entry=list(approach.entry),
                       deps=list(approach.deps), capture_targets=list(approach.capture_targets),
                       env=merged, notes=note, confidence=approach.confidence)


def _apply_hint(approach: RunApproach, action: dict) -> RunApproach | None:
    """Apply a HОW-only fix from the HintStore (add a dep / set an env var) to an approach."""
    if not isinstance(action, dict):
        return None
    if action.get("add_dep"):
        r = _with_dep(approach, str(action["add_dep"]), "hint: +dep %s (learned fix)" % action["add_dep"])
        if r:
            return r
    if isinstance(action.get("set_env"), dict):
        r = _with_env(approach, action["set_env"], "hint: env %s (learned fix)" % list(action["set_env"]))
        if r:
            return r
    return None


def heuristic_revise(result: RunResult, approach: RunApproach, history: list) -> RunApproach | None:
    """Key-free revise: on a missing module, add its PyPI distribution to deps (once). Otherwise give up on
    this approach (→ the loop moves to the next ranked candidate). Env-only: never edits source."""
    mod = _missing_module(result)
    if mod:
        dist = S.import_to_dist(mod)
        if dist and dist not in set(approach.deps):
            return _with_dep(approach, dist, "revise: +dep %s (missing-module heal)" % dist)
    return None


def make_revise(hints=None):
    """A revise closure that consults the HintStore first (an error-signature this loop — or any past run —
    already solved), then falls back to the key-free heuristic. HOW-only; never touches a verdict."""
    def revise(result: RunResult, approach: RunApproach, history: list):
        if hints is not None:
            from .cache import error_signature
            stderr = " ".join((m.get("stderr_tail") if isinstance(m, dict) else "") or "" for m in (result.meta or []))
            sig = error_signature(stderr)
            act = hints.get(sig) if sig else None
            if act:
                r = _apply_hint(approach, act)
                if r is not None:
                    return r
        return heuristic_revise(result, approach, history)
    return revise


# ── the bounded execute/observe/revise loop ───────────────────────────────────────────────────────────────────
def _captured(result: RunResult) -> bool:
    return bool(result.runs and result.runs[0])


def _fix_delta(old: RunApproach, new: RunApproach) -> dict | None:
    """The HOW-only change a revise applied (for the HintStore): a dep added or an env var set."""
    added = [d for d in new.deps if d not in old.deps]
    if added:
        return {"add_dep": added[0]}
    envd = {k: v for k, v in new.env.items() if old.env.get(k) != v}
    if envd:
        return {"set_env": envd}
    return None


def _stderr(result: RunResult) -> str:
    return " ".join((m.get("stderr_tail") if isinstance(m, dict) else "") or "" for m in (result.meta or []))


def execute(approaches: list[RunApproach], run_approach, *, revise=heuristic_revise,
            success=None, budget: Budget | None = None, hints=None, log=None, resolve_data=None) -> RunResult:
    """Try ranked ``approaches`` in order, revising each until it runs with captures or the budget stops us.

    ``run_approach(approach) -> RunResult`` is the INJECTED effector (build + probe + k-run). ``revise`` maps a
    failed result to the next approach (or None → next candidate). ``success(result) -> bool`` decides when to
    stop (default: ran and captured something). ``hints`` (optional HintStore) records a fix that VERIFIABLY
    worked (a revise whose next run succeeded), so a future novel repo with the same error gets the fix for
    free. Returns the first successful result, else the best-effort run that at least executed, else an honest
    empty RunResult (→ DISCOVERED — this is C3: no fabricated eval.py)."""
    budget = budget or Budget()
    success = success or (lambda r: r.ran_ok and _captured(r))
    trace: list[dict] = []
    best_effort: RunResult | None = None
    tried: set[tuple] = set()
    resolved: set[tuple] = set()                            # approaches whose missing-data we already tried to fix
    sig_fn: Callable[[str], str | None] | None = None
    if hints is not None:
        from .cache import error_signature as sig_fn

    for idx, approach in enumerate(approaches[:budget.max_approaches]):
        pending: tuple | None = None                       # (sig, action) applied last, awaiting verification
        while True:
            stop = budget.stop_reason()
            if stop:                                       # budget checked BEFORE the effector runs
                trace.append({"event": "budget-stop", "reason": stop, "approach": idx})
                if log:
                    log("orchestrator: stopping — %s" % stop)
                return _finish(best_effort, approach, trace)
            key = approach_key(approach)
            if key in tried:                               # oscillation: this exact run was already attempted
                trace.append({"event": "oscillation", "approach": idx})
                break
            tried.add(key)
            budget.charge_step()
            budget.charge_tokens(getattr(run_approach, "token_cost", 0))
            result = run_approach(approach)
            if not isinstance(result, RunResult):
                raise TypeError("run_approach must return a RunResult, got %r" % type(result))
            result.approach = approach
            trace.append({"event": "run", "approach": idx, "entry": " ".join(approach.entry),
                          "builder": approach.builder, "ran_ok": result.ran_ok, "captured": _captured(result)})
            if log:
                log("orchestrator: ran %s [%s] → ran_ok=%s captured=%s"
                    % (" ".join(approach.entry), approach.builder, result.ran_ok, _captured(result)))
            if success(result):
                if hints is not None and pending and pending[0] and pending[1]:
                    hints.record(pending[0], pending[1])   # this fix verifiably produced a good run
                    trace.append({"event": "hint-learned", "sig": pending[0]})
                result.trace = trace
                return result
            # Fallback to surface when NOTHING captures: prefer the highest-ranked attempt (the intended
            # entrypoint) so the user sees its real blocker — not a lower-ranked script that merely ran but
            # computed no verifiable number (e.g. a figures/plot script). A ran_ok result still upgrades a
            # purely-failed one at the SAME (first) slot; capture always wins via success() above.
            if best_effort is None:
                best_effort = result
            elif result.ran_ok and not best_effort.ran_ok and best_effort.approach is approach:
                best_effort = result                       # same approach, now running after a revise
            # ENVIRONMENTAL failure (missing data / needs-GPU): trying MORE entrypoints can't conjure a missing
            # file or a GPU — it only burns sandboxes (05 fail → 13_figures → notebook-timeout, ×2). Stop and
            # surface it so the caller acts (run the data-acquisition pipeline, or report missing-data honestly)
            # instead of grinding the whole ladder. A dep/argv/entrypoint failure still revises + tries the rest.
            from runner import build as _B
            _fk = _B.classify_failure(_stderr(result)).get("kind")
            # missing data: a DIFFERENT entrypoint can't conjure the file — but the data-resolution tool can
            # (relink a committed file to where the code reads it, or fetch a known dataset). Try it ONCE per
            # approach, then re-run the SAME approach now the input exists; only surface if it can't be fixed.
            if _fk == "missing-data" and resolve_data is not None and key not in resolved:
                resolved.add(key)
                try:
                    fixed = bool(resolve_data(_stderr(result)))
                except Exception:  # noqa: BLE001 — a resolver hiccup must not break the loop
                    fixed = False
                if fixed:
                    trace.append({"event": "data-resolved", "approach": idx})
                    if log:
                        log("orchestrator: resolved missing data — retrying the run")
                    tried.discard(key)                     # let the same approach run again now data exists
                    continue
            if _fk in ("missing-data", "needs-gpu"):
                trace.append({"event": "environmental-stop", "approach": idx})
                if log:
                    log("orchestrator: missing data/GPU — a different entrypoint can't fix that; surfacing it")
                result.trace = trace
                return result
            sig = sig_fn(_stderr(result)) if sig_fn else None
            revised = revise(result, approach, trace)
            if revised is None:
                break                                      # nothing more to try on this candidate → next
            if approach_key(revised) in tried:
                trace.append({"event": "no-progress", "approach": idx})
                break
            pending = (sig, _fix_delta(approach, revised))
            approach = revised

    return _finish(best_effort, approaches[0] if approaches else None, trace)


def _finish(best_effort, approach, trace) -> RunResult:
    if best_effort is not None:
        best_effort.trace = trace
        return best_effort
    return RunResult(ran_ok=False, runs=[], meta=[], cost={}, source_modified=[],
                     approach=approach, trace=trace)


# ── top-level entry (what the pipeline calls) ─────────────────────────────────────────────────────────────────
def budget_for_tier(tier) -> Budget:
    """Map a core.limits.Tier to a loop Budget (build plan §5: free = 1 approach, no revise; paid = full loop).
    ``tier.repair_steps`` gates the revise budget; 0 → a single approach, one shot."""
    steps = int(getattr(tier, "repair_steps", 0) or 0)
    if steps <= 0:
        return Budget(step_cap=1, max_approaches=1)
    return Budget(step_cap=max(2, steps + 2), max_approaches=MAX_APPROACHES)


def launch_command(approach: RunApproach, repo_dir: str) -> str:
    """A re-runnable one-liner reproducing the winning approach (build plan 'Transparent' + SOTA reproducible
    artifact, e.g. ExecutionAgent's launch.sh). Audit/repro aid only — never an input to a verdict."""
    if approach is None:
        return ""
    name = os.path.basename(repo_dir.rstrip("/")) or "repo"
    parts = ["cd %s" % name]
    if approach.deps:
        parts.append("pip install %s" % " ".join(approach.deps))
    env = " ".join("%s=%s" % (k, v) for k, v in (approach.env or {}).items())
    head = approach.entry[0] if approach.entry else ""
    if head.startswith("nb:"):
        run = "papermill %s out.ipynb" % head[3:]
    elif head.startswith("make:"):
        run = "make %s" % head[5:]
    else:
        run = "python %s" % " ".join(approach.entry)
    parts.append((env + " " if env else "") + run)
    return " && ".join(parts)


def _synthesize_predictions_run(repo_dir, run_approach, profile, model, log):
    """Last resort when NOTHING captured a number: ask the planner for a predict-and-dump driver that uses the
    repo's OWN model to write calma_predictions.csv, run it, and let the pipeline's artifact layer recompute the
    metric INDEPENDENTLY from those predictions. Returns the run result (with the driver recorded in
    source_modified → verdict capped at REPRODUCED-ONLY), or None if synthesis wasn't possible.

    FCR: a synthesized harness can NEVER reach CONFIRMED (the source_modified cap forces REPRODUCED-ONLY); the
    number itself is recomputed by core.artifacts, not by the driver — so a wrong/injected driver can only fail
    to match (nothing upgrades) or coincidentally match a continuous metric (still capped). Best-effort."""
    try:
        from planner import plan_predictions
    except Exception:  # noqa: BLE001
        return None
    plan = plan_predictions(repo_dir, model=model)
    if not plan or plan.get("confidence", 0) < 0.5 or not plan.get("driver"):
        return None
    driver_rel = "calma_eval.py"
    try:
        with open(os.path.join(repo_dir, driver_rel), "w") as fh:
            fh.write(plan["driver"])
    except OSError:
        return None
    if log:
        log("orchestrator: no runnable entrypoint captured a number — synthesized a predict-and-dump driver "
            "(%.0f%% conf); predictions recomputed INDEPENDENTLY, verdict capped at REPRODUCED-ONLY"
            % (100 * plan["confidence"]))
    deps = LIM.sanitize_pip(list(profile.declared_deps)
                            or S.entry_seeded_imports(repo_dir, [driver_rel]))
    appr = RunApproach(runner="local", builder=_builder_for(profile) if deps else "none",
                       entry=[driver_rel], deps=deps, capture_targets=[], env={},
                       notes="synthesized predict-and-dump driver (predictions recomputed independently)",
                       confidence=float(plan["confidence"]))
    result = run_approach(appr)
    result.approach = appr
    result.source_modified = list(result.source_modified or []) + [driver_rel]   # guarantee the REPRODUCED-ONLY cap
    return result


def orchestrate(repo_dir: str, run_approach, *, profile=None, use_llm: bool = True, model: str | None = None,
                plan: dict | None = None, revise=None, budget: Budget | None = None,
                cache=None, hints=None, log=None, synthesize: bool = False) -> RunResult:
    """assess → rank → execute. ``run_approach`` is the injected build+run effector (the pipeline supplies one
    wired to the real runners; tests supply a fake). ``plan`` reuses the pipeline's background-thread planner
    turn. ``cache``/``hints`` are the flywheel stores (fingerprint→approach, error→fix) — HOW-only, never a
    verdict channel. Returns a RunResult ready for the unchanged deterministic verify, with the Assessment
    Report + a re-runnable launch command on ``result.cost`` for the UI/audit."""
    profile = profile or assess(repo_dir)
    revise = revise if revise is not None else make_revise(hints)
    approaches = rank_approaches(profile, repo_dir, use_llm=use_llm, model=model, plan=plan, log=log)

    # flywheel: a known-good approach for this exact tree jumps to the front of the queue (LLM already skipped
    # for a cache hit since the profile is unchanged). Still flows through the full fail-closed verify.
    if cache is not None:
        hit = cache.get(profile.fingerprint)
        if hit is not None:
            approaches = [hit] + [a for a in approaches if approach_key(a) != approach_key(hit)]
            if log:
                log("orchestrator: flywheel cache hit — trying the known-good approach first")

    from . import registry as _REG
    # HOW-only data resolution: relink a committed file / fetch a known dataset so a missing-data run proceeds.
    # Verdict-free by construction (the registry forbids a verdict-touching tool), so it stays behind the firewall.
    def _resolve_data(err):
        return _REG.call("resolve_data_path", repo_dir, err)[0] if _REG.has("resolve_data_path") else False
    result = execute(approaches, run_approach, revise=revise, budget=budget, hints=hints, log=log,
                     resolve_data=_resolve_data)

    # last resort (opt-in): no declared/AI entrypoint captured a number → synthesize a predict-and-dump driver
    # and recompute the metric independently from the predictions it writes. Verdict-capped at REPRODUCED-ONLY.
    if synthesize and not _captured(result):
        syn = _synthesize_predictions_run(repo_dir, run_approach, profile, model, log)
        if syn is not None and (_captured(syn) or syn.ran_ok):
            result = syn

    if cache is not None and result.ran_ok and result.approach is not None:
        cache.put(profile.fingerprint, result.approach)   # remember the winner for the next repeat/sibling

    from .assess import report_lines
    result.cost = dict(result.cost or {})
    result.cost["assessment"] = report_lines(profile)
    result.cost["fingerprint"] = profile.fingerprint
    if result.approach is not None:
        result.cost["launch"] = launch_command(result.approach, repo_dir)
    return result
