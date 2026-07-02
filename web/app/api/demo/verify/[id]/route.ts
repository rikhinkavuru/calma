// Public, unauthenticated: GET /api/demo/verify/[id] → poll the fixed-repo demo job. Same shape as the
// authed /api/verify/[id] but with no session gate — job ids are opaque and this only ever surfaces the
// one fixed demo run, never a real user's private submission.
import { NextResponse } from "next/server";
import { verifyApi } from "@/lib/verify";

export const dynamic = "force-dynamic";

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    return NextResponse.json(await verifyApi.job(id));
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "the verification API is unreachable" },
      { status: 502 },
    );
  }
}
