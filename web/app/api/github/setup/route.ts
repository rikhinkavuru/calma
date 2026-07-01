// GET /api/github/setup?installation_id=…&setup_action=… — where GitHub redirects after the user installs
// the App. Register THIS url (on this origin) as the App's Setup URL so installs land back on the dashboard,
// not on a backend host. We persist the installation to the verification backend best-effort, then either
// hand the id back to the opener (when this ran in the connect POPUP) and close, or — for a same-tab
// install — redirect to /dashboard with the id. Both paths leave a working connection.
import { withAuth } from "@workos-inc/authkit-nextjs";
import { NextResponse } from "next/server";
import { tenantOf } from "@/lib/tier";

export const dynamic = "force-dynamic";

const API = process.env.CALMA_VERIFY_API_URL || "http://localhost:8787";
const SVC = (process.env.CALMA_VERIFY_TOKEN || process.env.CALMA_SERVICE_TOKEN || "").trim();

export async function GET(req: Request) {
  const url = new URL(req.url);
  const iid = url.searchParams.get("installation_id") || "";
  const action = url.searchParams.get("setup_action") || "";

  if (iid) {
    // Bind this installation to the signed-in user so it can't later be used cross-tenant (the backend's
    // _installation_ok check). GitHub redirects here in the user's own browser, so the session cookie is
    // present and withAuth resolves them.
    const { user } = await withAuth().catch(() => ({ user: null }));
    const devTenant = process.env.NODE_ENV !== "production" && process.env.DASHBOARD_DEV_TENANT_ID;
    const tenant = tenantOf(user, devTenant);
    try {
      // the spike backend stores installation_id ↔ tenant before redirecting; we just want the side effect.
      // Manual redirect so we don't chase its 302 to a backend page.
      await fetch(`${API}/connect/github/setup?installation_id=${encodeURIComponent(iid)}&setup_action=${encodeURIComponent(action)}`,
        { headers: { "X-Calma-Service-Token": SVC, "X-Calma-Tenant": tenant }, redirect: "manual", cache: "no-store" });
    } catch { /* best-effort: the client still carries the id below */ }
  }

  // Popup path: postMessage the id to the dashboard (the opener) and close. Same-tab fallback: redirect.
  const fallback = iid ? `/dashboard?installation_id=${encodeURIComponent(iid)}` : "/dashboard";
  const html = `<!doctype html><meta charset="utf-8"><title>Connecting…</title>
<body style="font-family:system-ui;color:#1a1a18;display:grid;place-items:center;height:100vh;margin:0">Connecting…</body>
<script>(function(){var iid=${JSON.stringify(iid)},origin=${JSON.stringify(url.origin)},fb=${JSON.stringify(fallback)};
try{if(window.opener&&!window.opener.closed){window.opener.postMessage({source:"calma-github",installation_id:iid},origin);window.close();return;}}catch(e){}
location.replace(fb);})();</script>`;
  return new NextResponse(html, {
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
  });
}
