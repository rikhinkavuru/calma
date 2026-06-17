"""The app/ firewall: every verdict comes from the engine (via the pr/ transport), so NO file under
app/ may import the verdict core (verdict / ledger / compare / recompute / numeric), nor edges, nor
calma in-process. Mirrors pr/tests/test_firewall.py + mcp/tests/test_firewall.py; a non-empty-scan
guard keeps it from degrading into a no-op.
"""
import glob
import os
import re

APP = os.path.join(os.path.dirname(__file__), "..")
CORE_FORBIDDEN = ("verdict", "ledger", "compare", "recompute", "numeric")


def _app_py_files():
    app_root = os.path.normpath(APP)
    for f in glob.glob(os.path.join(APP, "**", "*.py"), recursive=True):
        rel = os.path.relpath(os.path.normpath(f), app_root)
        if rel == "tests" or rel.startswith("tests" + os.sep):
            continue
        yield rel, open(f).read()


def test_app_never_imports_verdict_core():
    scanned = 0
    for rel, src in _app_py_files():
        scanned += 1
        for mod in CORE_FORBIDDEN:
            imported = (re.search(r"^\s*import\s+(?:[\w.]+\s*,\s*)*%s\b" % mod, src, re.M)
                        or re.search(r"^\s*from\s+%s\b" % mod, src, re.M))
            assert not imported, (rel, mod)
    assert scanned >= 2, "firewall scanned only %d non-test app files - glob/skip is broken" % scanned


def test_app_does_not_import_edges_or_calma_engine():
    """app/ shells to the engine through the pr/ transport; it never imports the edges package or the
    calma scripts in-process."""
    scanned = 0
    for rel, src in _app_py_files():
        scanned += 1
        assert not re.search(r"^\s*(import\s+edges|from\s+edges)\b", src, re.M), (rel, "edges")
        assert not re.search(r"^\s*(import\s+calma\b|from\s+calma\b)", src, re.M), (rel, "calma")
    assert scanned >= 2
