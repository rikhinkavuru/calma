# Calma control plane (P2-M2)

The hosted, multi-tenant service around the pure-stdlib engine: the verifications API, the Postgres data
model (CANONICAL §1), object storage (R2/S3), auth, billing, and the transparency log. **Separate from the
engine** — the engine stays dependency-free; this service is allowed third-party deps (kept in `requirements.txt`).

## Layout
```
control_plane/
  migrations/0001_init.sql   the CANONICAL §1 schema (orgs/tenants/users/api_keys/recipes/templates/
                             jobs/runs/verdicts/usage_meters/github_installs/audit_log) + RLS
  db.py                      .env loader + psycopg connection (reads DATABASE_URL)
  migrate.py                 apply migrations/*.sql in order, idempotent (schema_migrations table)
  setup-venv.sh              create ~/.calma/cp-venv and install deps
  requirements.txt           psycopg[binary] (+ fastapi/boto3/stripe/workos as the API lands)
```

## Run
```bash
bash control_plane/setup-venv.sh                          # one-time: ~/.calma/cp-venv + psycopg
~/.calma/cp-venv/bin/python control_plane/migrate.py          # apply pending migrations
~/.calma/cp-venv/bin/python control_plane/migrate.py --status # show applied + table list
```

Secrets come from the gitignored repo-root `.env` (template: `.env.example`). The deployed side uses `vercel env`.

## Supabase connection note (non-obvious — cost us a detour)
The **direct** host `db.<ref>.supabase.co` is IPv6-only / deprecated and does not resolve from many machines.
Use the **session pooler** (IPv4): host `aws-1-us-west-2.pooler.supabase.com`, port **5432** (session mode —
needed for migrations; 6543 is transaction mode), user `postgres.<ref>`. The password's `+` and `/` must be
percent-encoded (`%2B`, `%2F`) in `DATABASE_URL`. This project is in **us-west-2** on the `aws-1` scheme.

## The verifications API
FastAPI app at `control_plane/api/` (resource = `verifications`; public id = `verification_id`). Run it:
```bash
bash control_plane/setup-venv.sh                                      # one-time (psycopg + fastapi + boto3)
~/.calma/cp-venv/bin/python -m control_plane.api.bootstrap init --org "Acme" --slug acme --env test  # mint a key
~/.calma/cp-venv/bin/uvicorn control_plane.api.app:app --reload       # serve on :8000  (docs at /docs)
~/.calma/cp-venv/bin/python -m control_plane.api.tests.test_e2e       # full e2e vs real Supabase+R2+engine
```
Endpoints: `POST /v1/verifications` · `GET /v1/verifications[/{id}[/result|/proof]]` · `POST /v1/uploads`
(presigned R2 PUT) · `GET /healthz`. Auth = `Authorization: Bearer calma_sk_…` → tenant (SHA-256, constant-time).
`Idempotency-Key` dedupes. Errors are RFC-9457 problem+json. The API never reimplements verify — it stages the
bundle into a workdir and runs `calma verify --json` (the whole engine pipeline), then persists run+verdict and
stores artifacts/evidence in R2.

## Status
- ✅ Schema live in Supabase (14 tables, RLS, FK cascade for tenant offboarding, verdict CHECK = CANONICAL §3).
- ✅ Verifications API built + verified **end-to-end (18/18)**: submit → engine → persist → result/proof,
  idempotency, cross-tenant isolation, presigned uploads.
- ⏭️ Next: WorkOS auth (dashboard login), Stripe metering, the P2-M5 dashboard, and hosted E2B (P2-M1, key set).
- 🔭 Known v1 cuts: inline execution (queue/worker = master M1.5); validity_results stores the engine summary
  (full per-family extraction = follow-up); proof = stored evidence JSON (DSSE+Rekor = master M2.5);
  registry seeded with 5 rows (full recipe-catalogue sync = follow-up).
