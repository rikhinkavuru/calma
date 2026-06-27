"""calma.spike.runner — make a repo runnable and execute its entrypoint with capture armed.

local_runner   subprocess on the host (the no-E2B proof path; fast; for fixtures + simple CPU repos)
e2b_runner     E2B Firecracker microVM, network-denied (the real isolation path for untrusted code)

Both inject the SAME capture shim (spike/capture on PYTHONPATH + CALMA_CAPTURE_OUT) and return the same
shape: a list of `runs`, each a list of captured-call dicts, so core.diff is runner-agnostic.
"""
import json
import os

CAPTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "capture")


def parse_capture(path):
    """Read a CALMA_CAPTURE_OUT JSONL file into a list of call dicts (skips malformed lines)."""
    calls = []
    if not os.path.isfile(path):
        return calls
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                calls.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    calls.sort(key=lambda c: c.get("seq", 0))
    return calls


def capture_env(base_env, out_path, *, hooks="sklearn", targets=None, max_elems=None):
    """Build the env that arms capture: prepend spike/capture to PYTHONPATH + the capture config vars."""
    env = dict(base_env)
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = CAPTURE_DIR + (os.pathsep + prior if prior else "")
    env["CALMA_CAPTURE_OUT"] = out_path
    env["CALMA_CAPTURE_HOOKS"] = hooks
    if targets:
        env["CALMA_CAPTURE_TARGETS"] = json.dumps(targets)
    if max_elems:
        env["CALMA_CAPTURE_MAX_ELEMS"] = str(max_elems)
    return env
