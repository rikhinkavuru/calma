// Authed proxy: POST /api/verify → submit a repo to the verification API.
// The dashboard is the only first-party caller of the verification backend. We require a live WorkOS session
// here (withAuth, the same identity the dashboard shell gates on) and only then forward the submission with
// the server-side service token — so the backend stays first-party-only and the token never reaches a browser.
import { withAuth } from "@workos-inc/authkit-nextjs";
import { NextResponse } from "next/server";
import { verifyApi, VerifyApiError } from "@/lib/verify";
import { resolveTier, tenantOf, edgeGuard } from "@/lib/tier";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const { user } = await withAuth().catch(() => ({ user: null }));
  const devTenant = process.env.NODE_ENV !== "production" && process.env.DASHBOARD_DEV_TENANT_ID;
  if (!user && !devTenant) {
    return NextResponse.json({ error: "sign in to verify a repo" }, { status: 401 });
  }
  const tenant = tenantOf(user, devTenant);
  const tier = resolveTier(user);

  // First line of defense: shed a per-user flood at the edge before it reaches the backend or spends compute.
  const guard = edgeGuard(tenant);
  if (!guard.ok) {
    return NextResponse.json(
      { error: "too many requests — slow down" },
      { status: 429, headers: { "Retry-After": String(guard.retryAfter) } },
    );
  }

  const body = await req.json().catch(() => null);
  const repo = body?.repo && String(body.repo).trim();
  if (!repo) return NextResponse.json({ error: "a repo (owner/name or a GitHub URL) is required" }, { status: 400 });
  try {
    const out = await verifyApi.submit(
      {
        repo,
        deep: !!body.deep,
        runner: body.runner === "e2b" ? "e2b" : "local",
        entry: typeof body.entry === "string" ? body.entry : null,
        discover: body.discover !== false,
        pip_install: Array.isArray(body.pip_install) ? body.pip_install : null,
        installation_id: typeof body.installation_id === "string" ? body.installation_id : null,
        installation_proof: typeof body.installation_proof === "string" ? body.installation_proof : null,
      },
      { tenant, tier },
    );
    return NextResponse.json(out);
  } catch (e) {
    // Propagate the backend's admission decision (429 rate/quota, 402 upgrade, 403, 400) verbatim; only a
    // genuine transport failure becomes a 502.
    if (e instanceof VerifyApiError && [400, 401, 402, 403, 429].includes(e.status)) {
      const headers = e.retryAfter ? { "Retry-After": String(e.retryAfter) } : undefined;
      return NextResponse.json({ error: e.message }, { status: e.status, headers });
    }
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "the verification API is unreachable" },
      { status: 502 },
    );
  }
}
