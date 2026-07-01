// Tier resolution + a cheap edge burst guard for the verification proxy. The backend (spike/core/limits.py)
// is the AUTHORITATIVE meter (daily scans, sandbox-minutes, concurrency); this layer resolves *who* the user
// is and *what plan* they're on from the WorkOS identity, and adds a first-line-of-defense per-user burst
// limit so a flood is shed at the edge before it ever reaches the backend or spends a Vercel function.
//
// Billing isn't wired yet, so tier assignment is an env allowlist (emails or WorkOS user ids). Anyone not
// listed is `free` — fail closed on entitlement. Set CALMA_PRO_USERS / CALMA_ENTERPRISE_USERS (comma-sep),
// or CALMA_TIER_DEFAULT to grant a blanket tier during a launch.

export type Tier = "free" | "pro" | "enterprise";

type Userish = { id?: string | null; email?: string | null } | null | undefined;

function allowlist(env: string | undefined): Set<string> {
  return new Set(
    (env || "")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  );
}

export function resolveTier(user: Userish): Tier {
  const id = (user?.id || "").toLowerCase();
  const email = (user?.email || "").toLowerCase();
  const ent = allowlist(process.env.CALMA_ENTERPRISE_USERS);
  const pro = allowlist(process.env.CALMA_PRO_USERS);
  if ((id && ent.has(id)) || (email && ent.has(email))) return "enterprise";
  if ((id && pro.has(id)) || (email && pro.has(email))) return "pro";
  const dflt = (process.env.CALMA_TIER_DEFAULT || "free").toLowerCase();
  return dflt === "pro" || dflt === "enterprise" ? (dflt as Tier) : "free";
}

// A stable tenant id for metering: the WorkOS user id (falls back to the dev tenant, then "anon").
export function tenantOf(user: Userish, devTenant?: string | false | null): string {
  return user?.id || (devTenant || undefined) || "anon";
}

// ── edge burst guard ────────────────────────────────────────────────────────────────────────────────────
// A fixed 60s window per tenant. In-memory, per-instance — deliberately coarse (defense in depth, not the
// authoritative meter). Fluid Compute reuses instances so this catches the common single-instance flood; the
// backend's per-tenant limiter is the real ceiling across instances.
const EDGE_RPM = Number(process.env.CALMA_EDGE_RPM || "60") || 60;
const _win = new Map<string, { minute: number; count: number }>();

export function edgeGuard(tenant: string): { ok: boolean; retryAfter: number } {
  const now = Date.now();
  const minute = Math.floor(now / 60000);
  const cur = _win.get(tenant);
  if (!cur || cur.minute !== minute) {
    _win.set(tenant, { minute, count: 1 });
    // opportunistic cleanup so the map can't grow unbounded across many tenants
    if (_win.size > 5000) for (const [k, v] of _win) if (v.minute !== minute) _win.delete(k);
    return { ok: true, retryAfter: 0 };
  }
  cur.count += 1;
  if (cur.count > EDGE_RPM) return { ok: false, retryAfter: 60 - Math.floor((now % 60000) / 1000) };
  return { ok: true, retryAfter: 0 };
}
