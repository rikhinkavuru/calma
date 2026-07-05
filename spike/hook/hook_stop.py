#!/usr/bin/env python
"""hook_stop — the stop-hook guardrail, rebuilt on the spike engine.

When an agent finishes, this reads the final assistant message, extracts any reported metric numbers, and
runs the FAST no-reproduction validity scan against the working repo — surfacing leakage / trivial-baseline /
misreport before a wrong number ships. It is the correct-by-construction replacement for the old packaged
hook, whose intake false-REFUTED a bare "0.89": here the verdict comes from the spike engine
(validity_scan → pipeline), which is fail-closed — a number with nothing in the repo to check against is
INCOMPLETE, never REFUTED. Best-effort throughout: any failure exits 0 and never blocks the agent.

Wire as a Stop hook: it reads the hook payload as JSON on stdin ({cwd, last_assistant_message | transcript_path})
and prints a short report card to stderr (surfaced to the user), exit 0 always.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)
sys.path.insert(0, os.path.join(SPIKE, "capture"))


def _claims_from_message(message: str) -> list[dict]:
    """Metric+value claims mentioned in the message (reuses the engine's own discovery parser — the same
    precision gate that only turns a real catalog-metric span into a claim, so a bare year/count isn't one)."""
    from discovery import extract as DISC
    claims = DISC.from_text(message or "", location="assistant-message")
    for i, c in enumerate(claims):
        c["id"] = "msg_%d" % i
    return claims


def evaluate(message: str, cwd: str) -> dict | None:
    """The testable core: scrape claims from the message and run the no-reproduction validity scan against
    the repo at `cwd`. Returns the report card, or None when there is nothing to act on (no claim / no repo).
    Fail-closed by construction — the scan never REFUTES a number the repo did not produce."""
    if not cwd or not os.path.isdir(cwd):
        return None
    claims = _claims_from_message(message)
    if not claims:
        return None
    import validity_scan as VS
    return VS.scan(cwd, claims=claims)


def _read_payload() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return {}


def _final_assistant_text(payload: dict) -> str:
    msg = payload.get("last_assistant_message")
    if msg:
        return msg if isinstance(msg, str) else json.dumps(msg)
    path = payload.get("transcript_path")
    if path and os.path.isfile(path):
        try:
            last = ""
            with open(path, errors="replace") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("role") == "assistant" or rec.get("type") == "assistant":
                        last = rec.get("content") or rec.get("text") or last
                        if isinstance(last, list):
                            last = " ".join(p.get("text", "") for p in last if isinstance(p, dict))
            return last or ""
        except OSError:
            return ""
    return ""


def main() -> int:
    try:
        payload = _read_payload()
        card = evaluate(_final_assistant_text(payload), payload.get("cwd") or os.getcwd())
        if card:
            sys.stderr.write(_render(card) + "\n")
    except Exception:  # noqa: BLE001 — a guardrail must NEVER break the agent; any failure is silent
        pass
    return 0


def _render(card: dict) -> str:
    icon = {"PASS": "✅", "FAIL": "❌", "INCOMPLETE": "◻️"}.get(str(card.get("grade") or ""), "?")
    lines = ["[calma] validity: %s %s" % (icon, card.get("grade"))]
    for c in card.get("checks", []):
        if c.get("status") == "fail":
            for f in c.get("findings", []):
                lines.append("  ✗ %s: %s" % (c["name"], f))
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
