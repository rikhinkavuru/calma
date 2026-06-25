-- 0007 — templates + recipes are GLOBAL, read-only REFERENCE data (the recipe/template catalog), not
-- tenant-scoped. RLS is on (Supabase default) with no policy = default-deny, which blocks the NOBYPASSRLS
-- app role (calma_app) from the registry lookups it needs at submit (recipe_exists/template_exists).
-- A public-read policy is correct (no tenant data here). Writes still happen via the admin/owner path.
DROP POLICY IF EXISTS reference_read ON templates;
CREATE POLICY reference_read ON templates FOR SELECT USING (true);
DROP POLICY IF EXISTS reference_read ON recipes;
CREATE POLICY reference_read ON recipes FOR SELECT USING (true);
