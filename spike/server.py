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

import dataclasses
import hmac
import os
import re
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

from attest import attestation as ATT  # noqa: E402  — trust layer (feature 3/12/13/18), strictly post-verdict
from attest import badge as BADGE  # noqa: E402
from attest import signing as SIGN  # noqa: E402
from attest import tlog as TLOG  # noqa: E402
from connect import github_app as GH  # noqa: E402  — the GitHub App connector (anyone connects their repos)
from core import limits as LIM  # noqa: E402  — tiered rate limits / quotas / feature gates (PRICING.md)
import graph as GRAPH  # noqa: E402
import pipeline as PIPE  # noqa: E402  — the verification orchestration (discover → run → diff → validity)
from runner import supervisor as SUP  # noqa: E402  — process-isolation: heavy work runs in a capped child
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

# CRASH SAFETY: run the heavy in-process work (discovery / leakage / diff / E2B orchestration) in a disposable,
# resource-capped CHILD process instead of an API thread (runner/supervisor.py). A thread shares the API's
# memory and fate — one repo that OOMs or segfaults during that work would take down the whole API and every
# job with it (the 502). Process isolation makes the worst case ONE job ending cleanly as "exceeded budget"
# while the API stays up. On by default; CALMA_ISOLATE=0 reverts to the legacy in-thread path (dev only).
_ISOLATE = os.environ.get("CALMA_ISOLATE", "1").strip().lower() not in ("0", "false", "no")


def _token_ok(supplied: str | None) -> bool:
    """Constant-time service-token check (hmac.compare_digest) so a byte-by-byte timing side channel can't be
    used to recover the token. Open when no token is configured (the local-first operator flow)."""
    if not _VERIFY_TOKEN:
        return True
    return bool(supplied) and hmac.compare_digest(supplied, _VERIFY_TOKEN)


def require_service_token(x_calma_service_token: str | None = Header(default=None)):
    if not _token_ok(x_calma_service_token):
        raise HTTPException(401, "unauthorized — the verification API is first-party only")


@dataclasses.dataclass
class Identity:
    """Who is calling and at what tier. The service token authenticates the trusted first-party proxy; that
    proxy alone holds the token and sets X-Calma-Tenant (the end user/org id) + X-Calma-Tier (their plan)
    truthfully. Without the token an attacker can forge neither header. Token UNSET → the local operator
    (their machine, their keys): the unmetered `owner` tier."""
    tenant: str
    tier: object            # core.limits.Tier
    unmetered: bool


def identity(x_calma_service_token: str | None = Header(default=None),
             x_calma_tenant: str | None = Header(default=None),
             x_calma_tier: str | None = Header(default=None)) -> Identity:
    if not _token_ok(x_calma_service_token):
        raise HTTPException(401, "unauthorized — the verification API is first-party only")
    if _VERIFY_TOKEN:
        tenant = (x_calma_tenant or "").strip() or "anon"
        tier = LIM.resolve_tier(x_calma_tier)          # unknown/absent → the restrictive default (free)
    else:
        tenant = (x_calma_tenant or "").strip() or "owner"
        tier = LIM.resolve_tier("owner")
    return Identity(tenant=tenant, tier=tier, unmetered=tier.unmetered)


_SLUG_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


def _is_remote_repo(repo: str) -> bool:
    """True only for a GitHub slug or github URL. On a public deployment a LOCAL PATH must never be accepted:
    `_clone` returns a local dir as-is, so `repo='/app'` (or any host path) would upload the server's own
    source — including baked secrets — into a sandbox run. Fail closed: hosted verifies GitHub repos only."""
    s = (repo or "").strip()
    if s.startswith(("https://github.com/", "http://github.com/", "git@github.com:")):
        return True
    if not s or s.startswith((".", "/", "~")) or "\\" in s:   # local/relative/home paths are never remote
        return False
    if not _SLUG_RE.match(s):
        return False
    owner, name = s.split("/", 1)
    return owner not in (".", "..") and name not in (".", "..")


def _bind_installation(iid: str, tenant: str, action: str = "") -> None:
    """Record which tenant a GitHub App installation belongs to, so it can't be used cross-tenant."""
    if not iid:
        return
    with _LOCK:
        rec = INSTALLATIONS.get(iid) or {"installation_id": iid}
        rec["action"] = action or rec.get("action", "")
        if tenant and tenant not in ("", "anon", "owner"):
            rec["tenant"] = tenant
        INSTALLATIONS[iid] = rec


def _installation_ok(iid: str, tenant: str, unmetered: bool) -> bool:
    """Authorize use of a GitHub App installation (mint a scoped token / clone / list its private repos).
    The local operator (unmetered) may use any installation. On the hosted service an installation is usable
    ONLY by the tenant it was bound to at connect time — an unknown or mismatched id is refused, closing the
    IDOR where a guessed installation_id would clone another account's private repos."""
    if unmetered:
        return True
    with _LOCK:
        rec = INSTALLATIONS.get(iid)
    return bool(rec) and rec.get("tenant") == tenant


JOBS: dict[str, dict] = {}
INSTALLATIONS: dict[str, dict] = {}    # installation_id ↔ tenant (in-memory MVP); real = the control plane
_LOCK = threading.Lock()
# feature 12 — the local append-only transparency ledger (hash-chained, tamper-evident). Off the hot path;
# submission is fail-open (a log error never fails a job).
_TLOG = TLOG.LocalLedger(os.path.join(HERE, ".calma", "transparency-ledger.json"))
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
    top_k: int = 1_000_000               # deep-verify at most the top-K salient claims (tier cap); rest → DISCOVERED
    timeout: int = 600                   # per-sandbox wall-clock (tier cap)
    fetch_data: bool = False             # opt-in: fetch missing external data via Exa, then retry (paid-tier)
    installation_id: str | None = None   # clone via this GitHub App installation's short-lived token


def _set(job, **kw):
    with _LOCK:
        job.update(kw)
        job["updated"] = time.time()


def _log(job, msg):
    with _LOCK:
        # stamp every line with elapsed-since-submit so the timeline is readable e2e (where did the time go?)
        t = time.time() - job.get("created", time.time())
        job["logs"].append("[+%6.1fs] %s" % (t, msg))
        if len(job["logs"]) > 4000:                 # bound the in-memory log (a chatty run can stream a lot)
            job["logs"] = job["logs"][-4000:]
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
        repo_dir = _clone(req.repo, dest, job, req.installation_id)   # bounded git subprocess — stays here
        opts = PIPE.VerifyOptions(
            runner=req.runner,
            deep=req.deep,
            entry=req.entry,
            pip_install=req.pip_install,
            discover=req.discover,
            claims=list(req.claims or []),
            k=req.k,
            top_k=req.top_k,
            timeout=req.timeout,
            fetch_data=req.fetch_data,
            job_id=job["id"],
            venvs_dir=_VENVS,
            base_python=VENV_PY,
        )
        update = lambda **kw: _set(job, **kw)            # noqa: E731 — stage updates from the (possibly child) run
        logf = lambda msg: _log(job, msg)                # noqa: E731
        # The heavy work runs isolated by default so a pathological repo can crash its own child, never the
        # API. The supervisor streams the same stage/log events back, so the result + UX are identical.
        if _ISOLATE:
            result = SUP.run_isolated(repo_dir, opts, update=update, log=logf)
        else:
            result = PIPE.verify_repo(repo_dir, opts, update=update, log=logf)
        _set(job, status="done", stage="done", claims=result["claims"], counts=result["counts"],
             n_claims=result["n_claims"], leakage=result["leakage"], run=result["run"],
             receipt=result.get("receipt"), trace=result["trace"], finished=time.time())
        _log(job, "done — %s" % ", ".join("%s:%d" % (k, v) for k, v in result["counts"].items()))
    except SUP.BudgetExceeded as e:
        # The isolated child was killed or died (OOM / timeout / CPU / crash). The job ends cleanly with a
        # specific reason; the API is untouched — that's the whole guarantee.
        _set(job, status="error", stage="exceeded budget", error=str(e), failure_kind=e.kind,
             finished=time.time())
        _log(job, "stopped: %s" % str(e))
        if e.detail and e.detail.strip():
            _log(job, "  detail: %s" % e.detail.strip().splitlines()[-1][:200])
    except Exception as e:  # noqa: BLE001
        _set(job, status="error", stage="error", error="%s: %s" % (type(e).__name__, str(e)[:300]),
             finished=time.time())
        _log(job, "error: %s" % str(e)[:300])
    finally:
        # Always free the tenant's concurrency slot and bill the sandbox-seconds this job actually consumed
        # (the monthly COGS meter), whether it finished, errored, or was killed for exceeding its budget.
        if job.get("_slot"):
            lim = LIM.get_limiter()
            tenant = job.get("_tenant", "anon")
            lim.release_slot(tenant)
            sec = ((job.get("run") or {}).get("cost") or {}).get("sandbox_seconds") or 0
            lim.record_sandbox_seconds(tenant, sec)


@app.post("/api/verify")
def verify(req: VerifyReq, ident: Identity = Depends(identity)):
    """Admission control lives HERE — before a sandbox is ever provisioned (PRICING.md). Fail closed: meter the
    expensive thing (deep-verify scans, sandbox-minutes), gate paid features, keep discovery generous."""
    lim = LIM.get_limiter()
    tier = ident.tier

    # 1) burst rate on the submit path — the actual cost/abuse vector (polling GETs are cheap + exempt).
    d = lim.check_api_rate(ident.tenant, tier)
    if not d.ok:
        raise HTTPException(d.status, d.reason, headers={"Retry-After": str(d.retry_after or 1)})

    # 2) hosted service never accepts a local-path repo (would leak the host's own files/secrets into a run).
    if _FORCE_E2B and not _is_remote_repo(req.repo):
        raise HTTPException(400, "the hosted service verifies GitHub repos only (owner/name or a github URL)")

    # 3) clamp knobs (k, wall, top-K) to the tier and HARD-gate paid features (private repos, external fetch).
    #    This precedes the ownership check so a free user gets the clear "upgrade for private repos" (402)
    #    rather than a bare 403.
    clamped, dc = LIM.clamp_request(tier, req.model_dump())
    if not dc.ok:
        raise HTTPException(dc.status, dc.reason)

    # 4) a private-repo installation (paid tiers only, past the gate above) may be used only by the tenant it
    #    was connected to (cross-tenant IDOR guard).
    if req.installation_id and not _installation_ok(req.installation_id, ident.tenant, ident.unmetered):
        raise HTTPException(403, "that GitHub installation is not connected to your account")
    req.k = int(clamped.get("k", req.k))
    req.timeout = int(clamped.get("timeout", req.timeout))
    req.top_k = int(clamped.get("top_k", req.top_k))
    req.fetch_data = bool(clamped.get("fetch_data", req.fetch_data))
    # sanitize caller-supplied deps to plain PyPI specs (the tolerant install path) — a request can't smuggle
    # `--index-url http://evil/` or a VCS/URL ref into the installer. The repo's own requirements.txt (read
    # from the cloned source, installed faithfully) is unaffected.
    req.pip_install = LIM.sanitize_pip(req.pip_install) or None
    limit_notes = list(dc.notes)

    # 5) meter deep verifies (daily scan quota + monthly sandbox budget + per-tenant concurrency). A
    #    discovery-only scan draws nothing. At the budget ceiling we keep the funnel open — discovery still
    #    runs, deep is deferred with an honest "upgrade" note — rather than refusing outright.
    slot = False
    if req.deep:
        ds = lim.admit_scan(ident.tenant, tier)
        if not ds.ok:
            if ds.kind in ("concurrency", "api_rate"):
                raise HTTPException(ds.status, ds.reason, headers={"Retry-After": str(ds.retry_after or 10)})
            req.deep = False                # daily / sandbox budget exhausted → discovery-only, fail-open funnel
            req.discover = True
            limit_notes.append(ds.reason)
        else:
            slot = True

    # On a public deployment, never run untrusted code on the host — force the isolated E2B path.
    if _FORCE_E2B:
        req.runner = "e2b"
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "repo": req.repo, "runner": req.runner, "deep": req.deep,
           "status": "queued", "stage": "queued", "created": time.time(), "updated": time.time(),
           "claims": [], "counts": {}, "logs": [], "n_claims": 0, "leakage": [], "error": None,
           "tier": tier.name, "limit_notes": limit_notes, "_tenant": ident.tenant, "_slot": slot}
    if limit_notes:
        for n in limit_notes:
            _log(job, "limit: %s" % n)
    with _LOCK:
        JOBS[job_id] = job
    threading.Thread(target=run_job, args=(job, req), daemon=True).start()
    return {"id": job_id, "tier": tier.name, "deep": req.deep, "limit_notes": limit_notes}


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
        out = {k: v for k, v in job.items() if not k.startswith("_")}   # never leak internal keys (_tenant/_slot)
        if len(out["claims"]) > 500:
            out = dict(out, claims=out["claims"][:500], truncated=len(job["claims"]))
        return out


@app.get("/api/jobs/{job_id}/logs", dependencies=[Depends(require_service_token)])
def get_job_logs(job_id: str):
    """The full, timestamped e2e log for one job as plaintext — easy to read in a browser, `curl`, or tail.
    The same lines stream into the dashboard's live console; this is the raw view (and survives the UI)."""
    with _LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "no such job")
        lines = list(job.get("logs", []))
        header = "# calma verify %s — repo=%s status=%s stage=%s\n" % (
            job_id, job.get("repo"), job.get("status"), job.get("stage"))
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(header + "\n".join(lines) + "\n")


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


@app.get("/connect/github/setup", dependencies=[Depends(require_service_token)])
def github_setup(installation_id: str = "", setup_action: str = "",
                 x_calma_tenant: str | None = Header(default=None)):
    """Step 2: GitHub redirects here after install with the installation_id. Bind it to the connecting tenant
    (the trusted proxy forwards X-Calma-Tenant), then FORWARD to the first-party dashboard (if
    CALMA_DASHBOARD_URL is set) so its UI adopts the install and lists the repos — otherwise land on the local
    SPA. Binding is what lets `_installation_ok` refuse cross-tenant use later. Token-gated: only the
    first-party proxy (which forwards the connecting tenant) may record a binding, so it can't be hijacked to
    rebind someone else's installation. Open in the local flow (token unset)."""
    if installation_id:
        _bind_installation(installation_id, (x_calma_tenant or "").strip(), setup_action)
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
def gh_repos(installation_id: str, ident: Identity = Depends(identity)):
    """The repos this installation granted — listed via a short-lived installation token. Gated: the caller
    may only enumerate an installation bound to their own tenant (cross-tenant private-repo guard)."""
    if not _installation_ok(installation_id, ident.tenant, ident.unmetered):
        raise HTTPException(403, "that GitHub installation is not connected to your account")
    try:
        return GH.list_installation_repos(GH.installation_token_for(installation_id))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@app.get("/api/usage")
def usage(ident: Identity = Depends(identity)):
    """This tenant's live meter state (scans today, sandbox-minutes this month, in-flight, tier ceilings) — so
    the dashboard can show remaining budget and an honest 'upgrade' prompt before the ceiling is hit."""
    return LIM.get_limiter().usage(ident.tenant, ident.tier)


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


# ---- trust layer (features 3 / 12 / 13 / 18) -----------------------------------------------------
def _job_or_404(job_id: str) -> dict:
    with _LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    return job


def _repo_uri(job: dict) -> str:
    repo = job.get("repo") or "repo"
    sha = (job.get("run") or {}).get("commit") or job.get("commit") or ""
    base = repo if repo.startswith(("http", "git+")) else "git+https://github.com/%s" % repo
    return base + ("@" + sha if sha else "")


@app.get("/api/signing-key")
def signing_key():
    """Publish the CURRENT public signing key so anyone can verify a verdict attestation OFFLINE. Public by
    design (verification must not require trusting the API at fetch time)."""
    info = SIGN.public_key_info()
    return info or {"configured": False,
                    "note": "no signing key provisioned — attestations are emitted unsigned but well-formed"}


@app.get("/api/jobs/{job_id}/receipt", dependencies=[Depends(require_service_token)])
def job_receipt(job_id: str):
    """Feature 18 — the reproducibility receipt (canonical, content-addressed) for a completed job."""
    job = _job_or_404(job_id)
    receipt = job.get("receipt")
    if receipt is None:
        raise HTTPException(409, "receipt not available (job not deep-verified / still running)")
    return receipt


@app.get("/api/jobs/{job_id}/attestation", dependencies=[Depends(require_service_token)])
def job_attestation(job_id: str):
    """Feature 3 — a DSSE-signed in-toto verdict Statement per claim (unsigned-but-well-formed if no key). The
    subject is the receipt digest (#18). Also anchors each leaf to the transparency ledger (#12), fail-open."""
    job = _job_or_404(job_id)
    receipt = job.get("receipt")
    if receipt is None:
        raise HTTPException(409, "no receipt to attest (job not deep-verified / still running)")
    uri = _repo_uri(job)
    out = []
    for rec in job.get("claims") or []:
        env = ATT.build_attestation(rec, receipt, uri)
        TLOG.submit(env, "%s#%s" % (job_id, rec.get("id")), ledger=_TLOG)   # best-effort, fail-open
        out.append({"claim_id": rec.get("id"), "verdict": rec.get("verdict"), "envelope": env})
    return {"receipt_sha256": receipt.get("receipt_sha256"), "attestations": out}


@app.get("/api/jobs/{job_id}/inclusion-proof", dependencies=[Depends(require_service_token)])
def job_inclusion_proof(job_id: str):
    """Feature 12 — the transparency-ledger entries anchoring this job's attestations, plus a chain check."""
    _job_or_404(job_id)
    entries = [e for e in _TLOG.entries if str(e.get("verdict_id", "")).startswith(job_id + "#")]
    ok, msg = _TLOG.verify_chain()
    return {"entries": entries, "chain_ok": ok, "chain": msg}


@app.get("/api/badge/{job_id}")
def job_badge(job_id: str):
    """Feature 13 — a shields.io endpoint badge for the job's headline (most-salient) claim. Green ONLY for
    CONFIRMED; every fail-closed verdict renders amber/grey. Public."""
    job = _job_or_404(job_id)
    claims = job.get("claims") or []
    verdict = claims[0].get("verdict") if claims else "DISCOVERED"
    return JSONResponse(BADGE.badge(verdict, label="calma"))


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
