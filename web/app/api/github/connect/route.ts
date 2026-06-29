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

  // The app slug is PUBLIC (it's the github.com/apps/<slug> install URL) and stable, so it defaults to the
  // registered Calma App — no env config needed for the connect button to work on any deploy. Override via
  // GITHUB_APP_SLUG if the App is ever re-registered under a different slug.
  const slug = process.env.GITHUB_APP_SLUG || process.env.NEXT_PUBLIC_GITHUB_APP_SLUG || "calma-verify";
  return NextResponse.redirect(`https://github.com/apps/${slug}/installations/new`);
}
