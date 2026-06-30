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

from fastapi import Depends, FastAPI, Header, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from connect import github_app as GH  # noqa: E402  — the GitHub App connector (anyone connects their repos)
import graph as GRAPH  # noqa: E402
import pipeline as PIPE  # noqa: E402  — the verification orchestration (discover → run → diff → validity)
from synth import formula as SYNTH  # noqa: E402  — the catalog flywheel (store → Exa-synth → validate)
from synth import store as SYNTH_STORE  # noqa: E402

app = FastAPI(title="Calma — the correctness layer")

# Service-token gate for the verification API. The WorkOS-gated Next dashboard is the only first-party
# caller: it holds this token server-side and proxies authenticated user submissions here. When the token is
# SET we fail closed (the API is backend-only, never hit directly by a browser); when it is UNSET the API
# stays open for the local-first operator flow (your own machine, your own E2B keys). The SPA at "/" is a
# local dev/admin surface and is not token-gated.
_VERIFY_TOKEN = (os.environ.get("CALMA_VERIFY_TOKEN") or os.environ.get("CALMA_SERVICE_TOKEN") or "").strip()

# SAFETY: a PUBLIC backend runs code from repos that strangers submit. The local runner executes that code as
# a host subprocess (no isolation) — only safe for your own machine / curated repos. On any shared/public
# deployment set CALMA_FORCE_E2B=1: every run is forced into the E2B Firecracker microVM (network-denied,
# ephemeral), and a `local` request is refused. Fail-closed is the rule.
_FORCE_E2B = os.environ.get("CALMA_FORCE_E2B", "").strip().lower() not in ("", "0", "false", "no")


def require_service_token(x_calma_service_token: str | None = Header(default=None)):
    if _VERIFY_TOKEN and x_calma_service_token != _VERIFY_TOKEN:
        raise HTTPException(401, "unauthorized — the verification API is first-party only")


JOBS: dict[str, dict] = {}
INSTALLATIONS: dict[str, dict] = {}    # installation_id ↔ tenant (in-memory MVP); real = the control plane
_LOCK = threading.Lock()
_WORKDIR = os.path.join(tempfile.gettempdir(), "calma_web_repos")
_VENVS = os.path.join(_WORKDIR, ".venvs")
VENV_PY = sys.executable  # the harness venv (has numpy/sklearn) — used for fixture-class repos


class VerifyReq(BaseModel):
    repo: str                       # "owner/name" or a github URL or a local path
    runner: str = "local"           # "local" | "e2b"
    deep: bool = False              # attempt re-execution (needs an entrypoint)
    entry: str | None = None        # e.g. "eval.py" or "train.py --flag"
    pip_install: list[str] | None = None
    discover: bool = True
    claims: list[dict] | None = None
    k: int = 2
    fetch_data: bool = False             # opt-in: fetch missing external data via Exa, then retry (paid-tier)
    installation_id: str | None = None   # clone via this GitHub App installation's short-lived token


def _set(job, **kw):
    with _LOCK:
        job.update(kw)
        job["updated"] = time.time()


def _log(job, msg):
    with _LOCK:
        job["logs"].append(msg)
        job["updated"] = time.time()


def _clone(repo: str, dest: str, job, installation_id=None) -> str:
    """Clone a repo. Order: a GitHub App installation token (anyone's connected private repos) → gh (the
    operator's auth) → plain git. Or use a local path as-is."""
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
    if installation_id and GH.configured():           # the connected-via-GitHub-App path (short-lived token)
        try:
            tok = GH.installation_token_for(installation_id)
            ri = subprocess.run(["git", "clone", "--quiet", "--depth", "1", GH.clone_url(tok, slug), dest],
                                capture_output=True, text=True, timeout=240)
            if ri.returncode == 0:
                return dest
            _log(job, "installation-token clone failed, falling back: %s" % (ri.stderr or "")[-120:])
        except Exception as e:  # noqa: BLE001
            _log(job, "installation token error: %s" % str(e)[:120])
    gh_err = ""
    try:                                              # gh = the operator's local auth (not present on a server)
        r = subprocess.run(["gh", "repo", "clone", slug, dest, "--", "--depth", "1"],
                           capture_output=True, text=True, timeout=240)
        if r.returncode == 0:
            return dest
        gh_err = r.stderr or ""
    except FileNotFoundError:                          # no gh in this env → fall straight through to plain git
        gh_err = "gh not installed"
    r2 = subprocess.run(["git", "clone", "--quiet", "--depth", "1",
                         "https://github.com/%s.git" % slug, dest], capture_output=True, text=True,
                        timeout=240)
    if r2.returncode != 0:
        raise RuntimeError("clone failed: %s" % (gh_err or r2.stderr or "unknown")[:300])
    return dest


def run_job(job, req: VerifyReq):
    try:
        _set(job, status="running", stage="cloning")
        dest = os.path.join(_WORKDIR, job["id"])
        repo_dir = _clone(req.repo, dest, job, req.installation_id)
        result = PIPE.verify_repo(
            repo_dir,
            PIPE.VerifyOptions(
                runner=req.runner,
                deep=req.deep,
                entry=req.entry,
                pip_install=req.pip_install,
                discover=req.discover,
                claims=list(req.claims or []),
                k=req.k,
                fetch_data=req.fetch_data,
                job_id=job["id"],
                venvs_dir=_VENVS,
                base_python=VENV_PY,
            ),
            update=lambda **kw: _set(job, **kw),
            log=lambda msg: _log(job, msg),
        )
        _set(job, status="done", stage="done", claims=result["claims"], counts=result["counts"],
             n_claims=result["n_claims"], leakage=result["leakage"], run=result["run"],
             trace=result["trace"], finished=time.time())
        _log(job, "done — %s" % ", ".join("%s:%d" % (k, v) for k, v in result["counts"].items()))
    except Exception as e:  # noqa: BLE001
        _set(job, status="error", stage="error", error="%s: %s" % (type(e).__name__, str(e)[:300]),
             finished=time.time())
        _log(job, "error: %s" % str(e)[:300])


@app.post("/api/verify", dependencies=[Depends(require_service_token)])
def verify(req: VerifyReq):
    # On a public deployment, never run untrusted code on the host — force the isolated E2B path.
    if _FORCE_E2B:
        req.runner = "e2b"
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "repo": req.repo, "runner": req.runner, "deep": req.deep,
           "status": "queued", "stage": "queued", "created": time.time(), "updated": time.time(),
           "claims": [], "counts": {}, "logs": [], "n_claims": 0, "leakage": [], "error": None}
    with _LOCK:
        JOBS[job_id] = job
    threading.Thread(target=run_job, args=(job, req), daemon=True).start()
    return {"id": job_id}


@app.get("/api/jobs", dependencies=[Depends(require_service_token)])
def list_jobs():
    with _LOCK:
        return [{"id": j["id"], "repo": j["repo"], "status": j["status"], "stage": j["stage"],
                 "counts": j["counts"], "n_claims": j["n_claims"], "created": j["created"]}
                for j in sorted(JOBS.values(), key=lambda j: -j["created"])]


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_service_token)])
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


def _internal() -> bool:
    """The catalog (our trusted formulas) is IP/moat + a gameable surface — INTERNAL only. Exposed only
    when CALMA_INTERNAL is set (admin/dev); never to end users of the product."""
    return bool(os.environ.get("CALMA_INTERNAL"))


@app.get("/api/cost", dependencies=[Depends(require_service_token)])
def cost():
    """Operational cost telemetry: Exa calls this process + sandbox-seconds across jobs (the COGS meter)."""
    with _LOCK:
        jobs = list(JOBS.values())
    sandbox_seconds = sum((j.get("run") or {}).get("cost", {}).get("sandbox_seconds", 0) or 0 for j in jobs)
    deep = [j for j in jobs if (j.get("run") or {}).get("cost", {}).get("sandbox_seconds")]
    return {"exa_calls": SYNTH.exa_call_count(),
            "jobs_total": len(jobs), "deep_verifies": len(deep),
            "sandbox_seconds_total": round(sandbox_seconds, 1),
            "sandbox_seconds_avg": round(sandbox_seconds / len(deep), 1) if deep else 0.0}


@app.get("/api/config")
def config():
    return {"internal": _internal(),
            "github": {"configured": GH.configured(), "connected": len(INSTALLATIONS) > 0}}


@app.get("/api/graph")
def graph_view_json():
    """Formula + provenance graph: curated catalog, recipes, banked formulas, and recent verification jobs."""
    return GRAPH.build_graph(JOBS.values())


@app.get("/graph")
def graph_view_html():
    return HTMLResponse(GRAPH.html(GRAPH.build_graph(JOBS.values())))


_GH_SETUP_HTML = """<!doctype html><html><body style="font-family:system-ui;max-width:640px;margin:60px auto;
color:#1a1a18;line-height:1.6"><h2>Connect GitHub — one-time setup</h2><p>The GitHub App isn't configured
yet. Register it (once), then anyone can connect their repos:</p><ol>
<li>Open <a href="https://github.com/settings/apps/new?manifest">github.com/settings/apps/new?manifest</a>
and paste <code>spike/connect/app-manifest.yml</code> (set the webhook URL to this server first).</li>
<li>GitHub returns an <b>App ID</b>, a <b>private key</b> (.pem), and the <b>app slug</b>.</li>
<li>Set <code>CALMA_GH_APP_ID</code>, <code>CALMA_GH_PRIVATE_KEY</code> (the .pem path),
<code>CALMA_GH_APP_SLUG</code> and restart <code>./spike/web.sh</code>.</li></ol>
<p>Full steps: <code>spike/connect/CONNECT.md</code>. <a href="/">← back</a></p></body></html>"""


@app.get("/connect/github")
def connect_github():
    """Step 1: send the user to install the GitHub App (or show setup if it isn't registered yet)."""
    if not GH.configured():
        return HTMLResponse(_GH_SETUP_HTML)
    return RedirectResponse(GH.install_url())


@app.get("/connect/github/setup")
def github_setup(installation_id: str = "", setup_action: str = ""):
    """Step 2: GitHub redirects here after install with the installation_id. Store it, then FORWARD to the
    first-party dashboard (if CALMA_DASHBOARD_URL is set) so its UI adopts the install and lists the repos —
    otherwise land on the local SPA. (Best: set the App's Setup URL straight to <dashboard>/api/github/setup
    and skip this hop; this forward is the fallback so a misconfigured Setup URL still works.)"""
    if installation_id:
        with _LOCK:
            INSTALLATIONS[installation_id] = {"installation_id": installation_id, "action": setup_action}
    dash = (os.environ.get("CALMA_DASHBOARD_URL") or "").rstrip("/")
    if dash:
        from urllib.parse import quote
        return RedirectResponse("%s/api/github/setup?installation_id=%s&setup_action=%s"
                                % (dash, quote(installation_id), quote(setup_action)))
    return RedirectResponse("/?connected=" + installation_id)


@app.get("/api/installations")
def installations():
    with _LOCK:
        return list(INSTALLATIONS.values())


@app.get("/api/gh/repos")
def gh_repos(installation_id: str):
    """The repos this installation granted — listed via a short-lived installation token."""
    try:
        return GH.list_installation_repos(GH.installation_token_for(installation_id))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@app.get("/api/catalog")
def catalog_view():
    """INTERNAL: everything Calma can recompute (curated + flywheel-banked). 404 to non-internal callers so
    the trusted formulas (and how to game them) are never exposed to users."""
    if not _internal():
        raise HTTPException(404, "not found")
    from core import catalog as C
    curated = {m: {"metric": m, "aliases": [], "kind": "curated", "source": "trusted catalog",
                   "inputs": [], "validation": {"method": "curated + validated vs sklearn/scipy"}}
               for m in sorted(C.CATALOG)}
    for alias, m in C.ALIASES.items():
        if m in curated and alias != m:
            curated[m]["aliases"].append(alias)
    banked = []
    store = SYNTH_STORE.get_store()
    try:
        for r in store.all():
            banked.append({"metric": r.metric, "aliases": r.aliases, "kind": "synthesized",
                           "inputs": r.inputs, "source": r.source, "definition": r.definition,
                           "validation": r.validation})
    except Exception:  # noqa: BLE001
        pass
    recipe_ids = []
    try:
        from recipes import adapter as RA
        reg = RA._recipes()
        recipe_ids = sorted(reg.list_ids() if hasattr(reg, "list_ids") else reg._REGISTRY)
    except Exception:  # noqa: BLE001
        pass
    return {"curated": list(curated.values()), "banked": banked, "recipes": recipe_ids,
            "counts": {"curated": len(curated), "banked": len(banked), "recipes": len(recipe_ids),
                       "total": len(curated) + len(banked) + len(recipe_ids)},
            "store": getattr(store, "name", "local")}


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
