import os, re, glob
SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..",
                       ".claude", "skills", "calma", "scripts")
EDGES   = os.path.join(os.path.dirname(__file__), "..")
CORE_FORBIDDEN = ("verdict", "ledger", "compare", "recompute", "numeric")
EDGES_ALLOWED_CORE_IMPORTS = ("compiler", "dsl")   # A3 only

def test_core_never_imports_edges():
    for f in glob.glob(os.path.join(SCRIPTS, "**", "*.py"), recursive=True):
        src = open(f).read()
        assert not re.search(r"^\s*(import edges|from edges)", src, re.M), f

def test_edges_never_import_verdict_core():
    for f in glob.glob(os.path.join(EDGES, "**", "*.py"), recursive=True):
        if "/tests/" in f: continue
        src = open(f).read()
        for mod in CORE_FORBIDDEN:
            assert not re.search(r"(import|from)\s+.*\b%s\b" % mod, src) \
                   or mod in EDGES_ALLOWED_CORE_IMPORTS, (f, mod)

def test_engine_bridge_smoke():
    from edges.common import engine          # subprocess only
    res = engine.verify(os.path.join(SCRIPTS, "..", "assets", "btc"))
    assert res["verdict"] in ("REFUTED","CONFIRMED","CONFIRMED-WITH-CAVEATS","INVALIDATED","INCONCLUSIVE","MIXED")
