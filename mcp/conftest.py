"""pytest config for the mcp/ package.

Put the mcp/ directory itself on sys.path so `import calma_mcp` resolves to mcp/calma_mcp/. The repo
root dir `mcp/` has NO __init__.py, so `import mcp` still resolves to the installed MCP SDK (a regular
package in site-packages wins over a bare namespace directory, per PEP 420) -- no shadowing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
