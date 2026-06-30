// GET /api/github/setup?installation_id=…&setup_action=… — where GitHub redirects after the user installs
// the App. Register THIS url (on this origin) as the App's Setup URL so installs land back on the dashboard,
// not on a backend host. We persist the installation to the verification backend best-effort, then either
// hand the id back to the opener (when this ran in the connect POPUP) and close, or — for a same-tab
// install — redirect to /dashboard with the id. Both paths leave a working connection.
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const API = process.env.CALMA_VERIFY_API_URL || "http://localhost:8787";
const SVC = (process.env.CALMA_VERIFY_TOKEN || process.env.CALMA_SERVICE_TOKEN || "").trim();

export async function GET(req: Request) {
  const url = new URL(req.url);
  const iid = url.searchParams.get("installation_id") || "";
  const action = url.searchParams.get("setup_action") || "";

  if (iid) {
    try {
      // the spike backend stores the installation_id in its handler before redirecting; we just want the
      // side effect. Manual redirect so we don't chase its 302 to a backend page.
      await fetch(`${API}/connect/github/setup?installation_id=${encodeURIComponent(iid)}&setup_action=${encodeURIComponent(action)}`,
        { headers: { "X-Calma-Service-Token": SVC }, redirect: "manual", cache: "no-store" });
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
