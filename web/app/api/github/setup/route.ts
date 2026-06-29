// GET /api/github/setup?installation_id=…&setup_action=… — where GitHub redirects after the user installs
// the App. Register THIS url (on this origin) as the App's Setup URL + Redirect URL so installs land back on
// the dashboard, not on a backend host. We persist the installation to the verification backend best-effort
// (so it can list/clone via the installation token) and always land the user on /dashboard with the id, so
// the client can list the connected repos even if the backend is briefly unreachable.
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
      // the spike backend stores the installation_id in its handler before redirecting; we don't need its
      // response, just the side effect. Manual redirect so we don't chase its 302 to a backend page.
      await fetch(`${API}/connect/github/setup?installation_id=${encodeURIComponent(iid)}&setup_action=${encodeURIComponent(action)}`,
        { headers: { "X-Calma-Service-Token": SVC }, redirect: "manual", cache: "no-store" });
    } catch { /* best-effort: the client still carries the id below */ }
  }

  const dest = iid ? `/dashboard?installation_id=${encodeURIComponent(iid)}` : "/dashboard";
  return NextResponse.redirect(new URL(dest, url.origin));
}
