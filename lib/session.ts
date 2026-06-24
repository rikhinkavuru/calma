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

export const getSession = cache(async (): Promise<Session | null> => {
  try {
    const mod = await import("@workos-inc/authkit-nextjs");
    const { user } = await mod.withAuth();
    if (user) {
      const name = [user.firstName, user.lastName].filter(Boolean).join(" ") || user.email;
      const orgName = (user.email?.split("@")[1] || "personal") + " workspace";
      const prov = await provision({ workos_user_id: user.id, email: user.email, org_name: orgName });
      return { user: { email: user.email, name, mode: "workos" }, tenantId: prov.tenant_id };
    }
  } catch {
    // WorkOS not configured, or no active session — fall through to the dev tenant.
  }
  const dev = process.env.DASHBOARD_DEV_TENANT_ID;
  if (dev) return { user: { email: "dev@local", name: "Dev User", mode: "dev" }, tenantId: dev };
  return null;
});

export async function getSignInUrl(): Promise<string | null> {
  try {
    const mod = await import("@workos-inc/authkit-nextjs");
    return await mod.getSignInUrl();
  } catch {
    return null;
  }
}
