// Authed proxy: DELETE /api/keys/{id} → revoke one of this tenant's API keys. Tenant-scoped in the backend
// (a guessed id from another account 404s), behind the same WorkOS gate as the rest of the console.
import { withAuth } from "@workos-inc/authkit-nextjs";
import { NextResponse } from "next/server";
import { verifyApi, VerifyApiError } from "@/lib/verify";
import { resolveTier, tenantOf, devCodeTierFromCookie } from "@/lib/tier";

export const dynamic = "force-dynamic";

export async function DELETE(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { user } = await withAuth().catch(() => ({ user: null }));
  const devTenant = process.env.NODE_ENV !== "production" && process.env.DASHBOARD_DEV_TENANT_ID;
  if (!user && !devTenant) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const { id } = await params;
  const identity = { tenant: tenantOf(user, devTenant), tier: resolveTier(user, await devCodeTierFromCookie()) };
  try {
    return NextResponse.json(await verifyApi.revokeKey(id, identity));
  } catch (e) {
    const status = e instanceof VerifyApiError ? e.status : 502;
    return NextResponse.json({ error: e instanceof Error ? e.message : "unreachable" }, { status });
  }
}
