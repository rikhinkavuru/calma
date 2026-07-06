// Authed proxy: GET /api/keys → this tenant's API keys (metadata only); POST /api/keys → mint a new key
// (returns the plaintext ONCE). Same first-party WorkOS gate as the verify routes; the browser never touches
// the backend or its service token. Key management is backend-gated to the service-token identity, so it can
// only be reached through this authenticated proxy — never with an API key.
import { withAuth } from "@workos-inc/authkit-nextjs";
import { NextResponse } from "next/server";
import { verifyApi, VerifyApiError } from "@/lib/verify";
import { resolveTier, tenantOf, tierOverride } from "@/lib/tier";

export const dynamic = "force-dynamic";

async function ident() {
  const { user } = await withAuth().catch(() => ({ user: null }));
  const devTenant = process.env.NODE_ENV !== "production" && process.env.DASHBOARD_DEV_TENANT_ID;
  if (!user && !devTenant) return null;
  return { tenant: tenantOf(user, devTenant), tier: resolveTier(user, await tierOverride(user)) };
}

export async function GET() {
  const id = await ident();
  if (!id) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  try {
    return NextResponse.json(await verifyApi.listKeys(id));
  } catch (e) {
    const status = e instanceof VerifyApiError ? e.status : 502;
    return NextResponse.json({ error: e instanceof Error ? e.message : "unreachable" }, { status });
  }
}

export async function POST(req: Request) {
  const id = await ident();
  if (!id) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const name = typeof body?.name === "string" ? body.name.slice(0, 80) : "";
  try {
    return NextResponse.json(await verifyApi.createKey(name, id));
  } catch (e) {
    const status = e instanceof VerifyApiError ? e.status : 502;
    return NextResponse.json({ error: e instanceof Error ? e.message : "unreachable" }, { status });
  }
}
