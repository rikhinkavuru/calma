// Authed proxy: GET /api/jobs → the caller's own past verification scans (tenant-scoped, newest-first).
// Same first-party WorkOS gate as the verify routes; the browser never touches the backend or its token.
import { withAuth } from "@workos-inc/authkit-nextjs";
import { NextResponse } from "next/server";
import { verifyApi, VerifyApiError } from "@/lib/verify";
import { resolveTier, tenantOf, tierOverride } from "@/lib/tier";

export const dynamic = "force-dynamic";

export async function GET() {
  const { user } = await withAuth().catch(() => ({ user: null }));
  const devTenant = process.env.NODE_ENV !== "production" && process.env.DASHBOARD_DEV_TENANT_ID;
  if (!user && !devTenant) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  try {
    const tier = resolveTier(user, await tierOverride(user));
    const jobs = await verifyApi.listJobs({ tenant: tenantOf(user, devTenant), tier });
    return NextResponse.json(jobs);
  } catch (e) {
    const status = e instanceof VerifyApiError ? e.status : 502;
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "the verification API is unreachable" },
      { status },
    );
  }
}
