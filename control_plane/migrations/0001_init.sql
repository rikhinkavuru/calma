-- Calma control-plane schema — migration 0001 (initial).
-- Source of truth: ~/calma-strategy/build-plan/CANONICAL-DECISIONS.md §1 (which amends spec-01 §6).
-- Master milestone: P2-M2. Applied by control_plane/migrate.py (idempotent via schema_migrations).
--
-- BYOC INVARIANT: every table below stores HASHES + verdicts + metadata, NEVER raw inputs / artifact
-- bodies / code. Raw data lives in the customer's object store (R2/S3) and never enters Postgres.
-- RLS (tenant_id) is enabled on every tenant-scoped table; the app sets app.tenant_id per request.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS citext;     -- case-insensitive email

-- ============================ identity / tenancy ============================

CREATE TABLE IF NOT EXISTS orgs (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name               TEXT NOT NULL,
  workos_org_id      TEXT UNIQUE,                  -- WorkOS org (SSO/SCIM); null for PLG self-serve
  plan               TEXT NOT NULL DEFAULT 'free', -- free|pro|enterprise
  deployment         TEXT NOT NULL DEFAULT 'cloud' -- cloud|byoc|on-prem (drives provider + residency)
                       CHECK (deployment IN ('cloud','byoc','on-prem')),
  stripe_customer_id TEXT,                          -- billing (CANONICAL §1)
  billing_status     TEXT NOT NULL DEFAULT 'active',
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tenants (               -- the ISOLATION unit; an org has >= 1 tenant
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id        UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  slug          TEXT NOT NULL,
  object_bucket TEXT NOT NULL DEFAULT '',           -- per-tenant bucket/prefix root (R2/S3)
  kms_key_arn   TEXT,                                -- per-tenant CMK; null = shared default key
  quota         JSONB NOT NULL DEFAULT '{}'::jsonb,  -- concurrency / rate / monthly-units overrides
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, slug)
);
CREATE INDEX IF NOT EXISTS ix_tenants_org ON tenants(org_id);

CREATE TABLE IF NOT EXISTS users (                  -- CANONICAL §1: NO role column (see memberships)
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id         UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  workos_user_id TEXT UNIQUE,
  email          CITEXT NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, email)
);

CREATE TABLE IF NOT EXISTS memberships (            -- CANONICAL §1: multi-org users w/ per-org roles
  org_id  UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role    TEXT NOT NULL DEFAULT 'member'            -- owner|admin|member (org RBAC)
            CHECK (role IN ('owner','admin','member')),
  PRIMARY KEY (org_id, user_id)
);

CREATE TABLE IF NOT EXISTS api_keys (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  prefix       TEXT NOT NULL,                        -- shown in UI (e.g. "calma_sk_live_3f2a")
  key_id       TEXT NOT NULL,                        -- public 8-char id (calma_sk_live_<keyid8>_<secret43>)
  key_hash     BYTEA NOT NULL,                       -- SHA-256(secret), NOT argon2id (CANONICAL §1)
  environment  TEXT NOT NULL DEFAULT 'live'          -- live|test
                 CHECK (environment IN ('live','test')),
  scopes       TEXT[] NOT NULL DEFAULT '{verify:write,verify:read}',
  last_used_at TIMESTAMPTZ,
  expires_at   TIMESTAMPTZ,
  revoked_at   TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_api_keys_key_id ON api_keys(key_id);
CREATE INDEX IF NOT EXISTS ix_api_keys_tenant ON api_keys(tenant_id) WHERE revoked_at IS NULL;

-- ============================ recipe / template registry ============================

CREATE TABLE IF NOT EXISTS recipes (                -- the SOTA recipes, versioned + content-pinned
  id                TEXT NOT NULL,                  -- "trading.sharpe"
  version           TEXT NOT NULL,                  -- semver of the recipe logic
  family            TEXT NOT NULL,                  -- trading|classification|quant-risk|...
  metric            TEXT NOT NULL,                  -- "sharpe"
  tolerance         JSONB NOT NULL DEFAULT '{}'::jsonb,
  validity_families TEXT[] NOT NULL DEFAULT '{}',
  spec_sha256       BYTEA NOT NULL,
  PRIMARY KEY (id, version)
);

CREATE TABLE IF NOT EXISTS templates (              -- runtime snapshots (warm-pool keys)
  id           TEXT PRIMARY KEY,                    -- "python-3.11" | "r-4.4" | ...
  language     TEXT NOT NULL,
  image_digest TEXT NOT NULL,                       -- sha256-pinned base image (T7)
  provider     TEXT NOT NULL,                       -- e2b|k8s-sandbox|northflank|local-docker
  sbom_uri     TEXT,
  signature    BYTEA,                               -- cosign signature of the image
  warm_min     INT NOT NULL DEFAULT 0,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================ jobs / runs / verdicts ============================

CREATE TABLE IF NOT EXISTS jobs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- == public verification_id + billing key
  tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  api_key_id      UUID REFERENCES api_keys(id),
  idempotency_key TEXT,                              -- client-supplied; dedupe anchor
  recipe_id       TEXT NOT NULL,
  recipe_version  TEXT NOT NULL,
  template_id     TEXT NOT NULL REFERENCES templates(id),
  trust           TEXT NOT NULL DEFAULT 'untrusted-third-party'
                    CHECK (trust IN ('own-code','untrusted-third-party')),
  status          TEXT NOT NULL DEFAULT 'QUEUED',    -- §4.2 state machine
  priority        TEXT NOT NULL DEFAULT 'interactive',
  bundle_sha256   BYTEA NOT NULL,                    -- hash of the code bundle (no code in PG)
  contract_sha256 BYTEA NOT NULL,
  data_ref_digest BYTEA NOT NULL,                    -- hash over sorted(data_refs.sha256) (no data in PG)
  limits          JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (recipe_id, recipe_version) REFERENCES recipes(id, version)
);
-- one job = one billable unit; a retried submit with the same key returns the existing job (no double-bill)
CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_idem ON jobs(tenant_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_jobs_tenant_created ON jobs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status)
  WHERE status NOT IN ('COMPLETED','REFUSED','FAILED','TIMED_OUT','DEDUPED');

CREATE TABLE IF NOT EXISTS runs (                   -- one row per execution attempt (INTERNAL only)
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id             UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  tenant_id          UUID NOT NULL REFERENCES tenants(id),
  attempt            INT NOT NULL DEFAULT 1,
  provider           TEXT NOT NULL,                  -- which driver actually ran it
  isolation_tier     TEXT NOT NULL,                  -- e2b-firecracker | container | bwrap-verified | ...
  tier_verified      BOOL NOT NULL DEFAULT false,
  phase              TEXT NOT NULL,                  -- STAGING|PROBING|RUNNING|RUN_DONE|...
  run_exit_status    INT,
  exit_code          INT,
  killed             BOOL,
  network_run        TEXT,                           -- "off" only when tier_verified
  determinism_mode   TEXT,                           -- controlled-to-bit|measured-band|uncontrolled
  determinism_digest BYTEA,                          -- the reproducibility anchor (execprovider §5-G)
  resource_usage     JSONB,                          -- cpu_seconds, peak_rss_mb, wall_seconds
  doctor             JSONB NOT NULL DEFAULT '{}'::jsonb,   -- the positive-control result (slimmed)
  stdout_tail        TEXT,                           -- bounded; NOT raw data (capped tail)
  stderr_tail        TEXT,
  lease_expires_at   TIMESTAMPTZ,                    -- crash-recovery lease
  started_at         TIMESTAMPTZ,
  finished_at        TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_runs_job ON runs(job_id);
CREATE INDEX IF NOT EXISTS ix_runs_lease ON runs(lease_expires_at) WHERE finished_at IS NULL;

CREATE TABLE IF NOT EXISTS verdicts (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id                  UUID NOT NULL UNIQUE REFERENCES runs(id) ON DELETE CASCADE,
  job_id                  UUID NOT NULL REFERENCES jobs(id),
  tenant_id               UUID NOT NULL REFERENCES tenants(id),
  -- the INTERNAL claim enum (store INCONCLUSIVE, never the display "CAN'T-CONFIRM") — CANONICAL §3
  verdict                 TEXT NOT NULL CHECK (verdict IN (
                            'CONFIRMED','CONFIRMED-WITH-CAVEATS','REFUTED','INVALIDATED',
                            'FLAG_FOR_DECLARATION','INCONCLUSIVE')),
  repo_verdict            TEXT,                       -- computed rollup; may be MIXED|CONTESTED
  claimed_value           NUMERIC,
  recomputed_value        NUMERIC,
  abs_diff                NUMERIC,
  within_tolerance        BOOL,
  validity_results        JSONB NOT NULL DEFAULT '{}'::jsonb,  -- per-family pass/fail
  proof_uri               TEXT,                       -- object-store ref to the signed .proof bundle
  proof_sha256            BYTEA,
  signature               BYTEA,                      -- Ed25519/DSSE over the verdict (host-side)
  rekor_log_index         BIGINT,                     -- transparency-log index; null until LOGGED
  rekor_checkpoint_sha256 BYTEA,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_verdicts_tenant_created ON verdicts(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_verdicts_job ON verdicts(job_id);

-- ============================ billing / integrations ============================

CREATE TABLE IF NOT EXISTS usage_meters (           -- Stripe meter cache (CANONICAL §1)
  org_id         UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  period_start   TIMESTAMPTZ NOT NULL,
  period_end     TIMESTAMPTZ NOT NULL,
  units          BIGINT NOT NULL DEFAULT 0,
  last_synced_at TIMESTAMPTZ,
  PRIMARY KEY (org_id, period_start)
);

CREATE TABLE IF NOT EXISTS github_installs (        -- token columns TEXT (the ~520-char ghs_ format)
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  gh_installation_id BIGINT NOT NULL,
  gh_account_login TEXT,
  app_slug        TEXT,
  suspended       BOOL NOT NULL DEFAULT false,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (gh_installation_id)
);

-- ============================ audit (hash-chained, immutable) ============================

CREATE TABLE IF NOT EXISTS audit_log (              -- ONE table (kill the name audit_events) — CANONICAL §1
  id              BIGSERIAL PRIMARY KEY,
  tenant_id       UUID NOT NULL REFERENCES tenants(id),
  actor_type      TEXT NOT NULL,                     -- user|api_key|system|reviewer
  actor_id        UUID,
  action          TEXT NOT NULL,                     -- job.submit|verdict.sign|key.revoke|reviewer.signoff|...
  resource_type   TEXT NOT NULL,
  resource_id     UUID,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,   -- hashes + ids only, NEVER raw data
  prev_hash       BYTEA,                              -- hash-chained for tamper-evidence
  entry_hash      BYTEA NOT NULL,
  rekor_log_index BIGINT,                             -- transparency-log index (CANONICAL §1)
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_audit_tenant_created ON audit_log(tenant_id, created_at DESC);

-- ============================ Row-Level Security (tenant isolation) ============================
-- Every tenant-scoped table: enable RLS + a policy keyed on the per-request app.tenant_id GUC. The
-- control plane sets `SET LOCAL app.tenant_id = '<uuid>'` per transaction; cross-tenant reads then
-- return zero rows. (The owning `postgres` role bypasses RLS for migrations/admin — by design.)
DO $$
DECLARE t TEXT;
BEGIN
  -- `tenants` is keyed on its OWN id (it has no tenant_id column).
  ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS tenant_isolation ON tenants;
  CREATE POLICY tenant_isolation ON tenants
    USING (id = current_setting('app.tenant_id', true)::uuid);
  -- the child tables all carry a tenant_id column.
  FOREACH t IN ARRAY ARRAY['api_keys','jobs','runs','verdicts','audit_log'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    EXECUTE format($p$CREATE POLICY tenant_isolation ON %I
                      USING (tenant_id = current_setting('app.tenant_id', true)::uuid)$p$, t);
  END LOOP;
END $$;

COMMIT;
