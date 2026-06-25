-- 0005 — make RLS a REAL second wall (D3-03 / ROOT). DRAFT: applying this is founder+creds-gated because
-- it changes which DB role the app connects as (a new password + a DATABASE_URL swap), so it is NOT applied
-- by the offline test path. Today the control plane connects as the table OWNER, which BYPASSES RLS — tenant
-- isolation rests entirely on the explicit `WHERE tenant_id = %s` in every query. 2026 multi-tenant SOTA:
-- the moment a bypass role is the app role, RLS is decorative. This migration creates a NOBYPASSRLS app role
-- so a forgotten WHERE becomes an empty result set instead of a cross-tenant leak.
--
-- TO APPLY (founder):
--   1. Pick a strong password; create the role (below) with it.
--   2. Update DATABASE_URL (Vercel calma-api env) to connect as `calma_app` instead of the owner.
--   3. Confirm the per-request tenant GUC is transaction-scoped (repo.set_tenant → SET LOCAL app.tenant_id
--      inside a txn; db.py already clears it on connection return). Add the W7 `app.org_id` once W7 ships.
--   4. Run the control-plane e2e + the cross-tenant isolation test as `calma_app` (must return zero rows
--      cross-tenant even with the WHERE removed) before flipping prod.

-- CREATE ROLE calma_app LOGIN NOBYPASSRLS PASSWORD '<SET-A-STRONG-PASSWORD>';
-- GRANT USAGE ON SCHEMA public TO calma_app;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO calma_app;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO calma_app;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO calma_app;

-- FORCE RLS on the core tenant-scoped tables so the policy applies even to a privileged connection, and add
-- WITH CHECK so a cross-tenant INSERT/UPDATE is rejected (0001 set USING only). Idempotent.
DO $$
DECLARE t TEXT;
BEGIN
  ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
  FOREACH t IN ARRAY ARRAY['api_keys','jobs','runs','verdicts','audit_log'] LOOP
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation_chk ON %I', t);
    EXECUTE format($p$CREATE POLICY tenant_isolation_chk ON %I
                      FOR ALL
                      USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
                      WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)$p$, t);
  END LOOP;
END $$;
