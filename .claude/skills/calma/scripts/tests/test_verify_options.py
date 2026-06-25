"""H2: verify()'s run-mode flags travel in ONE VerifyOptions object, and the CLI builds it in a
single place so no dispatch path can drop a flag (the bug that left --run-only without
cross_engine / check_determinism). Pure stdlib, offline. Run: python3 test_verify_options.py
"""
import inspect
import os
import sys
from dataclasses import FrozenInstanceError, replace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import calma as C  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


class NS:  # a stand-in argparse namespace
    def __init__(self, **kw):
        self.__dict__.update(kw)


# --- the carrier is frozen + has exactly the run-mode fields ---
opt = C.VerifyOptions()
truth(opt.force is False and opt.trust == "own-code" and opt.isolation is None,
      "defaults match verify()'s historical defaults")
try:
    opt.force = True  # type: ignore
    truth(False, "frozen: assignment must raise")
except FrozenInstanceError:
    truth(True, "frozen: assignment raises")
truth(C._OPT_FIELDS == {"force", "check_determinism", "run_only", "cross_engine",
                        "trust", "isolation", "timeout", "restore", "why"},
      "VerifyOptions carries exactly the 9 run-mode flags")

# --- from_args: every CLI flag round-trips into the object, in ONE place ---
a = NS(force=True, check_determinism=True, run_only=True, cross_engine=True,
       trust="third-party", isolation="docker", timeout=42, restore=True)
o = C.VerifyOptions.from_args(a)
truth(o.force and o.check_determinism and o.run_only and o.cross_engine and o.restore,
      "from_args: bool flags round-trip")
truth(o.trust == "third-party" and o.isolation == "docker" and o.timeout == 42,
      "from_args: scalar flags round-trip")

# --- THE regression: a single options object means --run-only carries cross_engine +
#     check_determinism (the two flags the old run-only dispatch silently dropped) ---
a2 = NS(force=False, check_determinism=True, run_only=True, cross_engine=True,
        trust="own-code", isolation=None, timeout=None, restore=False)
o2 = C.VerifyOptions.from_args(a2)
truth(o2.run_only and o2.cross_engine and o2.check_determinism,
      "run-only + cross-engine + determinism all survive into one opts (the dropped-flag fix)")

# --- the auto-retry uses replace(), so it can't drop a flag either ---
retry = replace(o2, force=True, restore=True)
truth(retry.force and retry.restore and retry.cross_engine and retry.check_determinism
      and retry.run_only,
      "replace(opts, force, restore) preserves every other flag")

# --- VerifyOptions rejects unknown fields (a typo fails loud at construction) ---
try:
    C.VerifyOptions(forcce=True)  # typo
    truth(False, "unknown field must raise")
except TypeError:
    truth(True, "VerifyOptions rejects unknown keys (frozen, fixed field set)")

# --- the **legacy shim is GONE: opts= is the ONLY way to pass run-mode flags. A loose run-mode kwarg on
#     verify() is now an unexpected-keyword TypeError, not a silently-accepted second config path. ---
try:
    C.verify(HERE, opts=C.VerifyOptions(), force=True)
    truth(False, "a loose run-mode kwarg alongside opts= must raise (the shim is gone)")
except TypeError:
    truth(True, "verify() rejects a loose run-mode kwarg alongside opts=")
try:
    C.verify(HERE, force=True)  # even on its own, loose run-mode kwargs no longer exist
    truth(False, "a loose run-mode kwarg on its own must raise (no **legacy)")
except TypeError:
    truth(True, "verify() takes no **legacy kwargs at all - opts= is the single path")

# --- verify()'s signature is EXACTLY the 4 positionals + opts: NO **legacy shim remains ---
sig = inspect.signature(C.verify)
params = list(sig.parameters)
truth(params == ["target", "claim", "metric", "run_id", "opts"],
      "verify signature is exactly target, claim, metric, run_id, opts (no **legacy)")
truth(not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()),
      "verify has NO **legacy shim - opts= is the single, only run-mode entry")

# --- production callsites in calma.py use opts=, never the old loose run-mode kwargs ---
# strip the VerifyOptions(...) / replace(...) constructors first - run-mode kwargs are EXPECTED
# inside them; what we forbid is loose kwargs passed straight to verify().
import re  # noqa: E402
src = open(os.path.join(HERE, "..", "calma.py")).read().replace("\n", " ")
cleaned = re.sub(r"VerifyOptions\([^)]*\)", "OPTS", src)
cleaned = re.sub(r"replace\([^)]*\)", "OPTS", cleaned)
prod_calls = re.findall(r"(?<![A-Za-z_])verify\([^)]*\)", cleaned)
RUN_MODE = r"\b(force|check_determinism|run_only|cross_engine|restore|trust|isolation|timeout|why)="
loose = [c for c in prod_calls if re.search(RUN_MODE, c)]
truth(not loose, "no production verify() callsite passes loose run-mode kwargs: %s" % loose)

print("verify-options (H2): %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
