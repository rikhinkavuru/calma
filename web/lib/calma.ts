// Control-plane client — now reduced to tenant provisioning only. The verification flow moved to the
// verification API (lib/verify.ts + the /api/verify proxies); the old control-plane verification/keys
// surfaces were removed with the old dashboard. provision() maps a WorkOS user → a Calma tenant and is the
// one cross-service call still on the path (best-effort at login, lazy in getSession). server-only.
import "server-only";

const API = process.env.CALMA_API_URL || "http://localhost:8000";
const SVC = process.env.CALMA_SERVICE_TOKEN || "";

export async function provision(body: { workos_user_id: string; email: string; org_name: string;
  workos_org_id?: string }): Promise<{ org_id: string; tenant_id: string }> {
  const res = await fetch(API + "/internal/provision", {
    method: "POST",
    headers: { "X-Calma-Service-Token": SVC, "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) throw new Error("provision failed: " + res.status);
  return res.json();
}
