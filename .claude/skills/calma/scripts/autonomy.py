"""calma.autonomy - operating modes + the action gate for autonomous use.

THE INVARIANT (never broken): autonomy governs ACTIONS taken AROUND a verification - escalation,
sealing, publishing, retrying - and NEVER the verdict. The verdict, every statistic, the confidence
and the gate are always produced by the deterministic core regardless of mode. A mode can change
what Calma DOES, never what it DECIDES. (If a mode could change the verdict, Calma would just be the
LLM-judge it is built to beat.)

Modes (least -> most autonomous):
  ask     (default) compute + report only; run no follow-on action.
  suggest compute + report, then PRINT the exact next command(s); run nothing.
  auto    compute + report, then RUN safe follow-ons (seal/timestamp, restore-retry).
          OUTWARD actions (publish to the public registry, send a bundle) stay OFF even in auto
          unless explicitly allowlisted - they are hard to undo, so they always need a human's
          standing opt-in via config.

Resolution precedence: --mode flag  >  env CALMA_MODE  >  .calma/config.json {"mode": ...}  >  ask.
Outward opt-in (auto only): .calma/config.json {"autonomy": {"auto_publish": true}} or
                            {"autonomy": {"allowlist": ["publish", ...]}}.

Every autonomy decision is breadcrumbed to .calma/auto_history.jsonl (the same trail the Stop hook
uses) so a human can audit exactly what an autonomous Calma did.
"""
import json
import os
import time

MODES = ("ask", "suggest", "auto")


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
