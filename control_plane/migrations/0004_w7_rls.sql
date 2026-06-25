-- 0004 — RLS on the W7 allocator tables (D3-04). Closes the gap noted in 0003: the 0001 DO-block only
-- covers core tables (api_keys/jobs/runs/verdicts/audit_log/tenants); the W7 tables shipped unprotected.
--
-- The W7 tables are ORG-scoped (an allocator is an org), so these policies key on a per-request
-- `app.org_id` GUC (NOT app.tenant_id). The W7 control-plane API, when built, MUST
-- `SET LOCAL app.org_id = '<uuid>'` per transaction (mirroring how the core path sets app.tenant_id).
-- Child tables derive the org through their FK chain (managers.org_id is the root).
--
-- IMPORTANT: like 0001, this only BITES when the app connects as a NOBYPASSRLS role (see 0005). As the
-- table owner it is bypassed (defense-in-depth). FORCE is included so that once 0005 lands the owner is
-- also subject. Safe to apply now (the W7 tables are empty + not yet served by any live API endpoint);
-- sequence it with the W7 launch so a query missing `app.org_id` doesn't silently return zero rows.

DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['managers','mandates','manager_verifications','reviews','sign_offs'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS org_isolation ON %I', t);
  END LOOP;
END $$;

-- managers: org_id is direct.
CREATE POLICY org_isolation ON managers
  USING (org_id = current_setting('app.org_id', true)::uuid)
  WITH CHECK (org_id = current_setting('app.org_id', true)::uuid);

-- mandates -> managers
CREATE POLICY org_isolation ON mandates
  USING (manager_id IN (SELECT id FROM managers
                        WHERE org_id = current_setting('app.org_id', true)::uuid))
  WITH CHECK (manager_id IN (SELECT id FROM managers
                             WHERE org_id = current_setting('app.org_id', true)::uuid));

-- manager_verifications -> mandates -> managers
CREATE POLICY org_isolation ON manager_verifications
  USING (mandate_id IN (SELECT m.id FROM mandates m JOIN managers g ON g.id = m.manager_id
                        WHERE g.org_id = current_setting('app.org_id', true)::uuid))
  WITH CHECK (mandate_id IN (SELECT m.id FROM mandates m JOIN managers g ON g.id = m.manager_id
                             WHERE g.org_id = current_setting('app.org_id', true)::uuid));

-- reviews / sign_offs -> manager_verifications -> mandates -> managers
CREATE POLICY org_isolation ON reviews
  USING (verification_id IN (SELECT mv.id FROM manager_verifications mv
                             JOIN mandates m ON m.id = mv.mandate_id
                             JOIN managers g ON g.id = m.manager_id
                             WHERE g.org_id = current_setting('app.org_id', true)::uuid))
  WITH CHECK (verification_id IN (SELECT mv.id FROM manager_verifications mv
                                  JOIN mandates m ON m.id = mv.mandate_id
                                  JOIN managers g ON g.id = m.manager_id
                                  WHERE g.org_id = current_setting('app.org_id', true)::uuid));

CREATE POLICY org_isolation ON sign_offs
  USING (verification_id IN (SELECT mv.id FROM manager_verifications mv
                             JOIN mandates m ON m.id = mv.mandate_id
                             JOIN managers g ON g.id = m.manager_id
                             WHERE g.org_id = current_setting('app.org_id', true)::uuid))
  WITH CHECK (verification_id IN (SELECT mv.id FROM manager_verifications mv
                                  JOIN mandates m ON m.id = mv.mandate_id
                                  JOIN managers g ON g.id = m.manager_id
                                  WHERE g.org_id = current_setting('app.org_id', true)::uuid));
