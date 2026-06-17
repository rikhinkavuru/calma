"""The MCP firewall: every verdict comes from a calma.py subprocess, so NO file under mcp/ may import
the verdict core (verdict / ledger / compare / recompute / numeric). The server is transport only.

Mirrors edges/tests/test_firewall.py: it matches real import STATEMENTS (import X / from X import ...),
never the same word appearing in a docstring or comment. A non-empty-scan guard keeps the test from
silently degrading into a no-op (the P1.4-discovered failure mode).
"""
import glob
import os
import re

MCP = os.path.join(os.path.dirname(__file__), "..")
CORE_FORBIDDEN = ("verdict", "ledger", "compare", "recompute", "numeric")


def test_mcp_never_imports_verdict_core():
    mcp_root = os.path.normpath(MCP)
    scanned = 0
    for f in glob.glob(os.path.join(MCP, "**", "*.py"), recursive=True):
        rel = os.path.relpath(os.path.normpath(f), mcp_root)
        if rel == "tests" or rel.startswith("tests" + os.sep):
            continue                                          # skip ONLY the test files
        scanned += 1
        src = open(f).read()
        for mod in CORE_FORBIDDEN:
            imported = (re.search(r"^\s*import\s+(?:[\w.]+\s*,\s*)*%s\b" % mod, src, re.M)
                        or re.search(r"^\s*from\s+%s\b" % mod, src, re.M))
            assert not imported, (rel, mod)
    assert scanned >= 3, "firewall scanned only %d non-test mcp files - glob/skip is broken" % scanned


def test_mcp_does_not_import_edges_or_calma_engine():
    """Belt and suspenders: the transport stays decoupled -- it shells out to `python -m edges.extract`
    and to calma.py, it never imports the edges package or the calma scripts in-process."""
    mcp_root = os.path.normpath(MCP)
    scanned = 0
    for f in glob.glob(os.path.join(MCP, "**", "*.py"), recursive=True):
        rel = os.path.relpath(os.path.normpath(f), mcp_root)
        if rel == "tests" or rel.startswith("tests" + os.sep):
            continue
        scanned += 1
        src = open(f).read()
        assert not re.search(r"^\s*(import\s+edges|from\s+edges)\b", src, re.M), (rel, "edges")
        assert not re.search(r"^\s*(import\s+calma\b|from\s+calma\b)", src, re.M), (rel, "calma")
    assert scanned >= 3
