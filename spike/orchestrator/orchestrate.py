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


# ── S6: delta-repair discipline — a revise is a CONSTRAINED, additive delta, never a verification-weakening
#        regeneration (build plan §4.2) — plus a registry-vocabulary LLM revise for env errors the heuristic misses.
def _pkg_set(deps) -> set:
    from runner import build as _B  # noqa: PLC0415
    return {b for b in (_B.pkg_base(d) for d in (deps or [])) if b}


def _targets_cover(new_t, old_t) -> bool:
    def _k(t):
        return (t.get("target"), t.get("metric")) if isinstance(t, dict) else (None, None)
    return {_k(t) for t in (old_t or [])} <= {_k(t) for t in (new_t or [])}


def _safe_delta(old: RunApproach, new: RunApproach) -> bool:
    """A revise must be a CONSTRAINED, ADDITIVE delta over the current approach — never a free regeneration that
    weakens the verification. Allowed: grow or relax deps, add/change env vars. Forbidden: switch the entrypoint
    (that is the ranker's job, not a revise), shrink the capture targets, remove an env var, or drop an already
    installed package. A weaker capture can't manufacture a CONFIRM, but it turns the loop's discipline into a
    hollow pass — so every revise stays strictly additive."""
    if list(new.entry) != list(old.entry):
        return False
    if not _targets_cover(new.capture_targets, old.capture_targets):
        return False
    if not set(old.env or {}) <= set(new.env or {}):                 # env keys never removed (values may change)
        return False
    return _pkg_set(old.deps) <= _pkg_set(new.deps)                  # the installed package SET never shrinks


def _llm_revise(result: RunResult, approach: RunApproach, model) -> RunApproach | None:
    """Last-resort revise (S6): an LLM proposes a CONSTRAINED env fix (add-dep / set-env) for a failure the
    key-free heuristic couldn't map — a system lib (libGL → opencv-python-headless), a headless backend, a PyPI
    name that differs from the import. Sanitized in the planner + safety-gated by _safe_delta in make_revise;
    HOW-only, so a wrong fix only leaves the run failing, never a verdict."""
    import planner  # noqa: PLC0415 — lazy: the LLM layer isn't needed on the key-free / hermetic path
    fix = planner.propose_revise(_stderr(result), approach.deps, model)
    if not fix:
        return None
    new = approach
    if fix.get("add_dep"):
        new = _with_dep(new, str(fix["add_dep"]), "llm-revise: +dep %s" % fix["add_dep"]) or new
    if fix.get("set_env"):
        new = _with_env(new, fix["set_env"], "llm-revise: env %s" % list(fix["set_env"])) or new
    return new if approach_key(new) != approach_key(approach) else None


def _symptom(stderr: str) -> str:
    """The salient exception line of a failure — the retrievable text half of an XPU (dual modality). Concise
    + descriptive so a paraphrase of the same error vector-matches a past fix even when the exact signature
    differs (a novel repo whose symptom, not signature, is the same)."""
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip()]
    for ln in reversed(lines):                                 # the exception line is usually last + most specific
        if any(k in ln for k in ("Error", "error", "Exception", "Failed", "No such", "Errno", "not found")):
            return ln[:200]
    return (lines[-1][:200] if lines else "")


def make_revise(hints=None, xpu=None, model=None):
    """A revise closure that consults the experience stores BEFORE the key-free heuristic (the self-healing
    "error-signature → cached fix, no LLM" property). Order: the XPU store (telemetry-gated exact-OR-vector
    match), then the exact-signature HintStore (legacy/compat), then the heuristic, then a constrained LLM
    revise (S6, only when a ``model`` is supplied) for an env error none of the above mapped. Every candidate
    must pass ``_safe_delta`` — the S6 delta-repair discipline: a revise is a constrained ADDITIVE delta over the
    current approach, never a free regeneration that weakens the verification. HOW-only; never touches a verdict."""
    def revise(result: RunResult, approach: RunApproach, history: list):
        stderr = _stderr(result)
        sig = None
        if hints is not None or xpu is not None:
            from .cache import error_signature
            sig = error_signature(stderr)
        candidate = None
        if xpu is not None and (sig or stderr):
            hit = xpu.retrieve(sig, _symptom(stderr))          # (unit, score) or None; demoted units filtered
            if hit is not None:
                candidate = _apply_hint(approach, hit[0].action)
        if candidate is None and hints is not None and sig:
            act = hints.get(sig)
            if act:
                candidate = _apply_hint(approach, act)
        if candidate is None:
            candidate = heuristic_revise(result, approach, history)
        if candidate is None and model is not None:
            candidate = _llm_revise(result, approach, model)
        # S6 delta-repair discipline: reject a revise that isn't a constrained additive delta (switches the
        # entry, shrinks capture targets, removes env, or drops a package) — it could only weaken the run.
        if candidate is not None and not _safe_delta(approach, candidate):
            return None
        return candidate
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
            success=None, budget: Budget | None = None, hints=None, log=None, resolve_data=None,
            repo_dir: str | None = None, xpu=None) -> RunResult:
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
    if hints is not None or xpu is not None:
        from .cache import error_signature as sig_fn

    for idx, approach in enumerate(approaches[:budget.max_approaches]):
        pending: tuple | None = None                       # (sig, action, symptom) applied last, awaiting verify
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
            try:
                result = run_approach(approach)
            except Exception as e:  # noqa: BLE001 — an effector crash (sandbox boot / network / timeout / a
                # malformed repo) is a FAILED approach, never a dead orchestration. Synthesize a failed result
                # so the loop revises or advances to the next candidate — the single biggest "it just stopped
                # working" cause. FCR-safe: a failed result only ever yields DISCOVERED, never a false CONFIRM.
                result = RunResult(ran_ok=False, meta=[{"stderr_tail": ("effector error: %s" % e)[:800]}],
                                   approach=approach)
                if log:
                    log("orchestrator: approach errored (%s) — treating as failed, continuing" % str(e)[:140])
            if not isinstance(result, RunResult):
                raise TypeError("run_approach must return a RunResult, got %r" % type(result))
            result.approach = approach
            trace.append({"event": "run", "approach": idx, "entry": " ".join(approach.entry),
                          "builder": approach.builder, "ran_ok": result.ran_ok, "captured": _captured(result)})
            if log:
                log("orchestrator: ran %s [%s] → ran_ok=%s captured=%s"
                    % (" ".join(approach.entry), approach.builder, result.ran_ok, _captured(result)))
            if success(result):
                if pending and pending[0] and pending[1]:      # this fix VERIFIABLY produced a good run
                    if hints is not None:
                        hints.record(pending[0], pending[1])
                    if xpu is not None:                        # dual-modality: bank the symptom text too
                        xpu.record(pending[0], pending[1], symptom=(pending[2] if len(pending) > 2 else None))
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
            # PROSECUTOR–JUDGE observe (S2): label the failure setup-induced vs repo-bug and pick the next move
            # over the S1 remediation registry — beyond the raw exit code. `remediate` applies a licensed HOW-only
            # fix (missing data: relink a committed file / fetch a known dataset — a DIFFERENT entrypoint can't
            # conjure the file); `stop` surfaces an environmental wall (genuine missing input / needs-GPU) honestly;
            # `revise` iterates the approach. repo_dir unlocks the evidence gate (None on the hermetic fake path →
            # signature-only classification = the pre-S2 control flow). This never touches the FCR verdict Judge.
            from . import observe as _OBS
            obs = _OBS.observe(result, repo_dir, can_remediate=(resolve_data is not None),
                               already_resolved=(key in resolved))
            if obs.next_move == "remediate":
                resolved.add(key)                          # try the fix ONCE per approach
                try:
                    fixed = bool(resolve_data(_stderr(result)))
                except Exception:  # noqa: BLE001 — a resolver hiccup must not break the loop
                    fixed = False
                if fixed:
                    trace.append({"event": "data-resolved", "approach": idx, "evidence": obs.detail})
                    if log:
                        log("orchestrator: resolved missing data (%s) — retrying the run" % obs.detail)
                    tried.discard(key)                     # let the same approach run again now the input exists
                    continue
                obs = _OBS.observe(result, repo_dir, can_remediate=False, already_resolved=True)   # exhausted
            if obs.next_move == "stop":
                trace.append({"event": "environmental-stop", "approach": idx,
                              "label": obs.label, "detail": obs.detail})
                if log:
                    log("orchestrator: %s — %s; a different entrypoint can't fix that, surfacing it"
                        % (obs.label, obs.detail))
                result.trace = trace
                return result
            sig = sig_fn(_stderr(result)) if sig_fn else None
            revised = revise(result, approach, trace)
            if revised is None:
                break                                      # nothing more to try on this candidate → next
            if approach_key(revised) in tried:
                trace.append({"event": "no-progress", "approach": idx})
                break
            pending = (sig, _fix_delta(approach, revised), _symptom(_stderr(result)))   # + symptom for the XPU
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


# Reserved Calma filenames the synthesis path writes into a repo. They are Calma's own artifacts, never the
# repo's — so a pre-existing one can only be a leftover from an earlier synthesis run on a REUSED checkout. Left
# in place, a stale calma_predictions.csv would be read as a "committed" artifact on a later run where synthesis
# does NOT fire (so its calma_eval.py is unchanged → not in the snapshot diff → no cap) → an uncapped CONFIRMED
# on stale AI predictions. We purge them before every orchestrate run so they can only ever be this-run's output.
_RESERVED_ARTIFACTS = ("calma_eval.py", "calma_predictions.csv")


def _purge_reserved(repo_dir: str) -> None:
    for fn in _RESERVED_ARTIFACTS:
        try:
            os.remove(os.path.join(repo_dir, fn))
        except OSError:
            pass


def _has_committed_predictions(repo_dir: str) -> bool:
    """True if the repo already commits a real predictions file (excluding Calma's reserved name). Such a repo
    should be verified against its OWN artifact — synthesizing a driver would both waste a sandbox run and cap
    the legitimately-committed CONFIRMED down to REPRODUCED-ONLY (source_modified caps ALL affirmatives)."""
    try:
        from core import artifacts as _A
    except Exception:  # noqa: BLE001
        return False
    for p, _cols in (_A.find_prediction_files(repo_dir) or []):
        if os.path.basename(p) not in _RESERVED_ARTIFACTS:
            return True
    return False


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
        if log:
            conf = (plan or {}).get("confidence", 0)
            log("orchestrator: synthesis declined — the planner could not produce a confident predict-and-dump "
                "driver (%.0f%% conf, need ≥50%%)" % (100 * conf))
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
                cache=None, hints=None, log=None, synthesize: bool = False, xpu=None) -> RunResult:
    """assess → rank → execute. ``run_approach`` is the injected build+run effector (the pipeline supplies one
    wired to the real runners; tests supply a fake). ``plan`` reuses the pipeline's background-thread planner
    turn. ``cache``/``hints``/``xpu`` are the flywheel/experience stores (fingerprint→approach, error→fix,
    dual-modality XPU) — HOW-only, never a verdict channel. Returns a RunResult ready for the unchanged
    deterministic verify, with the Assessment Report + a re-runnable launch command on ``result.cost``."""
    profile = profile or assess(repo_dir)
    revise = revise if revise is not None else make_revise(hints, xpu, model)
    _purge_reserved(repo_dir)   # drop any stale calma_eval.py/calma_predictions.csv from a prior run on a reused checkout
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
    # We DO collect the tool's `modified` list (edited files + any data-substitution marker) and fold it into
    # source_modified below — a substituted/rewritten input must cap AFFIRMATIVE→REPRODUCED-ONLY (FCR), and the
    # pipeline's .py snapshot rail can't see a data swap or a notebook edit that this list records.
    _data_modified: list[str] = []
    def _resolve_data(err):
        if not _REG.has("resolve_data_path"):
            return False
        placed, _note, modified = _REG.call("resolve_data_path", repo_dir, err)
        if placed and modified:
            _data_modified.extend(m for m in modified if m not in _data_modified)
        return placed
    result = execute(approaches, run_approach, revise=revise, budget=budget, hints=hints, log=log,
                     resolve_data=_resolve_data, repo_dir=repo_dir, xpu=xpu)

    # last resort (opt-in): no declared/AI entrypoint captured a number → synthesize a predict-and-dump driver
    # and recompute the metric independently from the predictions it writes. Verdict-capped at REPRODUCED-ONLY.
    if synthesize and not _captured(result):
        _stop = budget.stop_reason() if budget is not None else None
        if _stop:                                              # don't start a doomed run at the budget/EOL wall
            if log:
                log("orchestrator: synthesis skipped — %s (no budget for another run)" % _stop)
        elif _has_committed_predictions(repo_dir):             # verify the real artifact, don't cap it with a synth
            if log:
                log("orchestrator: synthesis skipped — the repo already commits a predictions file (verified "
                    "directly, no synthesized driver)")
        else:
            syn = _synthesize_predictions_run(repo_dir, run_approach, profile, model, log)
            if syn is not None and (_captured(syn) or syn.ran_ok):
                result = syn

    # fold any data substitution/rewrite the resolver performed into the FINAL result (after a possible synthesis
    # swap) so the REPRODUCED-ONLY cap always fires — a swapped/fetched input verified on the wrong data is capped.
    if _data_modified:
        result.source_modified = list(result.source_modified or []) + [m for m in _data_modified
                                                                       if m not in (result.source_modified or [])]

    if cache is not None and result.ran_ok and result.approach is not None:
        cache.put(profile.fingerprint, result.approach)   # remember the winner for the next repeat/sibling

    from .assess import report_lines
    result.cost = dict(result.cost or {})
    result.cost["assessment"] = report_lines(profile)
    result.cost["fingerprint"] = profile.fingerprint
    if result.approach is not None:
        result.cost["launch"] = launch_command(result.approach, repo_dir)
    return result
