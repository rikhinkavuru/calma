"""Calma MCP server -- the deterministic verifier under every agent host.

AI proposes (the calling agent's number), determinism disposes (Calma's verdict). This server is a
TRANSPORT ONLY: every tool shells out to the shipped CLI

    python3 .claude/skills/calma/scripts/calma.py verify <target> --json      (calma_verify)
    python  -m edges.extract <target> --json                                   (calma_verify_artifact)
    python3 .claude/skills/calma/scripts/calma.py suggest <text> --json        (calma_suggest)

and returns the engine's JSON verbatim. It NEVER imports the verdict core
(verdict / ledger / compare / recompute / numeric) and never re-implements a verdict -- enforced by
mcp/tests/test_firewall.py. The server adds no interpretation: the verdict is always the subprocess's.

Safety guardrails (determinism + path safety):
  * Pass-through: --trust / --isolation / --timeout reach the engine unchanged; the server cannot
    downgrade isolation or weaken a verdict.
  * Workspace jail: a target path that escapes the workspace (CALMA_MCP_WORKSPACE, default: cwd) is
    rejected before any subprocess runs.
  * Timeout: every subprocess is bounded; the engine timeout is passed through and the transport adds
    a small grace margin on top.

Transports: stdio (primary) and optional streamable-HTTP (`--http`, needs the [http] extra).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import mcp.types as types
from mcp.server import Server

SERVER_NAME = "calma-mcp"

# repo-relative defaults; overridable for an installed deployment (see README).
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT_DEFAULT = os.path.abspath(os.path.join(_PKG_DIR, "..", ".."))
_CALMA_DEFAULT = os.path.join(_REPO_ROOT_DEFAULT, ".claude", "skills", "calma", "scripts", "calma.py")

# the engine's verdict enum (for documentation / schemas only -- never computed here)
_VERDICTS = ["CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "INVALIDATED", "FLAG_FOR_DECLARATION",
             "INCONCLUSIVE", "MIXED"]


# --- configuration (env-overridable; resolved per call so tests can set it) --------------------
def _calma_script() -> str:
    return os.environ.get("CALMA_SCRIPT", _CALMA_DEFAULT)


def _repo_root() -> str:
    return os.environ.get("CALMA_HOME", _REPO_ROOT_DEFAULT)


def _workspace() -> str:
    return os.path.realpath(os.environ.get("CALMA_MCP_WORKSPACE", os.getcwd()))


def _require_in_workspace(target: str) -> str:
    """Reject a target that escapes the workspace (path-traversal guard). Returns the abs path."""
    rp = os.path.realpath(target)
    ws = _workspace()
    if rp != ws and not rp.startswith(ws + os.sep):
        raise ValueError("target %r escapes the workspace %r (set CALMA_MCP_WORKSPACE to widen it)"
                         % (target, ws))
    return rp


_ISOLATION_TIERS = ("auto", "seatbelt", "bwrap", "docker", "container", "vm", "firecracker", "e2b",
                    "none", "host-not-isolated")


def _run_json(argv, *, timeout, cwd=None, env=None):
    """Run a subprocess and parse its stdout as the engine's --json. Mirrors edges/common/engine.py:
    a non-zero exit (e.g. a REFUTED gate-exit of 1) still carries valid JSON on stdout; only a true
    crash (no JSON) raises. Subprocess output is NOT echoed back to the caller (it can carry host paths /
    secrets) -- a crash returns a fixed, non-leaking message."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
    except subprocess.TimeoutExpired:
        raise RuntimeError("verification timed out")
    try:
        return json.loads(p.stdout)
    except ValueError:
        raise RuntimeError("the engine produced no JSON (exit %s); the target may not be a runnable "
                           "Calma project" % p.returncode)


# --- tool implementations (each is a thin shell-out; the engine owns every verdict) ------------
def verify(target, *, claim=None, metric=None, mode="ask", trust="own-code",
           isolation="auto", timeout=600, check_determinism=False) -> dict:
    """`calma verify <target> --json` -> the parsed verdict dict. The agent-guardrail tool: it works
    against the engine shipping today. --trust / --isolation / --timeout pass through unchanged so
    untrusted-code verification still routes through the engine's isolation tiers."""
    abs_target = _require_in_workspace(target)
    timeout = max(1, min(int(timeout), 86400))               # clamp: no 0/negative/unbounded transport wait
    if str(trust) not in ("own-code", "third-party"):
        raise ValueError("trust must be 'own-code' or 'third-party'")
    if str(isolation) not in _ISOLATION_TIERS:
        raise ValueError("isolation must be one of %s" % (_ISOLATION_TIERS,))
    # build all caller-controlled VALUES as option args (which argparse binds as values, not flags), and
    # put the positional target AFTER `--` so a target/claim beginning with '-' can never smuggle a flag.
    argv = ["python3", _calma_script(), "verify", "--json",
            "--trust", str(trust), "--isolation", str(isolation), "--timeout", str(timeout)]
    # the free-text caller values go as `--opt=VALUE` single tokens: argparse binds the value even when it
    # begins with '-' (a bare `--claim --restore` would otherwise be parsed as the --restore FLAG, or a
    # legitimate claim like '-31.6%' would be rejected). mode is a fixed enum, so plain form is fine.
    if claim:
        argv.append("--claim=" + str(claim))
    if metric:
        argv.append("--metric=" + str(metric))
    if mode:
        argv += ["--mode", str(mode)]
    if check_determinism:
        argv += ["--check-determinism"]
    argv += ["--", abs_target]                                # end-of-options: target is unambiguously positional
    return _run_json(argv, timeout=timeout + 30)


def debug(target, *, claim=None, metric=None, trust="own-code", isolation="auto", timeout=600) -> dict:
    """`calma verify <target> --run-only --json` -> {run_only, metrics:[{metric, binding, claimed,
    recomputed, gap, reason}], isolation_tier, ...}. NO verdict, NO gate: it re-runs + recomputes + diffs
    so an agent can SEE what the code actually computes and how far the claim is, mid-task, then iterate -
    instead of a pass/fail. Same isolation pass-through as calma_verify; the engine still owns every
    number (the transport never recomputes a thing)."""
    abs_target = _require_in_workspace(target)
    timeout = max(1, min(int(timeout), 86400))
    if str(trust) not in ("own-code", "third-party"):
        raise ValueError("trust must be 'own-code' or 'third-party'")
    if str(isolation) not in _ISOLATION_TIERS:
        raise ValueError("isolation must be one of %s" % (_ISOLATION_TIERS,))
    argv = ["python3", _calma_script(), "verify", "--run-only", "--json",
            "--trust", str(trust), "--isolation", str(isolation), "--timeout", str(timeout)]
    if claim:
        argv.append("--claim=" + str(claim))            # `--opt=VALUE` so a leading '-' can't smuggle a flag
    if metric:
        argv.append("--metric=" + str(metric))
    argv += ["--", abs_target]                            # end-of-options: target is unambiguously positional
    return _run_json(argv, timeout=timeout + 30)


def verify_artifact(target, *, mode="flag") -> dict:
    """`python -m edges.extract <target> --json --mode <mode>` -> the A1 Report JSON (catches first,
    each tied to its source span). Wraps the A1 CLI seam; the engine still owns every verdict."""
    abs_target = _require_in_workspace(target)
    root = _repo_root()
    env = dict(os.environ)
    env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.pop("CALMA_EDGES_RECORD", None)                       # transport never records; replay/live only
    argv = [sys.executable, "-m", "edges.extract", abs_target, "--json", "--mode", str(mode)]
    return _run_json(argv, timeout=900, cwd=root, env=env)


def suggest(query, *, top=5) -> dict:
    """`calma suggest <text> --json` -> ranked recipe candidates for a free-text ask. (The shipped
    `suggest` ranks recipes from free text, so this tool takes a `query`, not a target dir.)"""
    argv = ["python3", _calma_script(), "suggest", str(query), "--top", str(int(top)), "--json"]
    return _run_json(argv, timeout=120)


# --- tool + resource schemas -------------------------------------------------------------------
_TOOLS = [
    types.Tool(
        name="calma_verify",
        description="Independently verify a computational claim by RE-EXECUTING the target to ground "
                    "truth and recomputing the headline number, then prove or break the claim. "
                    "Deterministic (no LLM): the agent proposes the number, Calma's engine disposes "
                    "the verdict. Returns the engine's --json verdict verbatim.",
        inputSchema={
            "type": "object",
            "required": ["target"],
            "properties": {
                "target": {"type": "string", "description": "folder with the code and its outputs"},
                "claim": {"type": ["string", "null"], "default": None,
                          "description": "the headline claim, e.g. 'sharpe 1.85'"},
                "metric": {"type": ["string", "null"], "default": None,
                           "description": "force a specific recipe/metric id"},
                "mode": {"type": "string", "enum": ["ask", "suggest", "auto"], "default": "ask"},
                "trust": {"type": "string", "enum": ["own-code", "third-party"], "default": "own-code",
                          "description": "untrusted code routes through stronger isolation"},
                "isolation": {"type": "string", "default": "auto",
                              "enum": list(_ISOLATION_TIERS),
                              "description": "isolation tier (auto picks by trust); passed through, "
                                             "never downgraded below the engine default"},
                "timeout": {"type": "integer", "default": 600, "minimum": 1},
                "check_determinism": {"type": "boolean", "default": False},
            },
        },
    ),
    types.Tool(
        name="calma_verify_artifact",
        description="Verify EVERY number in an artifact directory automatically (notebook / PDF / CSV "
                    "+ the data it was computed from), each catch tied to its source span. Wraps the "
                    "A1 claim-graph pipeline; returns the Report JSON with catches first.",
        inputSchema={
            "type": "object",
            "required": ["target"],
            "properties": {
                "target": {"type": "string",
                           "description": "a directory the engine can run (artifact + entrypoint + data)"},
                "mode": {"type": "string", "enum": ["flag", "fix"], "default": "flag",
                         "description": "flag: surface catches. fix: also emit the A4 repair handoffs."},
            },
        },
    ),
    types.Tool(
        name="calma_suggest",
        description="Unclear what to verify? Rank the recipes a free-text description best matches "
                    "(the shipped recipe suggester). Returns ranked candidates as JSON.",
        inputSchema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "the ask, e.g. 'my risk-adjusted return "
                                                           "looked strong'"},
                "top": {"type": "integer", "default": 5, "minimum": 1},
            },
        },
    ),
    types.Tool(
        name="calma_debug",
        description="Iterate mid-task: re-run the target, RECOMPUTE the metric from the raw outputs, and "
                    "return the binding + recomputed value + gap vs your claim - with NO verdict and NO "
                    "gate. Use this while building (\"what does the code actually compute, and how far off "
                    "is my number?\"); use calma_verify for the gating pass/fail. Returns "
                    "{metrics:[{metric, binding, claimed, recomputed, gap, reason}], isolation_tier, ...}.",
        inputSchema={
            "type": "object",
            "required": ["target"],
            "properties": {
                "target": {"type": "string", "description": "folder with the code and its outputs"},
                "claim": {"type": ["string", "null"], "default": None,
                          "description": "optional claim to measure the gap against, e.g. 'accuracy 0.94'"},
                "metric": {"type": ["string", "null"], "default": None,
                           "description": "force a specific recipe/metric id"},
                "trust": {"type": "string", "enum": ["own-code", "third-party"], "default": "own-code"},
                "isolation": {"type": "string", "default": "auto", "enum": list(_ISOLATION_TIERS)},
                "timeout": {"type": "integer", "default": 600, "minimum": 1},
            },
        },
    ),
]

_RESOURCES = [
    types.Resource(uri="calma://recipes", name="Calma recipe catalog",
                   description="every built-in metric recipe, grouped by family (coverage at a glance)",
                   mimeType="text/plain"),
    types.Resource(uri="calma://catch-history",
                   name="Calma catch-history registry",
                   description="the (Rekor-backed) catch-history registry summary, if configured",
                   mimeType="text/plain"),
]

_DISPATCH = {
    "calma_verify": lambda a: verify(
        a["target"], claim=a.get("claim"), metric=a.get("metric"), mode=a.get("mode", "ask"),
        trust=a.get("trust", "own-code"), isolation=a.get("isolation", "auto"),
        timeout=a.get("timeout", 600), check_determinism=a.get("check_determinism", False)),
    "calma_verify_artifact": lambda a: verify_artifact(a["target"], mode=a.get("mode", "flag")),
    "calma_suggest": lambda a: suggest(a["query"], top=a.get("top", 5)),
    "calma_debug": lambda a: debug(
        a["target"], claim=a.get("claim"), metric=a.get("metric"),
        trust=a.get("trust", "own-code"), isolation=a.get("isolation", "auto"),
        timeout=a.get("timeout", 600)),
}


# --- resource readers (best-effort; never raise the server down) -------------------------------
def _read_recipes() -> str:
    try:
        p = subprocess.run(["python3", _calma_script(), "recipes"],
                           capture_output=True, text=True, timeout=120)
        return p.stdout or p.stderr or "(no recipe output)"
    except Exception as e:                                    # pragma: no cover - defensive
        return "recipe catalog unavailable: %s" % e


def _read_catch_history() -> str:
    try:
        p = subprocess.run(["python3", _calma_script(), "registry", "verify"],
                           capture_output=True, text=True, timeout=120, cwd=_repo_root())
        out = (p.stdout or "").strip()
        return out or "(no catch-history registry configured)"
    except Exception as e:                                    # pragma: no cover - defensive
        return "catch-history registry unavailable: %s" % e


# --- the MCP server wiring ---------------------------------------------------------------------
def build_server() -> Server:
    """Construct the low-level MCP Server with the calma_* tools + read-only resources. Used by both
    the stdio entrypoint and the in-process test client."""
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools():
        return list(_TOOLS)

    @server.call_tool()
    async def _call_tool(name, arguments):
        arguments = arguments or {}
        fn = _DISPATCH.get(name)
        if fn is None:
            raise ValueError("unknown tool: %s" % name)
        result = fn(arguments)                                # the engine's JSON, verbatim
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    @server.list_resources()
    async def _list_resources():
        return list(_RESOURCES)

    @server.read_resource()
    async def _read_resource(uri):
        u = str(uri)
        if u == "calma://recipes":
            return _read_recipes()
        if u == "calma://catch-history":
            return _read_catch_history()
        raise ValueError("unknown resource: %s" % u)

    return server


# --- entrypoints -------------------------------------------------------------------------------
async def _run_stdio():
    from mcp.server.stdio import stdio_server
    server = build_server()
    init_options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options)


def _serve_http(host, port):
    """Optional streamable-HTTP transport (needs the [http] extra: starlette + uvicorn)."""
    from contextlib import asynccontextmanager

    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.routing import Mount

    server = build_server()
    manager = StreamableHTTPSessionManager(app=server, stateless=True)

    async def _handle(scope, receive, send):
        await manager.handle_request(scope, receive, send)

    @asynccontextmanager
    async def _lifespan(app):
        async with manager.run():
            yield

    app = Starlette(routes=[Mount("/mcp", app=_handle)], lifespan=_lifespan)
    uvicorn.run(app, host=host, port=port)


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(
        prog="calma-mcp",
        description="Host-agnostic MCP server exposing Calma's deterministic verifier (stdio by "
                    "default; --http for streamable HTTP).")
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)

    if a.http:
        _serve_http(a.host, a.port)
        return 0

    import anyio
    anyio.run(_run_stdio)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
