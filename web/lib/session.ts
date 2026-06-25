// Resolve the current dashboard session -> { user, tenantId }. Two sources:
//   1. WorkOS AuthKit (production login) -> provision/look-up the Calma tenant for the WorkOS user.
//   2. DASHBOARD_DEV_TENANT_ID (local dev) -> run the dashboard WITHOUT the interactive WorkOS flow.
// Memoized per request with React cache() so provisioning happens at most once per render.
import "server-only";
import { cache } from "react";
import { provision } from "./calma";

export type Session = {
  user: { email: string; name: string; mode: "workos" | "dev" };
  tenantId: string;
};

// A WorkOS user's Calma tenant is stable, but provision() is a DB upsert + registry seed — too expensive to
// run on EVERY page render. Cache workos_user_id -> tenantId in memory (per warm serverless instance, which
// Fluid Compute reuses across requests), so only the FIRST render on a cold instance pays the round-trip.
const tenantCache = new Map<string, string>();

export const getSession = cache(async (): Promise<Session | null> => {
  try {
    const mod = await import("@workos-inc/authkit-nextjs");
    const { user } = await mod.withAuth();
    if (user) {
      const name = [user.firstName, user.lastName].filter(Boolean).join(" ") || user.email;
      let tenantId = tenantCache.get(user.id);
      if (!tenantId) {
        const orgName = (user.email?.split("@")[1] || "personal") + " workspace";
        const prov = await provision({ workos_user_id: user.id, email: user.email, org_name: orgName });
        tenantId = prov.tenant_id;
        tenantCache.set(user.id, tenantId);
      }
      return { user: { email: user.email, name, mode: "workos" }, tenantId };
    }
  } catch (e) {
    // WorkOS not configured, or no active session — fall through to the dev tenant.
    console.error("[calma] getSession withAuth error:", e instanceof Error ? e.message : e);
  }
  // D3-05: the dev-tenant bypass is a non-prod convenience ONLY. Hard-gate it off in production so a
  // mis-set DASHBOARD_DEV_TENANT_ID env can never become an unauthenticated tenant backdoor on the live app.
  const dev = process.env.NODE_ENV !== "production" ? process.env.DASHBOARD_DEV_TENANT_ID : undefined;
  if (dev) return { user: { email: "dev@local", name: "Dev User", mode: "dev" }, tenantId: dev };
  return null;
});

export async function getSignInUrl(): Promise<string | null> {
  try {
    const mod = await import("@workos-inc/authkit-nextjs");
    return await mod.getSignInUrl();
  } catch (e) {
    console.error("[calma] getSignInUrl error:", e instanceof Error ? e.message : e);
    return null;
  }
}
