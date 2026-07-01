// Server-side client for the Calma *verification* API (the spike FastAPI service: connect a repo → re-run
// it → recompute the numbers). This is a different backend from lib/calma.ts (the control plane): it owns
// the connect → scan → findings job loop. Called only from the authed proxy route handlers under
// app/api/verify — the service token is sent server-to-server and never reaches the browser.
//
// NB: intentionally NOT `import "server-only"` — this module is imported by route handlers, and in this
// codebase server-only throws there (see app/callback/route.ts). It is still only ever imported server-side.

const API = process.env.CALMA_VERIFY_API_URL || "http://localhost:8787";
const SVC = (process.env.CALMA_VERIFY_TOKEN || process.env.CALMA_SERVICE_TOKEN || "").trim();

// The identity the trusted proxy forwards to the backend so it can meter + tier-gate the request. Only this
// server-side module (which alone holds the service token) can set these headers, so the backend can trust
// them: an attacker without the token cannot forge a tenant or upgrade their own tier.
export type Identity = { tenant: string; tier: string };

// A structured error that preserves the backend's HTTP status + reason (429 rate/quota, 402 upgrade, 403,
// 400) so the route handler can surface the right status to the browser instead of a blanket 502.
export class VerifyApiError extends Error {
  status: number;
  retryAfter?: number;
  constructor(status: number, message: string, retryAfter?: number) {
    super(message);
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

async function call(path: string, init?: RequestInit, id?: Identity) {
  const res = await fetch(API + path, {
    ...init,
    headers: {
      "X-Calma-Service-Token": SVC,
      "Content-Type": "application/json",
      ...(id ? { "X-Calma-Tenant": id.tenant, "X-Calma-Tier": id.tier } : {}),
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    // FastAPI returns {"detail": "..."}; fall back to the raw body.
    let reason = body.slice(0, 300);
    try {
      const j = JSON.parse(body);
      if (j?.detail) reason = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not json */
    }
    const ra = Number(res.headers.get("Retry-After") || "") || undefined;
    throw new VerifyApiError(res.status, reason || `verify API ${res.status} on ${path}`, ra);
  }
  return res.json();
}

export type VerifySubmit = {
  repo: string;
  deep?: boolean;
  runner?: "local" | "e2b";
  entry?: string | null;
  discover?: boolean;
  pip_install?: string[] | null;
  installation_id?: string | null;
};

export type Repo = {
  name: string;
  slug: string;
  visibility: string;
  description?: string;
  language?: string;
};

export type GithubConfig = { internal: boolean; github: { configured: boolean; connected: boolean } };
export type Installation = { installation_id: string; action?: string };

// the per-claim record the pipeline returns (see spike/pipeline.py _claim_out)
export type Claim = {
  id: string;
  metric: string;
  claimed: string;
  context?: string;
  location?: string;
  source?: string;
  verdict: string;
  reason?: string;
  diff?: { claimed?: unknown; produced?: number; recomputed?: number };
  provenance?: string | null;
  validity?: { invalidating: string[]; advisory: string[] };
};

export type Job = {
  id: string;
  repo: string;
  status: string;
  stage: string;
  counts: Record<string, number>;
  n_claims: number;
  claims: Claim[];
  leakage: { dataset: string; findings: { kind: string; magnitude: number; detail: string }[] }[];
  run: { ran: boolean; calls: number; entry: string; error?: string; error_full?: string } | null;
  logs: string[];
  error: string | null;
  failure_kind?: string;        // memory | timeout | cpu | crashed | error — why an isolated job was stopped
  truncated?: number;
};

export type Usage = {
  tier: string;
  scans_today: number;
  scans_per_day: number;
  sandbox_minutes_used: number;
  sandbox_minutes_per_month: number;
  inflight: number;
  concurrency: number;
};

export const verifyApi = {
  submit: (body: VerifySubmit, id: Identity): Promise<{ id: string; tier: string; deep: boolean; limit_notes: string[] }> =>
    call(
      "/api/verify",
      {
        method: "POST",
        body: JSON.stringify({
          repo: body.repo,
          deep: !!body.deep,
          runner: body.runner === "e2b" ? "e2b" : "local",
          entry: body.entry || null,
          discover: body.discover !== false,
          pip_install: Array.isArray(body.pip_install) ? body.pip_install : null,
          installation_id: body.installation_id || null,
          k: 2,
        }),
      },
      id,
    ),
  usage: (id: Identity): Promise<Usage> => call("/api/usage", undefined, id),
  job: (id: string): Promise<Job> => call(`/api/jobs/${encodeURIComponent(id)}`),
  // the full e2e log as plaintext (the backend's /api/jobs/{id}/logs) — for the "raw ↗" view.
  logsText: async (id: string): Promise<string> => {
    const res = await fetch(`${API}/api/jobs/${encodeURIComponent(id)}/logs`, {
      headers: { "X-Calma-Service-Token": SVC },
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`verify API ${res.status} on logs`);
    return res.text();
  },
};

// Read-only GitHub/repo surfaces for the connect + repo-picker UX (proxied through /api/github).
export const githubApi = {
  config: (): Promise<GithubConfig> => call("/api/config"),
  repos: (): Promise<Repo[]> => call("/api/repos"),
  installations: (): Promise<Installation[]> => call("/api/installations"),
  ghRepos: (installationId: string, id: Identity): Promise<Repo[]> =>
    call(`/api/gh/repos?installation_id=${encodeURIComponent(installationId)}`, undefined, id),
};
