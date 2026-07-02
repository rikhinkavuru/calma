// Authed proxy: GET /api/verify/[id]/logs → the job's full, timestamped e2e log as plaintext. Same
// first-party gate as the other verify routes; the browser opens this for the "raw ↗" view and never touches
// the verification backend (or its service token) directly.
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
    const text = await verifyApi.logsText(id, { tenant: tenantOf(user, devTenant), tier: resolveTier(user) });
    return new NextResponse(text, {
      status: 200,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "the verification API is unreachable" },
      { status: 502 },
    );
  }
}
