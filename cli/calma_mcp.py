"""calma_mcp — the Calma verification engine as an MCP tool for AI agents.

`python -m calma_mcp` (stdio). Gives an agent a `calma_verify` tool that re-runs a repo and recomputes the
numbers it reports, returning the engine's per-claim verdicts. TRANSPORT ONLY: every tool shells out to the
`calma` CLI (which calls the hosted API with your CALMA_API_KEY) and returns its JSON verbatim — the server
never computes or interprets a verdict itself. "AI proposes, determinism disposes."

Config (env):
    CALMA_API_KEY   your API key (https://calma1.vercel.app/dashboard/keys)
    CALMA_API_URL   engine base URL (default https://calma-engine.fly.dev)
    CALMA_CLI       path to the calma CLI (default: the `calma` on PATH, else this dir's calma.py)

Install:  pip install "calma[mcp]"   (brings in the `mcp` package)
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

SERVER_NAME = "calma"
_HERE = os.path.dirname(os.path.abspath(__file__))


def _cli() -> list[str]:
    """How to invoke the CLI: an explicit CALMA_CLI, else `calma` on PATH, else this package's calma.py."""
    override = os.environ.get("CALMA_CLI")
    if override:
        return override.split()
    import shutil
    if shutil.which("calma"):
        return ["calma"]
    return [sys.executable, os.path.join(_HERE, "calma.py")]


def _run(args: list[str], timeout: int = 1800) -> str:
    try:
        p = subprocess.run(_cli() + args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "calma timed out after %ds" % timeout})
    if p.returncode not in (0, 1):          # 1 = a non-CONFIRMED verdict, still valid output
        return json.dumps({"error": (p.stderr or p.stdout or "calma failed").strip()[:800]})
    return (p.stdout or "").strip() or json.dumps({"error": "no output"})


def build_server():
    import mcp.types as types
    from mcp.server import Server

    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="calma_verify",
                description=("Verify the numbers a code repository reports: re-run it, recompute every reported "
                             "metric from the raw outputs, and return a per-claim verdict (CONFIRMED / REFUTED / "
                             "INVALIDATED / REPRODUCED_ONLY / INCONCLUSIVE / DISCOVERED). Never a false confirm."),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "owner/name or a github URL"},
                        "deep": {"type": "boolean", "default": True,
                                 "description": "re-run the repo (true) or a no-run validity check only (false)"},
                        "entry": {"type": "string", "description": "entrypoint override (auto-detected otherwise)"},
                    },
                    "required": ["repo"],
                },
            ),
            types.Tool(
                name="calma_scans",
                description="List your recent Calma scans and their verdict counts.",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        if name == "calma_verify":
            args = ["verify", str(arguments["repo"]), "--json"]
            if arguments.get("deep", True):
                args.append("--deep")
            if arguments.get("entry"):
                args += ["--entry", str(arguments["entry"])]
            out = _run(args)
        elif name == "calma_scans":
            out = _run(["scans", "--json"], timeout=60)
        else:
            out = json.dumps({"error": "unknown tool %s" % name})
        return [types.TextContent(type="text", text=out)]

    return server


def main() -> int:
    try:
        import mcp.server.stdio  # noqa: F401
    except ImportError:
        sys.stderr.write("the MCP server needs the `mcp` package — install with: pip install 'calma[mcp]'\n")
        return 1
    from mcp.server.stdio import stdio_server

    async def _serve():
        server = build_server()
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_serve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
