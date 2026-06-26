"""Tests for CALMA_REQUIRE_ISOLATED — the multi-tenant-host guard that stops the AUTO own-code path from
degrading to an UNWRAPPED host run on a host without a verified sandbox tier (the control-plane fix for
"dashboard uploads default to own-code that can degrade to unisolated host execution").

The host's real native tier is forced to `host-not-isolated` (monkeypatching the doctor) so the test is
deterministic on any host — a dev Mac with a working Seatbelt tier included. Pure stdlib.
Run: python3 test_require_isolated.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import run_hermetic as H  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- the env-flag helper: only the canonical truthy spellings count -------------------------------
for _v in ("1", "true", "TRUE", "Yes", "on", " 1 "):
    os.environ["_CALMA_FLAG_T"] = _v
    truth(H._env_flag("_CALMA_FLAG_T"), "env-flag truthy: %r" % _v)
for _v in ("0", "false", "no", "off", "", "garbage"):
    os.environ["_CALMA_FLAG_T"] = _v
    truth(not H._env_flag("_CALMA_FLAG_T"), "env-flag falsy: %r" % _v)
os.environ.pop("_CALMA_FLAG_T", None)
truth(not H._env_flag("_CALMA_FLAG_UNSET"), "env-flag unset -> False")


# --- force the native own-code tier to host-not-isolated (works on macOS Seatbelt + Linux bwrap) ---
_HNI = {"tier": "host-not-isolated", "sandbox_exec": False,
        "note": "forced host-not-isolated for the require-isolated test"}
H.doctor = lambda *a, **k: dict(_HNI)
H.bwrap_doctor = lambda *a, **k: dict(_HNI)


def _own_code_base():
    d = tempfile.mkdtemp(prefix="calma_ri_")
    with open(os.path.join(d, "m.py"), "w") as fh:
        fh.write("print('ok')\n")
    json.dump({"run": {"entrypoint": "m.py"}, "env": {"trust": "own-code"},
               "artifacts": [], "metrics": []}, open(os.path.join(d, "verify.yaml"), "w"))
    return d


# (A) flag ON: own-code on a host with NO verified tier is REFUSED (exit 3) BEFORE any host execution.
os.environ["CALMA_REQUIRE_ISOLATED"] = "1"
_a = _own_code_base()
try:
    rA = H.run(os.path.join(_a, "verify.yaml"), base=_a, timeout=30)
finally:
    shutil.rmtree(_a, ignore_errors=True)
truth(rA.get("exit_code") == 3, "require-isolated ON: own-code on host-not-isolated is REFUSED (exit 3, got %s)"
      % rA.get("exit_code"))
truth(rA.get("isolation_tier") == "host-not-isolated", "refusal stamps host-not-isolated honestly")
truth("verified isolation is required" in (rA.get("reason") or ""),
      "refusal reason names the require-isolated policy")
truth(rA.get("container_present") is False, "refused run never claims a verified tier")

# (B) flag OFF: the AUTO own-code path PROCEEDS unwrapped (today's honest-caveat behaviour for a dev host
#     running its OWN code without a sandbox) — it must NOT refuse for the isolation reason.
os.environ.pop("CALMA_REQUIRE_ISOLATED", None)
_b = _own_code_base()
try:
    rB = H.run(os.path.join(_b, "verify.yaml"), base=_b, timeout=30)
finally:
    shutil.rmtree(_b, ignore_errors=True)
truth(rB.get("exit_code") == 0, "require-isolated OFF: own-code still runs (honest caveat, exit 0, got %s)"
      % rB.get("exit_code"))
truth(rB.get("isolation_tier") == "host-not-isolated", "OFF path stamps host-not-isolated (no verified claim)")
truth(rB.get("container_present") is False, "OFF path never claims a verified tier")

# (C) regression guard: an EXPLICIT --isolation seatbelt/bwrap STILL fails loud on host-not-isolated,
#     independent of the flag (the pre-existing explicit-refusal must be unchanged).
os.environ.pop("CALMA_REQUIRE_ISOLATED", None)
_c = _own_code_base()
try:
    _explicit = "bwrap" if sys.platform.startswith("linux") else "seatbelt"
    rC = H.run(os.path.join(_c, "verify.yaml"), base=_c, timeout=30, isolation=_explicit)
finally:
    shutil.rmtree(_c, ignore_errors=True)
truth(rC.get("exit_code") == 3, "explicit --isolation on host-not-isolated still REFUSES (exit 3, got %s)"
      % rC.get("exit_code"))
truth("requested but unavailable" in (rC.get("reason") or ""),
      "explicit-refusal reason is the requested-but-unavailable wording (unchanged)")

print("require-isolated: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
