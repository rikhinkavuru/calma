"""M4: auto-mode is genuinely offline-capable. --offline (env CALMA_OFFLINE / config) skips the ONE
network step - the RFC 3161 timestamp - while the LOCAL catch-record still accrues. The local append
happens INDEPENDENT of (before) the timestamp, so a network hiccup can't drop it. Pure stdlib,
offline (no real network). Run: python3 test_auto_offline.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import calma as C  # noqa: E402
import attest  # noqa: E402
import rfc3161  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- _offline_enabled resolver precedence ---
truth(C._offline_enabled(True, ".") is True, "offline: --offline wins")
os.environ["CALMA_OFFLINE"] = "1"
truth(C._offline_enabled(False, ".") is True, "offline: env CALMA_OFFLINE=1 enables")
os.environ["CALMA_OFFLINE"] = "0"
truth(C._offline_enabled(False, ".") is False, "offline: env CALMA_OFFLINE=0 disables")
del os.environ["CALMA_OFFLINE"]
truth(C._offline_enabled(False, ".") is False, "offline: default off")

# --- _autonomy_followup: offline skips the TSA call, online makes it; local accrues either way ---
calls = {"ts": 0, "local": 0}
_orig_ts, _orig_local, _orig_gate = (rfc3161.timestamp_bundle, C._auto_local_publish, C.AUT.gate)
rfc3161.timestamp_bundle = lambda *a, **k: calls.__setitem__("ts", calls["ts"] + 1)
C._auto_local_publish = lambda *a, **k: calls.__setitem__("local", calls["local"] + 1)
C.AUT.gate = lambda *a, **k: "execute"

tmp = tempfile.mkdtemp(prefix="calma_m4_")
run_dir = os.path.join(tmp, "run")
os.makedirs(run_dir)
open(os.path.join(run_dir, attest.BUNDLE_NAME), "w").write("{}")
res = {"run_dir": run_dir, "repo_verdict": "REFUTED"}

C._autonomy_followup(res, "auto", tmp, quiet=True, offline=True)
truth(calls["ts"] == 0, "offline: the RFC 3161 TSA call is NOT made")
truth(calls["local"] == 1, "offline: the local catch-record IS still appended")

C._autonomy_followup(res, "auto", tmp, quiet=True, offline=False)
truth(calls["ts"] == 1, "online: the TSA timestamp IS made")
truth(calls["local"] == 2, "online: local catch-record appended (before the network step)")

rfc3161.timestamp_bundle, C._auto_local_publish, C.AUT.gate = _orig_ts, _orig_local, _orig_gate
import shutil  # noqa: E402
shutil.rmtree(tmp, ignore_errors=True)
print("auto-offline (M4): %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
