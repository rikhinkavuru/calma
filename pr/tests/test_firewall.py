"""The pr/ firewall: every verdict comes from an engine subprocess, so NO file under pr/ may import the
verdict core (verdict / ledger / compare / recompute / numeric), nor the edges package, nor calma in
process. The bot is transport only. Mirrors mcp/tests/test_firewall.py: matches real import STATEMENTS
(import X / from X import ...), never the same word in a docstring/comment; a non-empty-scan guard keeps
it from degrading into a no-op.
"""
import glob
import os
import re

PR = os.path.join(os.path.dirname(__file__), "..")
CORE_FORBIDDEN = ("verdict", "ledger", "compare", "recompute", "numeric")


def _pr_py_files():
    pr_root = os.path.normpath(PR)
    for f in glob.glob(os.path.join(PR, "**", "*.py"), recursive=True):
        rel = os.path.relpath(os.path.normpath(f), pr_root)
        if rel == "tests" or rel.startswith("tests" + os.sep):
            continue                                          # skip ONLY the test files
        yield rel, open(f).read()


def test_pr_never_imports_verdict_core():
    scanned = 0
    for rel, src in _pr_py_files():
        scanned += 1
        for mod in CORE_FORBIDDEN:
            imported = (re.search(r"^\s*import\s+(?:[\w.]+\s*,\s*)*%s\b" % mod, src, re.M)
                        or re.search(r"^\s*from\s+%s\b" % mod, src, re.M))
            assert not imported, (rel, mod)
    assert scanned >= 3, "firewall scanned only %d non-test pr files - glob/skip is broken" % scanned


def test_pr_does_not_import_edges_or_calma_engine():
    """Belt and suspenders: the transport stays decoupled - it shells out to `python -m edges.extract`
    and to calma.py; it never imports the edges package or the calma scripts in-process."""
    scanned = 0
    for rel, src in _pr_py_files():
        scanned += 1
        assert not re.search(r"^\s*(import\s+edges|from\s+edges)\b", src, re.M), (rel, "edges")
        assert not re.search(r"^\s*(import\s+calma\b|from\s+calma\b)", src, re.M), (rel, "calma")
    assert scanned >= 3
