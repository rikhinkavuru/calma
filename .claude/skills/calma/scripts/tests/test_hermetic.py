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

# P1-1: the code under test must NOT be able to write calma's own state (<base>/.calma) -
# the deny comes AFTER the base-wide write allow, and Seatbelt is last-match-wins. Real probe.
if doc["sandbox_exec"]:
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, ".calma"))
    with open(os.path.join(d, ".calma", "cache.json"), "w") as fh:
        fh.write('{"planted": false}')
    with open(os.path.join(d, "evil.py"), "w") as fh:
        fh.write("import os\n"
                 "try:\n"
                 "    open('.calma/cache.json', 'w').write('{\"planted\": true}')\n"
                 "    print('CALMA_WRITTEN')\n"
                 "except Exception:\n"
                 "    print('CALMA_DENIED')\n"
                 "try:\n"
                 "    os.makedirs('.calma/run', exist_ok=True)\n"
                 "    open('.calma/run/ledger.json', 'w').write('{}')\n"
                 "    print('LEDGER_PLANTED')\n"
                 "except Exception:\n"
                 "    print('LEDGER_DENIED')\n"
                 "open('ok.txt', 'w').write('ok')\n"
                 "print('BASE_WRITABLE')\n")
    with open(os.path.join(d, "verify.yaml"), "w") as fh:
        json.dump({"run": {"entrypoint": "evil.py", "network": "off"},
                   "env": {"trust": "own-code"}, "artifacts": [], "metrics": []}, fh)
    r4 = H.run(os.path.join(d, "verify.yaml"), base=d, timeout=30)
    out4 = r4.get("stdout_tail", "")
    truth("CALMA_DENIED" in out4 and "CALMA_WRITTEN" not in out4,
          "sandboxed code cannot overwrite .calma/cache.json (last-match-wins deny holds)")
    truth("LEDGER_DENIED" in out4 and "LEDGER_PLANTED" not in out4,
          "sandboxed code cannot plant a ledger under .calma/")
    truth("BASE_WRITABLE" in out4 and os.path.exists(os.path.join(d, "ok.txt")),
          "the base dir itself stays writable (only .calma is denied)")
    truth(open(os.path.join(d, ".calma", "cache.json")).read() == '{"planted": false}',
          "pre-existing cache.json bytes are untouched after the sandboxed run")

# P2: env whitelist - parent secrets never reach the child; contract passthrough does
de = tempfile.mkdtemp()
with open(os.path.join(de, "envprobe.py"), "w") as fh:
    fh.write("import os\n"
             "print('SECRET=' + repr(os.environ.get('CALMA_TEST_SECRET')))\n"
             "print('DECLARED=' + repr(os.environ.get('CALMA_TEST_DECLARED')))\n"
             "print('HAS_PATH=' + str(bool(os.environ.get('PATH'))))\n")
with open(os.path.join(de, "verify.yaml"), "w") as fh:
    json.dump({"run": {"entrypoint": "envprobe.py", "network": "off"},
               "env": {"trust": "own-code", "passthrough": ["CALMA_TEST_DECLARED"]},
               "artifacts": [], "metrics": []}, fh)
os.environ["CALMA_TEST_SECRET"] = "leak-me"
os.environ["CALMA_TEST_DECLARED"] = "declared-ok"
try:
    r5 = H.run(os.path.join(de, "verify.yaml"), base=de, timeout=30)
finally:
    del os.environ["CALMA_TEST_SECRET"]
    del os.environ["CALMA_TEST_DECLARED"]
out5 = r5.get("stdout_tail", "")
truth("SECRET=None" in out5 and "leak-me" not in out5,
      "undeclared parent env vars are stripped from the child (no secret exfil surface)")
truth("DECLARED='declared-ok'" in out5, "contract env.passthrough vars ARE forwarded")
truth("HAS_PATH=True" in out5, "the whitelist keeps PATH (toolchains still resolve)")

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
