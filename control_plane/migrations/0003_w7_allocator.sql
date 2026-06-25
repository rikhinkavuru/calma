-- 0003 — W7 allocator workflow (Product B) data model. CANONICAL-DECISIONS §1 + spec 04 §"Data model".
-- BYOC INVARIANT (same as 0001): metadata ONLY — hashes + verdicts + labels, NEVER raw manager data. The
-- proof/evidence/lineage are object-storage refs + content hashes; the raw bytes stay in the BYOC sandbox.
-- The Verification table is RENAMED `manager_verifications` (CANONICAL §1) so it never collides with the core
-- `jobs/runs/verdicts` path; it links to a core job via `run_id`. Org-scoped (an allocator is an org).

-- ============================ allocator entities ============================

CREATE TABLE IF NOT EXISTS managers (              -- a fund/strategy manager an allocator diligences
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id       UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  name         TEXT NOT NULL,
  legal_entity TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, name)
);
CREATE INDEX IF NOT EXISTS ix_managers_org ON managers(org_id);

CREATE TABLE IF NOT EXISTS mandates (              -- manager × strategy × period × declared-contract = the unit
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  manager_id      UUID NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
  strategy        TEXT NOT NULL,
  metric          TEXT NOT NULL,                   -- the headline metric (sharpe / total_return / numerai_corr …)
  period_start    DATE,
  period_end      DATE,
  contract_sha256 TEXT,                            -- the committed verify.yaml hash (the declared scope)
  declared_blocks JSONB NOT NULL DEFAULT '{}'::jsonb,  -- which validity blocks the manager declared (W8b depth)
  connector_ref   TEXT,                            -- local | s3 | sftp | data-room (connectors.py); NOT the data
  created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_mandates_manager ON mandates(manager_id);

CREATE TABLE IF NOT EXISTS manager_verifications (  -- one verification of a mandate (verdict + proof, metadata only)
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  mandate_id           UUID NOT NULL REFERENCES mandates(id) ON DELETE CASCADE,
  run_id               UUID,                       -- links to the core jobs.id (the actual verify run)
  -- the engine verdict (CANONICAL §3, incl. FLAG_FOR_DECLARATION); store the INTERNAL enum, never the display.
  repo_verdict         TEXT CHECK (repo_verdict IN (
                         'CONFIRMED','CONFIRMED-WITH-CAVEATS','REFUTED','INVALIDATED',
                         'FLAG_FOR_DECLARATION','MIXED','INCONCLUSIVE')),
  headline_metric      TEXT,
  claimed_value        NUMERIC,
  recomputed_value     NUMERIC,
  family_scope         JSONB NOT NULL DEFAULT '{}'::jsonb,  -- the per-family status (checked/flagged/…)
  inferred_flags       JSONB NOT NULL DEFAULT '[]'::jsonb,  -- the M-8b.2 FLAG_FOR_DECLARATION findings
  evidence_bundle_sha256 TEXT,                     -- the IDD/ODD evidence bundle hash (W8c)
  proof_bundle_uri     TEXT,                       -- object-storage ref to the proof bundle (proof only)
  input_lineage_sha256 TEXT,                       -- the W8(d) provenance hash, NOT the data
  nav_corroboration    TEXT CHECK (nav_corroboration IN ('matched','mismatch','unavailable')),
  -- the sign-off state machine state (signoff.py); a non-clean verdict blocks IC_APPROVED without a waiver.
  state                TEXT NOT NULL DEFAULT 'SUBMITTED' CHECK (state IN (
                         'SUBMITTED','UNDER_REVIEW','REVIEWER_SIGNED',
                         'IC_APPROVED','IC_REJECTED','RETURNED_TO_MANAGER')),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_mverif_mandate ON manager_verifications(mandate_id);

-- ============================ sign-off (M-7.5) ============================

CREATE TABLE IF NOT EXISTS reviews (               -- an ODD analyst's worked checklist + signature
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  verification_id UUID NOT NULL REFERENCES manager_verifications(id) ON DELETE CASCADE,
  reviewer_id     UUID REFERENCES users(id) ON DELETE SET NULL,
  checklist       JSONB NOT NULL DEFAULT '{}'::jsonb,  -- the §4 ODD-analyst checklist marks
  notes_redacted  TEXT,                            -- analyst notes (no raw data)
  signature_dsse  TEXT,                            -- DSSE/SSHSIG keyed to the reviewer's WorkOS identity
  signed_at       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_reviews_verif ON reviews(verification_id);

CREATE TABLE IF NOT EXISTS sign_offs (             -- the sign-off AUTHORITY (orthogonal to memberships.role)
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  verification_id UUID NOT NULL REFERENCES manager_verifications(id) ON DELETE CASCADE,
  signer_id       UUID REFERENCES users(id) ON DELETE SET NULL,
  role            TEXT NOT NULL CHECK (role IN ('reviewer','ic')),
  action          TEXT NOT NULL,                   -- open_review|reviewer_sign|ic_approve|ic_reject|return_to_manager
  waive_reason    TEXT,                            -- REQUIRED to ic_approve a non-clean verdict (recorded)
  prev_hash       TEXT,                            -- the signoff.py hash-chained, replayable audit event
  entry_hash      TEXT NOT NULL,
  signature_dsse  TEXT,
  signed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_signoffs_verif ON sign_offs(verification_id);

-- NOTE (audit 2026-06-24): these W7 tables are NOT covered by the RLS policy in 0001 — 0001's DO-block
-- enables RLS only on a hard-coded ARRAY['api_keys','jobs','runs','verdicts','audit_log'] (+ tenants), and
-- it predates these tables. They are also org-scoped (managers.org_id), not tenant_id-keyed, so the 0001
-- policy shape does not apply as-is. RLS is currently moot in production (the app connects as the table
-- owner, which BYPASSES RLS — isolation rests on the explicit WHERE in every query), but when these tables
-- are wired to the multi-tenant API they MUST get an org-scoped RLS policy (and ideally a NOBYPASSRLS app
-- role + FORCE ROW LEVEL SECURITY). Until then: the connector/runner only ever writes hashes + verdicts
-- here — raw manager data never reaches these tables (the BYOC invariant).
