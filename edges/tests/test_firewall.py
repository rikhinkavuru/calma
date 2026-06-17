import os, re, glob
SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..",
                       ".claude", "skills", "calma", "scripts")
EDGES   = os.path.join(os.path.dirname(__file__), "..")
CORE_FORBIDDEN = ("verdict", "ledger", "compare", "recompute", "numeric")
EDGES_ALLOWED_CORE_IMPORTS = ("compiler", "dsl")   # A3 only

def test_core_never_imports_edges():
    scanned = 0
    for f in glob.glob(os.path.join(SCRIPTS, "**", "*.py"), recursive=True):
        scanned += 1
        src = open(f).read()
        assert not re.search(r"^\s*(import edges|from edges)", src, re.M), f
    assert scanned >= 20, "core scan globbed only %d files - SCRIPTS path is wrong" % scanned

def test_edges_never_import_verdict_core():
    edges_root = os.path.normpath(EDGES)
    scanned = 0
    for f in glob.glob(os.path.join(EDGES, "**", "*.py"), recursive=True):
        rel = os.path.relpath(os.path.normpath(f), edges_root)     # 'common/engine.py', not '.../tests/../...'
        if rel == "tests" or rel.startswith("tests" + os.sep):
            continue                                                # skip ONLY the test files
        scanned += 1
        src = open(f).read()
        for mod in CORE_FORBIDDEN:
            # match a real import STATEMENT (import X / import a, X / from X import ...),
            # never prose in a docstring/comment that merely contains the word.
            imported = (re.search(r"^\s*import\s+(?:[\w.]+\s*,\s*)*%s\b" % mod, src, re.M)
                        or re.search(r"^\s*from\s+%s\b" % mod, src, re.M))
            assert not imported or mod in EDGES_ALLOWED_CORE_IMPORTS, (rel, mod)
    # the firewall must never silently become a no-op again (the P1.4-discovered bug):
    assert scanned >= 5, "firewall scanned only %d non-test edge files - glob/skip is broken" % scanned

def test_engine_bridge_smoke():
    from edges.common import engine          # subprocess only
    res = engine.verify(os.path.join(SCRIPTS, "..", "assets", "btc"))
    assert res["verdict"] in ("REFUTED","CONFIRMED","CONFIRMED-WITH-CAVEATS","INVALIDATED","INCONCLUSIVE","MIXED")
