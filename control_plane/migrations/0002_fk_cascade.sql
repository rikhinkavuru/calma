-- migration 0002 — make the secondary tenant_id / job_id FKs ON DELETE CASCADE (and api_key_id SET NULL),
-- so deleting a tenant/org cleans up its runs/verdicts/audit in one statement (tenant offboarding + GDPR
-- deletion, CANONICAL §5). 0001's primary parent chain already cascaded jobs<-tenant and runs<-jobs; these
-- redundant scoping FKs were the holdouts. Found by the API e2e test's cleanup step.

BEGIN;

ALTER TABLE runs
  DROP CONSTRAINT IF EXISTS runs_tenant_id_fkey,
  ADD  CONSTRAINT runs_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;

ALTER TABLE verdicts
  DROP CONSTRAINT IF EXISTS verdicts_tenant_id_fkey,
  ADD  CONSTRAINT verdicts_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  DROP CONSTRAINT IF EXISTS verdicts_job_id_fkey,
  ADD  CONSTRAINT verdicts_job_id_fkey FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE;

ALTER TABLE audit_log
  DROP CONSTRAINT IF EXISTS audit_log_tenant_id_fkey,
  ADD  CONSTRAINT audit_log_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;

-- a deleted API key should unlink (not delete) its historical jobs.
ALTER TABLE jobs
  DROP CONSTRAINT IF EXISTS jobs_api_key_id_fkey,
  ADD  CONSTRAINT jobs_api_key_id_fkey FOREIGN KEY (api_key_id) REFERENCES api_keys(id) ON DELETE SET NULL;

COMMIT;
