"""Tests for run_hermetic.py: verified isolation (doctor), sandboxed re-emit, egress denial, and the
untrusted-third-party refusal. On a host without sandbox-exec these degrade to host-not-isolated (still
asserted honestly). Pure stdlib. Run: python3 test_hermetic.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import run_hermetic as H  # noqa: E402

BTC = os.path.join(SCR, "..", "assets", "btc")
_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


doc = H.doctor(BTC)
if doc["sandbox_exec"]:
    truth(doc["secret_read_blocked"], "doctor: planted secret-read is BLOCKED")
    truth(doc["egress_blocked"], "doctor: network egress is BLOCKED")
    truth(doc["tier"] == "seatbelt-verified", "doctor: tier seatbelt-verified")
else:
    truth(doc["tier"] == "host-not-isolated", "no sandbox-exec -> host-not-isolated (honest)")

# run the BTC entrypoint network-off -> re-emits artifacts, exit 0
res = H.run(os.path.join(BTC, "verify.yaml"), base=BTC)
truth(res["exit_code"] == 0, "BTC entrypoint runs clean under the tier (exit %s)" % res["exit_code"])
truth(res["determinism_mode"] == "controlled-to-bit", "pure-stdlib entrypoint -> controlled-to-bit")
truth(os.path.exists(os.path.join(BTC, "runs", "oos", "returns.csv")), "raw artifact re-emitted")
truth("claimed_in_sample_return" in res["stdout_tail"], "entrypoint output captured")

# egress denial: an entrypoint that tries to reach the network FAILS under the tier
if doc["sandbox_exec"]:
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "fetch.py"), "w") as fh:
        fh.write("import socket\nsocket.create_connection(('1.1.1.1',80),timeout=4)\nprint('REACHED')\n")
    with open(os.path.join(d, "verify.yaml"), "w") as fh:
        json.dump({"run": {"entrypoint": "fetch.py", "network": "off"},
                   "env": {"trust": "own-code"}, "artifacts": [], "metrics": []}, fh)
    r2 = H.run(os.path.join(d, "verify.yaml"), base=d, timeout=30)
    truth(r2["exit_code"] in (1, 4) and "REACHED" not in r2.get("stdout_tail", ""),
          "network-fetch entrypoint is blocked by the egress boundary (exit %s)" % r2["exit_code"])

# untrusted third-party code with no container/VM tier -> refused (exit 3)
du = tempfile.mkdtemp()
with open(os.path.join(du, "x.py"), "w") as fh:
    fh.write("print('hi')\n")
with open(os.path.join(du, "verify.yaml"), "w") as fh:
    json.dump({"run": {"entrypoint": "x.py"}, "env": {"trust": "untrusted-third-party"},
               "artifacts": [], "metrics": []}, fh)
r3 = H.run(os.path.join(du, "verify.yaml"), base=du)
truth(r3["exit_code"] == 3 and r3["phase"] == "refused", "untrusted + no container -> refused exit 3")

print("run_hermetic: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
