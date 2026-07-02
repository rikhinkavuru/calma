"""runner.acquire — detect + run a repo's OWN data-acquisition pipeline (the download-first research case).

Many research repos don't bundle their data; they ship numbered acquisition scripts (`01_download.py …
08_*.py`) or a `make data` target that pull the datasets from HuggingFace / Zenodo / a bucket. In a
network-denied sandbox the eval then fails on a missing file (`FileNotFoundError: data/…parquet`) → DISCOVERED.

This module, gated to paid tiers (core.limits.allow_data_acquisition), runs that acquisition pipeline in a
BOUNDED, allowlisted-internet phase so the data materializes, then the normal eval + recompute proceeds. It is
FCR-safe by construction: acquisition only WRITES input data; the number is still captured from the real run
and recomputed independently, so a wrong/incomplete fetch yields a failed/again-missing run → DISCOVERED,
never a false CONFIRM. Purely orchestration — the runner (local/e2b) is injected, so it's testable without a
sandbox or network.
"""
from __future__ import annotations

import os
import re
import subprocess

# numbered pipeline steps: 01_download.py, 02-prepare.py, step3_fetch.py … — the dominant research shape.
_NUMBERED = re.compile(r"^(?:step[_-]?)?(\d{1,2})[_.\- ]", re.I)
# name signals for an acquisition script when it isn't numbered.
_ACQUIRE_WORDS = ("download", "fetch", "acquire", "acquisition", "get_data", "getdata", "prepare_data",
                  "prepare", "setup_data", "make_dataset", "build_dataset", "pull_data", "ingest")
_SKIP = {".git", "__pycache__", ".venv", "venv", "env", ".venvs", "node_modules", "results", "data"}
_MAX_STEPS = 12


def find_acquisition(repo_dir: str) -> list[list[str]]:
    """Return an ORDERED list of acquisition commands (each an argv) to run before the eval. Priority:
      1. numbered scripts (01_*.py … NN_*.py) in a code/scripts dir or root, run in numeric order;
      2. else name-matched acquisition scripts (download/fetch/prepare/…);
      3. else a Makefile `data`/`download`/`setup`/`prepare` target (returned as ['make', target]).
    Best-effort + bounded; empty when nothing recognizable is present."""
    # 1 + 2: python scripts
    scripts: list[tuple] = []      # (sort_key, argv)
    for base in ("", "code", "scripts", "src", "data_prep", "preprocessing", "pipeline"):
        d = os.path.join(repo_dir, base) if base else repo_dir
        if not os.path.isdir(d):
            continue
        try:
            files = sorted(f for f in os.listdir(d) if f.endswith(".py") and f not in ("__init__.py",))
        except OSError:
            continue
        for f in files:
            rel = os.path.join(base, f) if base else f
            m = _NUMBERED.match(f)
            if m:
                scripts.append(((0, int(m.group(1)), rel), [rel]))
            elif any(w in f.lower() for w in _ACQUIRE_WORDS):
                scripts.append(((1, 0, rel), [rel]))
        if scripts:
            break                  # first dir with candidates wins (don't mix root + code/)
    if scripts:
        scripts.sort(key=lambda s: s[0])
        # numbered: run the whole ordered prefix (they build on each other). name-matched: just those.
        return [argv for _k, argv in scripts][:_MAX_STEPS]

    # 3: a Makefile data target
    for mk in ("Makefile", "makefile", "GNUmakefile"):
        p = os.path.join(repo_dir, mk)
        if os.path.isfile(p):
            try:
                text = open(p, errors="replace").read()
            except OSError:
                break
            targets = re.findall(r"^([A-Za-z0-9][\w.-]*)\s*:(?!=)", text, re.M)
            for want in ("data", "download", "dataset", "prepare", "setup", "get_data"):
                if want in targets:
                    return [["make", want]]
            break
    return []


def run_acquisition(commands: list[list[str]], run_cmd, *, log=None) -> dict:
    """Run each acquisition command in order via the injected ``run_cmd(argv) -> {ok, tail}`` effector (local
    subprocess or an internet-enabled E2B command). Stops at the first failure (later steps depend on earlier
    ones). Returns {"ran": [...], "ok": bool, "failed": argv|None}. Bounded by the caller's budget."""
    ran: list[list[str]] = []
    for argv in commands:
        if log:
            log("acquire: running %s" % " ".join(argv))
        try:
            r = run_cmd(argv)
        except Exception as e:  # noqa: BLE001 — an effector error is a failed step, never a crash
            r = {"ok": False, "tail": str(e)[:300]}
        ran.append(argv)
        if not r.get("ok"):
            if log:
                log("acquire: step failed (%s) — stopping" % " ".join(argv))
            return {"ran": ran, "ok": False, "failed": argv, "tail": r.get("tail", "")}
    return {"ran": ran, "ok": True, "failed": None}


def local_run_cmd(repo_dir: str, python: str, timeout: int = 900):
    """An injectable effector that runs one acquisition argv as a host subprocess WITH network (the local
    proof path — fixtures/curated only). Returns {ok, tail}."""
    def _run(argv):
        exe = [python, *argv] if str(argv[0]).endswith(".py") else list(argv)
        try:
            p = subprocess.run(exe, cwd=repo_dir, capture_output=True, text=True, timeout=timeout)
            return {"ok": p.returncode == 0, "tail": (p.stderr or p.stdout or "")[-400:]}
        except (OSError, subprocess.SubprocessError) as e:
            return {"ok": False, "tail": str(e)[:300]}
    return _run
