"""`calma draft` -- generate a verify.yaml for a repo so you can point Calma at a messy repo. Tests the
in-process heuristic path (DC.draft + write + report) and the guard rails (existing file, --force,
not-a-dir, --json). The --ai path (shell-out to edges + LLM) needs an API key and is exercised manually;
its graceful fallback to the heuristic is what keeps this command always-useful. Pure stdlib, offline.
Run: python3 test_draft_cmd.py
"""
import contextlib
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import calma  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def _repo():
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "gen.py"), "w") as fh:
        fh.write("import csv, os\nos.makedirs('runs', exist_ok=True)\n"
                 "open('runs/out.csv','w').write('x\\n1\\n')\n")
    return d


def _call(**kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = calma.draft_cmd(**kw)
    return rc, buf.getvalue()


# heuristic draft writes a runnable skeleton + exits 0
d = _repo()
rc, out = _call(target=d, ai=False)
truth(rc == 0, "heuristic draft exits 0")
dest = os.path.join(d, "verify.yaml")
truth(os.path.isfile(dest), "heuristic draft writes verify.yaml")
contract = json.load(open(dest))
truth((contract.get("run") or {}).get("entrypoint") == "gen.py",
      "the drafted contract detects the entrypoint")
truth("review before relying on it" in out, "the report flags the draft as needing review")

# an existing verify.yaml is not clobbered without --force
rc2, _ = _call(target=d, ai=False)
truth(rc2 == 2, "an existing verify.yaml -> exit 2 (no clobber without --force)")
rc3, _ = _call(target=d, ai=False, force=True)
truth(rc3 == 0, "--force overwrites an existing verify.yaml")

# not a directory -> exit 2 (never crashes)
rc4, _ = _call(target=os.path.join(d, "nope"), ai=False)
truth(rc4 == 2, "a non-directory target -> exit 2")

# --json is machine-readable and labels the source
d2 = _repo()
rc5, out5 = _call(target=d2, ai=False, as_json=True)
parsed = json.loads(out5)
truth(rc5 == 0 and parsed.get("source") == "heuristic" and parsed.get("contract"),
      "--json prints {source: heuristic, contract, ...}")
truth(parsed.get("ai_fell_back") is False, "--json: heuristic (no --ai) did not fall back")

print("draft_cmd: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
