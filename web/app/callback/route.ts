// WorkOS AuthKit OAuth callback. The redirect URI (NEXT_PUBLIC_WORKOS_REDIRECT_URI) must point here and
// be registered in the WorkOS dashboard (Redirects). After a successful login the user lands on /dashboard.
import { handleAuth } from "@workos-inc/authkit-nextjs";
import { writeTenantCookie } from "@/lib/tenant-cookie";

// Provision the Calma tenant ONCE here, at login, and cache it in a sealed cookie — instead of paying the
// cold cross-service provision() call on every dashboard render. Runs in the callback route handler while
// the user is already mid-redirect, so the cost is hidden in "logging in". The provision call is inlined
// (not imported from @/lib/calma) because that module is `server-only`, which throws inside a route
// handler (route handlers are outside the RSC module graph).
export const GET = handleAuth({
  returnPathname: "/dashboard",
  onSuccess: async ({ user }) => {
    try {
      const API = process.env.CALMA_API_URL || "http://localhost:8000";
      const SVC = process.env.CALMA_SERVICE_TOKEN || "";
      const orgName = (user.email?.split("@")[1] || "personal") + " workspace";
      const res = await fetch(API + "/internal/provision", {
        method: "POST",
        headers: { "X-Calma-Service-Token": SVC, "Content-Type": "application/json" },
        body: JSON.stringify({ workos_user_id: user.id, email: user.email, org_name: orgName }),
        cache: "no-store",
      });
      if (!res.ok) return; // non-fatal: getSession() will provision lazily on first render
      const { tenant_id } = (await res.json()) as { tenant_id?: string };
      if (tenant_id) await writeTenantCookie(user.id, tenant_id);
    } catch (e) {
      console.error("[calma] callback provision error:", e instanceof Error ? e.message : e);
    }
  },
});
