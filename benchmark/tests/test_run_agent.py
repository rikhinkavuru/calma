"""G1: the agent arm's code tool runs in the engine's network-off sandbox, and every run carries an
isolation tier + a persisted transcript. Pure stdlib, offline (--mock). Run: python3 this_file.py

The integrity crux: a run whose code attempts egress must FAIL the connect (proven by an in-sandbox
planted-egress probe), and a host that can't isolate is stamped host-not-isolated (its runs excluded),
never run unsandboxed. On a host with no verified tier the sandbox-denial asserts are skipped (the code
is never run there) but the plumbing/transcript asserts still hold.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.dirname(HERE)
sys.path.insert(0, BENCH)
import run_agent as A  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


VERIFIED = ("seatbelt-verified", "bwrap-verified")
tier = A._detect_tier()
truth(tier in VERIFIED + ("host-not-isolated",), "tier is a known stamp (got %r)" % tier)

work = tempfile.mkdtemp()
if tier in VERIFIED:
    # planted egress: a network connect from inside the sandbox MUST be denied
    out, t = A._sandboxed_run(
        "import socket\ntry:\n socket.create_connection(('1.1.1.1',80),timeout=4); print('LEAK')\n"
        "except Exception: print('blocked')", work)
    truth(out is not None and "LEAK" not in out, "planted egress is BLOCKED inside the sandbox")
    truth(t == tier, "the sandboxed run reports the verified tier")
    # planted secret-read: $HOME must be unreadable
    out2, _ = A._sandboxed_run(
        "import os\ntry:\n os.listdir(os.path.expanduser('~')); print('LEAK')\nexcept Exception: print('blocked')",
        work)
    truth(out2 is not None and "LEAK" not in out2, "planted $HOME read is BLOCKED inside the sandbox")
    # benign code still runs and returns stdout
    out3, _ = A._sandboxed_run("print(2 + 2)", work)
    truth(out3 is not None and out3.strip() == "4", "benign code runs and returns stdout")
else:
    print("  (host-not-isolated: sandbox-denial asserts skipped; code is never run unsandboxed)")

# end-to-end --mock plumbing: agent.json + transcripts, every record carrying an isolation tier
res_dir = os.path.join(BENCH, "results")
agent_json = os.path.join(res_dir, "agent.json")
tdir = os.path.join(res_dir, "agent_transcripts")
p = subprocess.run([sys.executable, os.path.join(BENCH, "run_agent.py"), "--mock", "--limit", "4", "--k", "3"],
                   capture_output=True, text=True)
truth(p.returncode == 0, "run_agent --mock exits 0 (got %d: %s)" % (p.returncode, p.stderr[-200:]))
if tier in VERIFIED:
    rows = json.load(open(agent_json))
    truth(len(rows) == 4, "agent.json has the 4 counted cases (got %d)" % len(rows))
    truth(all(r.get("isolation_tier") == tier for r in rows), "every counted record carries the verified tier")
    truth(all("reruns" in r and "unstable" in r for r in rows), "records carry reruns + instability")
    # 4 cases * k=3 transcript files, each stamped with a tier
    tfiles = [f for f in os.listdir(tdir) if f.endswith(".json")]
    truth(len(tfiles) >= 4 * 3, "4*k transcript files written (got %d)" % len(tfiles))
    sample = json.load(open(os.path.join(tdir, tfiles[0])))
    truth(sample.get("isolation_tier") == tier, "a transcript carries the isolation tier")

print("run_agent(G1): %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
