// Public, unauthenticated: GET /api/demo/verify/[id] → poll the fixed-repo demo job. Same shape as the
// authed /api/verify/[id] but with no session gate. Resolves the SAME IP-hash tenant the submit route used
// (lib/tier.ts demoTenant) and forwards it — the backend now scopes every job to its owning tenant
// (server.py _job_or_404), so this genuinely only ever surfaces the caller's OWN demo run, never another
// visitor's or a real signed-in user's private job (previously true only by an unenforced comment/convention).
import { NextResponse } from "next/server";
import { verifyApi } from "@/lib/verify";
import { demoTenant } from "@/lib/tier";

export const dynamic = "force-dynamic";

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    return NextResponse.json(await verifyApi.job(id, { tenant: demoTenant(req), tier: "demo" }));
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "the verification API is unreachable" },
      { status: 502 },
    );
  }
}
