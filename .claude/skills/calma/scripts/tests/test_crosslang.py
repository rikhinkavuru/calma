"""Cross-language served-fraction regression. Calma runs the program as a black box and recomputes in
its own Python layer, so any language that emits a machine-readable file is verifiable. Each language is
SKIPPED if its toolchain is absent (CI-portable). Pure stdlib. Run: python3 test_crosslang.py
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
sys.path.insert(0, os.path.join(SCR, "..", "calibration"))
import served_fraction as SF  # noqa: E402
import verdict as V  # noqa: E402

A = os.path.join(SCR, "..", "assets", "lang")
_n = _fail = _skip = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# (dir, toolchain binary, expected verdict). C++ fixture is flawed -> REFUTED; the rest honest -> CAVEATS.
# Node is served since the isolation profile grants metadata-only reads on the run base's ancestors
# (its CJS loader lstat's /Users while realpath-resolving the entrypoint).
CASES = [
    ("r", "Rscript", V.CAVEATS),
    ("julia", "julia", V.CAVEATS),
    ("cpp", "c++", V.REFUTED),
    ("rust", "rustc", V.CAVEATS),
    ("node", "node", V.CAVEATS),
]
for d, tool, expected in CASES:
    if not shutil.which(tool):
        _skip += 1
        print("  SKIP [%s] (no %s on host)" % (d, tool))
        continue
    r = SF.assess(os.path.join(A, d), label=d)
    truth(r["served"], "%s served (real verdict, not UNVERIFIABLE)" % d)
    truth(r["verdict"] == expected, "%s -> %s (got %s)" % (d, expected, r["verdict"]))
    truth(r["determinism"] == "uncontrolled", "%s stamped uncontrolled (non-Python)" % d)
    shutil.rmtree(os.path.join(A, d, ".calma"), ignore_errors=True)
    for junk in (".calma_bin", ".calma_contract.json"):
        p = os.path.join(A, d, junk)
        if os.path.exists(p):
            os.remove(p)

print("crosslang: %d checks, %d failures, %d languages skipped" % (_n, _fail, _skip))
sys.exit(1 if _fail else 0)
