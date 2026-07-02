// Authed proxy: GET /api/verify/[id] → poll a verification job's status + verdicts.
// Same first-party gate as the submit route. The browser polls this; it never touches the verification
// backend (or its service token) directly.
import { withAuth } from "@workos-inc/authkit-nextjs";
import { NextResponse } from "next/server";
import { verifyApi } from "@/lib/verify";
import { resolveTier, tenantOf } from "@/lib/tier";

export const dynamic = "force-dynamic";

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { user } = await withAuth().catch(() => ({ user: null }));
  const devTenant = process.env.NODE_ENV !== "production" && process.env.DASHBOARD_DEV_TENANT_ID;
  if (!user && !devTenant) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const { id } = await params;
  try {
    return NextResponse.json(await verifyApi.job(id, { tenant: tenantOf(user, devTenant), tier: resolveTier(user) }));
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "the verification API is unreachable" },
      { status: 502 },
    );
  }
}
