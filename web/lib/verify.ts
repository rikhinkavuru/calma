// Server-side client for the Calma *verification* API (the spike FastAPI service: connect a repo → re-run
// it → recompute the numbers). This is a different backend from lib/calma.ts (the control plane): it owns
// the connect → scan → findings job loop. Called only from the authed proxy route handlers under
// app/api/verify — the service token is sent server-to-server and never reaches the browser.
//
// NB: intentionally NOT `import "server-only"` — this module is imported by route handlers, and in this
// codebase server-only throws there (see app/callback/route.ts). It is still only ever imported server-side.

const API = process.env.CALMA_VERIFY_API_URL || "http://localhost:8787";
const SVC = (process.env.CALMA_VERIFY_TOKEN || process.env.CALMA_SERVICE_TOKEN || "").trim();

async function call(path: string, init?: RequestInit) {
  const res = await fetch(API + path, {
    ...init,
    headers: {
      "X-Calma-Service-Token": SVC,
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`verify API ${res.status} on ${path}: ${body.slice(0, 300)}`);
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
};

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
  truncated?: number;
};

export const verifyApi = {
  submit: (body: VerifySubmit): Promise<{ id: string }> =>
    call("/api/verify", {
      method: "POST",
      body: JSON.stringify({
        repo: body.repo,
        deep: !!body.deep,
        runner: body.runner === "e2b" ? "e2b" : "local",
        entry: body.entry || null,
        discover: body.discover !== false,
        pip_install: Array.isArray(body.pip_install) ? body.pip_install : null,
        k: 2,
      }),
    }),
  job: (id: string): Promise<Job> => call(`/api/jobs/${encodeURIComponent(id)}`),
};
