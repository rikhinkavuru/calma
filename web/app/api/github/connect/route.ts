// GET /api/github/connect → send the user to install the Calma GitHub App.
// Same-origin so it works on any deployment (no hardcoded host): we 302 to GitHub's public install URL,
// built from the app slug server-side. GitHub then redirects back to the App's configured setup URL
// (set that to <this-origin>/api/github/setup — see spike/connect/CONNECT.md).
import { withAuth } from "@workos-inc/authkit-nextjs";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const { user } = await withAuth().catch(() => ({ user: null }));
  const devTenant = process.env.NODE_ENV !== "production" && process.env.DASHBOARD_DEV_TENANT_ID;
  const origin = new URL(req.url).origin;
  if (!user && !devTenant) return NextResponse.redirect(new URL("/dashboard", origin));

  const slug = process.env.GITHUB_APP_SLUG || process.env.NEXT_PUBLIC_GITHUB_APP_SLUG || "";
  if (!slug) {
    // App not registered / slug not configured — bounce back with a hint instead of a broken link.
    return NextResponse.redirect(new URL("/dashboard?github=unconfigured", origin));
  }
  return NextResponse.redirect(`https://github.com/apps/${slug}/installations/new`);
}
