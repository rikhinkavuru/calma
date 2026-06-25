// Server-side client for the Calma verifications API (FastAPI). The dashboard is a trusted FIRST PARTY:
// it authenticates with the shared service token + the session's tenant id (never a per-tenant API key).
// Used only from server components / server actions — the service token never reaches the browser.
import "server-only";

const API = process.env.CALMA_API_URL || "http://localhost:8000";
const SVC = process.env.CALMA_SERVICE_TOKEN || "";

async function call(path: string, tenantId: string, init?: RequestInit) {
  const res = await fetch(API + path, {
    ...init,
    headers: {
      "X-Calma-Service-Token": SVC,
      "X-Calma-Tenant-Id": tenantId,
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Calma API ${res.status} on ${path}: ${body.slice(0, 300)}`);
  }
  return res.json();
}

export type Verification = {
  verification_id: string;
  status: string;
  recipe: { id: string; version: string };
  created_at: string;
  verdict?: string;
  repo_verdict?: string;
  reason?: string;
  claim?: { metric: string; value: number };
  recomputed?: { value?: number; abs_diff?: number; within_tolerance?: boolean };
  validity?: Record<string, unknown>;
  execution?: { isolation_tier?: string; tier_verified?: boolean; network_run?: string; determinism_mode?: string };
  proof?: { uri?: string };
};

export type ApiKey = {
  id: string; prefix: string; environment: string; created_at: string;
  last_used_at?: string | null; revoked: boolean;
};

export const calma = {
  listVerifications: (t: string): Promise<{ data: Verification[]; next_cursor: string | null }> =>
    call("/v1/verifications?limit=50", t),
  getVerification: (t: string, id: string): Promise<Verification> =>
    call(`/v1/verifications/${id}/result`, t),
  getProof: (t: string, id: string): Promise<Record<string, unknown>> =>
    call(`/v1/verifications/${id}/proof`, t),
  listKeys: (t: string): Promise<{ data: ApiKey[] }> => call("/v1/keys", t),
  createKey: (t: string, environment: string) =>
    call("/v1/keys", t, { method: "POST", body: JSON.stringify({ environment }) }),
  revokeKey: (t: string, id: string) => call(`/v1/keys/${id}`, t, { method: "DELETE" }),
  uploadUrl: (t: string, kind: string, sha256: string): Promise<{ url: string; uri: string }> =>
    call("/v1/uploads", t, { method: "POST", body: JSON.stringify({ kind, sha256 }) }),
  submit: (t: string, body: unknown): Promise<Verification> =>
    call("/v1/verifications", t, { method: "POST", body: JSON.stringify(body) }),
};

export async function provision(body: { workos_user_id: string; email: string; org_name: string;
  workos_org_id?: string }): Promise<{ org_id: string; tenant_id: string }> {
  const res = await fetch(API + "/internal/provision", {
    method: "POST",
    headers: { "X-Calma-Service-Token": SVC, "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) throw new Error("provision failed: " + res.status);
  return res.json();
}
