"""calma.autonomy - operating modes + the action gate for autonomous use.

THE INVARIANT (never broken): autonomy governs ACTIONS taken AROUND a verification - escalation,
sealing, publishing, retrying - and NEVER the verdict. The verdict, every statistic, the confidence
and the gate are always produced by the deterministic core regardless of mode. A mode can change
what Calma DOES, never what it DECIDES. (If a mode could change the verdict, Calma would just be the
LLM-judge it is built to beat.)

Calma's autonomy has TWO independent axes, so the operator controls BOTH "what gets checked" and
"what happens after a check" - neither can change the VERDICT itself:

  1. VERIFY SCOPE  (the zero-touch Stop hook: how aggressively it auto-verifies an agent's numbers)
       off       never auto-verify (the hook stays silent; explicit kill switch).
       headline  (default) verify the ONE headline numeric claim in the agent's turn.
       all       verify EVERY checkable numeric claim in the turn (up to a safety cap).
     A break (REFUTED / MIXED / INVALIDATED) at any scope still blocks the stop, so a wrong number is
     never reported. (For exhaustive "every number in a notebook/report" coverage, use the A1 pipeline
     `python -m edges.extract`.)

  2. ACTION MODE  (what Calma DOES around a verification - escalation, sealing, publishing, retrying)
       ask       (default) compute + report only; run no follow-on action.
       suggest   compute + report, then PRINT the exact next command(s); run nothing.
       auto      compute + report, then RUN safe follow-ons (seal/timestamp, restore-retry).
                 OUTWARD actions (publish to the registry, send a bundle) stay OFF even in auto unless
                 explicitly allowlisted - hard to undo, so they always need a human's standing opt-in.

THE INVARIANT (never broken): a scope/mode changes what Calma DOES, NEVER what it DECIDES. The verdict,
every statistic, the confidence and the gate are always produced by the deterministic core. (If a mode
could change the verdict, Calma would just be the LLM-judge it is built to beat.)

Resolution precedence:
  scope:  cli_scope arg  >  env CALMA_VERIFY  >  .calma/config.json {"verify": ...}  >  headline.
          (the hook is invoked with no args, so in practice env CALMA_VERIFY / config drive the scope.)
  mode:   --mode flag    >  env CALMA_MODE     >  .calma/config.json {"mode": ...}    >  ask.
Outward opt-in (auto only): .calma/config.json {"autonomy": {"auto_publish": true}} or
                            {"autonomy": {"allowlist": ["publish", ...]}}.

Every autonomy decision is breadcrumbed to .calma/auto_history.jsonl (the same trail the Stop hook
uses) so a human can audit exactly what an autonomous Calma did.
"""
import json
import os
import time

MODES = ("ask", "suggest", "auto")
VERIFY_SCOPES = ("off", "headline", "all")
# the hook's per-turn verification budget for scope='all' - bounded so the hook stays imperceptible
# (each verification is a sandbox re-exec). Exhaustive coverage is the A1 pipeline's job, not the hook's.
SCOPE_ALL_CAP = 5


def _config(base):
    for p in (os.path.join(base or ".", ".calma", "config.json"),
              os.path.expanduser("~/.calma/config.json")):
        try:
            d = json.load(open(p))
            if isinstance(d, dict):
                return d
        except (OSError, ValueError):
            continue
    return {}


def resolve_mode(cli_mode=None, base="."):
    """The active mode. Precedence: cli > env CALMA_MODE > .calma/config.json > 'ask'. Any
    unrecognized value is ignored (falls through), so a typo degrades to the safe default."""
    for cand in (cli_mode, os.environ.get("CALMA_MODE"), _config(base).get("mode")):
        if cand:
            c = str(cand).strip().lower()
            if c in MODES:
                return c
    return "ask"


def resolve_verify_scope(cli_scope=None, base=".", config=None):
    """The active VERIFY SCOPE for the zero-touch hook. Precedence: cli > env CALMA_VERIFY >
    .calma/config.json {"verify"} > 'headline'. An unrecognized value degrades to the safe default.
    Back-compat: CALMA_HOOK=0/off/false (the legacy kill switch) maps to 'off'."""
    if str(os.environ.get("CALMA_HOOK", "")).strip().lower() in ("0", "off", "false", "no"):
        return "off"
    cfg = config if config is not None else _config(base)
    for cand in (cli_scope, os.environ.get("CALMA_VERIFY"), cfg.get("verify")):
        if cand:
            c = str(cand).strip().lower()
            if c in VERIFY_SCOPES:
                return c
    return "headline"


def max_claims_for(scope, cfg_cap=None):
    """How many of a turn's checkable claims the hook verifies for the given scope. 'off' -> 0 (skip),
    'headline' -> 1, 'all' -> SCOPE_ALL_CAP. A project may only LOWER this via the hook's max_claims cap,
    never raise it (a project can DISABLE/LIMIT the hook, never escalate it)."""
    base = {"off": 0, "headline": 1, "all": SCOPE_ALL_CAP}.get(scope, 1)
    if cfg_cap is not None:
        try:
            base = min(base, max(0, int(cfg_cap)))
        except (TypeError, ValueError):
            pass
    return base


def gate(mode, action, outward=False, base=".", config=None):
    """Decide a NON-verdict action: returns 'execute' | 'suggest' | 'skip'.

    The verdict is NEVER routed through here - it always runs. Outward actions require an explicit
    standing opt-in even in auto (else they downgrade to 'suggest', never silently fire)."""
    if mode not in MODES:
        mode = "ask"
    if mode == "ask":
        return "skip"
    if mode == "suggest":
        return "suggest"
    # auto
    if not outward:
        return "execute"
    cfg = config if config is not None else _config(base)
    au = cfg.get("autonomy") if isinstance(cfg.get("autonomy"), dict) else {}
    allowed = au.get("auto_publish") is True or action in (au.get("allowlist") or [])
    return "execute" if allowed else "suggest"


def log(base, mode, action, decision, detail=""):
    """Append an autonomy decision to .calma/auto_history.jsonl. Fail-open (never raises)."""
    try:
        d = os.path.join(base or ".", ".calma")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "auto_history.jsonl"), "a") as f:
            f.write(json.dumps({"ts": time.time(), "src": "autonomy", "mode": mode,
                                "action": action, "decision": decision, "detail": detail}) + "\n")
    except OSError:
        pass
