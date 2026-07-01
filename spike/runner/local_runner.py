"""local_runner — run a repo entrypoint as a host subprocess with capture armed, k times.

This is the guaranteed end-to-end proof path (no E2B dependency). It is NOT isolated — only use it on
trusted fixtures and curated CPU repos during the spike. Untrusted user code must take the E2B path.

run_local() executes `python <entry...>` in `repo_dir` k times, each writing its own capture JSONL, and
returns the parsed runs + stdout/stderr/timing so the spike loop can score reproduction + determinism.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

from . import capture_env, parse_capture


def run_local(repo_dir, entry, *, k=2, python=None, hooks="sklearn", targets=None,
              env_extra=None, timeout=600, max_elems=None):
    python = python or sys.executable
    entry = list(entry)
    runs, meta = [], []
    hooks_armed = None
    for i in range(max(1, k)):
        with tempfile.NamedTemporaryFile(prefix="calma_cap_", suffix=".jsonl", delete=False) as tf:
            out_path = tf.name
        base = dict(os.environ)
        # Headless by default: a verification sandbox has no display, so matplotlib must use the non-
        # interactive Agg backend — otherwise a stray plt.show() blocks the run until the timeout (a real
        # hang we hit on a curated repo). setdefault so an explicit operator override still wins; before
        # env_extra so callers can override too.
        base.setdefault("MPLBACKEND", "Agg")
        # determinism-enforcing env (core.determinism.enforced_env): freeze dict/set order + timezone so a
        # deterministic-by-construction repo isn't spuriously flagged NON-DETERMINISTIC. PYTHONHASHSEED must
        # be set before the interpreter starts — it is, this is the child's env. setdefault so overrides win.
        base.setdefault("PYTHONHASHSEED", "0")
        base.setdefault("TZ", "UTC")
        if env_extra:
            base.update(env_extra)
        base["CALMA_RUN_INDEX"] = str(i)  # lets a fixture simulate run-to-run drift deterministically
        env = capture_env(base, out_path, hooks=hooks, targets=targets, max_elems=max_elems)
        t0 = time.time()
        try:
            p = subprocess.run([python, *entry], cwd=repo_dir, env=env, timeout=timeout,
                               capture_output=True, text=True)
            rc, out, err, killed = p.returncode, p.stdout, p.stderr, False
        except subprocess.TimeoutExpired as e:
            rc, out, err, killed = -9, (e.stdout or ""), (e.stderr or "") + "\n[timeout]", True
        dt = time.time() - t0
        runs.append(parse_capture(out_path))
        if hooks_armed is None and os.path.isfile(out_path + ".hooks"):
            try:
                import json
                hooks_armed = json.load(open(out_path + ".hooks"))
            except Exception:  # noqa: BLE001
                pass
        meta.append({"returncode": rc, "killed": killed, "seconds": dt,
                     "stdout_tail": (out or "")[-2000:], "stderr_tail": (err or "")[-2000:]})
        for pth in (out_path, out_path + ".hooks"):
            try:
                os.remove(pth)
            except OSError:
                pass
    ran_ok = all(m["returncode"] == 0 for m in meta)
    return {"runs": runs, "meta": meta, "ran_ok": ran_ok, "hooks_armed": hooks_armed,
            "n_calls": [len(r) for r in runs]}
