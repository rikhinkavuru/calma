"""Run the deterministic core as a SUBPROCESS. No calma script is ever imported here, so edge code
literally cannot reach verdict.py. Verdict-producing edges (A1/A2/A4) go through this."""
import json, os, subprocess
CALMA = os.path.join(os.path.dirname(__file__), "..", "..",
                     ".claude", "skills", "calma", "scripts", "calma.py")

def verify(target, *, claim=None, metric=None, extra_args=(), timeout=600):
    """Run `calma verify <target> --json` and return the parsed dict (includes run_dir)."""
    argv = ["python3", os.path.abspath(CALMA), "verify", target, "--json"]
    if claim is not None:  argv += [str(claim)]
    if metric is not None: argv += ["--metric", metric]
    argv += list(extra_args)
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError("calma verify timed out after %ss (the target entrypoint hung)" % timeout)
    try:
        return json.loads(p.stdout)
    except ValueError:
        raise RuntimeError("calma verify produced no JSON: %s" % (p.stderr or p.stdout)[:500])

def read_ledger(run_dir): return json.load(open(os.path.join(run_dir, "ledger.json")))
def read_diff(run_dir):   return json.load(open(os.path.join(run_dir, "diff.json")))
