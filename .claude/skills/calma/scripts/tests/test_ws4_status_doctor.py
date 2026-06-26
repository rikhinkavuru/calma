"""WS4: `calma status` (the glance) + `calma doctor` (health) + the CALMA_QUIET toggle. Pure stdlib,
offline, read-only (no key is generated, no settings mutated). Run: python3 test_ws4_status_doctor.py
"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import calma as C   # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def _run(fn, *a, **k):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = fn(*a, **k)
    return rc, buf.getvalue()


# ---- _health_checks: structure + invariants ----
checks = C._health_checks()
keys = {c["key"] for c in checks}
truth({"engine", "runtime", "stop-hook", "guardrail", "signing-key"} <= keys,
      "doctor checks cover engine/runtime/hook/guardrail/signing-key")
truth(all(c["status"] in ("ok", "warn", "fail") for c in checks), "every check has a valid status")
truth(all(c["status"] == "ok" or c["fix"] for c in checks),
      "every non-OK check carries an actionable fix line")
truth(next(c for c in checks if c["key"] == "runtime")["status"] == "ok",
      "runtime check passes on a supported Python")

# ---- doctor: human render + exit code ----
rc, out = _run(C.doctor_cmd)
truth("calma doctor" in out and "[" in out, "doctor renders a checklist")
truth(rc in (0, 1), "doctor exits 0 (no fails) or 1 (a fail)")
rc_j, out_j = _run(C.doctor_cmd, as_json=True)
j = json.loads(out_j)
truth("checks" in j and isinstance(j["ok"], bool), "doctor --json is structured + has an ok flag")

# ---- guardrail opt-out + CALMA_QUIET are reflected ----
old = dict(os.environ)
try:
    os.environ["CALMA_HOOK"] = "0"
    g = next(c for c in C._health_checks() if c["key"] == "guardrail")
    truth(g["status"] == "warn" and "opted OUT" in g["detail"], "CALMA_HOOK=0 -> guardrail warns")
    os.environ.pop("CALMA_HOOK")
    os.environ["CALMA_QUIET"] = "1"
    g2 = next(c for c in C._health_checks() if c["key"] == "guardrail")
    truth(g2["status"] == "ok" and "quiet" in g2["detail"].lower(),
          "CALMA_QUIET=1 -> guardrail still active, per-run line quiet")
finally:
    os.environ.clear()
    os.environ.update(old)

# CALMA_QUIET turns the hook's coverage note OFF (the inverse of HUSKY=0).
sys.path.insert(0, os.path.join(HERE, ".."))
import hook_stop as HOOK  # noqa: E402
old2 = os.environ.get("CALMA_QUIET")
try:
    os.environ["CALMA_QUIET"] = "1"
    truth(HOOK._coverage_on({"coverage": True}) is False, "CALMA_QUIET=1 silences the hook coverage note")
    os.environ.pop("CALMA_QUIET")
    truth(HOOK._coverage_on({"coverage": True}) is True, "coverage note is ON by default")
finally:
    if old2 is not None:
        os.environ["CALMA_QUIET"] = old2

# ---- status: glance on a project with a synthetic history ----
tmp = tempfile.mkdtemp(prefix="calma-ws4-")
try:
    cd = os.path.join(tmp, ".calma")
    os.makedirs(cd)
    import time
    now = int(time.time())
    with open(os.path.join(cd, "history.jsonl"), "w") as fh:
        fh.write(json.dumps({"ts": now - 90, "run_id": "run", "verdict": "CONFIRMED", "gate_exit": 0,
                             "metric": "accuracy", "recomputed": 0.91}) + "\n")
        fh.write(json.dumps({"ts": now - 60, "run_id": "run", "verdict": "REFUTED", "gate_exit": 1,
                             "metric": "accuracy", "claimed": 0.99, "recomputed": 0.81}) + "\n")
        # the open-blocker case: a CONFIRMED verdict the GATE caught (exit 1). Must tally as Caught,
        # not green — keyed on the persisted gate_exit, never the verdict word alone.
        fh.write(json.dumps({"ts": now - 30, "run_id": "run", "verdict": "CONFIRMED", "gate_exit": 1,
                             "metric": "total_return", "recomputed": -0.324}) + "\n")
        # a pre-fix record with NO gate_exit field falls back to the verdict word (here, a clean pass).
        fh.write(json.dumps({"ts": now - 20, "run_id": "run", "verdict": "CONFIRMED",
                             "metric": "f1", "recomputed": 0.8}) + "\n")
    rc, out = _run(C.status_cmd, tmp)
    truth(rc == 0 and "calma status" in out, "status renders + exits 0")
    truth("last 7 days 4 check" in out, "status counts this project's 7-day history")
    truth("2 Confirmed" in out and "2 Caught" in out,
          "status keys on the persisted gate_exit: a CONFIRMED-with-open-blocker tallies as Caught")
    rc_j, out_j = _run(C.status_cmd, tmp, as_json=True)
    sj = json.loads(out_j)
    truth(sj["last7"]["Confirmed"] == 2 and sj["last7"]["Caught"] == 2,
          "status --json: gate_exit drives the tally (the open-blocker CONFIRMED is a Caught)")
finally:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

# ---- _ago helper ----
truth(C._ago(5) == "5s ago" and C._ago(120) == "2m ago" and C._ago(7200) == "2h ago"
      and C._ago(172800) == "2d ago", "_ago renders terse relative times")

print("ws4-status-doctor: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
