"""calma-mcp -- a host-agnostic MCP server exposing Calma's deterministic verifier.

Transport only: every tool shells out to the shipped `calma.py` CLI (and the A1 `edges.extract`
seam) and returns the engine's JSON verbatim. No verdict-core import (firewall): the verdict is
always the subprocess's. See server.py.
"""
from calma_mcp.server import build_server, main

__all__ = ["build_server", "main"]
