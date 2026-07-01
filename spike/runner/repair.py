"""calma.spike.runner.repair — the get-it-running repair loop (feature 1).

A bounded ReAct loop that, when a repo fails to run, proposes the next ENVIRONMENT action (install a dep, set
an env var, change an argv, fetch missing data), applies it, and re-runs — until the entrypoint produces its
numbers or the loop gives up. It emits a replayable `manifest` of the winning actions.

The FCR argument is the planner's, made structural by the ACTION SPACE: the loop can only ever change *how the
repo's own code runs*, never *what it computes*. There is NO source-edit action — the enum is
{PIP, APT, SETENV, ENTRYPOINT_ARG, FETCH_DATA, GIVE_UP}. A bad action → a still-failed run → DISCOVERED, never
a false CONFIRM; the number is still decided by the unchanged three-way diff + determinism gate. As a
belt-and-suspenders second rail, `snapshot_fn` fingerprints the repo's `.py` before/after: if a compute-path
source file changed anyway (an apt/pip post-install, a fetched .py), `manifest['source_modified']` is set and
the caller caps the verdict at REPRODUCED-ONLY. Pure orchestration; the model proposer + effectors are
injected, so this is fully testable without a sandbox or a key.
"""
from __future__ import annotations

import hashlib
import os
import re

GIVE_UP = "GIVE_UP"

# A plain PyPI requirement spec: name (+ optional extras) (+ optional version pins). NO flags (`--index-url`),
# NO URLs/VCS (`git+https://`), NO local paths (`.`, `/`) — those are pip arg-injection / supply-chain vectors
# a prompt-injected proposer could smuggle in. A missing-module heal only ever needs a bare package name.
_PIP_SPEC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9,._-]+\])?(?:[<>=!~]=?[0-9A-Za-z.*+!-]+)*$")


def is_safe_pip(arg) -> bool:
    """True iff `arg` is a plain, single PyPI requirement spec safe to hand to `pip install`. Rejects flags,
    URLs/VCS refs, local paths, and anything with whitespace or shell/pip metacharacters."""
    return isinstance(arg, str) and 0 < len(arg) <= 128 and bool(_PIP_SPEC.match(arg))
# the ENV-ONLY action space — there is deliberately no SOURCE_EDIT: the agent gets the repo running, the
# deterministic core decides if the number is right.
ACTIONS = {"PIP", "APT", "SETENV", "ENTRYPOINT_ARG", "FETCH_DATA", GIVE_UP}


def snapshot_pyfiles(repo_dir: str) -> dict:
    """Fingerprint every compute-path `.py` (sha1 of contents) so a post-repair source change is detectable.
    Skips venvs / caches / results."""
    skip = {".git", ".venvs", "venv", ".venv", "__pycache__", "results", "node_modules", ".calma"}
    out: dict[str, str] = {}
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in skip]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(root, fn)
            try:
                with open(p, "rb") as fh:
                    out[os.path.relpath(p, repo_dir)] = hashlib.sha1(fh.read()).hexdigest()
            except OSError:
                continue
    return out


def _changed(before: dict, after: dict) -> list[str]:
    return sorted({p for p in set(before) | set(after) if before.get(p) != after.get(p)})


def heuristic_propose(missing_module_fn):
    """A deterministic, key-free proposer: on a missing-module failure, propose installing that module (once).
    Mirrors the pipeline's existing 2-shot dep heal, generalized into the loop. Returns a propose(result,
    history) -> action closure."""
    def propose(result, history):
        mod = missing_module_fn(result)
        tried = {s.get("arg") for s in history if s.get("type") == "PIP"}
        if mod and mod not in tried:
            return {"type": "PIP", "arg": mod}
        return {"type": GIVE_UP}
    return propose


_SYSTEM = (
    "You are the environment-repair step of a verification system. A repository failed to run. Propose the "
    "SINGLE next action that will make it run, changing ONLY the environment — NEVER the repo's source code or "
    "the metric it computes. Pick one action: PIP (install a PyPI package; arg = package name), SETENV "
    "(arg = 'NAME=value'), ENTRYPOINT_ARG (arg = extra argv string), FETCH_DATA (arg = null), or GIVE_UP if no "
    "environment change can help. Do not propose editing files."
)
_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["PIP", "SETENV", "ENTRYPOINT_ARG", "FETCH_DATA", "GIVE_UP"]},
        "arg": {"type": ["string", "null"]},
        "reason": {"type": "string"},
    },
    "required": ["type"],
}


def _err(result) -> str:
    return " ".join((m.get("stderr_tail") or "")[-400:] for m in (result or {}).get("meta") or [])[-1500:]


def _llm_action(result, history, model):
    """One gated, best-effort model call returning an env-only action dict, or None on any failure."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except Exception:  # noqa: BLE001
        return None
    try:
        import json
        client = anthropic.Anthropic()
        ctx = "FAILURE:\n%s\n\nACTIONS ALREADY TRIED:\n%s" % (
            _err(result), [(s.get("type"), s.get("arg")) for s in history])
        resp = client.messages.create(
            model=model or os.environ.get("CALMA_REPAIR_MODEL", "claude-sonnet-5"), max_tokens=1024,
            system=_SYSTEM, output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{"role": "user", "content": ctx}])
        if resp.stop_reason == "max_tokens":
            return None
        raw = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001 — auth/rate/network/parse → fall back to the heuristic
        return None


def llm_propose(missing_module_fn, model=None):
    """A best-effort LLM proposer that falls back to the heuristic. Any out-of-enum suggestion or failure → the
    deterministic heuristic. The action space is still ENV-ONLY (the schema has no source-edit option), so the
    FCR argument is unchanged whether the step came from the model or the heuristic."""
    heur = heuristic_propose(missing_module_fn)

    def propose(result, history):
        action = _llm_action(result, history, model)
        if action and action.get("type") in ACTIONS:
            return action
        return heur(result, history)
    return propose


def repair_loop(run_fn, propose_fn, apply_fn, *, max_steps: int = 4, snapshot_fn=None, log=None):
    """Drive the env-only repair loop. Returns (final_result, manifest).

    run_fn(action|None) -> run_result (dict with 'ran_ok').  propose_fn(result, history) -> action dict
    {'type': <ACTIONS>, 'arg': ...}.  apply_fn(action) -> truthy if the env action was applied.
    snapshot_fn() -> a repo fingerprint (for the source-modified rail).
    """
    manifest: dict = {"steps": [], "succeeded": False, "gave_up": False, "source_modified": [], "steps_taken": 0}
    before = snapshot_fn() if snapshot_fn else None
    result = run_fn(None)
    steps = 0
    while not (result or {}).get("ran_ok") and steps < max(0, max_steps):
        action = propose_fn(result, manifest["steps"]) or {"type": GIVE_UP}
        atype = action.get("type")
        if atype not in ACTIONS or atype == GIVE_UP:
            manifest["gave_up"] = True
            break
        try:
            applied = bool(apply_fn(action))
        except Exception:  # noqa: BLE001 — an effector error is just a failed step, never a crash
            applied = False
        manifest["steps"].append({"type": atype, "arg": action.get("arg"), "applied": applied})
        if log:
            log("repair step %d: %s %s → %s" % (steps + 1, atype, action.get("arg"), "applied" if applied else "no-op"))
        if not applied:
            manifest["gave_up"] = True
            break
        result = run_fn(action)
        steps += 1
    if snapshot_fn and before is not None:
        manifest["source_modified"] = _changed(before, snapshot_fn())
    manifest["succeeded"] = bool((result or {}).get("ran_ok"))
    manifest["steps_taken"] = steps
    return result, manifest
