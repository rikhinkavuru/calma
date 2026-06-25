-- 0006 — SECURITY DEFINER helpers so the NOBYPASSRLS app role (calma_app, 0005) can do the THREE operations
-- that legitimately must see across tenants: (1) AUTH bootstrap — resolve an API key / tenant BEFORE the
-- request's tenant is known (RLS would otherwise return zero rows and break login); (2) the GLOBAL
-- concurrency ceiling count. These run as the definer (the bypassing owner), so calma_app calls them safely.
-- Additive + idempotent; a no-op for the current postgres connection (it already bypasses RLS).

CREATE OR REPLACE FUNCTION calma_lookup_api_key(p_key_id text)
  RETURNS SETOF api_keys LANGUAGE sql SECURITY DEFINER SET search_path = public STABLE AS $$
    SELECT * FROM api_keys WHERE key_id = p_key_id
$$;

CREATE OR REPLACE FUNCTION calma_lookup_tenant(p_id uuid)
  RETURNS SETOF tenants LANGUAGE sql SECURITY DEFINER SET search_path = public STABLE AS $$
    SELECT * FROM tenants WHERE id = p_id
$$;

CREATE OR REPLACE FUNCTION calma_active_job_count(p_since_seconds int)
  RETURNS bigint LANGUAGE sql SECURITY DEFINER SET search_path = public STABLE AS $$
    SELECT count(*) FROM jobs
    WHERE status <> ALL (ARRAY['COMPLETED','REFUSED','FAILED','TIMED_OUT','DEDUPED'])
      AND created_at > now() - (p_since_seconds * interval '1 second')
$$;

GRANT EXECUTE ON FUNCTION calma_lookup_api_key(text)  TO calma_app;
GRANT EXECUTE ON FUNCTION calma_lookup_tenant(uuid)   TO calma_app;
GRANT EXECUTE ON FUNCTION calma_active_job_count(int) TO calma_app;
