"""`python -m calma_mcp` -> the Calma MCP server (stdio by default; --http for streamable HTTP)."""
from calma_mcp.server import main

if __name__ == "__main__":
    raise SystemExit(main())
