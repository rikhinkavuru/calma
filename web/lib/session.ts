// Resolve the current dashboard session. Split into two layers so the cold, cross-service tenant
// provision NEVER blocks the dashboard shell:
//   - getUser():    WorkOS withAuth() only (local cookie decrypt, no network) -> identity for the
//                   sidebar/topbar/sign-in gate. Paints instantly.
//   - getSession(): identity + tenantId. tenantId is resolved without the round-trip whenever
//                   possible: (1) warm-instance memory cache, (2) the sealed cookie written at
//                   login, and only (3) a live provision() on a true cold/first render.
// Both memoized per request with React cache().
import "server-only";
import { cache } from "react";
import { provision } from "./calma";
import { readTenantCookie } from "./tenant-cookie";

export type Session = {
  user: { email: string; name: string; mode: "workos" | "dev" };
  tenantId: string;
};

type WorkosUser = { id: string; email: string; firstName?: string | null; lastName?: string | null };

// "Is the user authenticated?" — withAuth() only. A failure here (WorkOS not configured, no session)
// correctly returns null and lets the caller fall through to the dev tenant / sign-in gate.
const getAuthUser = cache(async (): Promise<WorkosUser | null> => {
  try {
    const mod = await import("@workos-inc/authkit-nextjs");
    return (await mod.withAuth()).user ?? null;
  } catch (e) {
    console.error("[calma] getSession withAuth error:", e instanceof Error ? e.message : e);
    return null;
  }
});

const displayName = (u: WorkosUser) => [u.firstName, u.lastName].filter(Boolean).join(" ") || u.email;

const devTenant = () =>
  process.env.NODE_ENV !== "production" ? process.env.DASHBOARD_DEV_TENANT_ID : undefined;

// Identity for the shell. FAST — no provision, no cross-service call.
export const getUser = cache(async (): Promise<Session["user"] | null> => {
  const u = await getAuthUser();
  if (u) return { email: u.email, name: displayName(u), mode: "workos" };
  if (devTenant()) return { email: "dev@local", name: "Dev User", mode: "dev" };
  return null;
});

// provision() is a DB upsert + registry seed — far too expensive for every render. Cache
// workos_user_id -> tenantId per warm serverless instance (Fluid Compute reuses these across requests).
const tenantCache = new Map<string, string>();

// Full session incl. tenantId. Used only by the data-fetching components, which already render inside a
// Suspense boundary — so even a cold provision() streams in under a skeleton instead of blocking the shell.
export const getSession = cache(async (): Promise<Session | null> => {
  const u = await getAuthUser();
  if (u) {
    // (1) warm memory cache, (2) sealed login cookie, (3) provision (cold/first render only).
    let tenantId = tenantCache.get(u.id) || (await readTenantCookie(u.id)) || undefined;
    if (!tenantId) {
      // provision() hits OUR control-plane API. If it fails, the user IS authenticated but our backend
      // is down — let the error propagate so error.tsx shows the retry view, NOT the sign-in gate.
      const orgName = (u.email?.split("@")[1] || "personal") + " workspace";
      const prov = await provision({ workos_user_id: u.id, email: u.email, org_name: orgName });
      tenantId = prov.tenant_id;
    }
    tenantCache.set(u.id, tenantId);
    return { user: { email: u.email, name: displayName(u), mode: "workos" }, tenantId };
  }
  // D3-05: the dev-tenant bypass is a non-prod convenience ONLY. Hard-gate it off in production so a
  // mis-set DASHBOARD_DEV_TENANT_ID env can never become an unauthenticated tenant backdoor on the live app.
  const dev = devTenant();
  if (dev) return { user: { email: "dev@local", name: "Dev User", mode: "dev" }, tenantId: dev };
  return null;
});
