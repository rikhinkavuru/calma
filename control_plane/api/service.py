"""control_plane.api.service — the verification orchestration: idempotency → job → execute (inline, via
the engine) → persist run + verdict → audit. Inline execution is the v1 cut; a queue + worker fleet
(master M1.5) slots in behind the same `submit()` later without changing the API surface."""
from __future__ import annotations

import hashlib
import os
import sys

from . import config, engine, errors, repo, storage

# the verified-tier gate, reused from the engine's SINGLE source (no drift — see tiers.py / doc §5-I).
sys.path.insert(0, os.path.join(config.REPO_ROOT, ".claude", "skills", "calma", "scripts"))
import tiers as _tiers  # noqa: E402
VERIFIED = set(_tiers.VERIFIED_TIERS)

CLAIM_ENUM = {"CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "INVALIDATED",
              "FLAG_FOR_DECLARATION", "INCONCLUSIVE"}


def _norm_claim(v):
    if v in CLAIM_ENUM:
        return v
    if v in ("CAN'T-CONFIRM", "CANT-CONFIRM", "CAN’T-CONFIRM"):
        return "INCONCLUSIVE"
    return "INCONCLUSIVE"        # MIXED/CONTESTED/unknown are never a single-claim verdict


def _split_verdict(result):
    metrics = result.get("metrics") or []
    headline = next((m for m in metrics if m.get("headline")), metrics[0] if metrics else None)
    claim_v = _norm_claim((headline or {}).get("verdict") or result.get("verdict"))
    return claim_v, result.get("verdict")     # (claim enum, repo rollup)


def _validity(result):
    return {"metric": result.get("metric"), "reason": result.get("reason"),
            "clean": result.get("clean"), "needs": result.get("needs")}


def _provider_for(tier):
    """The execution backend recorded on the run. Derived from the achieved isolation tier (the engine's
    own stamp) so the row tells the truth about WHERE the code ran — 'e2b' for the hosted microVM, else
    'local'. Falls back to the configured backend when no tier was achieved (stage/parse failures)."""
    t = (tier or "").lower()
    if "e2b" in t or "firecracker" in t:
        return "e2b"
    if config.EXEC_ISOLATION == "e2b" and t in ("", "n/a"):
        return "e2b"
    return "local"


def _admit(conn, tenant):
    """Reject a submit that would exceed the global ceiling, the tenant's concurrency cap, or its creation
    rate — the cost/abuse backstop for running untrusted code (kill-risk K6). Counts are time-bounded in
    Postgres so a crashed run ages out. Soft under burst (count-then-insert, no lock) — it is a safety
    backstop, not a billing-exact gate."""
    tid = tenant["id"]
    quota = tenant["quota"] or {}
    per_tenant = int(quota.get("max_concurrent") or config.MAX_CONCURRENT_PER_TENANT)
    per_min = int(quota.get("max_creates_per_min") or config.MAX_CREATES_PER_MIN)
    if repo.count_active_jobs(conn, since_seconds=config.ACTIVE_WINDOW_S) >= config.MAX_CONCURRENT_GLOBAL:
        raise errors.quota_exceeded("global concurrency ceiling reached; retry shortly", retry_after=10)
    if repo.count_active_jobs(conn, tenant_id=tid, since_seconds=config.ACTIVE_WINDOW_S) >= per_tenant:
        raise errors.quota_exceeded("at most %d concurrent verifications per tenant" % per_tenant, retry_after=10)
    if repo.count_recent_creates(conn, tid, 60) >= per_min:
        raise errors.quota_exceeded("creation rate limit: at most %d verifications/min" % per_min, retry_after=30)


def _maybe_delete_bundle(uri):
    """No-raw-retention: drop the uploaded bundle once the run is done (default; CALMA_RETAIN_BUNDLES to keep)."""
    if config.RETAIN_BUNDLES:
        return
    try:
        storage.delete(uri)
    except Exception:
        pass


def submit(conn, tenant, api_key_id, req, idem_key):
    tid = tenant["id"]
    existing = repo.find_job_by_idem(conn, tid, idem_key)
    if existing:
        # idempotency: same key, different body -> 409 (CANONICAL §2 / spec-01 §8)
        if existing["bundle_sha256"] and req.bundle.sha256 and \
                existing["bundle_sha256"].hex() != req.bundle.sha256.lower():
            raise errors.idempotency_conflict()
        return response_for_job(conn, tenant, existing)   # idempotent replay: no admission, no re-run

    _admit(conn, tenant)

    # Tenant-scope every caller-supplied object key BEFORE touching storage: a bundle/data_ref URI must
    # live under THIS tenant's prefix (t/<id>/...), else a tenant could reference — and have the engine
    # download + recompute over — another tenant's R2 objects (BOLA/IDOR, OWASP API1). The uploads API
    # only ever mints keys under the caller's prefix, so legitimate submits are unaffected.
    if not storage.key_under_tenant(req.bundle.uri, tid):
        raise errors.forbidden("bundle.uri is not under this tenant's storage prefix")
    for d in req.data_refs:
        if not storage.key_under_tenant(d.uri, tid):
            raise errors.forbidden("a data_ref.uri is not under this tenant's storage prefix")

    if not repo.template_exists(conn, req.template_id):
        raise errors.malformed("unknown template_id %r" % req.template_id)
    if not repo.recipe_exists(conn, req.recipe_id, req.recipe_version):
        raise errors.malformed("unknown recipe %s@%s" % (req.recipe_id, req.recipe_version))
    if not storage.exists(req.bundle.uri):
        raise errors.malformed("bundle not found in storage: %s" % req.bundle.uri)
    try:
        bundle_sha = bytes.fromhex(req.bundle.sha256)
    except ValueError:
        raise errors.malformed("bundle.sha256 must be hex")

    data_digest = hashlib.sha256(
        ",".join(sorted(d.sha256 for d in req.data_refs)).encode("utf-8")).digest()
    limits = req.limits.model_dump() if req.limits else {"wall_seconds": config.DEFAULT_WALL_SECONDS}
    limits["wall_seconds"] = min(int(limits.get("wall_seconds") or config.DEFAULT_WALL_SECONDS),
                                 config.MAX_WALL_SECONDS)   # cap requested wall time (cost/DoS)

    job = repo.insert_job(conn, tenant_id=tid, api_key_id=api_key_id, idem_key=idem_key,
                          recipe_id=req.recipe_id, recipe_version=req.recipe_version,
                          template_id=req.template_id, trust=req.trust, bundle_sha256=bundle_sha,
                          contract_sha256=bundle_sha, data_ref_digest=data_digest, limits=limits)
    job_id = str(job["id"])
    repo.insert_audit(conn, tenant_id=tid, actor_type="api_key", actor_id=api_key_id,
                      action="job.submit", resource_type="job", resource_id=job["id"],
                      metadata={"recipe": req.recipe_id, "bundle_sha256": req.bundle.sha256})

    _execute(conn, tenant, job_id, req, limits)
    return response_for_job(conn, tenant, repo.get_job(conn, tid, job_id))


def _execute(conn, tenant, job_id, req, limits):
    tid = tenant["id"]
    try:
        work = engine.prepare_workdir(tid, req.bundle.uri, req.data_refs)
    except Exception as e:
        repo.update_job(conn, tid, job_id, status="FAILED")
        repo.insert_audit(conn, tenant_id=tid, actor_type="system", actor_id=None,
                          action="job.stage_failed", resource_type="job", resource_id=job_id,
                          metadata={"error": str(e)[:200]})
        _maybe_delete_bundle(req.bundle.uri)
        return
    try:
        csha = engine.contract_sha256_hex(work)
        if csha:
            repo.update_job(conn, tid, job_id, contract_sha256=bytes.fromhex(csha))
        result, out, err, rc = engine.run_verify(work, req.trust, limits.get("wall_seconds", 120))

        # result is None  -> engine printed no parseable JSON.
        # result.ok False -> engine's explicit error envelope ({"ok": false, "error": ...}), e.g. an
        #   uncaught exception in the verify pipeline. Both are FAILED runs, NOT a verdict-less COMPLETED
        #   (which would surface to the client as a blank "successful" verification).
        if result is None or result.get("ok") is False:
            err_msg = (result or {}).get("error") or "engine produced no parseable verdict"
            repo.insert_run(conn, job_id=job_id, tenant_id=tid, provider=_provider_for(None),
                            isolation_tier="n/a",
                            tier_verified=False, phase="FAILED", run_exit_status=rc, exit_code=rc,
                            killed=False, network_run="n/a", determinism_mode="uncontrolled",
                            determinism_digest="", resource_usage={}, doctor={}, stdout_tail=out,
                            stderr_tail=err)
            repo.insert_audit(conn, tenant_id=tid, actor_type="system", actor_id=None,
                              action="job.run_failed", resource_type="job", resource_id=job_id,
                              metadata={"error": str(err_msg)[:200]})
            repo.update_job(conn, tid, job_id, status="FAILED")
            return

        gate_exit = int(result.get("gate_exit") or 0)
        refused, killed = gate_exit == 3, gate_exit == 4
        tier = result.get("isolation_tier") or "n/a"
        det = result.get("determinism_mode") or "uncontrolled"
        status = "REFUSED" if refused else "TIMED_OUT" if killed else "COMPLETED"

        run_id = str(repo.insert_run(
            conn, job_id=job_id, tenant_id=tid, provider=_provider_for(tier), isolation_tier=tier,
            tier_verified=tier in VERIFIED, phase="REFUSED" if refused else "RUN_DONE",
            run_exit_status=gate_exit, exit_code=gate_exit, killed=killed,
            network_run="off" if tier in VERIFIED else "host-default", determinism_mode=det,
            determinism_digest="", resource_usage={}, doctor={}, stdout_tail=out, stderr_tail=err))

        # A COMPLETED run MUST carry a verdict; a verdict-less "completed" is a silent engine failure
        # (e.g. recompute could not bind the artifact). Demote it to FAILED rather than store a blank row.
        if status == "COMPLETED" and not result.get("verdict"):
            status = "FAILED"
        if status == "COMPLETED":
            _manifest, proof_key = engine.collect_and_store(work, tid, job_id, run_id, result)
            claim_v, repo_v = _split_verdict(result)
            claimed, recomputed = result.get("claimed"), result.get("recomputed")
            absd = (abs(claimed - recomputed)
                    if isinstance(claimed, (int, float)) and isinstance(recomputed, (int, float))
                    else None)
            repo.insert_verdict(conn, run_id=run_id, job_id=job_id, tenant_id=tid, verdict=claim_v,
                                repo_verdict=repo_v, claimed_value=claimed, recomputed_value=recomputed,
                                abs_diff=absd,
                                within_tolerance=claim_v in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS"),
                                validity_results=_validity(result), proof_uri=proof_key)
            repo.insert_audit(conn, tenant_id=tid, actor_type="system", actor_id=None,
                              action="verdict.record", resource_type="job", resource_id=job_id,
                              metadata={"verdict": claim_v, "repo_verdict": repo_v})
        repo.update_job(conn, tid, job_id, status=status)
    finally:
        engine.cleanup(work)
        _maybe_delete_bundle(req.bundle.uri)   # raw input gone once the run is done (no-raw-retention)


def response_for_job(conn, tenant, job):
    vid = str(job["id"])
    resp = {
        "verification_id": vid,
        "status": job["status"],
        "recipe": {"id": job["recipe_id"], "version": job["recipe_version"]},
        "created_at": job["created_at"].isoformat(),
        "links": {"self": "/v1/verifications/%s" % vid,
                  "result": "/v1/verifications/%s/result" % vid,
                  "proof": "/v1/verifications/%s/proof" % vid},
    }
    v = repo.get_verdict_for_job(conn, tenant["id"], vid)
    if v:
        vr = v["validity_results"] or {}
        resp["verdict"] = v["verdict"]
        resp["repo_verdict"] = v["repo_verdict"]
        resp["reason"] = vr.get("reason")
        if vr.get("metric") is not None and v["claimed_value"] is not None:
            resp["claim"] = {"metric": vr.get("metric"), "value": float(v["claimed_value"])}
        resp["recomputed"] = {
            "value": float(v["recomputed_value"]) if v["recomputed_value"] is not None else None,
            "abs_diff": float(v["abs_diff"]) if v["abs_diff"] is not None else None,
            "within_tolerance": v["within_tolerance"]}
        resp["validity"] = vr
        resp["proof"] = {"uri": v["proof_uri"]} if v["proof_uri"] else None
        run = repo.get_latest_run(conn, tenant["id"], vid)
        if run:
            resp["execution"] = {"isolation_tier": run["isolation_tier"],
                                 "tier_verified": run["tier_verified"],
                                 "network_run": run["network_run"],
                                 "determinism_mode": run["determinism_mode"]}
    return resp
