#!/usr/bin/env python
"""calma.spike.server — the web product's backend: connect a repo → verify the numbers.

A thin FastAPI service over the spike engine (core + runner + discovery). It turns a repo into a durable
background job that streams status through the pipeline stages and returns per-claim verdicts, so the web UI
can show the connect → scan → findings flow (rebuild guide §6 "async by design": verification is never a
synchronous request).

    POST /api/verify   {repo, runner, deep, entry, pip_install, discover, claims}  -> {id}
    GET  /api/jobs                                                                 -> [job summary...]
    GET  /api/jobs/{id}                                                            -> full job + claims
    GET  /api/repos                                                                -> your GitHub repos (gh)
    GET  /                                                                         -> the SPA

Local-first (run on your machine; uses your E2B keys + gh auth). Deploy-ready: the same engine moves behind
apps/api later. In-memory jobs (MVP).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "capture"))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from core import diff as D  # noqa: E402
from core import verdict as VD  # noqa: E402
from discovery import extract as DISC  # noqa: E402
from runner import build  # noqa: E402
from runner.local_runner import run_local  # noqa: E402
from synth import formula as SYNTH  # noqa: E402  — the catalog flywheel (store → Exa-synth → validate)

app = FastAPI(title="Calma — the correctness layer")

JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
_WORKDIR = os.path.join(tempfile.gettempdir(), "calma_web_repos")
_VENVS = os.path.join(_WORKDIR, ".venvs")
VENV_PY = sys.executable  # the harness venv (has numpy/sklearn) — used for fixture-class repos

DISCOVERED = "DISCOVERED"  # a claim we found but did not deep-verify (static layer)


class VerifyReq(BaseModel):
    repo: str                       # "owner/name" or a github URL or a local path
    runner: str = "local"           # "local" | "e2b"
    deep: bool = False              # attempt re-execution (needs an entrypoint)
    entry: str | None = None        # e.g. "eval.py" or "train.py --flag"
    pip_install: list[str] | None = None
    discover: bool = True
    claims: list[dict] | None = None
    k: int = 2


def _set(job, **kw):
    with _LOCK:
        job.update(kw)
        job["updated"] = time.time()


def _log(job, msg):
    with _LOCK:
        job["logs"].append(msg)
        job["updated"] = time.time()


def _clone(repo: str, dest: str, job) -> str:
    """Clone via gh (handles private + auth) with a git fallback; or use a local path as-is."""
    if os.path.isdir(repo):
        return repo
    slug = repo.strip()
    for pre in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if slug.startswith(pre):
            slug = slug[len(pre):]
    slug = slug.removesuffix(".git")
    if os.path.isdir(dest):
        import shutil
        shutil.rmtree(dest, ignore_errors=True)
    _log(job, "cloning %s" % slug)
    r = subprocess.run(["gh", "repo", "clone", slug, dest, "--", "--depth", "1"],
                       capture_output=True, text=True, timeout=240)
    if r.returncode != 0:
        r2 = subprocess.run(["git", "clone", "--quiet", "--depth", "1",
                             "https://github.com/%s.git" % slug, dest], capture_output=True, text=True,
                            timeout=240)
        if r2.returncode != 0:
            raise RuntimeError("clone failed: %s" % (r.stderr or r2.stderr or "unknown")[:300])
    return dest


def _run_repo(repo_dir, runner, entry, pip_install, k, job):
    """Run the entrypoint k× with capture armed (the deep step). Sets job['run']; returns the run result.
    Runs BEFORE discovery so the entrypoint's generated results.json + stdout feed claim discovery."""
    entry_argv = entry.split() if entry else ["eval.py"]
    _set(job, stage="building")
    if runner == "e2b":
        from runner.e2b_runner import run_e2b
        _set(job, stage="running")
        r = run_e2b(repo_dir, entry_argv, k=k, pip_install=pip_install, timeout=600)
    else:
        python, note = build.ensure_venv(job["id"], pip_install, _VENVS, base_python=VENV_PY)
        _log(job, "env: %s" % note)
        _set(job, stage="running")
        r = run_local(repo_dir, entry_argv, k=k, python=python, timeout=600)
    ran_ok = r["ran_ok"]
    total_calls = sum(len(run) for run in r.get("runs", []))
    err = ""
    if not ran_ok:
        err = (" ".join(m.get("stderr_tail", "") for m in r.get("meta", [])).strip())[-260:]
        _log(job, "run failed: %s" % err[-200:])
    _log(job, "captured %d computation(s)" % total_calls)
    job["run"] = {"ran": ran_ok, "calls": total_calls, "entry": " ".join(entry_argv), "error": err}
    return r


def _diff_claims(claims, r, job):
    """Three-way diff each claim against the captured runs, via the flywheel resolver. A metric the run
    never recomputed stays DISCOVERED (not re-run) rather than a misleading INCONCLUSIVE."""
    _set(job, stage="diffing")
    records = []
    for claim in claims:
        if not r["runs"]:
            records.append(_claim_out(claim, DISCOVERED, "deep verify could not run the entrypoint", {}))
            continue
        rec = D.diff_claim(claim, r["runs"], resolver=SYNTH.recompute_any)   # catalog → store → Exa-synth
        v, reason = rec["verdict"], rec.get("reason", "")
        if v == VD.INCONCLUSIVE and "no captured computation" in reason:
            v = DISCOVERED
            reason = ("the re-run did not recompute this number"
                      + (" (the entrypoint failed to run)" if not job["run"]["ran"]
                         else " — point Calma at the script/args that compute it"))
        records.append(_claim_out(claim, v, reason, rec.get("diff", {}),
                                  provenance=rec.get("recompute_provenance")))
    return records


def _claim_out(claim, verdict, reason, diff, provenance=None):
    return {"id": claim.get("id"), "metric": claim.get("metric"), "claimed": claim.get("value"),
            "context": claim.get("context", ""), "location": claim.get("location", ""),
            "source": claim.get("source", "stated"), "confidence": claim.get("confidence"),
            "verdict": verdict, "reason": reason, "diff": diff, "provenance": provenance}


def run_job(job, req: VerifyReq):
    try:
        _set(job, status="running", stage="cloning")
        dest = os.path.join(_WORKDIR, job["id"])
        repo_dir = _clone(req.repo, dest, job)

        # deep verify RUNS FIRST so discovery can read the entrypoint's generated results.json + stdout.
        # auto-detect the entrypoint (README run-cmd / common script) when the user didn't name one.
        entry = req.entry
        if req.deep and not entry:
            entry = " ".join(build.detect_entrypoint(repo_dir) or [])
            if entry:
                _log(job, "auto-detected entrypoint: %s" % entry)
        r = _run_repo(repo_dir, req.runner, entry, req.pip_install, req.k, job) if req.deep else None

        claims = list(req.claims or [])
        if req.discover:
            _set(job, stage="discovering")
            stdout0 = r["meta"][0].get("stdout_tail", "") if (r and r.get("meta")) else ""
            discovered = DISC.discover(repo_dir, stdout_text=stdout0)
            _log(job, "discovered %d claim(s)" % len(discovered))
            claims = claims + discovered
        job["n_claims"] = len(claims)

        if req.deep and r:
            records = _diff_claims(claims, r, job)
        else:
            # static layer: report what we found + what we'd need to verify it
            records = [_claim_out(c, DISCOVERED,
                                  "discovered in %s — provide an entrypoint to re-run and verify"
                                  % c.get("source", "the repo"), {}) for c in claims]

        counts: dict[str, int] = {}
        for rec in records:
            counts[rec["verdict"]] = counts.get(rec["verdict"], 0) + 1
        _set(job, status="done", stage="done", claims=records, counts=counts,
             finished=time.time())
        _log(job, "done — %s" % ", ".join("%s:%d" % (k, v) for k, v in counts.items()))
    except Exception as e:  # noqa: BLE001
        _set(job, status="error", stage="error", error="%s: %s" % (type(e).__name__, str(e)[:300]),
             finished=time.time())
        _log(job, "error: %s" % str(e)[:300])


@app.post("/api/verify")
def verify(req: VerifyReq):
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "repo": req.repo, "runner": req.runner, "deep": req.deep,
           "status": "queued", "stage": "queued", "created": time.time(), "updated": time.time(),
           "claims": [], "counts": {}, "logs": [], "n_claims": 0, "error": None}
    with _LOCK:
        JOBS[job_id] = job
    threading.Thread(target=run_job, args=(job, req), daemon=True).start()
    return {"id": job_id}


@app.get("/api/jobs")
def list_jobs():
    with _LOCK:
        return [{"id": j["id"], "repo": j["repo"], "status": j["status"], "stage": j["stage"],
                 "counts": j["counts"], "n_claims": j["n_claims"], "created": j["created"]}
                for j in sorted(JOBS.values(), key=lambda j: -j["created"])]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with _LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "no such job")
        # cap claims sent to the UI (a big benchmark can discover hundreds); UI shows the count
        out = dict(job)
        if len(out["claims"]) > 500:
            out = dict(out, claims=out["claims"][:500], truncated=len(job["claims"]))
        return out


@app.get("/api/repos")
def repos():
    try:
        r = subprocess.run(["gh", "repo", "list", "--limit", "100", "--json",
                            "name,nameWithOwner,visibility,description,primaryLanguage,pushedAt"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return JSONResponse([], status_code=200)
        import json
        data = json.loads(r.stdout)
        data.sort(key=lambda d: d.get("pushedAt", ""), reverse=True)
        return [{"name": d["name"], "slug": d["nameWithOwner"], "visibility": d["visibility"],
                 "description": d.get("description") or "",
                 "language": (d.get("primaryLanguage") or {}).get("name", "")} for d in data]
    except Exception:  # noqa: BLE001
        return JSONResponse([], status_code=200)


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "web", "index.html"))


@app.get("/app.js")
def appjs():
    return FileResponse(os.path.join(HERE, "web", "app.js"), media_type="application/javascript")


if __name__ == "__main__":
    import uvicorn
    os.makedirs(_WORKDIR, exist_ok=True)
    port = int(os.environ.get("PORT", "8787"))
    print("\n  Calma — connect a repo, verify the numbers")
    print("  → open  http://localhost:%d\n" % port)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
