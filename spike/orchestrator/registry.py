"""calma.spike.orchestrator.registry — the tool registry + the agent≠executor gateway (build plan §2, §4).

Every orchestrator capability is a small, typed, individually-FCR-safe tool registered here. The agent never
calls a function directly and never emits free-form shell: it proposes a tool NAME from a fixed enum and the
``call`` gateway dispatches it. This is the SOTA "deterministic tool routing beats LLM-generated tool names"
result (a 200-task benchmark found 90.8% of ReAct retries targeted hallucinated tool names) made structural.

The one non-negotiable invariant (build plan §0): **no registered tool may touch a verdict.** It is enforced
at registration, not by convention — ``register`` hard-rejects ``touches_verdict=True`` and rejects any tool
whose name collides with the verdict/binding vocabulary. The CI firewall test re-checks the live registry.
Keep this module free of ``core.verdict`` / ``core.diff`` imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

KINDS = ("static", "exec")
COSTS = ("free", "cheap", "moderate", "heavy")

# Substrings that name the deterministic verify surface. A tool must never be named for these — it is the
# clearest, cheapest structural signal that the registry stayed on the make-runnable side of the firewall.
_VERDICT_VOCAB = ("verdict", "decide", "confirm", "refute", "invalidat", "binding",
                  "recompute", "diff_claim", "three_way", "threeway")


@dataclass(frozen=True)
class Tool:
    """A registered capability. ``kind`` = static (pure/cheap, no sandbox) | exec (runs code under supervisor
    caps). ``touches_verdict`` is frozen ``False`` — the type exists so the firewall can assert it, and
    ``register`` refuses any other value."""
    name: str
    fn: Callable
    kind: str
    cost: str
    summary: str
    touches_verdict: bool = False


_REGISTRY: dict[str, Tool] = {}


def register(name: str, *, kind: str, cost: str, summary: str,
             touches_verdict: bool = False) -> Callable[[Callable], Callable]:
    """Decorator: register ``fn`` as an orchestrator tool. Raises at import time on any violation, so a
    misconfigured tool can never reach runtime."""
    if kind not in KINDS:
        raise ValueError("tool %r: kind %r not in %r" % (name, kind, KINDS))
    if cost not in COSTS:
        raise ValueError("tool %r: cost %r not in %r" % (name, cost, COSTS))
    if touches_verdict:
        raise ValueError("tool %r declares touches_verdict=True — forbidden by the FCR firewall (§0). The "
                         "orchestrator may only change HOW a repo runs, never a verdict." % name)
    low = name.lower()
    for bad in _VERDICT_VOCAB:
        if bad in low:
            raise ValueError("tool name %r collides with the verdict vocabulary (%r) — rename; the "
                             "orchestrator never owns the diff/verdict." % (name, bad))
    if name in _REGISTRY:
        raise ValueError("tool %r already registered" % name)

    def _wrap(fn: Callable) -> Callable:
        _REGISTRY[name] = Tool(name=name, fn=fn, kind=kind, cost=cost, summary=summary,
                               touches_verdict=False)
        return fn
    return _wrap


def get(name: str) -> Tool:
    if name not in _REGISTRY:
        raise KeyError("unknown tool %r (registry has %d tools)" % (name, len(_REGISTRY)))
    return _REGISTRY[name]


def has(name: str) -> bool:
    return name in _REGISTRY


def tool_names() -> list[str]:
    return sorted(_REGISTRY)


def tools() -> list[Tool]:
    return [_REGISTRY[n] for n in sorted(_REGISTRY)]


def tools_by_kind(kind: str) -> list[Tool]:
    return [t for t in tools() if t.kind == kind]


def call(name: str, *args, **kwargs):
    """The agent≠executor boundary: dispatch a tool by NAME. The agent proposes the name (from a fixed enum);
    only this gateway actually invokes it. Raises KeyError on an unknown/hallucinated name — never executes
    an arbitrary string. (Loop-level budgets, allowlist, and no-progress detection wrap this in orchestrate.)"""
    return get(name).fn(*args, **kwargs)
