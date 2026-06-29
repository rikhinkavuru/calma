// Authed read-only proxy for the connect + repo-picker UX: GET /api/github?kind=config|repos|installations|gh-repos
// Same first-party gate as the verify proxy (a live WorkOS session), then forwards to the verification API
// with the server-side service token. The browser never touches the backend or token directly.
import { withAuth } from "@workos-inc/authkit-nextjs";
import { NextResponse } from "next/server";
import { githubApi } from "@/lib/verify";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const { user } = await withAuth().catch(() => ({ user: null }));
  const devTenant = process.env.NODE_ENV !== "production" && process.env.DASHBOARD_DEV_TENANT_ID;
  if (!user && !devTenant) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const url = new URL(req.url);
  const kind = url.searchParams.get("kind");
  try {
    switch (kind) {
      case "config":
        return NextResponse.json(await githubApi.config());
      case "repos":
        return NextResponse.json(await githubApi.repos());
      case "installations":
        return NextResponse.json(await githubApi.installations());
      case "gh-repos": {
        const iid = url.searchParams.get("installation_id");
        if (!iid) return NextResponse.json({ error: "installation_id required" }, { status: 400 });
        return NextResponse.json(await githubApi.ghRepos(iid));
      }
      default:
        return NextResponse.json({ error: "unknown kind" }, { status: 400 });
    }
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "the verification API is unreachable" },
      { status: 502 },
    );
  }
}
