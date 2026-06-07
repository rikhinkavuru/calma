"""Run every Calma test suite. Pure stdlib. Exit non-zero if any suite fails.
Run: python3 .claude/skills/calma/scripts/tests/run_all.py
"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
suites = sorted(s for s in glob.glob(os.path.join(HERE, "test_*.py")))
fails = 0
for s in suites:
    r = subprocess.run([sys.executable, s], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        fails += 1
        sys.stderr.write(r.stderr)
        print("  -> %s FAILED (exit %d)" % (os.path.basename(s), r.returncode))
print("\n%d suite(s), %d failed" % (len(suites), fails))
sys.exit(1 if fails else 0)
