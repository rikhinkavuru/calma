"""control_plane.api.repo — all DB access, tenant-scoped. Every tenant-bound query carries an explicit
`WHERE tenant_id = %s` (the real guard — the owner role bypasses RLS); we ALSO set app.tenant_id per
connection so the RLS policies hold if/when we connect as a restricted role. psycopg3 + dict rows."""
from __future__ import annotations

import hashlib
import json

from psycopg.rows import dict_row

from . import config


def connect():
    return config.connect()           # autocommit psycopg connection from DATABASE_URL


def set_tenant(conn, tenant_id):
    conn.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))


def _one(conn, sql, params=()):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def _all(conn, sql, params=()):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


# ---------------- auth ----------------
# These two resolve the key/tenant BEFORE the request tenant is known, so under the NOBYPASSRLS app role
# (calma_app) they must go through the SECURITY DEFINER lookups (0006) — a direct SELECT would be RLS-empty
# and break login. Functionally identical under the bypassing postgres role.
def get_api_key(conn, key_id):
    return _one(conn, "SELECT * FROM calma_lookup_api_key(%s)", (key_id,))


def touch_api_key(conn, api_key_id):
    conn.execute("UPDATE api_keys SET last_used_at = now() WHERE id = %s", (api_key_id,))


def get_tenant(conn, tenant_id):
    return _one(conn, "SELECT * FROM calma_lookup_tenant(%s)", (tenant_id,))


# ---------------- provisioning (first-party / WorkOS) ----------------
def provision_tenant(conn, *, workos_user_id, email, org_name, workos_org_id=None):
    """Find-or-create the org/tenant/user for a WorkOS user. Idempotent on workos_user_id."""
    u = _one(conn, "SELECT id, org_id FROM users WHERE workos_user_id=%s", (workos_user_id,))
    if u:
        t = _one(conn, "SELECT id FROM tenants WHERE org_id=%s ORDER BY created_at LIMIT 1",
                 (u["org_id"],))
        return {"org_id": str(u["org_id"]), "tenant_id": str(t["id"])}
    org = _one(conn, "INSERT INTO orgs (name, workos_org_id) VALUES (%s,%s) RETURNING id",
               (org_name, workos_org_id))
    tenant = _one(conn, "INSERT INTO tenants (org_id, slug, object_bucket) VALUES (%s,'default','calma') "
                        "RETURNING id", (org["id"],))
    user = _one(conn, "INSERT INTO users (org_id, workos_user_id, email) VALUES (%s,%s,%s) RETURNING id",
                (org["id"], workos_user_id, email))
    conn.execute("INSERT INTO memberships (org_id, user_id, role) VALUES (%s,%s,'owner')",
                 (org["id"], user["id"]))
    return {"org_id": str(org["id"]), "tenant_id": str(tenant["id"])}


# ---------------- api-key admin (dashboard) ----------------
def list_api_keys(conn, tenant_id):
    return _all(conn,
        "SELECT id, prefix, key_id, environment, scopes, last_used_at, created_at, revoked_at "
        "FROM api_keys WHERE tenant_id=%s ORDER BY created_at DESC", (tenant_id,))


def insert_api_key(conn, tenant_id, prefix, key_id, key_hash, environment):
    return _one(conn,
        "INSERT INTO api_keys (tenant_id, prefix, key_id, key_hash, environment) "
        "VALUES (%s,%s,%s,%s,%s) RETURNING id, created_at",
        (tenant_id, prefix, key_id, key_hash, environment))


def revoke_api_key(conn, tenant_id, key_id_uuid):
    with conn.cursor() as cur:
        cur.execute("UPDATE api_keys SET revoked_at=now() WHERE id=%s AND tenant_id=%s AND revoked_at IS NULL",
                    (key_id_uuid, tenant_id))
        return cur.rowcount


# ---------------- registry guards ----------------
def recipe_exists(conn, recipe_id, version):
    return _one(conn, "SELECT 1 FROM recipes WHERE id=%s AND version=%s", (recipe_id, version)) is not None


def template_exists(conn, template_id):
    return _one(conn, "SELECT 1 FROM templates WHERE id=%s", (template_id,)) is not None


# ---------------- jobs ----------------
def find_job_by_idem(conn, tenant_id, idem_key):
    if not idem_key:
        return None
    return _one(conn, "SELECT * FROM jobs WHERE tenant_id=%s AND idempotency_key=%s",
                (tenant_id, idem_key))


# Admission control (kill-risk K6). "Active" = non-terminal AND created within the window, so a crashed row
# (stuck non-terminal) ages out instead of wedging the count. tenant_id=None counts ACROSS all tenants — the
# owner role bypasses RLS, so this global ceiling is real, not per-tenant.
_TERMINAL = ("COMPLETED", "REFUSED", "FAILED", "TIMED_OUT", "DEDUPED")


def count_active_jobs(conn, tenant_id=None, since_seconds=600):
    if tenant_id is None:
        # the GLOBAL ceiling must see all tenants; under the NOBYPASSRLS app role a direct count is
        # RLS-filtered to the current tenant, so go through the SECURITY DEFINER fn (0006).
        cur = conn.execute("SELECT calma_active_job_count(%s)", (since_seconds,))
        return cur.fetchone()[0]
    # per-tenant: the explicit WHERE + RLS (app.tenant_id set) both scope to this tenant.
    # `status <> ALL(%s)` (array) — psycopg3 can't expand a tuple into IN; `%s::int * interval` pins the type.
    cur = conn.execute(
        "SELECT count(*) FROM jobs WHERE status <> ALL(%s) "
        "AND created_at > now() - (%s::int * interval '1 second') AND tenant_id = %s",
        (list(_TERMINAL), since_seconds, tenant_id))
    return cur.fetchone()[0]


_ADMIT_LOCK = 728041  # fixed pg advisory-lock key serializing submit admission (count -> insert)


def tenant_ids_for_org(conn, org_id):
    cur = conn.execute("SELECT id FROM tenants WHERE org_id = %s", (org_id,))
    return [str(r[0]) for r in cur.fetchall()]


def delete_org(conn, org_id):
    # FK ON DELETE CASCADE (migration 0002) removes the org's tenants/jobs/runs/verdicts/audit rows.
    conn.execute("DELETE FROM orgs WHERE id = %s", (org_id,))


def admission_lock(conn):
    conn.execute("SELECT pg_advisory_lock(%s)", (_ADMIT_LOCK,))


def admission_unlock(conn):
    conn.execute("SELECT pg_advisory_unlock(%s)", (_ADMIT_LOCK,))


def count_recent_creates(conn, tenant_id, since_seconds=60):
    cur = conn.execute(
        "SELECT count(*) FROM jobs WHERE tenant_id = %s "
        "AND created_at > now() - (%s::int * interval '1 second')",
        (tenant_id, since_seconds))
    return cur.fetchone()[0]


def insert_job(conn, *, tenant_id, api_key_id, idem_key, recipe_id, recipe_version, template_id,
               trust, bundle_sha256, contract_sha256, data_ref_digest, limits):
    row = _one(conn,
        "INSERT INTO jobs (tenant_id, api_key_id, idempotency_key, recipe_id, recipe_version, "
        "  template_id, trust, status, bundle_sha256, contract_sha256, data_ref_digest, limits) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,'QUEUED',%s,%s,%s,%s) RETURNING id, status, created_at",
        (tenant_id, api_key_id, idem_key, recipe_id, recipe_version, template_id, trust,
         bundle_sha256, contract_sha256, data_ref_digest, json.dumps(limits)))
    return row


def update_job(conn, tenant_id, job_id, *, status=None, contract_sha256=None):
    sets, params = ["updated_at = now()"], []
    if status is not None:
        sets.append("status = %s"); params.append(status)
    if contract_sha256 is not None:
        sets.append("contract_sha256 = %s"); params.append(contract_sha256)
    params += [job_id, tenant_id]
    conn.execute("UPDATE jobs SET %s WHERE id=%%s AND tenant_id=%%s" % ", ".join(sets), tuple(params))


def get_job(conn, tenant_id, job_id):
    return _one(conn, "SELECT * FROM jobs WHERE id=%s AND tenant_id=%s", (job_id, tenant_id))


def list_jobs(conn, tenant_id, limit, cursor_created=None, cursor_id=None):
    if cursor_created and cursor_id:
        return _all(conn,
            "SELECT * FROM jobs WHERE tenant_id=%s AND (created_at, id) < (%s::timestamptz, %s::uuid) "
            "ORDER BY created_at DESC, id DESC LIMIT %s",
            (tenant_id, cursor_created, cursor_id, limit))
    return _all(conn,
        "SELECT * FROM jobs WHERE tenant_id=%s ORDER BY created_at DESC, id DESC LIMIT %s",
        (tenant_id, limit))


# ---------------- runs / verdicts ----------------
def insert_run(conn, *, job_id, tenant_id, provider, isolation_tier, tier_verified, phase,
               run_exit_status, exit_code, killed, network_run, determinism_mode,
               determinism_digest, resource_usage, doctor, stdout_tail, stderr_tail):
    row = _one(conn,
        "INSERT INTO runs (job_id, tenant_id, provider, isolation_tier, tier_verified, phase, "
        "  run_exit_status, exit_code, killed, network_run, determinism_mode, determinism_digest, "
        "  resource_usage, doctor, stdout_tail, stderr_tail, started_at, finished_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now(), now()) RETURNING id",
        (job_id, tenant_id, provider, isolation_tier, tier_verified, phase, run_exit_status,
         exit_code, killed, network_run, determinism_mode,
         bytes.fromhex(determinism_digest) if determinism_digest else None,
         json.dumps(resource_usage or {}), json.dumps(doctor or {}),
         (stdout_tail or "")[:8000], (stderr_tail or "")[:8000]))
    return row["id"]


def insert_verdict(conn, *, run_id, job_id, tenant_id, verdict, repo_verdict, claimed_value,
                   recomputed_value, abs_diff, within_tolerance, validity_results, proof_uri):
    row = _one(conn,
        "INSERT INTO verdicts (run_id, job_id, tenant_id, verdict, repo_verdict, claimed_value, "
        "  recomputed_value, abs_diff, within_tolerance, validity_results, proof_uri) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (run_id, job_id, tenant_id, verdict, repo_verdict, claimed_value, recomputed_value,
         abs_diff, within_tolerance, json.dumps(validity_results or {}), proof_uri))
    return row["id"]


def get_verdict_for_job(conn, tenant_id, job_id):
    return _one(conn, "SELECT * FROM verdicts WHERE job_id=%s AND tenant_id=%s "
                      "ORDER BY created_at DESC LIMIT 1", (job_id, tenant_id))


def get_latest_run(conn, tenant_id, job_id):
    return _one(conn, "SELECT * FROM runs WHERE job_id=%s AND tenant_id=%s "
                      "ORDER BY attempt DESC, started_at DESC LIMIT 1", (job_id, tenant_id))


# ---------------- audit (hash-chained, tamper-evident) ----------------
def insert_audit(conn, *, tenant_id, actor_type, actor_id, action, resource_type, resource_id,
                 metadata):
    prev = _one(conn, "SELECT entry_hash FROM audit_log WHERE tenant_id=%s "
                      "ORDER BY id DESC LIMIT 1", (tenant_id,))
    prev_hash = prev["entry_hash"] if prev else None
    payload = json.dumps({"tenant": str(tenant_id), "actor_type": actor_type,
                          "actor_id": str(actor_id) if actor_id else None, "action": action,
                          "resource_type": resource_type,
                          "resource_id": str(resource_id) if resource_id else None,
                          "metadata": metadata or {}}, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256((prev_hash or b"") + payload.encode("utf-8")).digest()
    conn.execute(
        "INSERT INTO audit_log (tenant_id, actor_type, actor_id, action, resource_type, "
        "  resource_id, metadata, prev_hash, entry_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (tenant_id, actor_type, actor_id, action, resource_type, resource_id,
         json.dumps(metadata or {}), prev_hash, h))
